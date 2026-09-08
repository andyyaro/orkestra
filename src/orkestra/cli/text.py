"""Text shaping shared by the console renderers."""

from __future__ import annotations

ELLIPSIS = "…"


def clip(text: str, limit: int) -> str:
    """Shorten text to `limit` characters, marking that anything was dropped.

    Silent truncation is how a diagnosis disappears: an event line that ends
    mid-sentence looks exactly like an event line that had nothing more to say.
    The marker makes the loss visible, so the reader knows to run
    `orkestra events --full`.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + ELLIPSIS
