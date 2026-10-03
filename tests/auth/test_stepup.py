"""Step-up: a fresh assertion, once, for one purpose, in the asking session."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from labhq.approvals.policy import default_confirmations
from labhq.auth import AuthError, credentials, verify_step_up
from labhq.auth.settings import AuthSettings
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db.enums import RiskClass
from labhq.db.models import WebSession
from tests.auth.authenticator import SoftwareAuthenticator
from tests.auth.conftest import LOCAL, WRITE, enroll, link_token, log_in


def challenge_for(client: TestClient, purpose: str) -> dict[str, Any]:
    response = client.post("/api/auth/step-up/options", json={"purpose": purpose}, headers=WRITE)
    assert response.status_code == 200, response.text
    options: dict[str, Any] = response.json()
    return options


async def session_id(context: Context) -> int:
    async with context.sessions() as db:
        return (await db.scalars(select(WebSession).order_by(WebSession.id))).all()[-1].id


async def verify(
    context: Context,
    sid: int,
    purpose: str,
    assertion: dict[str, Any],
    settings: AuthSettings,
) -> None:
    async with context.sessions() as db:
        try:
            await verify_step_up(
                db,
                context.clock.now(),
                session_id=sid,
                purpose=purpose,
                assertion=assertion,
                origin=LOCAL,
                settings=settings,
            )
        finally:
            await db.commit()


async def test_a_fresh_assertion_for_the_purpose_passes(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, context: Context, settings: AuthSettings
) -> None:
    options = challenge_for(signed_in, "approval:1")
    await verify(
        context, await session_id(context), "approval:1", enrolled.get(options, LOCAL), settings
    )


async def test_an_assertion_for_one_approval_does_not_pass_for_another(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, context: Context, settings: AuthSettings
) -> None:
    sid = await session_id(context)
    assertion = enrolled.get(challenge_for(signed_in, "approval:1"), LOCAL)
    with pytest.raises(AuthError) as refused:
        await verify(context, sid, "approval:2", assertion, settings)
    assert refused.value.code == "challenge_invalid"
    # The refusal did not spend the challenge: it is still good for the purpose it was issued for.
    await verify(context, sid, "approval:1", assertion, settings)


async def test_an_assertion_cannot_be_replayed(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, context: Context, settings: AuthSettings
) -> None:
    sid = await session_id(context)
    assertion = enrolled.get(challenge_for(signed_in, "approval:1"), LOCAL)
    await verify(context, sid, "approval:1", assertion, settings)
    with pytest.raises(AuthError) as refused:
        await verify(context, sid, "approval:1", assertion, settings)
    assert refused.value.code == "challenge_invalid"


async def test_a_valid_session_without_an_assertion_never_passes(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, context: Context, settings: AuthSettings
) -> None:
    sid = await session_id(context)
    assert signed_in.get("/api/auth/credentials").status_code == 200
    for bogus in ({}, {"id": enrolled.id}, {"response": {"clientDataJSON": "e30"}}):
        with pytest.raises(AuthError):
            await verify(context, sid, "approval:1", bogus, settings)
    # Even a real login assertion (a different purpose) does not stand in for a step-up.
    login = signed_in.post("/api/auth/login/options").json()
    with pytest.raises(AuthError):
        await verify(context, sid, "approval:1", enrolled.get(login, LOCAL), settings)


async def test_an_expired_challenge_is_refused(
    signed_in: TestClient,
    enrolled: SoftwareAuthenticator,
    context: Context,
    settings: AuthSettings,
    clock: FakeClock,
) -> None:
    sid = await session_id(context)
    assertion = enrolled.get(challenge_for(signed_in, "approval:1"), LOCAL)
    clock.advance(timedelta(seconds=settings.challenge_ttl_seconds + 1))
    with pytest.raises(AuthError) as refused:
        await verify(context, sid, "approval:1", assertion, settings)
    assert refused.value.code == "challenge_invalid"


async def test_a_challenge_belongs_to_the_session_that_asked(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, context: Context, settings: AuthSettings
) -> None:
    first = await session_id(context)
    assertion = enrolled.get(challenge_for(signed_in, "approval:1"), LOCAL)
    assert log_in(signed_in, enrolled).status_code == 200
    second = await session_id(context)
    assert second != first
    with pytest.raises(AuthError) as refused:
        await verify(context, second, "approval:1", assertion, settings)
    assert refused.value.code == "challenge_invalid"


async def test_a_revoked_passkey_fails_a_step_up(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, context: Context, settings: AuthSettings
) -> None:
    sid = await session_id(context)
    options = challenge_for(signed_in, "approval:1")
    # A second passkey keeps the session alive while the first is revoked.
    other = SoftwareAuthenticator()
    token = await link_token(context, settings)
    assert enroll(signed_in, token, other).status_code == 200
    listed = signed_in.get("/api/auth/credentials").json()
    async with context.sessions() as db:
        await credentials.revoke(db, listed[0]["id"], context.clock.now())
        await db.commit()
    with pytest.raises(AuthError) as refused:
        await verify(context, sid, "approval:1", enrolled.get(options, LOCAL), settings)
    assert refused.value.code == "credential_revoked"


async def test_a_malformed_purpose_is_refused(signed_in: TestClient) -> None:
    response = signed_in.post(
        "/api/auth/step-up/options", json={"purpose": "anything"}, headers=WRITE
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "purpose_invalid"


async def test_step_up_options_need_a_session(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/auth/step-up/options", json={"purpose": "approval:1"}, headers=WRITE
    )
    assert response.status_code == 401


def test_the_passkey_confirmation_kind_may_approve_heavy_and_voice_may_not() -> None:
    assert default_confirmations.get("passkey").can_approve(RiskClass.HEAVY)
    assert not default_confirmations.get("voice").can_approve(RiskClass.HEAVY)
