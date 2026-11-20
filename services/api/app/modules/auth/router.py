from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import DB, CurrentUser, get_claims
from app.core.ratelimit import get_limiter
from app.core.security import TokenClaims
from app.modules.auth import service
from app.modules.auth.schemas import (
    EimzoChallenge,
    EimzoLink,
    EimzoLogin,
    MfaChallenge,
    MfaVerify,
    OneIdAuthorize,
    OneIdCallback,
    OtpLogin,
    OtpRequest,
    OtpRequested,
    RefreshRequest,
    TokenPair,
    TotpCode,
    TotpSetup,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp", response_model=OtpRequested, summary="Telefon raqamga SMS-kod yuborish")
async def request_otp(body: OtpRequest, db: DB) -> OtpRequested:
    issued = await service.request_otp(db, body.phone)
    return OtpRequested(expires_in=issued.expires_in, resend_in=issued.resend_in)


@router.post(
    "/otp/verify",
    response_model=TokenPair | MfaChallenge,
    summary="SMS-kod bilan kirish / ro'yxatdan o'tish",
)
async def login_otp(body: OtpLogin, db: DB) -> TokenPair | MfaChallenge:
    await get_limiter().hit(f"login:{body.phone}", limit=10, window_s=900)
    return await service.login_with_otp(db, phone_raw=body.phone, code=body.code, consent=body.consent)


@router.post("/2fa/verify", response_model=TokenPair, summary="TOTP ikkinchi bosqich")
async def verify_mfa(body: MfaVerify, db: DB) -> TokenPair:
    return await service.verify_mfa(db, mfa_token=body.mfa_token, code=body.code)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, db: DB) -> TokenPair:
    return await service.refresh(db, body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    db: DB,
    user: CurrentUser,
    claims: Annotated[TokenClaims, Depends(get_claims)],
    all_devices: bool = False,
) -> None:
    await service.logout(db, session_id=claims.session_id, user_id=user.id, all_devices=all_devices)


@router.post("/2fa/setup", response_model=TotpSetup)
async def totp_setup(db: DB, user: CurrentUser) -> TotpSetup:
    secret, uri = await service.totp_setup(db, user)
    return TotpSetup(secret=secret, otpauth_uri=uri)


@router.post("/2fa/enable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_enable(body: TotpCode, db: DB, user: CurrentUser) -> None:
    await service.totp_enable(db, user, body.code)


@router.get("/oneid/authorize", response_model=OneIdAuthorize)
async def oneid_authorize() -> OneIdAuthorize:
    url, state = service.oneid_start()
    return OneIdAuthorize(url=url, state=state)


@router.post("/oneid", response_model=TokenPair | MfaChallenge, summary="OneID orqali kirish")
async def oneid_callback(body: OneIdCallback, db: DB) -> TokenPair | MfaChallenge:
    return await service.oneid_callback(db, code=body.code, state=body.state)


@router.get("/eimzo/challenge", response_model=EimzoChallenge, summary="E-IMZO: imzolash uchun challenge")
async def eimzo_challenge(response: Response) -> EimzoChallenge:
    response.headers["Cache-Control"] = "no-store"  # doc: challenge must never be cached
    challenge, ttl = await service.eimzo_challenge()
    return EimzoChallenge(challenge=challenge, ttl=ttl)


@router.post("/eimzo", response_model=TokenPair | MfaChallenge, summary="E-IMZO orqali kirish / ro'yxatdan o'tish")
async def eimzo_login(body: EimzoLogin, db: DB) -> TokenPair | MfaChallenge:
    return await service.eimzo_login(db, pkcs7=body.pkcs7, consent=body.consent)


@router.post(
    "/eimzo/link",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mavjud akkauntga E-IMZO (tasdiqlangan shaxs) bog'lash",
)
async def eimzo_link(body: EimzoLink, db: DB, user: CurrentUser) -> None:
    await service.eimzo_link(db, user, pkcs7=body.pkcs7)
