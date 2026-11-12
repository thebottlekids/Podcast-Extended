"""Provider-specific request headers for LLM calls.

OpenCode Go (``https://opencode.ai/zen/go/v1``) rejects chat completion
requests with HTTP 400 ``MissingSessionID`` unless every request carries an
``x-opencode-session`` header. OpenCode's contract asks for a session id that
is stable per conversation, so we mint exactly one id per process and reuse it
for every call: a per-request id would look like an unbounded stream of new
sessions on their side.

Every other lane (local Ollama gateway, OpenAI, ...) must receive exactly the
request it received before this module existed, so callers always gate on the
configured base URL and get an empty mapping when it is not an OpenCode host.
"""

from __future__ import annotations

import uuid
from typing import Final
from urllib.parse import urlparse

OPENCODE_HOST: Final[str] = "opencode.ai"
OPENCODE_SESSION_HEADER: Final[str] = "x-opencode-session"
LLM_USER_AGENT: Final[str] = "podcast-extended/1.0"

# Generated once per process; see the module docstring.
_PROCESS_SESSION_ID: Final[str] = f"podly-{uuid.uuid4().hex[:16]}"


def _base_url_host(base_url: str | None) -> str:
    """Return the lower-cased host of a base URL, tolerating a missing scheme."""
    if not base_url:
        return ""
    candidate = base_url.strip()
    if "//" not in candidate:
        # urlparse("opencode.ai/zen/go/v1") has no hostname; make it netloc-shaped.
        candidate = f"//{candidate}"
    return (urlparse(candidate).hostname or "").lower()


def is_opencode_base_url(base_url: str | None) -> bool:
    """True when ``base_url`` points at an OpenCode gateway."""
    host = _base_url_host(base_url)
    return bool(host) and (host == OPENCODE_HOST or host.endswith(f".{OPENCODE_HOST}"))


def opencode_session_id() -> str:
    """Return the process-wide OpenCode session id."""
    return _PROCESS_SESSION_ID


def llm_extra_headers(base_url: str | None) -> dict[str, str]:
    """Return extra HTTP headers required by the configured LLM lane.

    Empty for every non-OpenCode lane, so existing providers (and their tests)
    are unaffected.
    """
    if not is_opencode_base_url(base_url):
        return {}
    return {
        OPENCODE_SESSION_HEADER: _PROCESS_SESSION_ID,
        "User-Agent": LLM_USER_AGENT,
    }
