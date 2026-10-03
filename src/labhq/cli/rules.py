"""`labhq rules list|add|enable|disable`: health rules, each with the reason it exists."""

import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import typer

from labhq.cli.context import CliError, Context, execute, fail
from labhq.db.enums import HealthRuleAction
from labhq.health.manage import (
    RuleError,
    RuleView,
    add_rule,
    list_rules,
    set_enabled,
)

rules_app = typer.Typer(help="Health rules: list, add, enable, disable.", no_args_is_help=True)

OPERATOR = "operator"


def rule_line(view: RuleView) -> str:
    rule = view.rule
    state = "enabled" if rule.enabled else "disabled"
    latest = "no incident yet"
    if view.latest is not None:
        latest = f"incident {view.latest.id} {view.latest.status}"
    return (
        f"rule {rule.id} {rule.name!r}: {rule.type} -> {rule.action}, {state}, "
        f"by {rule.created_by}, params {json.dumps(rule.params, sort_keys=True)}, "
        f"reason {rule.reason!r}, {latest}"
    )


@rules_app.command("list")
def list_command() -> None:
    """Every rule with its type, params, action, reason, creator, state and latest incident."""

    async def body(context: Context) -> list[str]:
        async with context.sessions() as db:
            return [rule_line(view) for view in await list_rules(db)]

    lines = execute(body)
    typer.echo("\n".join(lines) if lines else "no rules")


@rules_app.command("add")
def add(
    rule_type: Annotated[str, typer.Argument(help="Rule type, for example threshold or trend.")],
    reason: Annotated[str, typer.Option(help="Why the rule exists. Required.")],
    params: Annotated[str, typer.Option(help="JSON object of the type's params.")] = "{}",
    action: Annotated[HealthRuleAction, typer.Option(help="What a violation does.")] = (
        HealthRuleAction.NOTIFY
    ),
    name: Annotated[
        str | None, typer.Option(help="A short name. Default: from type and params.")
    ] = None,
    host: Annotated[
        int | None, typer.Option(help="Bind to one host id. Default: every host.")
    ] = None,
    by: Annotated[str, typer.Option(help="Who adds the rule.")] = OPERATOR,
) -> None:
    """Add an enabled rule; its params are validated by its type."""
    try:
        parsed: Any = json.loads(params)
    except ValueError as error:
        fail(f"--params is not valid JSON: {error}")
    if not isinstance(parsed, dict):
        fail("--params must be a JSON object")

    async def body(context: Context) -> str:
        async with context.sessions() as db, db.begin():
            rule = await add_rule(
                db,
                context.clock,
                rule_type=rule_type,
                params=parsed,
                action=action,
                reason=reason,
                created_by=by,
                name=name,
                host_id=host,
            )
            return f"rule {rule.id} added"

    typer.echo(_guarded(body))


def _toggle(rule_id: int, enabled: bool, by: str) -> str:
    async def body(context: Context) -> str:
        async with context.sessions() as db, db.begin():
            rule = await set_enabled(db, context.clock, rule_id, enabled=enabled, by=by)
            return f"rule {rule.id} {'enabled' if rule.enabled else 'disabled'}"

    return _guarded(body)


def _guarded[T](command: Callable[[Context], Awaitable[T]]) -> T:
    async def body(context: Context) -> T:
        try:
            return await command(context)
        except RuleError as error:
            raise CliError(str(error)) from error

    return execute(body)


@rules_app.command("enable")
def enable(
    rule_id: Annotated[int, typer.Argument(help="The rule's id.")],
    by: Annotated[str, typer.Option(help="Who enables it.")] = OPERATOR,
) -> None:
    """Evaluate the rule again."""
    typer.echo(_toggle(rule_id, True, by))


@rules_app.command("disable")
def disable(
    rule_id: Annotated[int, typer.Argument(help="The rule's id.")],
    by: Annotated[str, typer.Option(help="Who disables it.")] = OPERATOR,
) -> None:
    """Stop evaluating the rule; it stays listed."""
    typer.echo(_toggle(rule_id, False, by))
