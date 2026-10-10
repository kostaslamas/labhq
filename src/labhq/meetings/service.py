"""Request a meeting, start it once approved, and request meetings on a cadence.

Starting a meeting is a light approval (plan §5): a request records the meeting and a
pending `start_meeting` approval; `start` runs it only after a human approved.
"""

from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from labhq.approvals import ApprovalService
from labhq.approvals.policy import default_confirmations
from labhq.approvals.registry import Registry
from labhq.clock import Clock
from labhq.db.enums import AgentStatus, ApprovalStatus, MeetingStatus
from labhq.db.models import Agent, Approval, Meeting, MeetingParticipant, Project
from labhq.hierarchy import find_ceo
from labhq.meetings.forecast import Forecast, room_forecast
from labhq.meetings.kinds import MeetingKind
from labhq.meetings.kinds import default_kinds as builtin_kinds
from labhq.meetings.room import DecisionRoom
from labhq.meetings.runner import MeetingRunner
from labhq.meetings.settings import MeetingSettings, get_meeting_settings

START_MEETING_ACTION = "start_meeting"

_STARTABLE = frozenset({ApprovalStatus.APPROVED, ApprovalStatus.EXECUTED})
_REFUSED = frozenset({ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED})


class MeetingError(RuntimeError):
    """A meeting request that cannot be carried out as given."""


class MeetingNotApprovedError(MeetingError):
    pass


class MeetingService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Clock,
        approvals: ApprovalService,
        runner: MeetingRunner,
        kinds: Registry[MeetingKind] = builtin_kinds,
        settings: MeetingSettings | None = None,
        room: DecisionRoom | None = None,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._approvals = approvals
        self._runner = runner
        self._room = room
        self._kinds = kinds
        self._settings = settings or get_meeting_settings()

    def kind(self, key: str) -> MeetingKind:
        return self._kinds.get(key)

    @property
    def room(self) -> DecisionRoom:
        if self._room is None:
            raise MeetingError("no decision room is configured")
        return self._room

    async def request(
        self,
        *,
        project_id: int,
        kind: str,
        agenda: str | None = None,
        participants: Sequence[int] | None = None,
        requested_by: int | None = None,
        pinned: tuple[str, int] | None = None,
    ) -> Meeting:
        """Record a meeting and its pending approval. Nothing runs until it is approved.

        `pinned` is the `(kind, id)` of the CEO proposal a decision room discusses.
        """
        meeting_kind = self._kinds.get(kind)
        async with self._sessions() as db:
            project = await db.get(Project, project_id)
            if project is None:
                raise MeetingError(f"no project {project_id}")
            agents = await _attendees(db, project, meeting_kind, participants)
            forecast = (
                await room_forecast(
                    db, [agent.id for agent in agents], agents[0].id, self._settings
                )
                if meeting_kind.live
                else None
            )
            meeting = Meeting(
                project_id=project.id,
                kind=meeting_kind.key,
                agenda=agenda or meeting_kind.agenda.format(project=project.name),
                status=MeetingStatus.REQUESTED,
                facilitator_agent_id=agents[0].id,
                pinned_kind=pinned[0] if pinned else None,
                pinned_id=pinned[1] if pinned else None,
                estimate_micros=forecast.low_micros if forecast else None,
                estimate_high_micros=forecast.high_micros if forecast else None,
                estimate_source=forecast.source.value if forecast else None,
                cost_cap_micros=self._settings.decision_cost_cap_micros if forecast else None,
                created_at=self._clock.now(),
            )
            db.add(meeting)
            await db.flush()
            db.add_all(
                MeetingParticipant(
                    meeting_id=meeting.id, agent_id=agent.id, display_name=agent.title
                )
                for agent in agents
            )
            await db.commit()
        approval = await self._approvals.request(
            START_MEETING_ACTION,
            {
                "meeting_id": meeting.id,
                "project_id": project_id,
                "kind": meeting_kind.key,
                **(_forecast_payload(forecast, self._settings) if forecast else {}),
            },
            agent_id=requested_by,
        )
        async with self._sessions() as db:
            stored = await db.get_one(Meeting, meeting.id)
            stored.approval_id = approval.id
            await db.commit()
            return stored

    async def start(self, meeting_id: int) -> Meeting:
        """Run an approved meeting; cancel a refused one; refuse one still pending."""
        async with self._sessions() as db:
            meeting = await db.get(Meeting, meeting_id)
            if meeting is None:
                raise MeetingError(f"no meeting {meeting_id}")
            approval = await db.get(Approval, meeting.approval_id) if meeting.approval_id else None
        status = approval.status if approval is not None else None
        if status in _STARTABLE:
            self._require_person(meeting.kind, approval)
            self._require_forecast(meeting)
            if not self._kinds.get(meeting.kind).live:
                return await self._runner.run(meeting_id)
            if self._room is None:
                raise MeetingError(f"no room is configured for a {meeting.kind} meeting")
            return await self._room.run(meeting_id)
        if status in _REFUSED:
            return await self._cancel(meeting_id)
        raise MeetingNotApprovedError(f"meeting {meeting_id} has no approved start")

    def _require_forecast(self, meeting: Meeting) -> None:
        """A live room never starts unless the owner could see its range and its cap."""
        if not self._kinds.get(meeting.kind).live:
            return
        shown = (meeting.estimate_micros, meeting.estimate_high_micros, meeting.cost_cap_micros)
        if None in shown or meeting.estimate_source is None:
            raise MeetingError(f"room {meeting.id} has no cost range and hard cap to approve")

    def _require_person(self, kind: str, approval: Approval | None) -> None:
        """A room the owner must start is never started on an agent's own approval."""
        if approval is None or not self._kinds.get(kind).owner_starts:
            return
        confirmation = approval.confirmation_kind
        if confirmation is not None and default_confirmations.get(confirmation).by_agent:
            raise MeetingNotApprovedError(f"a {kind} meeting needs the owner's approval")

    async def start_decided(self) -> list[Meeting]:
        """Start or cancel every requested meeting whose approval a human has decided."""
        async with self._sessions() as db:
            ids = list(
                await db.scalars(
                    select(Meeting.id)
                    .join(Approval, Meeting.approval_id == Approval.id)
                    .where(
                        Meeting.status == MeetingStatus.REQUESTED,
                        Approval.status.in_(_STARTABLE | _REFUSED),
                    )
                    .order_by(Meeting.id)
                )
            )
        return [await self.start(meeting_id) for meeting_id in ids]

    async def request_due(self, project_id: int) -> list[Meeting]:
        """Request each kind whose cadence has elapsed. No cadence is set by default."""
        requested = []
        for kind, seconds in sorted(self._settings.cadence_seconds.items()):
            async with self._sessions() as db:
                latest = await db.scalar(
                    select(func.max(Meeting.created_at)).where(
                        Meeting.project_id == project_id,
                        Meeting.kind == kind,
                        Meeting.status != MeetingStatus.CANCELLED,
                    )
                )
            if latest is not None and self._clock.now() - latest < timedelta(seconds=seconds):
                continue
            requested.append(await self.request(project_id=project_id, kind=kind))
        return requested

    async def _cancel(self, meeting_id: int) -> Meeting:
        async with self._sessions() as db:
            await db.execute(
                update(Meeting)
                .where(Meeting.id == meeting_id, Meeting.status == MeetingStatus.REQUESTED)
                .values(status=MeetingStatus.CANCELLED, ended_at=self._clock.now())
            )
            await db.commit()
            return await db.get_one(Meeting, meeting_id)


