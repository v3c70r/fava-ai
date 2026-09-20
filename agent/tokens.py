"""Token counting helpers for context-window management."""

import logging

logger = logging.getLogger(__name__)

#: Model used for tokenizer selection. Exact counts per provider differ, but
#: this is only used to decide when to trim history.
_REFERENCE_MODEL = "gpt-4o"


def _approx_tokens(messages) -> int:
    """Cheap fallback: ~4 characters per token, plus tool-call overhead."""
    chars = 0
    for message in messages:
        if message.content:
            chars += len(message.content)
        if getattr(message, "tool_calls", None):
            for tc in message.tool_calls:
                chars += len(tc.function.name or "")
                chars += len(tc.function.arguments or "")
        chars += 8  # per-message role framing overhead
    return chars // 4 + 1


def count_tokens(messages) -> int:
    """Estimate the token count of a message list.

    Uses litellm's tokenizer when available (it may need to download an
    encoding) and falls back to a character heuristic offline.
    """
    if not messages:
        return 0
    try:
        import litellm

        return int(
            litellm.token_counter(
                model=_REFERENCE_MODEL,
                messages=[m.to_litellm() for m in messages],
            )
        )
    except Exception:
        return _approx_tokens(messages)
