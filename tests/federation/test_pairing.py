"""Acceptance 1: invite, add, list and revoke; the key is stored only as a hash."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from labhq.federation.errors import FederationError, UnauthorizedError
from labhq.federation.invites import Invites
from labhq.federation.keys import hash_key
from labhq.federation.nodes import Nodes
from labhq.settings import DATABASE_FILENAME
from tests.cli.conftest import Cli, cli, data_dir
from tests.federation.conftest import NODE_NAME, Pairing
from tests.worktrees.conftest import isolated_git, remote, repo

__all__ = ["cli", "data_dir", "isolated_git", "remote", "repo"]

KEY = re.compile(r"^lhqf_\S+$", re.MULTILINE)


def _dump(data_dir: Path) -> str:
    with closing(sqlite3.connect(data_dir / DATABASE_FILENAME)) as connection:
        return "\n".join(connection.iterdump())


def test_the_cli_pairs_two_instances_and_stores_only_the_hash(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "lab", "--repo", str(repo))
    cli.ok("org", "ceo", "--adapter", "fake")

    invited = cli.ok("federation", "invite", "--label", "office")
    key = KEY.search(invited)
    assert key is not None
    secret = key.group(0)
    assert "invite 1 office: active, scopes orders,reports" in invited

    added = cli.ok(
        "federation",
        "add",
        "https://b.example",
        secret,
        "--project",
        "lab",
        "--name",
        NODE_NAME,
        "--spend-cap-usd",
        "2.5",
    )
    assert "node 1 lab-b (https://b.example): active, scopes orders,reports" in added
    assert "per-order cap $2.5000" in added

    listing = cli.ok("federation", "list")
    assert "node 1 lab-b" in listing
    assert "invite 1 office: active" in listing

    # The agent that stands for the node is a remote manager in the CEO's chart.
    [manager] = cli.rows("SELECT role, adapter, reports_to, status FROM agents WHERE id = 2")
    assert tuple(manager) == ("manager", "remote", 1, "active")
    # Only the hash is stored, on both sides of the pairing: no table holds the key.
    assert secret not in _dump(cli.data_dir)
    assert [row[0] for row in cli.rows("SELECT key_hash FROM federation_nodes")] == [
        hash_key(secret)
    ]
    assert [row[0] for row in cli.rows("SELECT key_hash FROM federation_invites")] == [
        hash_key(secret)
    ]

    assert "node 1 lab-b" in cli.ok("federation", "revoke", NODE_NAME)
    assert "revoked" in cli.ok("federation", "list")
    assert "invite 1 office: revoked" in cli.ok("federation", "revoke", "--invite", "1")


def test_a_scope_must_be_one_the_endpoint_knows(cli: Cli) -> None:
    cli.ok("init")

    result = cli("federation", "invite", "--scope", "everything")

    assert result.exit_code == 1
    assert "unknown scope everything" in result.stderr


def test_adding_needs_a_ceo_and_a_real_key(cli: Cli, repo: Path) -> None:
    cli.ok("init")
    cli.ok("project", "add", "lab", "--repo", str(repo))

    not_a_key = cli("federation", "add", "https://b.example", "nope", "--project", "lab")
    no_ceo = cli("federation", "add", "https://b.example", "lhqf_" + "x" * 30, "--project", "lab")

    assert "not a pairing key" in not_a_key.stderr
    assert "no CEO yet" in no_ceo.stderr


async def test_a_revoked_key_is_refused_on_the_next_poll(pairing: Pairing) -> None:
    await pairing.poll()

    await Nodes(pairing.upstream.sessions, clock=pairing.upstream.clock).revoke(NODE_NAME)

    with pytest.raises(UnauthorizedError, match="revoked or unknown"):
        await pairing.poll()


async def test_a_key_revoked_where_it_was_printed_stops_polling_at_once(
    pairing: Pairing,
) -> None:
    await Invites(pairing.downstream.sessions, clock=pairing.downstream.clock).revoke(1)

    with pytest.raises(FederationError, match="revoked here"):
        await pairing.poll()


async def test_the_same_key_cannot_be_registered_twice(pairing: Pairing) -> None:
    with pytest.raises(FederationError, match="already registered"):
        await Nodes(pairing.upstream.sessions, clock=pairing.upstream.clock).add(
            "https://other.example", pairing.key, project="lab", name="other"
        )
