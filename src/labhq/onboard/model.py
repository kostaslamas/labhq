"""Step: agents have a model, through the owner's Claude Code login or an API key (ADR 0001).

labhq asks the unmodified `claude` binary whether it is logged in, through its documented
`claude auth status` command, and reads only the `loggedIn` answer. It never reads, copies or
names any credential file.
"""

import json
import subprocess

from labhq.adapters.claude_env import API_KEY_VARIABLE
from labhq.onboard.base import Detection, ManualAction, OnboardContext, Outcome, StepError

CONSUMER_TERMS = "https://www.anthropic.com/legal/consumer-terms"
LEGAL_AND_COMPLIANCE = "https://code.claude.com/docs/en/legal-and-compliance"
NOTICE_FILENAME = "model-notice-shown"
NOTICE = (
    "Models: labhq starts the unmodified Claude Code binary. It uses your own Claude login "
    f"by default, or API billing when {API_KEY_VARIABLE} is set. labhq never reads, copies "
    "or stores your credentials. You are responsible for staying within your plan's terms:\n"
    f"  Consumer Terms of Service: {CONSUMER_TERMS}\n"
    f"  Legal and compliance: {LEGAL_AND_COMPLIANCE}"
)
LOGIN_ACTION = ManualAction(
    f"Log in to Claude Code by running `claude` once, or set {API_KEY_VARIABLE}; "
    "agents need one of them, the connector and notifications do not.",
    link="https://code.claude.com/docs/en/setup",
)


def claude_logged_in(binary: str, timeout: float) -> bool:
    try:
        result = subprocess.run(
            [binary, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    try:
        status = json.loads(result.stdout)
    except ValueError:
        return False
    # Only this one field is read; everything else in the answer is ignored.
    return isinstance(status, dict) and status.get("loggedIn") is True


class ModelLoginStep:
    name = "model login"
    required = False

    def detect(self, context: OnboardContext) -> Detection:
        if context.environ.get(API_KEY_VARIABLE):
            return Detection(True, f"{API_KEY_VARIABLE} is set: agents use API billing")
        binary = self._binary(context)
        if binary is None:
            return Detection(False, "Claude Code (`claude`) not found")
        if claude_logged_in(binary, context.onboard.login_check_timeout_seconds):
            return Detection(True, "Claude Code is logged in: agents use your login")
        return Detection(False, "Claude Code is not logged in")

    def manual(self, context: OnboardContext, detection: Detection) -> ManualAction | None:
        return None if detection.present else LOGIN_ACTION

    def automate(self, context: OnboardContext) -> None:
        """Show the ADR 0001 notice on the first run only, and record that it was shown."""
        marker = context.settings.data_dir / NOTICE_FILENAME
        if marker.exists():
            return
        context.say(NOTICE)
        try:
            marker.write_text(context.clock.now().isoformat() + "\n", encoding="utf-8")
        except OSError as error:
            raise StepError(f"cannot record the notice: {error.strerror or error}") from error

    def verify(self, context: OnboardContext) -> Outcome:
        detection = self.detect(context)
        if not detection.present:
            raise StepError(detection.detail)
        return Outcome(detection.detail)

    @staticmethod
    def _binary(context: OnboardContext) -> str | None:
        configured = context.settings.cli_path
        return str(configured) if configured is not None else context.which("claude")
