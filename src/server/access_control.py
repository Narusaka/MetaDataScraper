import json
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
LOOPBACK_ORIGIN_REGEX = (
    r"^https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?$"
)


def _normalize_origin(value: str) -> Optional[str]:
    raw = str(value or "").strip().rstrip("/")
    if not raw or raw == "null":
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in {"http", "https"}:
            return None
        if not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            return None
        port = parsed.port
    except ValueError:
        return None

    host = parsed.hostname.lower()
    rendered_host = f"[{host}]" if ":" in host else host
    default_port = 80 if parsed.scheme == "http" else 443
    suffix = f":{port}" if port and port != default_port else ""
    return f"{parsed.scheme}://{rendered_host}{suffix}"


@dataclass(frozen=True)
class TrustedOriginPolicy:
    explicit_origins: frozenset[str]
    allow_loopback: bool = True

    @classmethod
    def from_environment(cls) -> "TrustedOriginPolicy":
        configured = os.getenv("WEB_ALLOWED_ORIGINS", "")
        origins = []
        for value in configured.split(","):
            if not value.strip():
                continue
            normalized = _normalize_origin(value)
            if not normalized:
                raise ValueError(
                    f"Invalid WEB_ALLOWED_ORIGINS entry: {value.strip()}"
                )
            origins.append(normalized)
        allow_loopback = os.getenv(
            "WEB_ALLOW_LOOPBACK_ORIGINS",
            "1",
        ).strip().lower() in {"1", "true", "yes", "on"}
        return cls(frozenset(origins), allow_loopback=allow_loopback)

    def allows(self, origin: Optional[str]) -> bool:
        if origin is None:
            return True
        normalized = _normalize_origin(origin)
        if not normalized:
            return False
        if normalized in self.explicit_origins:
            return True
        if not self.allow_loopback:
            return False
        return (urlsplit(normalized).hostname or "").lower() in LOOPBACK_HOSTS

    @property
    def cors_origins(self) -> list[str]:
        return sorted(self.explicit_origins)

    @property
    def cors_origin_regex(self) -> Optional[str]:
        return LOOPBACK_ORIGIN_REGEX if self.allow_loopback else None


class TrustedOriginMiddleware:
    """Reject browser cross-origin traffic before it reaches privileged APIs."""

    def __init__(self, app, policy: TrustedOriginPolicy):
        self.app = app
        self.policy = policy

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        origin = headers.get("origin")
        if self.policy.allows(origin):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        body = json.dumps({
            "detail": {
                "code": "UNTRUSTED_ORIGIN",
                "message": "Browser origin is not trusted by this local service",
            }
        }).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"vary", b"Origin"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
