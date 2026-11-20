"""E-IMZO (ЭЦП) integration via the official E-IMZO-SERVER.

Reference: https://github.com/qo0p/e-imzo-doc (sections 2.2, 3.4).

Topology
--------
browser (E-IMZO app, ``EIMZOClient.createPkcs7``) --PKCS#7--> our API --> E-IMZO-SERVER
                                                                         (private network)

* ``/frontend/*`` endpoints (challenge, timestamp, join) may be public; we proxy them anyway.
* ``/backend/*`` endpoints (auth, verify) must be reachable only from our backend.
* Every PKCS#7 call carries ``X-Real-IP`` (end-user IP) and ``Host`` (our domain).
* Request bodies are raw Base64 text (no JSON). Responses are JSON with ``status`` (1 = OK).

The server itself checks signatures, certificate chains and revocation (OCSP via
its VPN to the CA). We additionally check *what* was signed and *who* signed it.
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.context import get_client
from app.core.errors import AppError, IntegrationUnavailable, Unauthorized, ValidationFailed
from app.core.timeutils import local_tz

log = logging.getLogger(__name__)

OID_PINFL = "1.2.860.3.16.1.2"  # ПИНФЛ (JShShIR)
OID_LEGAL_TIN = "1.2.860.3.16.1.1"  # Юр.ИНН (yuridik shaxs STIR) — absent for individuals
FIELD_PERSON_TIN = "UID"  # Физ.ИНН (jismoniy shaxs STIR)

# Test hook: lets tests plug an httpx.MockTransport that emulates E-IMZO-SERVER.
_transport: httpx.AsyncBaseTransport | None = None


def configure_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


class EimzoRejected(AppError):
    """E-IMZO-SERVER answered, but rejected the signature/certificate."""

    status_code = 422
    code = "eimzo_rejected"
    message = "E-IMZO signature was rejected"


# status -> (exception class, code, Uzbek message). Shared by auth and verify (doc tables 2.2.2 / 2.2.4).
_AUTH_STATUS: dict[int, tuple[type[AppError], str, str]] = {
    -1: (
        IntegrationUnavailable,
        "eimzo_status_check_failed",
        "Sertifikat holatini tekshirib bo'lmadi, keyinroq urining",
    ),
    -5: (
        Unauthorized,
        "eimzo_time_window",
        "Imzo vaqti ruxsat etilgan oraliqdan tashqarida (qurilma soatini tekshiring)",
    ),
    -10: (EimzoRejected, "eimzo_signature_invalid", "Elektron imzo yaroqsiz"),
    -11: (EimzoRejected, "eimzo_certificate_invalid", "Sertifikat yaroqsiz yoki bekor qilingan"),
    -12: (EimzoRejected, "eimzo_certificate_expired", "Imzolangan sanada sertifikat amal qilmagan"),
    -20: (Unauthorized, "eimzo_challenge_expired", "Challenge topilmadi yoki muddati o'tgan, qaytadan urining"),
    -24: (EimzoRejected, "eimzo_policy_not_allowed", "Sertifikat turi ruxsat etilmagan"),
    -25: (EimzoRejected, "eimzo_ca_not_allowed", "Sertifikat beruvchi markaz ruxsat etilmagan"),
}
_VERIFY_STATUS: dict[int, tuple[type[AppError], str, str]] = {
    **{k: v for k, v in _AUTH_STATUS.items() if k not in (-5, -20)},
    -20: (IntegrationUnavailable, "eimzo_tsa_status_failed", "Vaqt tamg'asi holatini tekshirib bo'lmadi"),
    -21: (EimzoRejected, "eimzo_tsa_invalid", "Vaqt tamg'asi imzosi yaroqsiz"),
    -22: (EimzoRejected, "eimzo_tsa_certificate_invalid", "Vaqt tamg'asi sertifikati yaroqsiz"),
    -23: (EimzoRejected, "eimzo_tsa_certificate_expired", "Vaqt tamg'asi sertifikati muddati o'tgan"),
}


# --- value objects -----------------------------------------------------------------------


def parse_x500(value: str | dict[str, Any] | None) -> dict[str, str]:
    """`subjectName` is a map in auth responses and an X.500 string in verify responses."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    out: dict[str, str] = {}
    for part in _split_rdn(value):
        k, sep, v = part.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def _split_rdn(s: str) -> list[str]:
    parts, cur, escaped = [], [], False
    for ch in s:
        if escaped:
            cur.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ",":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        # Docs: "yyyy-MM-dd HH:mm:ss" (server local time = Asia/Tashkent)
        return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=local_tz()).astimezone(UTC)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class CertificateIdentity:
    serial_number: str | None
    common_name: str | None
    pinfl: str | None
    person_tin: str | None
    legal_tin: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    subject: dict[str, str] = field(default_factory=dict)

    @property
    def is_legal_entity(self) -> bool:
        return bool(self.legal_tin)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> CertificateIdentity:
        subject = parse_x500(d.get("subjectName"))
        return cls(
            serial_number=d.get("serialNumber"),
            common_name=subject.get("CN"),
            pinfl=subject.get(OID_PINFL),
            person_tin=subject.get(FIELD_PERSON_TIN),
            legal_tin=subject.get(OID_LEGAL_TIN),
            valid_from=_dt(d.get("validFrom")),
            valid_to=_dt(d.get("validTo")),
            subject=subject,
        )


