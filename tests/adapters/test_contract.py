"""The adapter contract, run against every registered adapter.

The fake runs as it is; the Claude adapter runs with `ClaudeSDKClient` stubbed at the
boundary, and the Ollama adapter against a fake `/api/chat` on `httpx.MockTransport`. A real
login or a local Ollama runs the same checks by hand (docs/checks/claude-adapter.md,
docs/checks/ollama-adapter.md).
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from labhq.adapters import AdapterFactory, FakeAdapter, FakeScript, default_registry
from labhq.adapters.contract import CHECKS, ContractViolationError, check_interrupt
from tests.adapters.fake_ollama import FakeOllama
from tests.adapters.stub_sdk import StubScript, stub_claude


def _fake(check: str, tmp_path: Path) -> AdapterFactory:
    script = FakeScript(wait_for_interrupt=check == "interrupt")
    return lambda: FakeAdapter(script)


def _claude(check: str, tmp_path: Path) -> AdapterFactory:
    return stub_claude(StubScript(wait_for_interrupt=check == "interrupt"))


def _ollama(check: str, tmp_path: Path) -> AdapterFactory:
    return FakeOllama(hold=check == "interrupt").factory(tmp_path / "sessions")


HARNESSES: dict[str, Callable[[str, Path], AdapterFactory]] = {
    "fake": _fake,
    "claude": _claude,
    "ollama": _ollama,
}


def test_every_registered_adapter_has_a_contract_harness() -> None:
    # A new registration without a harness would otherwise skip the contract silently.
    assert sorted(HARNESSES) == default_registry.adapter_keys()


@pytest.mark.parametrize("check", sorted(CHECKS))
@pytest.mark.parametrize("key", default_registry.adapter_keys())
async def test_adapter_honours_the_contract(key: str, check: str, tmp_path: Path) -> None:
    results = await CHECKS[check](HARNESSES[key](check, tmp_path), tmp_path)
    assert results


async def test_the_contract_rejects_an_interrupt_reported_as_a_failure(tmp_path: Path) -> None:
    # Proves the interrupt check can fail: an adapter that ignores the abort reason
    # and reports a plain error is caught.
    script = FakeScript(subtype="error_during_execution", is_error=True, terminal_reason=None)
    with pytest.raises(ContractViolationError, match="interrupted"):
        await check_interrupt(lambda: _MisreportingFake(script), tmp_path)


class _MisreportingFake(FakeAdapter):
    async def interrupt(self) -> None:
        self.script.interrupts += 1
