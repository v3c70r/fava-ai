import json
from collections import defaultdict
from datetime import date

from fava_ai.tools.base import BaseTool, ToolResult
from beancount.query import query as bql_query
from beancount.core import realization
from beancount.core.inventory import Inventory
from beancount.core.amount import Amount


def _prepare_entries(ledger):
    """Get all entries from ledger."""
    return ledger.all_entries


class RunBQLTool(BaseTool):
    def __init__(self, ledger):
        self._ledger = ledger

    @property
    def name(self) -> str:
        return "run_bql"

    @property
    def description(self) -> str:
        return (
            "Execute a Beancount Query Language (BQL) query against the ledger. "
            "BQL is an SQL-like language. Common columns: account, date, number(position), "
            "payee, narration, balance, change. Use SELECT with SUM(position), COUNT(*), etc. "
            "Filter with WHERE account ~ 'Expenses' or WHERE date >= 2024-01-01."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "BQL query string to execute",
                },
            },
            "required": ["query"],
        }

    def execute(self, query: str) -> ToolResult:
        try:
            rtypes, rrows = bql_query.run_query(
                self._ledger.all_entries,
                self._ledger.options,
                query,
            )
            columns = [col[0] for col in rtypes]
            rows = []
            for row in rrows:
                row_data = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    if isinstance(val, date):
                        val = val.isoformat()
                    elif isinstance(val, Inventory):
                        val = val.to_string()
                    elif isinstance(val, Amount):
                        val = str(val)
                    elif hasattr(val, 'to_pydecimal'):
                        val = str(val.to_pydecimal())
                    elif val is not None and hasattr(val, 'real'):
                        val = val.real
                    row_data[col] = val if val is not None else ""
                rows.append(row_data)

            result_text = json.dumps({"columns": columns, "rows": rows, "row_count": len(rows)}, indent=2, ensure_ascii=False)
            return ToolResult(
                content=result_text,
                metadata={"columns": columns, "row_count": len(rows), "bql": query},
            )
        except Exception as e:
            return ToolResult(
                content=f"BQL Error: {e}",
                metadata={"error": str(e), "bql": query},
            )


class ListAccountsTool(BaseTool):
    def __init__(self, ledger):
        self._ledger = ledger

    @property
    def name(self) -> str:
        return "list_accounts"

    @property
    def description(self) -> str:
        return "List all accounts in the ledger, optionally filtered by a prefix. Returns account names and their current balances."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "Optional account name prefix to filter by (e.g. 'Expenses', 'Assets')",
                },
            },
        }

    def execute(self, prefix: str = "") -> ToolResult:
        entries = self._ledger.all_entries
        root = realization.realize(entries)

        accounts = []
        for real_account in realization.iter_children(root):
            acct_name = real_account.account
            if prefix and not acct_name.startswith(prefix):
                continue
            balance = real_account.balance
            accounts.append({
                "account": acct_name,
                "balance": balance.to_string() if not balance.is_empty() else "0",
            })

        result_text = json.dumps({"accounts": accounts, "count": len(accounts)}, indent=2, ensure_ascii=False)
        return ToolResult(content=result_text, metadata={"count": len(accounts)})


class AccountDetailsTool(BaseTool):
    def __init__(self, ledger):
        self._ledger = ledger

    @property
    def name(self) -> str:
        return "account_details"

    @property
    def description(self) -> str:
        return "Get detailed information about a specific account: current balance, recent postings, and metadata."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "account": {
                    "type": "string",
                    "description": "Full account name (e.g. 'Expenses:Food:Restaurant')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of recent postings to return (default 20)",
                },
            },
            "required": ["account"],
        }

    def execute(self, account: str, limit: int = 20) -> ToolResult:
        entries = self._ledger.all_entries

        postings_list = []
        count = 0
        for entry in entries:
            if hasattr(entry, 'postings'):
                for posting in entry.postings:
                    if posting.account == account:
                        count += 1
                        if len(postings_list) < limit:
                            postings_list.append({
                                "date": entry.date.isoformat() if hasattr(entry, 'date') else "",
                                "payee": str(entry.payee) if hasattr(entry, 'payee') and entry.payee else "",
                                "narration": str(entry.narration) if hasattr(entry, 'narration') and entry.narration else "",
                                "amount": posting.units.to_string() if posting.units else "0",
                            })

        root = realization.realize(entries)
        acct_node = realization.get_or_create(root, account)
        balance = acct_node.balance.to_string() if not acct_node.balance.is_empty() else "0"

        result = {
            "account": account,
            "balance": balance,
            "total_postings": count,
            "recent_postings": postings_list,
        }
        return ToolResult(
            content=json.dumps(result, indent=2, ensure_ascii=False),
            metadata={"account": account, "total_postings": count},
        )