@dataclass(frozen=True, slots=True)
class SignerInfo:
    certificate: CertificateIdentity
    signing_time: datetime | None
    timestamp_time: datetime | None
    timestamp_verified: bool


@dataclass(frozen=True, slots=True)
class VerifiedDocument:
    document: bytes | None
    signers: list[SignerInfo]


# --- client -------------------------------------------------------------------------------


class EimzoClient:
    def __init__(self) -> None:
        s = get_settings()
        if not s.eimzo_server_url:
            raise IntegrationUnavailable("E-IMZO server is not configured", code="eimzo_unavailable")
        self._base = s.eimzo_server_url.rstrip("/")
        self._host = s.eimzo_site_host
        self._timeout = s.eimzo_timeout_seconds

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "text/plain"}
        ip = get_client().ip
        if ip:
            h["X-Real-IP"] = ip
        if self._host:
            h["Host"] = self._host
        return h

    async def _call(self, method: str, path: str, body: str | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self._base, timeout=self._timeout, transport=_transport) as c:
                r = await c.request(method, path, content=body, headers=self._headers())
        except httpx.HTTPError as e:
            log.warning("eimzo_unreachable", extra={"path": path, "error": str(e)})
            raise IntegrationUnavailable("E-IMZO server is unreachable", code="eimzo_unavailable") from e
        if r.status_code == 400:
            raise ValidationFailed("Malformed signature data", code="eimzo_bad_request")
        if r.status_code >= 500 or r.status_code != 200:
            raise IntegrationUnavailable(f"E-IMZO server error {r.status_code}", code="eimzo_unavailable")
        try:
            data: dict[str, Any] = r.json()
        except ValueError as e:
            raise IntegrationUnavailable("E-IMZO server returned invalid JSON", code="eimzo_unavailable") from e
        return data

    @staticmethod
    def _raise_for_status(data: dict[str, Any], table: dict[int, tuple[type[AppError], str, str]]) -> None:
        status = data.get("status")
        if status == 1:
            return
        exc, code, msg = table.get(int(status or 0), (EimzoRejected, "eimzo_rejected", "E-IMZO imzoni rad etdi"))
        raise exc(msg, code=code, details={"eimzo_status": status, "eimzo_message": data.get("message")})

    @staticmethod
    def _check_b64(pkcs7_b64: str) -> str:
        cleaned = "".join(pkcs7_b64.split())
        try:
            base64.b64decode(cleaned, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValidationFailed("Signature is not valid Base64", code="eimzo_bad_request") from e
        return cleaned

    # -- frontend-side endpoints --

    async def challenge(self) -> tuple[str, int]:
        data = await self._call("GET", "/frontend/challenge")
        self._raise_for_status(data, _AUTH_STATUS)
        return str(data["challenge"]), int(data.get("ttl") or 120)

    async def attach_timestamp(self, pkcs7_b64: str) -> str:
        data = await self._call("POST", "/frontend/timestamp/pkcs7", self._check_b64(pkcs7_b64))
        self._raise_for_status(data, _VERIFY_STATUS)
        return str(data["pkcs7b64"])

    async def join(self, pkcs7_a: str, pkcs7_b: str) -> str:
        """Merge two attached PKCS#7 of the *same* document into one multi-signature container."""
        data = await self._call(
            "POST", "/frontend/pkcs7/join", f"{self._check_b64(pkcs7_a)}|{self._check_b64(pkcs7_b)}"
        )
        self._raise_for_status(data, _VERIFY_STATUS)
        return str(data["pkcs7b64"])

    # -- backend-only endpoints --

    async def authenticate(self, pkcs7_b64: str) -> CertificateIdentity:
        """Verify a signed challenge (doc §2.2.2). The server consumes the challenge (one-time)."""
        data = await self._call("POST", "/backend/auth", self._check_b64(pkcs7_b64))
        self._raise_for_status(data, _AUTH_STATUS)
        ident = CertificateIdentity.from_json(data.get("subjectCertificateInfo") or {})
        if not ident.pinfl:
            raise EimzoRejected("Sertifikatda JShShIR (PINFL) topilmadi", code="eimzo_no_pinfl")
        return ident

    async def verify_attached(self, pkcs7_b64: str) -> VerifiedDocument:
        data = await self._call("POST", "/backend/pkcs7/verify/attached", self._check_b64(pkcs7_b64))
        self._raise_for_status(data, _VERIFY_STATUS)
        info = data.get("pkcs7Info") or {}
        signers: list[SignerInfo] = []
        for s in info.get("signers") or []:
            if s.get("revokedStatusInfo") or s.get("exception"):
                raise EimzoRejected(
                    "Sertifikat bekor qilingan yoki to'xtatilgan",
                    code="eimzo_certificate_revoked",
                    details={"exception": s.get("exception")},
                )
            if not (s.get("verified") and s.get("certificateVerified")):
                raise EimzoRejected("Imzo yoki sertifikat zanjiri tasdiqlanmadi", code="eimzo_signature_invalid")
            if s.get("certificateValidAtSigningTime") is False:
                raise EimzoRejected("Imzolangan vaqtda sertifikat amal qilmagan", code="eimzo_certificate_expired")
            certs = s.get("certificate") or []
            if not certs:
                raise EimzoRejected("Imzolovchi sertifikati topilmadi", code="eimzo_signature_invalid")
            ts = s.get("timeStampInfo") or None
            ts_ok = bool(ts and ts.get("verified") and ts.get("certificateVerified") and ts.get("digestVerified", True))
            signers.append(
                SignerInfo(
                    certificate=CertificateIdentity.from_json(certs[0]),  # [0] = user cert, [1] = CA
                    signing_time=_dt(s.get("signingTime")),
                    timestamp_time=_dt(ts.get("time")) if ts else None,
                    timestamp_verified=ts_ok,
                )
            )
        if not signers:
            raise EimzoRejected("PKCS#7 da imzolovchi yo'q", code="eimzo_signature_invalid")
        doc_b64 = info.get("documentBase64")
        document = base64.b64decode(doc_b64) if doc_b64 else None
        return VerifiedDocument(document=document, signers=signers)


def get_client_or_raise() -> EimzoClient:
    return EimzoClient()
