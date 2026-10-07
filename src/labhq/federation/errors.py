"""Federation failures an operator or an agent can act on."""

from labhq.work import WorkError


class FederationError(WorkError):
    """A federation request that cannot be carried out as given.

    A `WorkError`, so the CLI prints it as one line and a role tool hands it back to the agent
    as a refusal instead of a traceback.
    """


class UnauthorizedError(FederationError):
    """The key is missing, unknown, revoked or lacks the scope. One answer for all four."""
