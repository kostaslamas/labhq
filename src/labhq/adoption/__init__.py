"""Adopt a running agent as a project's manager (ADR 0005).

Discovery lists running CLI agents from the process table. Adoption is a light
`adopt_agent` approval; once the owner approves it, the engine waits for the agent's turn
to end, ends the process and continues its conversation on labhq's private tmux server, in
the same directory, as the project's manager under the CEO. `AdoptedChecks` then checks
what the manager does.

Importing this package registers the `adopt_agent` action type and executor with
`labhq.approvals`.
"""

from labhq.adoption.checks import CHECKOUT_CHANGED, AdoptedChecks, CheckReport
from labhq.adoption.discovery import RunningAgent, discover, find_running
from labhq.adoption.move import AdoptionEngine, end_process
from labhq.adoption.observe import AdoptionError, OwnerTmux
from labhq.adoption.request import (
    ADOPT_AGENT,
    ADOPT_SAVED_SESSION,
    NO_ISOLATION_WARNING,
    AdoptionRequest,
    Adoptions,
    AdoptPayload,
    SavedSessionPayload,
)
from labhq.adoption.rules import MANAGER_RULES, RULES_RELATIVE_PATH, STATUS_REQUEST, rules_message
from labhq.adoption.settings import AdoptionSettings, get_adoption_settings
from labhq.adoption.state import AdoptionState, state_of
from labhq.approvals import ActionType, Executor, default_actions, default_executors
from labhq.db.enums import RiskClass


def adoption_executor(engine: AdoptionEngine) -> Executor:
    return Executor(run=engine.run, validate=AdoptPayload.model_validate)


# Light: the conversation is kept (ADR 0005). It still ends the owner's process, so it
# always waits for the owner.
default_actions.register(ADOPT_AGENT, ActionType(ADOPT_AGENT, RiskClass.LIGHT))
default_executors.register(ADOPT_AGENT, adoption_executor(AdoptionEngine()))
default_actions.register(ADOPT_SAVED_SESSION, ActionType(ADOPT_SAVED_SESSION, RiskClass.LIGHT))
default_executors.register(
    ADOPT_SAVED_SESSION,
    Executor(run=AdoptionEngine().run_saved, validate=SavedSessionPayload.model_validate),
)

__all__ = [
    "ADOPT_AGENT",
    "CHECKOUT_CHANGED",
    "MANAGER_RULES",
    "NO_ISOLATION_WARNING",
    "RULES_RELATIVE_PATH",
    "STATUS_REQUEST",
    "AdoptPayload",
    "AdoptedChecks",
    "AdoptionEngine",
    "AdoptionError",
    "AdoptionRequest",
    "AdoptionSettings",
    "AdoptionState",
    "Adoptions",
    "CheckReport",
    "OwnerTmux",
    "RunningAgent",
    "adoption_executor",
    "discover",
    "end_process",
    "find_running",
    "get_adoption_settings",
    "rules_message",
    "state_of",
]
