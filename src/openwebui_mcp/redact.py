"""Mask credentials before Open WebUI data is returned to an MCP caller.

Config exports and tool-server connections carry API keys, bearer tokens and
OAuth secrets. Tools that return them pass the payload through ``redact`` so a
credential never reaches the transcript. Writes always use the unredacted data
read straight from Open WebUI, never a redacted copy.
"""

import re
from typing import Any

REDACTED = "***redacted***"

_SECRET_NAME = re.compile(
    r"(api_?keys?|(^|[._])key$|secret|password|passwd|token|authorization|"
    r"credential|private_key|client_secret|cookie)",
    re.IGNORECASE,
)

# Names that match the pattern but hold no credential.
_NOT_SECRET = {
    "auth.enable_api_keys",
    "auth.api_key.endpoint_restrictions",
    "auth.api_key.allowed_endpoints",
    "enable_api_keys",
    "token_type",
    "max_tokens",
    "num_predict",
}


def is_secret_name(name: str) -> bool:
    """True when a key name looks like it holds a credential."""
    lowered = name.lower()
    if lowered in _NOT_SECRET or lowered.endswith("max_tokens"):
        return False
    return bool(_SECRET_NAME.search(lowered))


def _mask(value: Any) -> Any:
    if value in (None, "", [], {}):
        return value
    if isinstance(value, list):
        return [REDACTED if item not in (None, "") else item for item in value]
    if isinstance(value, dict):
        return {key: _mask(item) for key, item in value.items()}
    if isinstance(value, bool):
        return value
    return REDACTED


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with credential-like fields masked."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and is_secret_name(key):
                out[key] = _mask(item)
            elif isinstance(key, str) and key.lower() == "headers":
                out[key] = _mask(item) if isinstance(item, (str, dict)) else item
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
