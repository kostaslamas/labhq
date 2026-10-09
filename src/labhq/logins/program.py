"""The login duty of the always-on program, and the service built on labhq's tmux server."""

from labhq.adapters.tmux import get_tmux_settings
from labhq.adapters.tmux.server import TmuxMissingError, TmuxServer
from labhq.cli.context import Context
from labhq.logins.panes import TmuxPanes
from labhq.logins.service import LoginService
from labhq.logins.watch import login_pass

TMUX_STATE_DIR = "tmux"
WORK_DIR = "logins"


def default_login_service(context: Context) -> LoginService | None:
    """None where tmux is not installed: there is no pane to run a login command in."""
    data_dir = context.settings.data_dir
    try:
        server = TmuxServer(socket=get_tmux_settings().socket, state_dir=data_dir / TMUX_STATE_DIR)
    except TmuxMissingError:
        return None
    return LoginService(
        context.sessions, context.clock, TmuxPanes(server), work_dir=data_dir / WORK_DIR
    )


async def login_duty(context: Context) -> int:
    service = default_login_service(context)
    if service is None:
        return 0
    return await login_pass(context.sessions, context.clock, service)
