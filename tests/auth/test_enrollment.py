"""Enrollment links: one use, an expiry, and a host they cannot leave."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from labhq.auth.settings import AuthSettings
from labhq.cli.context import Context
from labhq.clock import FakeClock
from labhq.db.models import PasskeyCredential
from tests.auth.authenticator import SoftwareAuthenticator
from tests.auth.conftest import LOCAL, PUBLIC, WRITE, enroll, link_token, log_in


async def test_an_enrollment_link_works_once(
    app_client: TestClient, context: Context, settings: AuthSettings
) -> None:
    token = await link_token(context, settings)
    first = enroll(app_client, token, SoftwareAuthenticator())
    assert first.status_code == 200
    assert first.json()["rp_id"] == "localhost"

    second = app_client.post("/api/auth/enroll/options", json={"token": token})
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "enrollment_link_invalid"


async def test_a_link_cannot_be_spent_by_two_registrations_in_flight(
    app_client: TestClient, context: Context, settings: AuthSettings
) -> None:
    token = await link_token(context, settings)
    options = [
        app_client.post("/api/auth/enroll/options", json={"token": token}).json() for _ in range(2)
    ]
    keys = [SoftwareAuthenticator(), SoftwareAuthenticator()]
    results = [
        app_client.post(
            "/api/auth/enroll/verify",
            json={"token": token, "credential": key.create(opts, LOCAL)},
        )
        for key, opts in zip(keys, options, strict=True)
    ]
    assert sorted(r.status_code for r in results) == [200, 400]
    async with context.sessions() as db:
        assert len((await db.scalars(select(PasskeyCredential))).all()) == 1


async def test_an_expired_link_fails(
    app_client: TestClient, context: Context, settings: AuthSettings, clock: FakeClock
) -> None:
    token = await link_token(context, settings)
    clock.advance(timedelta(seconds=settings.enrollment_ttl_seconds + 1))
    response = app_client.post("/api/auth/enroll/options", json={"token": token})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "enrollment_link_invalid"


async def test_a_link_for_the_public_host_does_not_enroll_on_localhost(
    app_client: TestClient, context: Context, settings: AuthSettings
) -> None:
    token = await link_token(context, settings, PUBLIC)
    response = app_client.post("/api/auth/enroll/options", json={"token": token})
    assert response.status_code == 400


async def test_an_unknown_origin_cannot_enroll(
    app_client: TestClient, context: Context, settings: AuthSettings
) -> None:
    token = await link_token(context, settings)
    response = app_client.post(
        "/api/auth/enroll/options", json={"token": token}, headers={"Origin": "https://evil.test"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


async def test_a_passkey_enrolled_on_localhost_does_not_work_on_the_public_host(
    app_client: TestClient, enrolled: SoftwareAuthenticator
) -> None:
    options = app_client.post("/api/auth/login/options", headers={"Origin": PUBLIC})
    assert options.status_code == 409
    assert options.json()["error"]["code"] == "no_passkey"
    # An assertion made for localhost cannot be replayed against the public relying party.
    local = app_client.post("/api/auth/login/options").json()
    response = app_client.post(
        "/api/auth/login/verify",
        json={"credential": enrolled.get(local, LOCAL)},
        headers={"Origin": PUBLIC},
    )
    assert response.status_code == 400


async def test_a_signed_in_session_enrolls_the_public_host_with_a_qr_link(
    signed_in: TestClient,
) -> None:
    response = signed_in.post("/api/auth/enrollment-links", json={}, headers=WRITE)
    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith(f"{PUBLIC}/enroll#")
    assert body["qr"].startswith("data:image/svg+xml")

    phone = SoftwareAuthenticator()
    token = body["url"].split("#", 1)[1]
    assert enroll(signed_in, token, phone, PUBLIC).status_code == 200
    # The phone's passkey signs in on the public host, not on localhost.
    assert log_in(signed_in, phone, PUBLIC).status_code == 200
    local = signed_in.post("/api/auth/login/options").json()
    refused = signed_in.post("/api/auth/login/verify", json={"credential": phone.get(local, LOCAL)})
    assert refused.status_code == 401


async def test_link_creation_needs_a_session(app_client: TestClient) -> None:
    response = app_client.post("/api/auth/enrollment-links", json={}, headers=WRITE)
    assert response.status_code == 401
