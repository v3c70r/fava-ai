"""Recurring transaction detector — generates wiki/recurring/*.md."""

from collections import defaultdict
from decimal import Decimal

from fava_ai.knowledge.extractors.naming import merchant_key, slugify
from fava_ai.knowledge.wiki import WikiManager, WikiPage


class RecurringExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        self.wiki.delete_dir("recurring")
        recurring_dir = self.wiki.wiki_dir / "recurring"
        recurring_dir.mkdir(parents=True, exist_ok=True)

        by_merchant: dict[str, list] = defaultdict(list)
        for entry in entries:
            if not hasattr(entry, "date"):
                continue
            key = merchant_key(entry)
            if key:
                by_merchant[key].append(entry)

        recurring = {}
        for name, txns in by_merchant.items():
            if len(txns) < 3:
                continue

            sorted_txns = sorted(txns, key=lambda e: e.date)
            intervals = [
                (sorted_txns[i].date - sorted_txns[i - 1].date).days
                for i in range(1, len(sorted_txns))
            ]
            if not intervals:
                continue

            avg_interval = sum(intervals) / len(intervals)
            min_interval = min(intervals)
            max_interval = max(intervals)

            if 25 <= avg_interval <= 35 and min_interval >= 20 and max_interval <= 45:
                period = "monthly"
            elif 5 <= avg_interval <= 9 and min_interval >= 3 and max_interval <= 12:
                period = "weekly"
            elif 350 <= avg_interval <= 380 and min_interval >= 340 and max_interval <= 400:
                period = "yearly"
            else:
                continue

            # Sum expense postings per currency, per occurrence.
            per_ccy_total: dict[str, Decimal] = defaultdict(Decimal)
            per_ccy_count: dict[str, int] = defaultdict(int)
            accounts: set[str] = set()
            for e in sorted_txns:
                ccy_amounts: dict[str, Decimal] = defaultdict(Decimal)
                if hasattr(e, "postings"):
                    for p in e.postings:
                        if p.units and p.account.startswith("Expenses"):
                            ccy_amounts[p.units.currency] += abs(p.units.number)
                            accounts.add(p.account)
                for ccy, amt in ccy_amounts.items():
                    per_ccy_total[ccy] += amt
                    per_ccy_count[ccy] += 1

            if not per_ccy_total:
                continue

            averages = {
                ccy: (per_ccy_total[ccy] / per_ccy_count[ccy]).quantize(Decimal("0.01"))
                for ccy in per_ccy_total
            }

            recurring[name] = {
                "name": name,
                "period": period,
                "transaction_count": len(txns),
                "average_interval": round(avg_interval, 1),
                "averages": averages,
                "first_seen": str(sorted_txns[0].date),
                "last_seen": str(sorted_txns[-1].date),
                "accounts": sorted(accounts),
            }

        stats = {"recurring_generated": 0}
        oper_ccys = options.get("operating_currency", ["USD"]) or ["USD"]
        main_currency = oper_ccys[0]

        for name, data in sorted(recurring.items()):
            safe_name = slugify(name)
            content = self._render_recurring(data)

            page = WikiPage(
                path=recurring_dir / f"{safe_name}.md",
                metadata={
                    "title": name,
                    "type": "recurring",
                    "period": data["period"],
                    "transaction_count": data["transaction_count"],
                    "average_amount": str(
                        data["averages"].get(main_currency)
                        or next(iter(data["averages"].values()))
                    ),
                    "currencies": sorted(data["averages"]),
                },
                content=content,
            )
            page.save()
            stats["recurring_generated"] += 1

        self.wiki._update_index()
        return stats

    def _render_recurring(self, data: dict) -> str:
        lines = [
            f"# {data['name']}",
            "",
            "## Summary",
            f"- **Period:** {data['period']}",
            f"- **Transactions:** {data['transaction_count']}",
            f"- **Average interval:** {data['average_interval']} days",
            f"- **First seen:** {data['first_seen']}",
            f"- **Last seen:** {data['last_seen']}",
            "",
            "## Average amount",
            "",
            "| Currency | Average |",
            "|----------|---------|",
        ]
        for ccy in sorted(data["averages"]):
            lines.append(f"| {ccy} | {data['averages'][ccy]} |")

        if data.get("accounts"):
            lines.append("")
            lines.append("## Accounts")
            lines.extend(f"- {a}" for a in data["accounts"])

        return "\n".join(lines)
