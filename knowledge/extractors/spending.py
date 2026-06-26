"""Spending patterns extractor — generates wiki/patterns/spending.md."""

from collections import defaultdict
from decimal import Decimal

from fava_ai.knowledge.wiki import WikiManager, WikiPage


class SpendingExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        patterns_dir = self.wiki.wiki_dir / "patterns"
        patterns_dir.mkdir(parents=True, exist_ok=True)

        by_category = defaultdict(Decimal)
        by_month = defaultdict(Decimal)
        oper_ccy = options.get("operating_currency", ["USD"])[0]

        for entry in entries:
            if not hasattr(entry, "postings"):
                continue
            for p in entry.postings:
                if not p.units or p.units.currency != oper_ccy:
                    continue
                if not p.account.startswith("Expenses"):
                    continue

                parts = p.account.split(":")
                if len(parts) >= 3:
                    category = ":".join(parts[:3])
                elif len(parts) == 2:
                    category = p.account
                else:
                    category = p.account

                by_category[category] += abs(p.units.number)

                if hasattr(entry, "date"):
                    month_key = entry.date.strftime("%Y-%m")
                    by_month[month_key] += abs(p.units.number)

        lines = [
            "# Spending Patterns",
            "",
            "## By Category",
            f"*Currency: {oper_ccy}*",
            "",
            "| Category | Total |",
            "|----------|-------|",
        ]

        for cat, total in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {cat} | {total:.2f} {oper_ccy} |")

        lines.append("")
        lines.append("## By Month")
        lines.append("")
        lines.append("| Month | Total |")
        lines.append("|-------|-------|")

        for month, total in sorted(by_month.items()):
            lines.append(f"| {month} | {total:.2f} {oper_ccy} |")

        content = "\n".join(lines)

        page = WikiPage(
            path=patterns_dir / "spending.md",
            metadata={
                "title": "Spending Patterns",
                "type": "patterns",
                "currency": oper_ccy,
                "categories": len(by_category),
                "months": len(by_month),
            },
            content=content,
        )
        page.save()

        self.wiki._update_index()
        return {"spending_pages": 1, "categories": len(by_category)}


class CashflowExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        patterns_dir = self.wiki.wiki_dir / "patterns"
        patterns_dir.mkdir(parents=True, exist_ok=True)

        by_month = defaultdict(lambda: {"income": Decimal("0"), "expenses": Decimal("0")})
        oper_ccy = options.get("operating_currency", ["USD"])[0]

        for entry in entries:
            if not hasattr(entry, "postings") or not hasattr(entry, "date"):
                continue
            month_key = entry.date.strftime("%Y-%m")
            for p in entry.postings:
                if not p.units or p.units.currency != oper_ccy:
                    continue
                if p.account.startswith("Income"):
                    by_month[month_key]["income"] += abs(p.units.number)
                elif p.account.startswith("Expenses"):
                    by_month[month_key]["expenses"] += abs(p.units.number)

        lines = [
            "# Cash Flow",
            "",
            f"*Currency: {oper_ccy}*",
            "",
            "| Month | Income | Expenses | Net |",
            "|-------|--------|----------|-----|",
        ]

        for month in sorted(by_month.keys()):
            d = by_month[month]
            net = d["income"] - d["expenses"]
            lines.append(
                f"| {month} | {d['income']:.2f} | {d['expenses']:.2f} | {net:.2f} |"
            )

        content = "\n".join(lines)

        page = WikiPage(
            path=patterns_dir / "cashflow.md",
            metadata={
                "title": "Cash Flow",
                "type": "patterns",
                "currency": oper_ccy,
            },
            content=content,
        )
        page.save()

        self.wiki._update_index()
        return {"cashflow_pages": 1}