def _forecast_payload(forecast: Forecast, settings: MeetingSettings) -> dict[str, object]:
    return {
        "estimate_micros": forecast.low_micros,
        "estimate_high_micros": forecast.high_micros,
        "estimate_source": forecast.source.value,
        "cost_cap_micros": settings.decision_cost_cap_micros,
    }


async def _attendees(
    db: AsyncSession, project: Project, kind: MeetingKind, explicit: Sequence[int] | None
) -> list[Agent]:
    """The agents who attend, facilitator first. An explicit list overrides the kind's roles."""
    if explicit is not None:
        query = select(Agent).where(Agent.id.in_(explicit))
    else:
        query = select(Agent).where(
            Agent.project_id == project.id,
            Agent.status == AgentStatus.ACTIVE,
            Agent.role.in_(kind.participant_roles),
        )
    agents = list(await db.scalars(query.order_by(Agent.id)))
    missing = set(explicit or ()) - {agent.id for agent in agents}
    if missing:
        raise MeetingError(f"no agents {sorted(missing)}")
    # Turns run under the project, so its budget counts them: only its own agents attend.
    outsiders = [agent.id for agent in agents if agent.project_id != project.id]
    if outsiders:
        raise MeetingError(f"agents {outsiders} do not belong to project {project.name!r}")
    if kind.includes_ceo:
        ceo = await find_ceo(db)
        if ceo is None or ceo.status is not AgentStatus.ACTIVE:
            raise MeetingError("the CEO is not set up or not active")
        if not agents:
            raise MeetingError(f"project {project.name!r} has no manager to call")
        agents.insert(0, ceo)
    if not agents:
        raise MeetingError(f"project {project.name!r} has no agents for a {kind.key} meeting")
    # A stable sort keeps id order among the rest.
    agents.sort(key=lambda agent: agent.role != kind.facilitator_role)
    return agents
