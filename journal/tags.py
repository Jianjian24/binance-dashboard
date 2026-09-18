"""Map Binance clientOrderId prefixes to journal tags. No strategy process involved."""

from __future__ import annotations

PREFIX_TAGS: tuple[tuple[str, str], ...] = (
    ("GRIDB", "GRID"),
    ("GRIDN", "GRID"),
    ("GRIDT", "GRID"),
    ("MMBL", "MM"),
    ("MMSH", "MM"),
    ("MMCL", "MM"),
    ("MMMC", "MM"),
    ("TRAPO", "TRAP"),
    ("TRAPSL", "TRAP"),
    ("TRAPTP", "TRAP"),
    ("MSG", "SCALP"),
    ("MSGT", "SCALP"),
)


def tag_from_client_order_id(cid: str | None) -> str:
    text = (cid or "").strip()
    if not text:
        return "OTHER"
    upper = text.upper()
    for prefix, tag in PREFIX_TAGS:
        if upper.startswith(prefix):
            return tag
    return "OTHER"


def tags_from_cids(cids: list[str] | tuple[str, ...]) -> list[str]:
    seen: list[str] = []
    for cid in cids:
        tag = tag_from_client_order_id(cid)
        if tag not in seen:
            seen.append(tag)
    real = [tag for tag in seen if tag != "OTHER"]
    return real or ["OTHER"]
