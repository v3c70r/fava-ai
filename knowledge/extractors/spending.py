"""Spending patterns extractor — generates wiki/patterns/spending.md."""

from collections import defaultdict
from decimal import Decimal

from fava_ai.knowledge.wiki import WikiManager, WikiPage


def _ordered_currencies(seen: set[str], options: dict) -> list[str]:
    """Operating currencies first, then any others seen, all sorted."""
    operating = list(options.get("operating_currency", []) or [])
    ordered = [c for c in operating if c in seen]
    ordered += sorted(c for c in seen if c not in ordered)
    return ordered


class SpendingExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        patterns_dir = self.wiki.wiki_dir / "patterns"
        patterns_dir.mkdir(parents=True, exist_ok=True)

        # currency -> category -> total
        by_category: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        # currency -> month -> total
        by_month: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))

        for entry in entries:
            if not hasattr(entry, "postings"):
                continue
            for p in entry.postings:
                if not p.units or not p.account.startswith("Expenses"):
                    continue
                ccy = p.units.currency
                parts = p.account.split(":")
                category = ":".join(parts[:3]) if len(parts) >= 3 else p.account

                by_category[ccy][category] += abs(p.units.number)
                if hasattr(entry, "date"):
                    by_month[ccy][entry.date.strftime("%Y-%m")] += abs(p.units.number)

        currencies = _ordered_currencies(set(by_category) | set(by_month), options)

        lines = ["# Spending Patterns", ""]
        if not currencies:
            lines += ["_No expense postings found._", ""]
        else:
            lines += [
                "Currencies included: " + ", ".join(currencies) + ".",
                "Each currency is reported separately; amounts are never mixed.",
                "",
            ]
            for ccy in currencies:
                lines += [f"## {ccy}", "", "### By Category", "",
                          "| Category | Total |", "|----------|-------|"]
                for cat, total in sorted(
                    by_category.get(ccy, {}).items(), key=lambda x: x[1], reverse=True
                ):
                    lines.append(f"| {cat} | {total:.2f} {ccy} |")
                lines += ["", "### By Month", "",
                          "| Month | Total |", "|-------|-------|"]
                for month, total in sorted(by_month.get(ccy, {}).items()):
                    lines.append(f"| {month} | {total:.2f} {ccy} |")
                lines.append("")

        page = WikiPage(
            path=patterns_dir / "spending.md",
            metadata={
                "title": "Spending Patterns",
                "type": "patterns",
                "currencies": currencies,
                "categories": sum(len(v) for v in by_category.values()),
            },
            content="\n".join(lines),
        )
        page.save()

        self.wiki._update_index()
        return {
            "spending_pages": 1,
            "currencies": len(currencies),
            "categories": sum(len(v) for v in by_category.values()),
        }


class CashflowExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        patterns_dir = self.wiki.wiki_dir / "patterns"
        patterns_dir.mkdir(parents=True, exist_ok=True)

        # currency -> month -> {"income", "expenses"}
        by_month: dict[str, dict[str, dict[str, Decimal]]] = defaultdict(
            lambda: defaultdict(lambda: {"income": Decimal("0"), "expenses": Decimal("0")})
        )

        for entry in entries:
            if not hasattr(entry, "postings") or not hasattr(entry, "date"):
                continue
            month_key = entry.date.strftime("%Y-%m")
            for p in entry.postings:
                if not p.units:
                    continue
                ccy = p.units.currency
                if p.account.startswith("Income"):
                    by_month[ccy][month_key]["income"] += abs(p.units.number)
                elif p.account.startswith("Expenses"):
                    by_month[ccy][month_key]["expenses"] += abs(p.units.number)

        currencies = _ordered_currencies(set(by_month), options)

        lines = ["# Cash Flow", ""]
        if not currencies:
            lines += ["_No income or expense postings found._", ""]
        else:
            lines += [
                "Currencies included: " + ", ".join(currencies) + ".",
                "Each currency is reported separately; amounts are never mixed.",
                "",
            ]
            for ccy in currencies:
                lines += [f"## {ccy}", "",
                          "| Month | Income | Expenses | Net |",
                          "|-------|--------|----------|-----|"]
                for month in sorted(by_month[ccy].keys()):
                    d = by_month[ccy][month]
                    net = d["income"] - d["expenses"]
                    lines.append(
                        f"| {month} | {d['income']:.2f} | {d['expenses']:.2f} | {net:.2f} |"
                    )
                lines.append("")

        page = WikiPage(
            path=patterns_dir / "cashflow.md",
            metadata={
                "title": "Cash Flow",
                "type": "patterns",
                "currencies": currencies,
            },
            content="\n".join(lines),
        )
        page.save()

        self.wiki._update_index()
        return {"cashflow_pages": 1, "currencies": len(currencies)}
