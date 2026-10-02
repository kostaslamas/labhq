"""Handoffs between agents render as terse, structured text in a fixed field order."""

import pytest
from pydantic import ValidationError

from labhq.economy.handoff import Handoff, render_handoff

FIELD_ORDER = ["summary", "done", "next", "blockers", "refs"]


def test_a_handoff_renders_one_line_per_field_in_fixed_order() -> None:
    handoff = Handoff(
        summary="Login form validated server-side.",
        done=("added schema", "wired endpoint"),
        next=("add rate limit",),
        blockers=(),
        refs=("feat/login", "task#12"),
    )
    assert render_handoff(handoff) == (
        "summary: Login form validated server-side.\n"
        "done: added schema; wired endpoint\n"
        "next: add rate limit\n"
        "blockers: -\n"
        "refs: feat/login; task#12"
    )


def test_field_order_does_not_depend_on_construction_order() -> None:
    handoff = Handoff.model_validate(
        {"refs": ["r"], "blockers": ["b"], "next": ["n"], "done": ["d"], "summary": "s"}
    )
    keys = [line.split(":", 1)[0] for line in render_handoff(handoff).splitlines()]
    assert keys == FIELD_ORDER


def test_every_field_is_present_even_when_empty() -> None:
    rendered = render_handoff(Handoff(summary="nothing yet"))
    assert rendered.splitlines() == [
        "summary: nothing yet",
        "done: -",
        "next: -",
        "blockers: -",
        "refs: -",
    ]


def test_multiline_values_cannot_break_the_structure() -> None:
    handoff = Handoff(summary="first\n\nsecond", done=("a\n  b", "   "))
    lines = render_handoff(handoff).splitlines()
    assert len(lines) == len(FIELD_ORDER)
    assert lines[0] == "summary: first second"
    assert lines[1] == "done: a b"


def test_the_rendering_is_terse() -> None:
    rendered = render_handoff(Handoff(summary="s", done=("d",)))
    # No headings, bullets, blank lines or prose around the fields.
    assert "\n\n" not in rendered
    assert not any(line.startswith(("#", "-", "*")) for line in rendered.splitlines())


def test_a_handoff_needs_a_summary() -> None:
    with pytest.raises(ValidationError):
        Handoff(summary="")


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Handoff.model_validate({"summary": "s", "mood": "great"})
