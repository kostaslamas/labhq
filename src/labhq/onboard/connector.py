"""Step: the MCP connector token exists and is kept across runs."""

from labhq.mcp.auth import ensure_token, load_token
from labhq.onboard.base import Detection, ManualAction, OnboardContext, Outcome, StepError


class ConnectorTokenStep:
    name = "connector token"
    required = True

    def detect(self, context: OnboardContext) -> Detection:
        if load_token(context.settings.data_dir):
            return Detection(True, "kept from an earlier run")
        return Detection(False, "none yet")

    def manual(self, context: OnboardContext, detection: Detection) -> ManualAction | None:
        return None

    def automate(self, context: OnboardContext) -> None:
        try:
            context.token = ensure_token(context.settings.data_dir)
        except OSError as error:
            raise StepError(f"cannot store the token: {error.strerror or error}") from error

    def verify(self, context: OnboardContext) -> Outcome:
        stored = load_token(context.settings.data_dir)
        if not stored or stored != context.token:
            raise StepError("the stored token does not match the one issued")
        return Outcome("stored with mode 0600")
