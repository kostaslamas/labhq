"""The Ollama adapter against a fake `/api/chat`: streaming, resume, interrupt and failures."""

from pathlib import Path

import pytest

from labhq.adapters import AdapterError, RunRequest
from labhq.adapters.contract import run_once
from labhq.adapters.ollama import OllamaAdapter
from labhq.adapters.ollama_sessions import SessionStore
from labhq.db.enums import RunStatus
from labhq.runs.status import status_for
from tests.adapters.fake_ollama import MODEL, FakeOllama


def _request(prompt: str, resume: str | None = None, **config: object) -> RunRequest:
    return RunRequest(prompt=prompt, resume_session_id=resume, config=config)


async def test_chunks_stream_as_assistant_events_and_the_final_counts_are_usage(
    tmp_path: Path,
) -> None:
    server = FakeOllama(reply=lambda messages: "two words")
    events, result = await run_once(server.factory(tmp_path)(), _request("hi"))

    assert [e.kind for e in events] == ["system", "assistant", "assistant", "result"]
    assert [e.payload["text"] for e in events if e.kind == "assistant"] == ["two", " words"]
    assert server.requests[0]["stream"] is True
    assert status_for(result) is RunStatus.SUCCEEDED
    assert (result.text, result.model, result.cost_usd) == ("two words", MODEL, 0.0)
    assert result.usage == {"input_tokens": 11, "output_tokens": 2}


async def test_agent_config_overrides_the_model_and_adds_a_system_prompt(tmp_path: Path) -> None:
    server = FakeOllama(models={MODEL, "other:7b"})
    config = {"model": "other:7b", "system": "You are terse.", "options": {"temperature": 0}}
    await run_once(server.factory(tmp_path)(), _request("hi", **config))

    [body] = server.requests
    assert body["model"] == "other:7b"
    assert body["options"] == {"temperature": 0}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


async def test_a_resumed_run_sends_the_stored_conversation(tmp_path: Path) -> None:
    server = FakeOllama(reply=lambda messages: f"seen {len(messages)}")
    make = server.factory(tmp_path)
    _, first = await run_once(make(), _request("The codeword is AURORA-7."))
    _, second = await run_once(make(), _request("What was the codeword?", first.session_id))

    assert second.session_id == first.session_id
    assert server.requests[1]["messages"] == [
        {"role": "user", "content": "The codeword is AURORA-7."},
        {"role": "assistant", "content": "seen 1"},
        {"role": "user", "content": "What was the codeword?"},
    ]
    assert second.text == "seen 3"


async def test_interrupt_closes_the_stream_and_keeps_what_was_said(tmp_path: Path) -> None:
    server = FakeOllama(hold=True, reply=lambda messages: "partial answer")
    adapter = server.factory(tmp_path)()

    async def interrupt(adapter: OllamaAdapter, event: object) -> None:
        await server.held.wait()
        await adapter.interrupt()

    events, result = await run_once(adapter, _request("long task"), interrupt)  # type: ignore[arg-type]

    assert server.closed_streams == 1
    assert events[-1].kind == "result"
    assert status_for(result) is RunStatus.INTERRUPTED
    assert result.terminal_reason == "aborted_streaming"
    stored = SessionStore(tmp_path).load(str(result.session_id))
    assert stored.messages[-1] == {"role": "assistant", "content": "partial"}


async def test_an_unreachable_server_fails_and_says_to_start_ollama(tmp_path: Path) -> None:
    server = FakeOllama(refuse_connections=True)
    _, result = await run_once(server.factory(tmp_path)(), _request("hi"))

    assert status_for(result) is RunStatus.FAILED
    assert result.session_id is None
    assert "ollama serve" in result.errors[0]
    assert "http://ollama.test" in result.errors[0]


async def test_an_unknown_model_fails_and_says_what_to_pull(tmp_path: Path) -> None:
    server = FakeOllama()
    make = server.factory(tmp_path, model="missing:3b")
    _, result = await run_once(make(), _request("hi"))

    assert status_for(result) is RunStatus.FAILED
    assert "ollama pull missing:3b" in result.errors[0]
    assert list(tmp_path.iterdir()) == []


async def test_input_sent_mid_run_becomes_the_next_turn(tmp_path: Path) -> None:
    server = FakeOllama(reply=lambda messages: f"reply {len(messages)}")
    adapter = server.factory(tmp_path)()
    sent = False

    async def follow_up(adapter: OllamaAdapter, event: object) -> None:
        nonlocal sent
        if not sent:
            sent = True
            await adapter.send("And then?")

    _, result = await run_once(adapter, _request("Start."), follow_up)  # type: ignore[arg-type]

    assert len(server.requests) == 2
    assert server.requests[1]["messages"][-1] == {"role": "user", "content": "And then?"}
    assert (result.num_turns, result.text) == (2, "reply 3")


async def test_a_made_up_session_id_is_refused(tmp_path: Path) -> None:
    adapter = FakeOllama().factory(tmp_path)()
    with pytest.raises(AdapterError, match="not an Ollama session id"):
        await adapter.start(_request("hi", resume="../../etc/passwd"))
    with pytest.raises(AdapterError, match="no stored Ollama session"):
        await adapter.start(_request("hi", resume="0" * 32))
    await adapter.close()
