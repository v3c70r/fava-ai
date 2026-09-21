"""Inventory helpers for compact, human/LLM-readable balances."""

from collections import defaultdict
from decimal import Decimal

from beancount.core.inventory import Inventory


def summarize_inventory(inv: Inventory) -> str:
    """Per-currency totals, collapsing cost lots.

    A full ``Inventory.to_string()`` can be kilobytes of per-lot detail (one
    entry per purchase). For listings and account pages only the per-currency
    totals are useful; the lots remain available through BQL.
    """
    if inv.is_empty():
        return "0"
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for position in inv:
        units = getattr(position, "units", None)
        if units is not None:
            totals[units.currency] += units.number
    totals = {c: n for c, n in totals.items() if n != 0}
    if not totals:
        return "0"
    return "(" + ", ".join(f"{n} {c}" for c, n in sorted(totals.items())) + ")"


def inventory_magnitude(inv: Inventory) -> Decimal:
    """Rough magnitude across currencies, for sorting only."""
    total = Decimal("0")
    for position in inv:
        units = getattr(position, "units", None)
        if units is not None:
            total += abs(units.number)
    return total
