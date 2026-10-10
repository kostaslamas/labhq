"""Meeting kinds as data: `kind -> MeetingKind`. A new kind is one `register` call."""

from dataclasses import dataclass

from labhq.approvals.registry import Registry


@dataclass(frozen=True)
class MeetingKind:
    """What a kind of meeting is: its agenda, who attends, how long, what the minutes hold.

    `agenda` is a template formatted with `project`. Default participants are the project's
    active agents whose role is in `participant_roles`; an explicit list overrides them.
    The facilitator is the first participant whose role is `facilitator_role`.
    """

    key: str
    agenda: str
    participant_roles: frozenset[str]
    rounds: int
    minutes_instruction: str
    facilitator_role: str = "manager"
    # A live kind is a thread the owner takes part in, driven by `labhq.meetings.room`.
    live: bool = False
    # The global CEO attends besides the project's own agents.
    includes_ceo: bool = False
    # Only the owner may approve its start; the CEO's own `start_meeting` refuses it.
    owner_starts: bool = False

    def __post_init__(self) -> None:
        if self.rounds < 1:
            raise ValueError(f"meeting kind {self.key!r} needs at least one round")


MANAGER_AND_LEADS = frozenset({"manager", "lead"})

STANDUP = MeetingKind(
    key="standup",
    agenda="Standup for {project}: each participant says what is done, what is next and "
    "what blocks them.",
    participant_roles=MANAGER_AND_LEADS,
    rounds=1,
    minutes_instruction="Record a decision for every blocker resolved and an action item for "
    "every next step someone committed to.",
)

PLANNING = MeetingKind(
    key="planning",
    agenda="Planning for {project}: agree the next goals, split them into tasks and pick an "
    "owner for each.",
    participant_roles=MANAGER_AND_LEADS,
    rounds=2,
    minutes_instruction="Record each agreed goal as a decision and each task as an action "
    "item linked to its goal.",
)

REVIEW = MeetingKind(
    key="review",
    agenda="Review for {project}: go over what shipped since the last review, what failed "
    "and what to change.",
    participant_roles=MANAGER_AND_LEADS,
    rounds=1,
    minutes_instruction="Record each conclusion as a decision and each follow-up as an action "
    "item.",
)

DECISION = MeetingKind(
    key="decision",
    agenda="Decision room for {project}: the owner, the CEO and the project's manager settle "
    "one proposal.",
    participant_roles=frozenset({"manager"}),
    rounds=1,
    facilitator_role="ceo",
    live=True,
    includes_ceo=True,
    owner_starts=True,
    minutes_instruction="Record as a decision only what the owner agreed in the thread. Add an "
    "action item only for a step the owner asked for or accepted; leave out anything the "
    "owner did not confirm.",
)

default_kinds = Registry[MeetingKind]("meeting kind")
for _kind in (STANDUP, PLANNING, REVIEW, DECISION):
    default_kinds.register(_kind.key, _kind)
