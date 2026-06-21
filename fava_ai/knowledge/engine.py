"""KnowledgeEngine — orchestrates extraction to wiki on ledger load."""

import hashlib
import json
from pathlib import Path

from fava_ai.knowledge.wiki import WikiManager
from fava_ai.knowledge.extractors.accounts import AccountExtractor
from fava_ai.knowledge.extractors.merchants import MerchantExtractor
from fava_ai.knowledge.extractors.recurring import RecurringExtractor
from fava_ai.knowledge.extractors.portfolio import PortfolioExtractor
from fava_ai.knowledge.extractors.spending import SpendingExtractor, CashflowExtractor


class KnowledgeEngine:
    def __init__(self, wiki: WikiManager, config: dict | None = None):
        self.wiki = wiki
        self.config = config or {}
        self._last_hash = None
        self._extractors = [
            ("accounts", AccountExtractor(wiki)),
            ("merchants", MerchantExtractor(wiki)),
            ("recurring", RecurringExtractor(wiki)),
            ("portfolio", PortfolioExtractor(wiki)),
            ("spending", SpendingExtractor(wiki)),
            ("cashflow", CashflowExtractor(wiki)),
        ]

    def needs_rebuild(self, entries) -> bool:
        h = self._compute_hash(entries)
        hash_file = self.wiki.wiki_dir / ".entries_hash"
        if not hash_file.exists():
            return True
        old_hash = hash_file.read_text().strip()
        return old_hash != h

    def extract_all(self, entries, options) -> dict:
        h = self._compute_hash(entries)
        hash_file = self.wiki.wiki_dir / ".entries_hash"
        hash_file.write_text(h)

        self._init_agents_md(options)
        self.wiki.append_log("extraction_start", {"entries": len(entries)})

        total_stats = {}
        for name, extractor in self._extractors:
            try:
                stats = extractor.extract(entries, options)
                total_stats[name] = stats
            except Exception as e:
                total_stats[name] = {"error": str(e)}

        self._generate_overview(entries, options)
        self.wiki.append_log("extraction_complete", total_stats)
        return total_stats

    def _init_agents_md(self, options):
        path = self.wiki.wiki_dir / "AGENTS.md"
        if not path.exists():
            currencies = options.get("operating_currency", ["USD"])
            path.write_text(
                "---\ntitle: AGENTS\ntype: meta\n---\n\n"
                "# AGENTS.md\n\n"
                "This wiki is auto-generated from the Beancount ledger.\n"
                f"- Operating currencies: {', '.join(currencies)}\n"
                "- Each page has YAML frontmatter with metadata\n"
                "- Use the `wiki_search`, `wiki_read`, `wiki_list` tools to browse\n"
                "- index.md lists all pages by type\n"
                "- log.md is the chronological audit log\n",
                encoding="utf-8",
            )

    def _generate_overview(self, entries, options):
        txns = [e for e in entries if hasattr(e, "date")]
        dates = [e.date for e in txns] if txns else []
        date_range = f"{min(dates)} to {max(dates)}" if dates else "N/A"

        currencies = set()
        accounts = set()
        for e in entries:
            if hasattr(e, "postings"):
                for p in e.postings:
                    if p.units:
                        currencies.add(p.units.currency)
                    accounts.add(p.account)

        content = "\n".join([
            "# Ledger Overview",
            "",
            "## Summary",
            f"- **Operating currencies:** {', '.join(options.get('operating_currency', ['USD']))}",
            f"- **All currencies:** {', '.join(sorted(currencies))}",
            f"- **Transaction count:** {len(txns)}",
            f"- **Account count:** {len(accounts)}",
            f"- **Date range:** {date_range}",
            "",
            "## Sections",
            "- [[accounts/_index.md|Accounts]] — Account hierarchy with balances",
            "- [[merchants/_index.md|Merchants]] — Payee/merchant catalog",
            "- [[recurring/_index.md|Recurring]] — Detected recurring transactions",
            "- [[portfolio/holdings.md|Portfolio]] — Investment holdings",
            "- [[patterns/spending.md|Spending]] — Spending patterns by category",
            "- [[patterns/cashflow.md|Cashflow]] — Monthly income vs expenses",
            "",
            f"*Generated: auto*",
        ])

        overview = self.wiki.wiki_dir / "overview.md"
        overview.write_text(
            "---\ntitle: Ledger Overview\ntype: overview\n---\n\n" + content,
            encoding="utf-8",
        )

    @staticmethod
    def _compute_hash(entries) -> str:
        h = hashlib.sha256()
        for e in entries:
            if hasattr(e, "date"):
                h.update(str(e.date).encode())
            if hasattr(e, "payee") and e.payee:
                h.update(str(e.payee).encode())
        return h.hexdigest()
