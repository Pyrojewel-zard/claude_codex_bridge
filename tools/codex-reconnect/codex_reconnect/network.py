from __future__ import annotations

import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from urllib.parse import urlparse

from . import __version__


DEFAULT_OPENAI_PROBE_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_PUBLIC_PROBE_URL = "https://www.google.com/generate_204"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    url: str
    reachable: bool
    status: int | None
    elapsed_seconds: float
    error: str | None = None


class Readiness(str, Enum):
    READY = "ready"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    NETWORK_UNAVAILABLE = "network_unavailable"
    PRIMARY_UNAVAILABLE = "primary_unavailable"


def probe_https(
    url: str,
    *,
    timeout: float = 5.0,
    open_url: Callable[..., object] = urllib.request.urlopen,
) -> ProbeResult:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("probe URL must be an absolute https URL")
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": f"codex-reconnect/{__version__}"},
    )
    started = time.monotonic()
    try:
        response = open_url(
            request, timeout=timeout, context=ssl.create_default_context()
        )
        status = getattr(response, "status", None)
        close = getattr(response, "close", None)
        if callable(close):
            close()
        return ProbeResult(
            url,
            True,
            status if isinstance(status, int) else None,
            time.monotonic() - started,
        )
    except urllib.error.HTTPError as exc:
        # Any HTTP response proves the DNS/TCP/TLS/HTTP path is reachable.
        return ProbeResult(url, True, exc.code, time.monotonic() - started)
    except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as exc:
        return ProbeResult(url, False, None, time.monotonic() - started, str(exc))


def classify_readiness(primary: ProbeResult, public: ProbeResult | None) -> Readiness:
    if primary.reachable:
        return Readiness.READY
    if public is None:
        return Readiness.PRIMARY_UNAVAILABLE
    if public.reachable:
        return Readiness.UPSTREAM_UNAVAILABLE
    return Readiness.NETWORK_UNAVAILABLE
