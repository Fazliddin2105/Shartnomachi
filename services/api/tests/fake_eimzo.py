"""In-memory emulator of E-IMZO-SERVER (doc: github.com/qo0p/e-imzo-doc §2.2).

A "PKCS#7" here is Base64(JSON) describing the signed document and its signers,
so tests can produce valid / tampered / foreign signatures without real keys.
Responses follow the documented JSON shapes (status, subjectCertificateInfo,
pkcs7Info.signers[].certificate[], timeStampInfo, documentBase64, ...).
"""

from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass, field
from typing import Any

import httpx


def fake_sign(
    document: bytes,
    *,
    pinfl: str,
    cn: str = "TESTOV TEST TESTOVICH",
    uid: str = "400000001",
    legal_tin: str | None = None,
    revoked: bool = False,
) -> str:
    signer = {"cn": cn, "pinfl": pinfl, "uid": uid, "legal_tin": legal_tin, "revoked": revoked, "ts": False}
    payload = {"doc": base64.b64encode(document).decode(), "signers": [signer]}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def decode(pkcs7_b64: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(pkcs7_b64))  # type: ignore[no-any-return]


def _encode(obj: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def _x500(s: dict[str, Any]) -> str:
    parts = [f"CN={s['cn'].replace(',', chr(92) + ',')}", f"UID={s['uid']}", f"1.2.860.3.16.1.2={s['pinfl']}"]
    if s.get("legal_tin"):
        parts.append(f"1.2.860.3.16.1.1={s['legal_tin']}")
    return ",".join(parts)


@dataclass
class FakeEimzoServer:
    challenges: set[str] = field(default_factory=set)
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((path, dict(request.headers)))
        body = request.content.decode()
        if path.startswith("/backend") or path.startswith("/frontend/timestamp") or path.endswith("/join"):
            # documented requirement for PKCS#7 endpoints
            assert request.headers.get("X-Real-IP"), "X-Real-IP header is required"
            assert request.headers.get("Host") == "lexlab.test", "Host must be our site domain"
        if path == "/frontend/challenge":
            ch = secrets.token_hex(16)
            self.challenges.add(ch)
            return httpx.Response(200, json={"status": 1, "challenge": ch, "ttl": 120, "message": None})
        if path == "/backend/auth":
            p = decode(body)
            challenge = base64.b64decode(p["doc"]).decode()
            if challenge not in self.challenges:
                return httpx.Response(200, json={"status": -20, "message": "challenge not found"})
            self.challenges.discard(challenge)  # single use
            s = p["signers"][0]
            if s["revoked"]:
                return httpx.Response(200, json={"status": -11, "message": "certificate invalid"})
            subject = {"CN": s["cn"], "UID": s["uid"], "1.2.860.3.16.1.2": s["pinfl"]}
            return httpx.Response(
                200,
                json={
                    "status": 1,
                    "message": None,
                    "subjectCertificateInfo": {
                        "serialNumber": "7a1b2c",
                        "subjectName": subject,
                        "validFrom": "2025-01-01 00:00:00",
                        "validTo": "2027-01-01 00:00:00",
                    },
                },
            )
        if path == "/frontend/timestamp/pkcs7":
            p = decode(body)
            for s in p["signers"]:
                s["ts"] = True
            return httpx.Response(200, json={"status": 1, "pkcs7b64": _encode(p), "timestampedSignerList": []})
        if path == "/frontend/pkcs7/join":
            a, b = (decode(x) for x in body.split("|"))
            if a["doc"] != b["doc"]:
                return httpx.Response(200, json={"status": -10, "message": "documents differ"})
            return httpx.Response(
                200, json={"status": 1, "pkcs7b64": _encode({**a, "signers": a["signers"] + b["signers"]})}
            )
        if path == "/backend/pkcs7/verify/attached":
            p = decode(body)
            if any(s["revoked"] for s in p["signers"]):
                return httpx.Response(200, json={"status": -11, "message": "certificate invalid"})
            signers = [
                {
                    "signerId": {"subjectSerialNumber": "7a1b2c"},
                    "signingTime": "2026-11-20 16:00:00",
                    "certificate": [
                        {
                            "serialNumber": "7a1b2c",
                            "subjectName": _x500(s),
                            "validFrom": "2025-01-01 00:00:00",
                            "validTo": "2027-01-01 00:00:00",
                        },
                        {"serialNumber": "ca01", "subjectName": "CN=CA"},
                    ],
                    "verified": True,
                    "certificateVerified": True,
                    "certificateValidAtSigningTime": True,
                    "timeStampInfo": {
                        "verified": True,
                        "certificateVerified": True,
                        "digestVerified": True,
                        "time": "2026-11-20 16:00:01",
                    }
                    if s["ts"]
                    else None,
                }
                for s in p["signers"]
            ]
            return httpx.Response(
                200, json={"status": 1, "message": None, "pkcs7Info": {"signers": signers, "documentBase64": p["doc"]}}
            )
        return httpx.Response(404)
