"""Merchant catalog extractor — generates wiki/merchants/*.md."""

from collections import defaultdict
from decimal import Decimal

from fava_ai.knowledge.extractors.naming import merchant_key, slugify
from fava_ai.knowledge.wiki import WikiManager, WikiPage


class MerchantExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        self.wiki.delete_dir("merchants")
        merchants_dir = self.wiki.wiki_dir / "merchants"
        merchants_dir.mkdir(parents=True, exist_ok=True)

        merchant_data: dict[str, dict] = defaultdict(lambda: {
            "transactions": [],
            "total_spent": defaultdict(Decimal),
            "first_seen": None,
            "last_seen": None,
            "accounts": set(),
            "from_narration": False,
        })

        for entry in entries:
            if not hasattr(entry, "date"):
                continue
            key = merchant_key(entry)
            if not key:
                continue

            data = merchant_data[key]
            if not (getattr(entry, "payee", None) and str(entry.payee).strip()):
                data["from_narration"] = True
            data["transactions"].append(entry)
            data["first_seen"] = min(data["first_seen"] or entry.date, entry.date)
            data["last_seen"] = max(data["last_seen"] or entry.date, entry.date)

            if hasattr(entry, "postings"):
                for p in entry.postings:
                    if p.units and p.account.startswith("Expenses"):
                        data["total_spent"][p.units.currency] += p.units.number
                        data["accounts"].add(p.account)

        stats = {"merchants_generated": 0}
        oper_ccys = options.get("operating_currency", ["USD"]) or ["USD"]
        main_currency = oper_ccys[0]

        for name, data in sorted(merchant_data.items()):
            if not data["transactions"]:
                continue

            totals = {c: v for c, v in data["total_spent"].items() if v}
            main_total = totals.get(main_currency)
            if main_total is None and totals:
                main_total = next(iter(totals.values()))

            safe_name = slugify(name)
            content = self._render_merchant(name, data, totals)

            page = WikiPage(
                path=merchants_dir / f"{safe_name}.md",
                metadata={
                    "title": name,
                    "type": "merchant",
                    "total_transactions": len(data["transactions"]),
                    "total_spent": str(main_total if main_total is not None else 0),
                    "currencies": sorted(totals),
                    "source": "narration" if data["from_narration"] else "payee",
                    "first_seen": str(data["first_seen"]) if data["first_seen"] else "",
                    "last_seen": str(data["last_seen"]) if data["last_seen"] else "",
                },
                content=content,
            )
            page.save()
            stats["merchants_generated"] += 1

        self.wiki._update_index()
        return stats

    def _render_merchant(self, name: str, data: dict, totals: dict) -> str:
        txns = data["transactions"]
        lines = [
            f"# {name}",
            "",
            "## Summary",
            f"- **Total transactions:** {len(txns)}",
            f"- **First seen:** {data['first_seen']}",
            f"- **Last seen:** {data['last_seen']}",
            f"- **Matched on:** {'narration' if data['from_narration'] else 'payee'}",
        ]

        lines.append("")
        lines.append("## Total spent")
        if totals:
            lines.append("")
            lines.append("| Currency | Total |")
            lines.append("|----------|-------|")
            for ccy in sorted(totals):
                lines.append(f"| {ccy} | {totals[ccy]:.2f} |")
        else:
            lines.append("_No expense postings recorded._")

        lines += [
            "",
            "## Recent Transactions",
            "| Date | Amounts | Description |",
            "|------|---------|-------------|",
        ]

        recent = sorted(txns, key=lambda e: e.date, reverse=True)[:20]
        for e in recent:
            amounts = []
            if hasattr(e, "postings"):
                for p in e.postings:
                    if p.units:
                        amounts.append(str(p.units))
            narration = str(e.narration) if hasattr(e, "narration") and e.narration else ""
            lines.append(f"| {e.date} | {', '.join(amounts)} | {narration} |")

        return "\n".join(lines)
