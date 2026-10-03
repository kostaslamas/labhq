"""The IT agent's rule tools: a reason is required, the agent is the creator, no disable."""

import pytest

from labhq.db.enums import AgentStatus, HealthRuleAction
from labhq.db.models import Agent, Comment, HealthRule, Host
from labhq.guards.readonly import PERMISSION_MODE_KEY, READ_ONLY_MODE, classify
from labhq.roles import agent_reference
from tests.roles.conftest import Org

IT_CONFIG = {PERMISSION_MODE_KEY: READ_ONLY_MODE}
DISK = {"metric": "disk.percent", "comparison": ">", "value": 90}
IT_TOOLS = {"list_rules", "add_rule", "tune_rule", "write_diagnosis", "request_fix", "list_hosts"}


@pytest.fixture
async def it_agent(org: Org) -> int:
    now = org.clock.now()
    async with org.sessions() as db:
        agent = Agent(
            role="it",
            title="IT",
            reports_to=org.ceo,
            adapter="fake",
            config=dict(IT_CONFIG),
            status=AgentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        db.add(agent)
        await db.commit()
        return agent.id


async def test_add_rule_without_a_reason_is_refused(org: Org, it_agent: int) -> None:
    missing = await org.call("add_rule", it_agent, type="threshold", params=DISK, action="ticket")
    blank = await org.call(
        "add_rule", it_agent, type="threshold", params=DISK, action="ticket", reason="   "
    )
    assert missing.startswith("Invalid arguments for add_rule")
    assert "reason" in missing
    assert blank == "Refused: a rule needs a non-empty reason"
    assert await org.all(HealthRule) == []


async def test_a_rule_with_a_reason_is_listed_with_the_it_agent_as_creator(
    org: Org, it_agent: int
) -> None:
    reason = "The NAS fills up before backups; act at 90%."
    answer = await org.call(
        "add_rule",
        it_agent,
        type="threshold",
        params=DISK,
        action="ticket",
        reason=reason,
        name="disk over 90",
    )

    [rule] = await org.all(HealthRule)
    assert answer == f"Rule {rule.id} 'disk over 90' added and enabled."
    assert (rule.created_by, rule.reason, rule.enabled) == (agent_reference(it_agent), reason, True)
    assert rule.action is HealthRuleAction.TICKET
    listed = await org.call("list_rules", it_agent)
    assert f"by agent:{it_agent}" in listed
    assert f"Reason: {reason}" in listed


async def test_bad_params_are_refused_by_the_rule_type(org: Org, it_agent: int) -> None:
    answer = await org.call(
        "add_rule",
        it_agent,
        type="threshold",
        params={"metric": "x"},
        action="notify",
        reason="test",
    )
    assert answer.startswith("Refused:")
    assert await org.all(HealthRule) == []


async def test_tune_rule_needs_a_reason_and_replaces_the_params(org: Org, it_agent: int) -> None:
    await org.call(
        "add_rule", it_agent, type="threshold", params=DISK, action="notify", reason="first"
    )
    [rule] = await org.all(HealthRule)
    refused = await org.call("tune_rule", it_agent, rule=rule.id, params=DISK, reason="")
    tuned = await org.call(
        "tune_rule", it_agent, rule=rule.id, params={**DISK, "value": 95}, reason="too noisy"
    )

    assert refused.startswith("Invalid arguments")
    assert tuned == f"Rule {rule.id} tuned."
    rule = await org.get(HealthRule, rule.id)
    assert (rule.params["value"], rule.reason) == (95, "too noisy")


def test_the_it_agent_holds_its_tools_but_none_that_disables_a_rule(org: Org) -> None:
    names = {spec.name for spec in org.tools.for_agent("it", IT_CONFIG)}
    assert names == IT_TOOLS
    assert not any("disable" in name or "enable" in name for name in names)
    # Nobody else gets them.
    assert not IT_TOOLS & {spec.name for spec in org.tools.for_agent("manager", {})}


async def test_write_diagnosis_only_lands_on_an_infra_ticket(org: Org, it_agent: int) -> None:
    answer = await org.call("write_diagnosis", it_agent, ticket=org.site_task, diagnosis="x")
    assert answer == f"Refused: task {org.site_task} is not an infra ticket"
    assert await org.all(Comment) == []


async def test_list_hosts_gives_a_read_only_ssh_prefix(org: Org, it_agent: int) -> None:
    now = org.clock.now()
    async with org.sessions() as db:
        db.add_all(
            [
                Host(
                    name="nas",
                    address="10.0.0.5:2222",
                    ssh_user="labhq-ro",
                    created_at=now,
                    updated_at=now,
                ),
                Host(name="here", is_local=True, created_at=now, updated_at=now),
            ]
        )
        await db.commit()

    answer = await org.call("list_hosts", it_agent)

    prefix = "ssh -p 2222 labhq-ro@10.0.0.5"
    assert f"nas (unknown): {prefix} <command>" in answer
    assert "here (unknown): local: run commands directly" in answer
    # What the prefix runs is what the read-only classifier checks.
    assert classify(f"{prefix} df -h").allowed
    assert not classify(f"{prefix} rm -rf /data").allowed


async def test_request_fix_names_an_infra_ticket_and_a_known_host(org: Org, it_agent: int) -> None:
    wrong_ticket = await org.call(
        "request_fix",
        it_agent,
        host="nas",
        command="apt upgrade",
        reason="r",
        ticket=org.site_task,
    )
    assert wrong_ticket == f"Refused: task {org.site_task} is not an infra ticket"
    assert await org.approvals() == []
