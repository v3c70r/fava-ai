"""Portfolio extractor — generates wiki/portfolio/*.md."""

from collections import defaultdict
from decimal import Decimal

from beancount.core import realization
from fava_ai.knowledge.wiki import WikiManager, WikiPage


class PortfolioExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        self.wiki.delete_dir("portfolio")
        port_dir = self.wiki.wiki_dir / "portfolio"
        port_dir.mkdir(parents=True, exist_ok=True)

        commodities = defaultdict(lambda: {
            "total_units": Decimal("0"),
            "accounts": set(),
            "transactions": 0,
        })

        for entry in entries:
            if not hasattr(entry, "postings"):
                continue
            for p in entry.postings:
                if p.units and (p.account.startswith("Assets:") or p.account == "Assets"):
                    ccy = p.units.currency
                    c = commodities[ccy]
                    c["total_units"] += p.units.number
                    c["accounts"].add(p.account)
                    c["transactions"] += 1

        oper_ccy = options.get("operating_currency", ["USD"])[0]

        lines = [
            "# Portfolio",
            "",
            "## Holdings",
            f"*Extracted from Assets accounts*",
            "",
            "| Commodity | Total Units | Accounts | Transactions |",
            "|-----------|------------|----------|-------------|",
        ]

        stats = {"holdings": 0}
        for ccy, data in sorted(commodities.items()):
            if ccy == oper_ccy:
                continue
            lines.append(
                f"| {ccy} | {data['total_units']} | {len(data['accounts'])} | {data['transactions']} |"
            )
            stats["holdings"] += 1

        content = "\n".join(lines)

        page = WikiPage(
            path=port_dir / "holdings.md",
            metadata={
                "title": "Portfolio Holdings",
                "type": "portfolio",
                "holdings_count": stats["holdings"],
            },
            content=content,
        )
        page.save()

        self.wiki._update_index()
        return {"portfolio_pages": 1, "holdings": stats["holdings"]}
