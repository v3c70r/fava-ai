"""Portfolio extractor — generates wiki/portfolio/*.md."""

from collections import defaultdict
from decimal import Decimal

from fava_ai.knowledge.wiki import WikiManager, WikiPage


def _format_amounts(amounts: dict[str, Decimal]) -> str:
    if not amounts:
        return "—"
    return ", ".join(f"{v:.2f} {c}" for c, v in sorted(amounts.items()))


class PortfolioExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        self.wiki.delete_dir("portfolio")
        port_dir = self.wiki.wiki_dir / "portfolio"
        port_dir.mkdir(parents=True, exist_ok=True)

        operating = list(options.get("operating_currency", []) or [])

        # Latest price per (commodity, quote currency).
        latest_prices: dict[tuple[str, str], tuple] = {}
        for entry in entries:
            if type(entry).__name__ != "Price":
                continue
            amount = getattr(entry, "amount", None)
            if amount is None:
                continue
            key = (str(entry.currency), str(amount.currency))
            current = latest_prices.get(key)
            if current is None or entry.date >= current[0]:
                latest_prices[key] = (entry.date, amount.number)

        units: dict[str, Decimal] = defaultdict(Decimal)
        cost_basis: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        accounts: dict[str, set] = defaultdict(set)
        txns: dict[str, int] = defaultdict(int)

        for entry in entries:
            if not hasattr(entry, "postings"):
                continue
            touched: set[str] = set()
            for p in entry.postings:
                if not p.units:
                    continue
                if not (p.account.startswith("Assets:") or p.account == "Assets"):
                    continue
                ccy = str(p.units.currency)
                units[ccy] += p.units.number
                accounts[ccy].add(p.account)
                touched.add(ccy)
                cost = getattr(p, "cost", None)
                if cost is not None and getattr(cost, "number", None) is not None:
                    cost_basis[ccy][str(cost.currency)] += p.units.number * cost.number
            for ccy in touched:
                txns[ccy] += 1

        def market_value(ccy: str, qty: Decimal):
            # Prefer an operating currency, then any available quote currency.
            candidates = [c for c in operating if (ccy, c) in latest_prices]
            candidates += sorted(
                c for (base, c) in latest_prices if base == ccy and c not in candidates
            )
            if not candidates:
                return None, None
            quote = candidates[0]
            _, price = latest_prices[(ccy, quote)]
            return (qty * price), quote

        holdings = []
        sold = []
        for ccy in sorted(units):
            if ccy in operating:
                continue  # cash, not a holding
            qty = units[ccy]
            if qty == 0:
                if txns[ccy]:
                    sold.append(ccy)
                continue
            value, quote = market_value(ccy, qty)
            holdings.append({
                "commodity": ccy,
                "units": qty,
                "cost_basis": dict(cost_basis.get(ccy, {})),
                "market_value": value,
                "quote": quote,
                "accounts": sorted(accounts[ccy]),
                "transactions": txns[ccy],
            })

        has_valuation = any((h["commodity"], q) in latest_prices
                            for h in holdings for q in operating)
        total_value: dict[str, Decimal] = defaultdict(Decimal)
        for h in holdings:
            if h["market_value"] is not None and h["quote"]:
                total_value[h["quote"]] += h["market_value"]

        lines = ["# Portfolio", ""]
        if not holdings:
            lines += ["_No open investment positions._", ""]
        else:
            lines += [
                "## Holdings",
                "",
                "| Commodity | Units | Cost basis | Market value | Transactions |",
                "|-----------|-------|------------|--------------|--------------|",
            ]
            for h in holdings:
                mv = (
                    f"{h['market_value']:.2f} {h['quote']}"
                    if h["market_value"] is not None else "—"
                )
                lines.append(
                    f"| {h['commodity']} | {h['units']} | "
                    f"{_format_amounts(h['cost_basis'])} | {mv} | {h['transactions']} |"
                )
            lines.append("")
            if has_valuation and total_value:
                lines.append("**Total market value:** " + _format_amounts(total_value))
                lines.append("")
            else:
                lines.append(
                    "_Units only — no price data in the ledger, so no market value "
                    "could be computed._"
                )
                lines.append("")

            for h in holdings:
                lines.append(f"### {h['commodity']}")
                lines.append(f"- Accounts: {', '.join(h['accounts'])}")
                lines.append("")

        if sold:
            lines += [
                "## Closed positions (net zero units)",
                "",
                *[f"- {c}" for c in sold],
                "",
            ]

        page = WikiPage(
            path=port_dir / "holdings.md",
            metadata={
                "title": "Portfolio Holdings",
                "type": "portfolio",
                "holdings_count": len(holdings),
                "has_valuation": has_valuation,
                "total_market_value": _format_amounts(total_value) if total_value else "",
            },
            content="\n".join(lines),
        )
        page.save()

        self.wiki._update_index()
        return {"portfolio_pages": 1, "holdings": len(holdings), "closed": len(sold)}
