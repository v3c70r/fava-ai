"""Merchant catalog extractor — generates wiki/merchants/*.md."""

from collections import defaultdict
from decimal import Decimal

from fava_ai.knowledge.wiki import WikiManager, WikiPage


class MerchantExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        self.wiki.delete_dir("merchants")
        merchants_dir = self.wiki.wiki_dir / "merchants"
        merchants_dir.mkdir(parents=True, exist_ok=True)

        merchant_data = defaultdict(lambda: {
            "transactions": [],
            "total_spent": defaultdict(Decimal),
            "first_seen": None,
            "last_seen": None,
            "accounts": set(),
        })

        for entry in entries:
            if not hasattr(entry, "payee") or not entry.payee:
                continue
            if not hasattr(entry, "date"):
                continue

            payee = str(entry.payee).strip()
            if not payee:
                continue

            m = merchant_data[payee]
            m["transactions"].append(entry)
            m["first_seen"] = min(m["first_seen"] or entry.date, entry.date)
            m["last_seen"] = max(m["last_seen"] or entry.date, entry.date)

            if hasattr(entry, "postings"):
                for p in entry.postings:
                    if p.units:
                        m["total_spent"][p.units.currency] += p.units.number
                        m["accounts"].add(p.account)

        stats = {"merchants_generated": 0}
        main_currency = options.get("operating_currency", ["USD"])[0]

        for payee, data in sorted(merchant_data.items()):
            if len(data["transactions"]) < 1:
                continue

            total = data["total_spent"].get(main_currency, Decimal("0"))
            if total == 0 and data["total_spent"]:
                total = sum(data["total_spent"].values(), Decimal("0"))

            safe_name = self._slugify(payee)
            content = self._render_merchant(payee, data, main_currency)

            page_path = merchants_dir / f"{safe_name}.md"
            page = WikiPage(
                path=page_path,
                metadata={
                    "title": payee,
                    "type": "merchant",
                    "total_transactions": len(data["transactions"]),
                    "total_spent": str(total),
                    "currency": main_currency,
                    "first_seen": str(data["first_seen"]) if data["first_seen"] else "",
                    "last_seen": str(data["last_seen"]) if data["last_seen"] else "",
                },
                content=content,
            )
            page.save()
            stats["merchants_generated"] += 1

        self.wiki._update_index()
        return stats

    def _render_merchant(self, payee: str, data: dict, currency: str) -> str:
        txns = data["transactions"]
        total = data["total_spent"].get(currency, Decimal("0"))
        if total == 0 and data["total_spent"]:
            total = sum(data["total_spent"].values(), Decimal("0"))

        lines = [
            f"# {payee}",
            "",
            "## Summary",
            f"- **Total transactions:** {len(txns)}",
            f"- **Total spent:** {total} {currency}",
            f"- **First seen:** {data['first_seen']}",
            f"- **Last seen:** {data['last_seen']}",
            "",
            "## Recent Transactions",
            "| Date | Amount | Description |",
            "|------|--------|-------------|",
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

    @staticmethod
    def _slugify(name: str) -> str:
        import re
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")
        return slug or "unknown"
