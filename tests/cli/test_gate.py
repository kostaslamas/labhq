import functools

import httpx
import pytest

from tests.cli.conftest import Cli

TOKEN = "s3cret-token-value"


def handler(request: httpx.Request) -> httpx.Response:
    if request.method == "POST":
        return httpx.Response(200, json={"id": "t-1"})
    return httpx.Response(200, json={"status": "pending"})


def test_gate_test_prints_the_gates_answer_and_never_the_token(
    cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABHQ_GATE_BASE_URL", "https://gate.example")
    monkeypatch.setenv("LABHQ_GATE_TOKEN", TOKEN)
    monkeypatch.setattr(
        "labhq.cli.gate.httpx.AsyncClient",
        functools.partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)),
    )

    result = cli("gate", "test")

    assert result.exit_code == 0
    assert "request t-1: pending" in result.output
    assert TOKEN not in result.output


def test_gate_test_without_a_gate_says_what_to_set(cli: Cli) -> None:
    result = cli("gate", "test")

    assert result.exit_code == 1
    assert "LABHQ_GATE_BASE_URL" in result.output
