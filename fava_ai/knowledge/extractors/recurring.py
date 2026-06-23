"""Recurring transaction detector — generates wiki/recurring/*.md."""

from collections import defaultdict
from decimal import Decimal

from fava_ai.knowledge.wiki import WikiManager, WikiPage


class RecurringExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        self.wiki.delete_dir("recurring")
        recurring_dir = self.wiki.wiki_dir / "recurring"
        recurring_dir.mkdir(parents=True, exist_ok=True)

        payee_txns = defaultdict(list)
        for entry in entries:
            if not hasattr(entry, "payee") or not entry.payee:
                continue
            if not hasattr(entry, "date"):
                continue
            payee = str(entry.payee).strip()
            if not payee:
                continue
            payee_txns[payee].append(entry)

        recurring = {}
        for payee, txns in payee_txns.items():
            if len(txns) < 3:
                continue

            sorted_txns = sorted(txns, key=lambda e: e.date)
            intervals = []
            for i in range(1, len(sorted_txns)):
                delta = (sorted_txns[i].date - sorted_txns[i-1].date).days
                intervals.append(delta)

            if not intervals:
                continue

            avg_interval = sum(intervals) / len(intervals)
            min_interval = min(intervals)
            max_interval = max(intervals)

            is_monthly = 25 <= avg_interval <= 35 and min_interval >= 20 and max_interval <= 45
            is_weekly = 5 <= avg_interval <= 9 and min_interval >= 3 and max_interval <= 12
            is_yearly = 350 <= avg_interval <= 380 and min_interval >= 340 and max_interval <= 400

            if not (is_monthly or is_weekly or is_yearly):
                continue

            if is_monthly:
                period = "monthly"
            elif is_weekly:
                period = "weekly"
            else:
                period = "yearly"

            amounts = []
            accounts = set()
            for e in sorted_txns:
                if hasattr(e, "postings"):
                    for p in e.postings:
                        if p.units:
                            amounts.append(p.units.number)
                            accounts.add(p.account)

            if not amounts:
                continue

            avg_amount = sum(amounts, Decimal("0")) / len(amounts)

            recurring[payee] = {
                "payee": payee,
                "period": period,
                "transaction_count": len(txns),
                "average_interval": round(avg_interval, 1),
                "average_amount": round(avg_amount, 2),
                "first_seen": str(sorted_txns[0].date),
                "last_seen": str(sorted_txns[-1].date),
                "accounts": sorted(accounts),
            }

        stats = {"recurring_generated": 0}
        main_currency = options.get("operating_currency", ["USD"])[0]

        for payee, data in sorted(recurring.items()):
            safe_name = self._slugify(payee)
            content = self._render_recurring(data, main_currency)

            page_path = recurring_dir / f"{safe_name}.md"
            page = WikiPage(
                path=page_path,
                metadata={
                    "title": payee,
                    "type": "recurring",
                    "period": data["period"],
                    "transaction_count": data["transaction_count"],
                    "average_amount": str(data["average_amount"]),
                    "currency": main_currency,
                },
                content=content,
            )
            page.save()
            stats["recurring_generated"] += 1

        self.wiki._update_index()
        return stats

    def _render_recurring(self, data: dict, currency: str) -> str:
        return "\n".join([
            f"# {data['payee']}",
            "",
            "## Summary",
            f"- **Period:** {data['period']}",
            f"- **Transactions:** {data['transaction_count']}",
            f"- **Average interval:** {data['average_interval']} days",
            f"- **Average amount:** {data['average_amount']} {currency}",
            f"- **First seen:** {data['first_seen']}",
            f"- **Last seen:** {data['last_seen']}",
            "",
            "## Accounts",
            *[f"- {a}" for a in data.get("accounts", [])],
        ])

    @staticmethod
    def _slugify(name: str) -> str:
        import re
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        return slug.strip("-") or "unknown"
