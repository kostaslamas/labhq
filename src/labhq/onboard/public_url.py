"""Step: a Cloudflare quick tunnel publishes the connector and answers `initialize`."""

from labhq.expose import ExposureError, connector_url, exposures, verify_connector
from labhq.mcp.server import build_app
from labhq.mcp.tools.registry import default_registry
from labhq.onboard.base import Detection, ManualAction, OnboardContext, Outcome, StepError
from labhq.onboard.platforms import DOWNLOADS_PAGE, cloudflared_install_command
from labhq.onboard.server import ThreadServer

EXPOSURE = "quick-tunnel"
BINARY = "cloudflared"


class PublicUrlStep:
    name = "public URL"
    required = True

    def detect(self, context: OnboardContext) -> Detection:
        path = context.which(BINARY)
        if path is None:
            return Detection(False, f"{BINARY} not found")
        return Detection(True, f"{BINARY} at {path}")

    def manual(self, context: OnboardContext, detection: Detection) -> ManualAction | None:
        # Never a silent fall back to a local-only server: without the tunnel there is no URL.
        if context.which(BINARY) is not None:
            return None
        command = cloudflared_install_command(context.platform)
        return ManualAction(f"Install cloudflared: {command}", link=DOWNLOADS_PAGE)

    def automate(self, context: OnboardContext) -> None:
        if context.token is None:
            raise StepError("no connector token; the connector token step must run first")
        settings = context.onboard
        server = ThreadServer(
            build_app(default_registry, context.token), host=settings.host, port=settings.port
        )
        context.resources.callback(server.stop)
        server.start(settings.server_start_timeout_seconds)
        context.server = server
        try:
            exposure = exposures.get(EXPOSURE)().open(settings.port)
        except ExposureError as error:
            raise StepError(str(error)) from error
        context.resources.callback(exposure.close)
        context.public_url = exposure.url

    def verify(self, context: OnboardContext) -> Outcome:
        if context.public_url is None or context.token is None:
            raise StepError("no tunnel is open")
        try:
            verify_connector(
                context.public_url,
                context.token,
                attempts=context.onboard.verify_attempts,
                delay=context.onboard.verify_delay_seconds,
            )
        except ExposureError as error:
            raise StepError(str(error)) from error
        return Outcome(
            f"{context.public_url} answers `initialize`",
            label="Connector URL",
            link=connector_url(context.public_url, context.token),
            qr=True,
        )