class SearchTransactionsTool(BaseTool):
    def __init__(self, ledger):
        self._ledger = ledger

    @property
    def name(self) -> str:
        return "search_transactions"

    @property
    def description(self) -> str:
        return "Full-text search across transactions by payee, narration, or account name."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Search query string (case-insensitive)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 25)",
                },
            },
            "required": ["q"],
        }

    def execute(self, q: str, limit: int = 25) -> ToolResult:
        query_lower = q.lower()
        results = []
        for entry in self._ledger.all_entries:
            if not hasattr(entry, 'date'):
                continue
            if not hasattr(entry, 'payee') and not hasattr(entry, 'narration'):
                continue
            payee = str(entry.payee).lower() if hasattr(entry, 'payee') and entry.payee else ""
            narration = str(entry.narration).lower() if hasattr(entry, 'narration') and entry.narration else ""

            if query_lower in payee or query_lower in narration:
                postings = []
                if hasattr(entry, 'postings'):
                    for p in entry.postings:
                        postings.append({
                            "account": p.account,
                            "amount": p.units.to_string() if p.units else "0",
                        })

                results.append({
                    "date": entry.date.isoformat(),
                    "payee": str(entry.payee) if hasattr(entry, 'payee') and entry.payee else "",
                    "narration": str(entry.narration) if hasattr(entry, 'narration') and entry.narration else "",
                    "postings": postings,
                })

            if len(results) >= limit:
                break

        result_text = json.dumps({"results": results, "count": len(results)}, indent=2, ensure_ascii=False)
        return ToolResult(content=result_text, metadata={"query": q, "count": len(results)})


class LedgerInfoTool(BaseTool):
    def __init__(self, ledger):
        self._ledger = ledger

    @property
    def name(self) -> str:
        return "ledger_info"

    @property
    def description(self) -> str:
        return "Get a summary of the ledger: date range, operating currencies, account count, transaction count, and commodity list."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {},
        }

    def execute(self) -> ToolResult:
        entries = self._ledger.all_entries
        options = self._ledger.options

        txns = [e for e in entries if hasattr(e, 'date')]
        dates = [e.date for e in txns]
        date_range = f"{min(dates)} to {max(dates)}" if dates else "N/A"

        accounts_set = set()
        for e in entries:
            if hasattr(e, 'postings'):
                for p in e.postings:
                    accounts_set.add(p.account)
        account_count = len(accounts_set)

        currencies = set()
        for e in entries:
            if hasattr(e, 'postings'):
                for p in e.postings:
                    if p.units:
                        currencies.add(p.units.currency)

        commodities = set()
        for c in options.get("commodities", []):
            commodities.add(str(c))

        result = {
            "operating_currencies": list(options.get("operating_currency", [])),
            "all_currencies": sorted([str(c) for c in currencies]),
            "commodities": sorted([str(c) for c in commodities]),
            "transaction_count": len(txns),
            "account_count": account_count,
            "date_range": date_range,
        }
        return ToolResult(
            content=json.dumps(result, indent=2, ensure_ascii=False),
            metadata=result,
        )


def register_ledger_tools(registry, ledger):
    registry.register(RunBQLTool(ledger))
    registry.register(ListAccountsTool(ledger))
    registry.register(AccountDetailsTool(ledger))
    registry.register(SearchTransactionsTool(ledger))
    registry.register(LedgerInfoTool(ledger))
