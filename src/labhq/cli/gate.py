"""`labhq gate test|resend`: try the configured approval gate, re-send a stalled request."""

import asyncio
from pathlib import Path

import httpx
import typer

from labhq.approvals import ApprovalService
from labhq.approvals.gates import GateError, GateRelay, GateRequest, GateSettings, build_gate
from labhq.cli.context import Context, execute, fail

gate_app = typer.Typer(help="The external approval gate.", no_args_is_help=True)

TEST_COMMAND = "labhq gate test (harmless: nothing runs when this is approved)"


async def _send_test(settings: GateSettings) -> tuple[str, str, str | None]:
    async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
        gate = build_gate(settings, client)
        request_id = await gate.send(GateRequest(TEST_COMMAND, str(Path.cwd())))
        answer = await gate.status(request_id)
    return request_id, answer.status.value, answer.via


@gate_app.command("test")
def test() -> None:
    """Send a harmless request to the gate and print its answer."""
    settings = GateSettings()
    try:
        request_id, status, via = asyncio.run(_send_test(settings))
    except GateError as error:
        fail(str(error))
    typer.echo(f"request {request_id}: {status}" + (f" via {via}" if via else ""))


@gate_app.command("resend")
def resend(approval_id: int) -> None:
    """Send an approval to the gate again after its request expired or lacked a passkey."""

    async def body(context: Context) -> None:
        settings = GateSettings()
        async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
            try:
                relay = GateRelay(
                    context.sessions,
                    ApprovalService(context.sessions, clock=context.clock),
                    build_gate(settings, client),
                    name=settings.name,
                    passkey_proofs=settings.proofs,
                )
                await relay.resend(approval_id)
            except GateError as error:
                fail(str(error))

    execute(body)
    typer.echo(f"approval {approval_id} will go to the gate on the next pass")
