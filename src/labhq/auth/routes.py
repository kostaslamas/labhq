"""`/api/auth`: sign in, enroll, step up. Nothing here logs a token, challenge or assertion."""

from datetime import datetime
from typing import Annotated, Any, Literal

import segno
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from labhq.api.deps import ClockDep, OwnerDep, SessionDep, current_owner
from labhq.api.errors import ApiError
from labhq.auth import authentication, credentials, enrollment, stepup
from labhq.auth.errors import AuthError
from labhq.auth.resolver import SessionOwner, clear_session_cookie, register, set_session_cookie
from labhq.auth.sessions import revoke_session
from labhq.auth.settings import AuthSettings, get_auth_settings
from labhq.db.models import PasskeyCredential

# Importing the routes is what makes the session cookie count: the API's `current_owner` asks the
# registered resolvers, and this is the one that knows sessions.
register()

public_router = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(prefix="/auth", tags=["auth"])

Options = dict[str, Any]
SettingsDep = Annotated[AuthSettings, Depends(get_auth_settings)]


class AuthStatus(BaseModel):
    authenticated: bool
    # Whether any passkey can sign in; when false the login page says how to enroll one.
    enrolled: bool


class Credential(BaseModel):
    """What the UI may know about a passkey. The public key stays on the server."""

    id: int
    name: str
    rp_id: str
    transports: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class EnrollmentLink(BaseModel):
    url: str
    expires_at: datetime
    # An SVG data URI the page shows in an `<img>`.
    qr: str


class AssertionBody(BaseModel):
    credential: dict[str, Any]


class EnrollOptionsBody(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class EnrollVerifyBody(EnrollOptionsBody):
    credential: dict[str, Any]
    name: str = Field(default=enrollment.DEFAULT_NAME, max_length=200)


class EnrollmentLinkBody(BaseModel):
    # `public` points the link at LABHQ_PUBLIC_URL, for a phone; `here` at the address in use.
    target: Literal["public", "here"] = "public"


class StepUpBody(BaseModel):
    purpose: str = Field(max_length=64)


def refuse(error: AuthError) -> ApiError:
    return ApiError(error.status_code, error.code, error.message)


def origin_of(request: Request) -> str | None:
    return request.headers.get("origin")


def credential_out(row: PasskeyCredential) -> Credential:
    return Credential(
        id=row.id,
        name=row.name,
        rp_id=row.rp_id,
        transports=row.transports,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked=row.revoked_at is not None,
    )


def session_of(owner: OwnerDep) -> SessionOwner:
    if not isinstance(owner, SessionOwner):
        raise ApiError(401, "unauthorized", "Sign in to continue.")
    return owner


SignedIn = Annotated[SessionOwner, Depends(session_of)]


@public_router.get("/status")
async def auth_status(request: Request, db: SessionDep) -> AuthStatus:
    """Whether this browser is signed in, without a 401 for the login page to special-case."""
    try:
        await current_owner(request)
        authenticated = True
    except ApiError:
        authenticated = False
    return AuthStatus(authenticated=authenticated, enrolled=await credentials.any_active(db))


@public_router.post("/login/options")
async def auth_login_options(
    request: Request, db: SessionDep, clock: ClockDep, settings: SettingsDep
) -> Options:
    try:
        options = await authentication.begin_login(db, settings, clock.now(), origin_of(request))
    except AuthError as error:
        raise refuse(error) from None
    await db.commit()
    return options


@public_router.post("/login/verify")
async def auth_login_verify(
    body: AssertionBody,
    request: Request,
    response: Response,
    db: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> AuthStatus:
    try:
        token = await authentication.finish_login(
            db, settings, clock.now(), origin_of(request), body.credential
        )
    except AuthError as error:
        # The spent challenge stays spent: a failed assertion is never retried.
        await db.commit()
        raise refuse(error) from None
    await db.commit()
    set_session_cookie(request, response, settings, token)
    return AuthStatus(authenticated=True, enrolled=True)


@public_router.post("/enroll/options")
async def auth_enroll_options(
    body: EnrollOptionsBody,
    request: Request,
    db: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> Options:
    try:
        options = await enrollment.begin(db, settings, clock.now(), origin_of(request), body.token)
    except AuthError as error:
        raise refuse(error) from None
    await db.commit()
    return options


@public_router.post("/enroll/verify")
async def auth_enroll_verify(
    body: EnrollVerifyBody,
    request: Request,
    db: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> Credential:
    try:
        row = await enrollment.finish(
            db,
            settings,
            clock.now(),
            origin_of(request),
            token=body.token,
            credential=body.credential,
            name=body.name,
        )
    except AuthError as error:
        await db.commit()
        raise refuse(error) from None
    await db.commit()
    return credential_out(row)


@router.post("/logout")
async def auth_logout(
    owner: SignedIn, response: Response, db: SessionDep, settings: SettingsDep
) -> AuthStatus:
    await revoke_session(db, owner.session_id)
    await db.commit()
    clear_session_cookie(response, settings)
    return AuthStatus(authenticated=False, enrolled=await credentials.any_active(db))


@router.get("/credentials")
async def auth_credentials_list(db: SessionDep) -> list[Credential]:
    return [credential_out(row) for row in await credentials.all_credentials(db)]


@router.delete("/credentials/{credential_id}")
async def auth_credentials_revoke(
    credential_id: int, db: SessionDep, clock: ClockDep
) -> Credential:
    try:
        row = await credentials.revoke(db, credential_id, clock.now())
    except AuthError as error:
        raise refuse(error) from None
    await db.commit()
    return credential_out(row)


@router.post("/enrollment-links")
async def auth_enrollment_links_create(
    body: EnrollmentLinkBody,
    request: Request,
    db: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> EnrollmentLink:
    """A one-time link for another passkey, with a QR code to open it on a phone."""
    base = settings.public_url if body.target == "public" else None
    base = base or origin_of(request)
    if base is None:
        raise ApiError(400, "origin_required", "The request carries no Origin header.")
    try:
        link = await enrollment.create_link(db, settings, clock.now(), base)
    except AuthError as error:
        raise refuse(error) from None
    await db.commit()
    qr = segno.make(link.url, error="m").svg_data_uri(scale=6, border=2, xmldecl=False)
    return EnrollmentLink(url=link.url, expires_at=link.expires_at, qr=qr)


@router.post("/step-up/options")
async def auth_step_up_options(
    body: StepUpBody,
    request: Request,
    owner: SignedIn,
    db: SessionDep,
    clock: ClockDep,
    settings: SettingsDep,
) -> Options:
    """Challenge for one purpose, such as `approval:42`; the approval endpoint checks the answer."""
    try:
        options = await stepup.begin_step_up(
            db,
            clock.now(),
            session_id=owner.session_id,
            purpose=body.purpose,
            origin=origin_of(request),
            settings=settings,
        )
    except AuthError as error:
        raise refuse(error) from None
    await db.commit()
    return options
