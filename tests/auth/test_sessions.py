"""Sign-in, the session cookie, its expiry and what is stored."""

import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from labhq.auth.settings import AuthSettings
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db.models import PasskeyCredential, WebauthnChallenge, WebSession
from tests.auth.authenticator import SoftwareAuthenticator
from tests.auth.conftest import LOCAL, PUBLIC, WRITE, enroll, link_token, log_in


async def test_without_a_session_every_authenticated_route_is_401(app_client: TestClient) -> None:
    for method, path in [
        ("get", "/api/auth/credentials"),
        ("post", "/api/auth/logout"),
        ("post", "/api/auth/step-up/options"),
        ("post", "/api/auth/enrollment-links"),
        ("delete", "/api/auth/credentials/1"),
    ]:
        response = getattr(app_client, method)(path, headers=WRITE)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "unauthorized"
    status = app_client.get("/api/auth/status")
    assert status.json() == {"authenticated": False, "enrolled": False}


async def test_logging_in_with_a_passkey_creates_a_session(
    app_client: TestClient, enrolled: SoftwareAuthenticator
) -> None:
    response = log_in(app_client, enrolled)
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "enrolled": True}
    assert app_client.get("/api/auth/credentials").status_code == 200
    assert app_client.get("/api/auth/status").json()["authenticated"] is True


async def test_the_cookie_is_http_only_strict_and_secure_off_loopback(
    app_client: TestClient,
    enrolled: SoftwareAuthenticator,
    context: Context,
    settings: AuthSettings,
) -> None:
    local = log_in(app_client, enrolled).headers["set-cookie"].lower()
    assert "httponly" in local
    assert "samesite=strict" in local
    assert "secure" not in local

    # The public host is reached over https and gets a Secure cookie.
    phone = SoftwareAuthenticator()
    token = await link_token(context, settings, PUBLIC)
    assert enroll(app_client, token, phone, PUBLIC).status_code == 200
    with TestClient(app_client.app, base_url=PUBLIC, headers={"Origin": PUBLIC}) as remote:
        public = log_in(remote, phone, PUBLIC).headers["set-cookie"].lower()
    assert "secure" in public
    assert "httponly" in public


async def test_a_write_needs_the_custom_header(signed_in: TestClient) -> None:
    response = signed_in.post("/api/auth/enrollment-links", json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "write_header_required"
    assert signed_in.post("/api/auth/enrollment-links", json={}, headers=WRITE).status_code == 200


async def test_logout_ends_the_session(signed_in: TestClient) -> None:
    assert signed_in.post("/api/auth/logout", headers=WRITE).status_code == 200
    assert signed_in.get("/api/auth/credentials").status_code == 401


async def test_a_session_expires_when_idle(
    signed_in: TestClient, clock: FakeClock, settings: AuthSettings
) -> None:
    clock.advance(timedelta(seconds=settings.session_idle_seconds - 60))
    assert signed_in.get("/api/auth/credentials").status_code == 200
    clock.advance(timedelta(seconds=settings.session_idle_seconds + 1))
    assert signed_in.get("/api/auth/credentials").status_code == 401


async def test_a_session_expires_at_the_absolute_limit_however_active(
    signed_in: TestClient, clock: FakeClock, settings: AuthSettings
) -> None:
    step = timedelta(seconds=settings.session_idle_seconds - 60)
    elapsed = timedelta(0)
    while elapsed + step < timedelta(seconds=settings.session_absolute_seconds):
        clock.advance(step)
        elapsed += step
        assert signed_in.get("/api/auth/credentials").status_code == 200
    clock.advance(step)
    assert signed_in.get("/api/auth/credentials").status_code == 401


async def test_revoking_a_passkey_ends_its_sessions_and_blocks_login(
    signed_in: TestClient, enrolled: SoftwareAuthenticator
) -> None:
    listed = signed_in.get("/api/auth/credentials").json()
    assert [row["revoked"] for row in listed] == [False]
    revoked = signed_in.delete(f"/api/auth/credentials/{listed[0]['id']}", headers=WRITE)
    assert revoked.json()["revoked"] is True
    assert signed_in.get("/api/auth/credentials").status_code == 401

    # No active passkey is left, so there is nothing to sign in with.
    assert signed_in.post("/api/auth/login/options").status_code == 409


async def test_a_revoked_credential_assertion_is_rejected(
    signed_in: TestClient, enrolled: SoftwareAuthenticator, context: Context
) -> None:
    options = signed_in.post("/api/auth/login/options").json()
    async with context.sessions() as db:
        row = (await db.scalars(select(PasskeyCredential))).one()
        row.revoked_at = context.clock.now()
        await db.commit()
    response = signed_in.post(
        "/api/auth/login/verify", json={"credential": enrolled.get(options, LOCAL)}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "credential_revoked"


async def test_a_sign_count_regression_is_rejected(
    app_client: TestClient, enrolled: SoftwareAuthenticator
) -> None:
    assert log_in(app_client, enrolled).status_code == 200
    assert log_in(app_client, enrolled).status_code == 200
    # A clone replays an old counter value.
    options = app_client.post("/api/auth/login/options").json()
    response = app_client.post(
        "/api/auth/login/verify",
        json={"credential": enrolled.get(options, LOCAL, sign_count=1)},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "assertion_invalid"


async def test_a_login_challenge_is_single_use(
    app_client: TestClient, enrolled: SoftwareAuthenticator
) -> None:
    options = app_client.post("/api/auth/login/options").json()
    assertion = enrolled.get(options, LOCAL)
    assert (
        app_client.post("/api/auth/login/verify", json={"credential": assertion}).status_code == 200
    )
    replay = app_client.post("/api/auth/login/verify", json={"credential": assertion})
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "challenge_invalid"


async def test_an_assertion_without_user_verification_is_rejected(
    app_client: TestClient, enrolled: SoftwareAuthenticator
) -> None:
    enrolled.user_verified = False
    assert log_in(app_client, enrolled).status_code == 401


async def test_only_hashes_are_stored_and_nothing_secret_is_logged(
    app_client: TestClient,
    context: Context,
    settings: AuthSettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    authenticator = SoftwareAuthenticator()
    token = await link_token(context, settings)
    enrollment_options = app_client.post("/api/auth/enroll/options", json={"token": token}).json()
    attestation = authenticator.create(enrollment_options, LOCAL)
    app_client.post("/api/auth/enroll/verify", json={"token": token, "credential": attestation})
    login_options = app_client.post("/api/auth/login/options").json()
    assertion = authenticator.get(login_options, LOCAL)
    login = app_client.post("/api/auth/login/verify", json={"credential": assertion})
    cookie = app_client.cookies.get("labhq_session")
    assert login.status_code == 200 and cookie
    app_client.post("/api/auth/login/verify", json={"credential": assertion})  # a replay

    secrets_ = [
        token,
        cookie,
        enrollment_options["challenge"],
        login_options["challenge"],
        assertion["response"]["signature"],
        assertion["response"]["clientDataJSON"],
        attestation["response"]["attestationObject"],
    ]
    log = caplog.text
    assert all(secret not in log for secret in secrets_)

    async with context.sessions() as db:
        stored = (await db.scalars(select(WebSession))).one()
        assert cookie not in stored.token_hash
        assert len(stored.token_hash) == 64
        # The enrollment link is stored hashed, too.
        links = (await db.scalars(select(WebauthnChallenge.challenge))).all()
        assert token not in links
