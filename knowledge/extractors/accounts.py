"""Account graph extractor — generates wiki/accounts/*.md."""

from collections import defaultdict

from beancount.core import realization
from fava_ai.knowledge.wiki import WikiManager, WikiPage
from fava_ai.util.inventory import summarize_inventory


class AccountExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        root = realization.realize(entries)
        stats = {"accounts_generated": 0}

        self.wiki.delete_dir("accounts")
        accounts_dir = self.wiki.wiki_dir / "accounts"
        accounts_dir.mkdir(parents=True, exist_ok=True)

        counts = self._transaction_counts(entries)

        accounts_data = []
        for real_acct in realization.iter_children(root):
            name = real_acct.account
            if name in ("", "root"):
                continue
            # Direct children only — `iter_children` is a pre-order traversal
            # that yields the node itself first (which made every page list
            # itself as its own sub-account).
            children = [child.account for child in real_acct.values() if child.account]
            accounts_data.append({
                "name": name,
                "balance": summarize_inventory(real_acct.balance),
                "aggregate_balance": summarize_inventory(
                    realization.compute_balance(real_acct)
                ),
                "depth": name.count(":"),
                "parent": ":".join(name.split(":")[:-1]) if ":" in name else "",
                "children": children,
                "transaction_count": counts.get(name, 0),
            })

        for data in accounts_data:
            safe_name = data["name"].replace(":", "-")
            content = self._render_account(data)

            page = WikiPage(
                path=accounts_dir / f"{safe_name}.md",
                metadata={
                    "title": data["name"],
                    "type": "account",
                    "balance": data["balance"],
                    "aggregate_balance": data["aggregate_balance"],
                    "depth": data["depth"],
                    "transaction_count": data["transaction_count"],
                },
                content=content,
            )
            page.save()
            stats["accounts_generated"] += 1

        self.wiki._update_index()
        return stats

    @staticmethod
    def _transaction_counts(entries) -> dict:
        """Transactions touching each account's subtree, counted once each."""
        counts: dict[str, int] = defaultdict(int)
        for entry in entries:
            if not hasattr(entry, "postings"):
                continue
            accounts: set[str] = set()
            for posting in entry.postings:
                parts = posting.account.split(":")
                for i in range(1, len(parts) + 1):
                    accounts.add(":".join(parts[:i]))
            for account in accounts:
                counts[account] += 1
        return counts

    def _render_account(self, data: dict) -> str:
        lines = [
            f"# {data['name']}",
            "",
            "## Summary",
            f"- **Balance (own):** {data['balance']}",
            f"- **Balance (including sub-accounts):** {data['aggregate_balance']}",
            f"- **Depth:** {data['depth']}",
            f"- **Transaction count:** {data['transaction_count']}",
        ]

        if data["parent"]:
            safe_parent = data["parent"].replace(":", "-")
            lines.append(f"- **Parent:** [[accounts/{safe_parent}.md|{data['parent']}]]")

        if data["children"]:
            lines.append("")
            lines.append("## Sub-accounts")
            for child in data["children"]:
                safe_child = child.replace(":", "-")
                lines.append(f"- [[accounts/{safe_child}.md|{child}]]")

        return "\n".join(lines)
