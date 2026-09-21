"""Shared naming helpers for knowledge extractors."""

import re

#: Trailing card / terminal numbers (e.g. "CARD 1234", "STORE 9911", "*1234").
_TERMINAL_NOISE_RE = re.compile(r"(?:card|debit|pos|purchase|xxxx|\*)?\s*\d{3,}\b", re.IGNORECASE)
#: Delimiters that separate a merchant from the rest of a description.
_SPLIT_RE = re.compile(r"\s+[-–—|#;*:]\s*|[-–—|#;*]")
_WS_RE = re.compile(r"\s+")

_MAX_KEY = 80


def merchant_key(entry) -> str | None:
    """Return a merchant identifier for an entry.

    Uses the payee when present; otherwise derives one from the narration so
    narration-only ledgers (common with bank imports) still get a catalog.
    """
    payee = getattr(entry, "payee", None)
    if payee and str(payee).strip():
        return str(payee).strip()

    narration = getattr(entry, "narration", None)
    if not narration:
        return None
    text = str(narration).strip()
    if not text:
        return None

    cleaned = _TERMINAL_NOISE_RE.sub("", text)
    first = _SPLIT_RE.split(cleaned, maxsplit=1)[0]
    first = _WS_RE.sub(" ", first).strip(" -–—|#;*:")
    if not first:
        first = text
    return first[:_MAX_KEY] or None


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower())
    return slug.strip("-") or "unknown"
