"""Request-scoped context (request id, client ip, user agent) via contextvars."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_client: ContextVar[ClientInfo | None] = ContextVar("client", default=None)


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip: str | None
    user_agent: str | None


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def set_client(info: ClientInfo) -> None:
    _client.set(info)


def get_client() -> ClientInfo:
    return _client.get() or ClientInfo(ip=None, user_agent=None)
