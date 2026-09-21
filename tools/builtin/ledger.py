import json
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fava_ai.tools.base import BaseTool, ToolResult

try:
    from beanquery import query as bql_query
except ImportError:
    from beancount.query import query as bql_query
from beancount.core import realization
from beancount.core.amount import Amount
from beancount.core.inventory import Inventory


def _prepare_entries(ledger):
    """Get all entries from ledger."""
    return ledger.all_entries


#: Tools must not dump unbounded output into the model context.
MAX_TOOL_ROWS = 200
MAX_TOOL_CHARS = 8000


def _fit_rows(rows, build, max_rows=MAX_TOOL_ROWS, max_chars=MAX_TOOL_CHARS):
    """Bound a list of row dicts so the serialized payload fits the budget.

    ``build`` serializes a candidate row list for the size check. Returns the
    (possibly truncated) rows and whether truncation happened. When the payload
    is too large it keeps the largest fitting prefix (binary search) rather than
    halving, so as many leading rows as possible are preserved.
    """
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    if not rows or len(build(rows)) <= max_chars:
        return rows, truncated

    lo, hi, best = 1, len(rows), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if len(build(rows[:mid])) <= max_chars:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return rows[:best], True


def _json_safe(val):
    """Convert a BQL result value into something JSON-serialisable."""
    if val is None:
        return ""
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, Inventory):
        return val.to_string()
    if isinstance(val, Amount):
        return str(val)
    if isinstance(val, Decimal):
        return str(val)
    if hasattr(val, "to_pydecimal"):
        return str(val.to_pydecimal())
    if isinstance(val, (str, bool, int, float)):
        return val
    if hasattr(val, "real"):
        return val.real
    return str(val)


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
            all_rows = []
            for row in rrows:
                row_data = {
                    col: _json_safe(row[i]) for i, col in enumerate(columns)
                }
                all_rows.append(row_data)

            total = len(all_rows)
            rows, truncated = _fit_rows(
                all_rows,
                lambda r: json.dumps(
                    {"columns": columns, "rows": r}, ensure_ascii=False
                ),
            )
            payload = {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "total_rows": total,
                "truncated": truncated,
            }
            result_text = json.dumps(payload, indent=2, ensure_ascii=False)
            return ToolResult(
                content=result_text,
                metadata={
                    "columns": columns, "row_count": len(rows),
                    "total_rows": total, "truncated": truncated, "bql": query,
                },
            )
        except Exception as e:
            return ToolResult(
                content=f"BQL Error: {e}",
                metadata={"error": str(e), "bql": query},
            )


def _inv_summary(inv: Inventory) -> str:
    """Sum an inventory by currency, collapsing cost lots.

    A full inventory can be kilobytes of per-lot detail (one entry per purchase);
    for account listing we only need the per-currency totals.
    """
    if inv.is_empty():
        return "0"
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for position in inv:
        units = getattr(position, "units", None)
        if units is not None:
            totals[units.currency] += units.number
    totals = {c: n for c, n in totals.items() if n != 0}
    if not totals:
        return "0"
    return "(" + ", ".join(f"{n} {c}" for c, n in sorted(totals.items())) + ")"


def _inv_abs_total(inv: Inventory):
    """Rough magnitude across currencies, for sorting only."""
    total = Decimal("0")
    for position in inv:
        units = getattr(position, "units", None)
        if units is not None:
            total += abs(units.number)
    return total


class ListAccountsTool(BaseTool):
    def __init__(self, ledger):
        self._ledger = ledger

    @property
    def name(self) -> str:
        return "list_accounts"

    @property
    def description(self) -> str:
        return (
            "List accounts with two balances: `balance` (the account's own postings "
            "only) and `aggregate_balance` (including all sub-accounts). Use "
            "`aggregate_balance` for totals such as net worth — parent accounts "
            "correctly show their subtree total. Filter with `prefix` (e.g. 'Assets') "
            "or `contains` (any substring). Results are sorted by absolute aggregate "
            "balance and capped by `limit`."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "Optional account name prefix to filter by (e.g. 'Expenses', 'Assets')",
                },
                "contains": {
                    "type": "string",
                    "description": "Optional case-insensitive substring to match anywhere in the account name",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of accounts to return (default 100)",
                },
                "sort": {
                    "type": "string",
                    "enum": ["aggregate", "name"],
                    "description": "Sort by absolute aggregate balance (default) or by name",
                },
            },
        }

    def execute(self, prefix: str = "", contains: str = "", limit: int = 100,
                sort: str = "aggregate") -> ToolResult:
        entries = self._ledger.all_entries
        root = realization.realize(entries)
        contains_lower = contains.lower()

        rows = []
        for real_account in realization.iter_children(root):
            acct_name = real_account.account
            if not acct_name:
                continue
            if prefix and not acct_name.startswith(prefix):
                continue
            if contains_lower and contains_lower not in acct_name.lower():
                continue
            aggregate = realization.compute_balance(real_account)
            rows.append({
                "account": acct_name,
                "balance": _inv_summary(real_account.balance),
                "aggregate_balance": _inv_summary(aggregate),
                "depth": acct_name.count(":"),
                "_magnitude": _inv_abs_total(aggregate),
            })

        if sort == "name":
            rows.sort(key=lambda r: r["account"])
        else:
            rows.sort(key=lambda r: (-r["_magnitude"], r["account"]))

        total_matching = len(rows)
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = 100
        truncated = total_matching > limit
        rows = rows[:limit]
        for row in rows:
            row.pop("_magnitude", None)

        fitted, size_truncated = _fit_rows(
            rows, lambda r: json.dumps({"accounts": r}, indent=2, ensure_ascii=False)
        )
        payload = {
            "accounts": fitted,
            "count": len(fitted),
            "total_matching": total_matching,
            "truncated": truncated or size_truncated,
        }
        return ToolResult(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            metadata={"count": len(fitted), "total_matching": total_matching},
        )


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

        postings_list: list[dict] = []
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

        rows, truncated = _fit_rows(
            postings_list,
            lambda r: json.dumps({"recent_postings": r}, indent=2, ensure_ascii=False),
        )
        result = {
            "account": account,
            "balance": balance,
            "total_postings": count,
            "recent_postings": rows,
            "truncated": truncated or len(rows) < len(postings_list),
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
        results: list[dict] = []
        total_matches = 0
        for entry in self._ledger.all_entries:
            if not hasattr(entry, 'date'):
                continue
            if not hasattr(entry, 'payee') and not hasattr(entry, 'narration'):
                continue
            payee = str(entry.payee).lower() if hasattr(entry, 'payee') and entry.payee else ""
            narration = str(entry.narration).lower() if hasattr(entry, 'narration') and entry.narration else ""

            if query_lower in payee or query_lower in narration:
                total_matches += 1
                if len(results) >= limit:
                    continue
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

        rows, truncated = _fit_rows(
            results,
            lambda r: json.dumps({"results": r}, indent=2, ensure_ascii=False),
        )
        payload = {
            "results": rows,
            "count": len(rows),
            "total_results": total_matches,
            "truncated": truncated or len(rows) < len(results),
        }
        result_text = json.dumps(payload, indent=2, ensure_ascii=False)
        return ToolResult(
            content=result_text,
            metadata={"query": q, "count": len(rows), "total_results": total_matches},
        )


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

        txns = [e for e in entries if type(e).__name__ == "Transaction"]
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
