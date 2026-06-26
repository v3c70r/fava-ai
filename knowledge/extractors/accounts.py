"""Account graph extractor — generates wiki/accounts/*.md."""

from beancount.core import realization

from fava_ai.knowledge.wiki import WikiManager, WikiPage


class AccountExtractor:
    def __init__(self, wiki: WikiManager):
        self.wiki = wiki

    def extract(self, entries, options) -> dict:
        root = realization.realize(entries)
        stats = {"accounts_generated": 0}

        self.wiki.delete_dir("accounts")

        accounts_dir = self.wiki.wiki_dir / "accounts"
        accounts_dir.mkdir(parents=True, exist_ok=True)

        accounts_data = []
        for real_acct in realization.iter_children(root):
            acct_name = real_acct.account
            if acct_name in ("", "root"):
                continue

            balance = real_acct.balance
            balance_str = balance.to_string() if not balance.is_empty() else "0"

            children = []
            for child in realization.iter_children(real_acct):
                children.append(child.account)

            txns_count = 0
            for e in entries:
                if hasattr(e, "postings"):
                    for p in e.postings:
                        if p.account == acct_name or p.account.startswith(acct_name + ":"):
                            txns_count += 1
                            break

            depth = acct_name.count(":")
            parent = ":".join(acct_name.split(":")[:-1]) if ":" in acct_name else ""

            accounts_data.append({
                "name": acct_name,
                "balance": balance_str,
                "depth": depth,
                "parent": parent,
                "children": children,
                "transaction_count": txns_count,
            })

        for data in accounts_data:
            safe_name = data["name"].replace(":", "-")
            content = self._render_account(data, accounts_data)

            page_path = accounts_dir / f"{safe_name}.md"
            page = WikiPage(
                path=page_path,
                metadata={
                    "title": data["name"],
                    "type": "account",
                    "balance": data["balance"],
                    "depth": data["depth"],
                    "transaction_count": data["transaction_count"],
                },
                content=content,
            )
            page.save()
            stats["accounts_generated"] += 1

        self.wiki._update_index()
        return stats

    def _render_account(self, data: dict, all_data: list) -> str:
        lines = [
            f"# {data['name']}",
            "",
            "## Summary",
            f"- **Balance:** {data['balance']}",
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
