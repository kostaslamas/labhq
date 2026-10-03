"""An incident on a `ticket` rule wakes the IT agent once; its fix request runs nothing."""

from datetime import time

from labhq.db.enums import (
    AgentStatus,
    ApprovalStatus,
    HealthRuleAction,
    RiskClass,
    WakeupSource,
    WakeupStatus,
)
from labhq.db.models import (
    Agent,
    Approval,
    Comment,
    HealthRule,
    HealthSample,
    Host,
    Incident,
    Task,
)
from labhq.health.incidents import evaluate_rules
from labhq.health.intervention import INTERVENTION_ACTION
from labhq.it import IT_CONFIG, ItDepartment, ItSettings, incident_key
from labhq.scheduler import Outcome
from tests.it.conftest import DepartmentFactory, SpyExecutor, start_it_agent
from tests.roles.conftest import Org

DISK = {"metric": "disk.percent", "comparison": ">", "value": 90}
# Before the daily report, so only incidents wake the agent here.
LATE_REPORT = time(23, 0)


async def violate(org: Org, action: HealthRuleAction = HealthRuleAction.TICKET) -> Incident:
    """A host whose disk crosses a rule; the health pass opens the incident (and its ticket)."""
    now = org.clock.now()
    async with org.sessions() as db:
        host = Host(name="nas", address="nas.lan", ssh_user="ro", created_at=now, updated_at=now)
        db.add(host)
        await db.flush()
        db.add(
            HealthRule(
                type="threshold",
                name="disk",
                params=DISK,
                action=action,
                reason="backups",
                created_by="operator",
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(HealthSample(host_id=host.id, metric="disk.percent", value=95.0, sampled_at=now))
        await db.flush()
        [change] = await evaluate_rules(db, org.clock)
        await db.commit()
        return change.incident


async def test_an_incident_wakes_the_it_agent_once_with_the_ticket_as_its_task(
    org: Org, department: DepartmentFactory
) -> None:
    incident = await violate(org)
    assert incident.task_id is not None
    it = await department(report_time=LATE_REPORT)

    first = await it.tick()
    again = await it.tick()
    org.clock.advance(300)
    later = await it.tick()

    assert first.agent_id is not None
    [created] = first.incidents
    assert created.outcome is Outcome.CREATED
    assert [result.outcome for result in again.incidents + later.incidents] == [
        Outcome.DUPLICATE,
        Outcome.DUPLICATE,
    ]
    [wakeup] = await org.wakeups()
    assert (wakeup.agent_id, wakeup.task_id) == (first.agent_id, incident.task_id)
    assert (wakeup.source, wakeup.status) == (WakeupSource.ASSIGNMENT, WakeupStatus.PENDING)
    assert wakeup.idempotency_key == incident_key(incident)
    assert f"incident {incident.id} opened on nas" in wakeup.reason
    ticket = await org.get(Task, incident.task_id)
    assert ticket.assignee_id == first.agent_id


async def test_the_it_agent_is_one_read_only_agent_under_the_ceo(org: Org) -> None:
    first = await start_it_agent(org)
    second = await start_it_agent(org)

    assert first == second
    agent = await org.get(Agent, first)
    assert (agent.role, agent.project_id, agent.reports_to) == ("it", None, org.ceo)
    assert agent.config == IT_CONFIG
    assert agent.status is AgentStatus.ACTIVE


async def test_its_diagnosis_lands_on_the_ticket_and_its_fix_request_runs_nothing(
    org: Org, department: DepartmentFactory, intervention: SpyExecutor
) -> None:
    incident = await violate(org)
    agent_id = (await (await department(report_time=LATE_REPORT)).tick()).agent_id
    assert agent_id is not None and incident.task_id is not None

    diagnosis = "/data is 95% full: old snapshots. Propose pruning snapshots older than 30 days."
    noted = await org.call(
        "write_diagnosis", agent_id, ticket=incident.task_id, diagnosis=diagnosis
    )
    command = "zfs destroy tank/data@2026-08-01"
    requested = await org.call(
        "request_fix",
        agent_id,
        host="nas",
        command=command,
        reason="free space",
        ticket=incident.task_id,
    )

    assert noted == f"Diagnosis recorded on ticket #{incident.task_id}."
    [comment] = [c for c in await org.all(Comment) if c.author_agent_id == agent_id]
    assert (comment.task_id, comment.body) == (incident.task_id, diagnosis)
    [approval] = await org.all(Approval)
    assert (approval.type, approval.risk_class) == (INTERVENTION_ACTION, RiskClass.HEAVY)
    assert approval.status is ApprovalStatus.PENDING
    assert (approval.task_id, approval.requested_by_agent_id) == (incident.task_id, agent_id)
    assert approval.payload == {
        "host": "nas",
        "command": command,
        "reason": "free space",
        "ticket": incident.task_id,
    }
    assert approval.execution is None
    assert intervention.calls == []
    assert f"A{approval.id} (heavy)" in requested


async def test_a_malformed_fix_request_is_refused_before_any_approval(
    org: Org, department: DepartmentFactory, intervention: SpyExecutor
) -> None:
    incident = await violate(org)
    agent_id = (await (await department(report_time=LATE_REPORT)).tick()).agent_id
    assert agent_id is not None and incident.task_id is not None

    unknown_host = await org.call(
        "request_fix",
        agent_id,
        host="ghost",
        command="reboot",
        reason="r",
        ticket=incident.task_id,
    )
    blank_command = await org.call(
        "request_fix", agent_id, host="nas", command="  ", reason="r", ticket=incident.task_id
    )

    assert unknown_host == "Refused: no host named 'ghost'"
    assert blank_command.startswith("Refused:")
    assert await org.all(Approval) == []


async def test_a_notify_rule_wakes_nobody(org: Org, department: DepartmentFactory) -> None:
    await violate(org, HealthRuleAction.NOTIFY)
    result = await (await department(report_time=LATE_REPORT)).tick()
    assert result.incidents == []
    assert await org.wakeups() == []


async def test_without_an_active_it_agent_nothing_wakes_until_there_is_one(
    org: Org,
) -> None:
    incident = await violate(org)
    it = ItDepartment(org.sessions, org.clock, ItSettings(report_time=LATE_REPORT))

    nobody = await it.tick()
    agent_id = await start_it_agent(org)
    async with org.sessions() as db:
        agent = await db.get_one(Agent, agent_id)
        agent.status = AgentStatus.PAUSED
        await db.commit()
    paused = await it.tick()

    assert (nobody.agent_id, paused.agent_id) == (None, agent_id)
    assert await org.wakeups() == []
    assert await org.all(Approval) == []

    async with org.sessions() as db:
        agent = await db.get_one(Agent, agent_id)
        agent.status = AgentStatus.ACTIVE
        await db.commit()
    await it.tick()

    # The incident opened before the agent could run; it is not lost.
    [wakeup] = await org.wakeups()
    assert (wakeup.agent_id, wakeup.task_id) == (agent_id, incident.task_id)
