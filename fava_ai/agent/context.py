from fava_ai.tools.registry import ToolRegistry


class ContextBuilder:
    def __init__(self, ledger, tool_registry: ToolRegistry):
        self._ledger = ledger
        self._tool_registry = tool_registry

    def build_system_prompt(self) -> str:
        tools_desc = self._build_tools_description()
        ledger_info = self._get_ledger_summary()

        return f"""You are an AI assistant for a Beancount/Fava personal finance ledger.
Your role is to help the user understand and analyze their financial data.

## Ledger Summary
{ledger_info}

## Available Tools
{tools_desc}

## Guidelines
1. When asked about financial data, use the available tools to query the ledger.
2. Always verify data using the tools before making claims.
3. If a tool returns an error, explain the error to the user.
4. Be precise with numbers and dates.
5. Do not make up financial data - only report what the tools return.
6. When using run_bql, write valid BQL queries. The syntax is:
   SELECT <columns> WHERE <posting-filter> GROUP BY <key> ORDER BY <col> DESC LIMIT <n>
   - FROM clause is OPTIONAL (omit it for basic queries, it defaults to all transactions)
   - WHERE filters POSTINGS, not entries. Use `account ~ 'Expenses'` regex match.
   - Columns: date, account, position, payee, narration, balance, change
   - Aggregate: sum(position), count(*), first(date), last(date)
   - Functions: COST(position), UNITS(position), YEAR(date), MONTH(date)
   - Date literals: 2024-01-01 (YYYY-MM-DD format)
   - Correct: SELECT account, sum(position) WHERE account ~ 'Expenses' GROUP BY account ORDER BY sum(position) DESC LIMIT 3
   - WRONG: SELECT ... FROM account WHERE ... (no FROM-account, no AS aliases in GROUP BY)
   - WRONG: SELECT account, sum(position) AS total ... ORDER BY total (use ORDER BY sum(position) instead)
7. Format monetary amounts clearly with currency symbols.
8. If you're not sure about something, use the tools to check.
"""

    def _build_tools_description(self) -> str:
        lines = []
        for tool in self._tool_registry.list_tools():
            lines.append(f"- **{tool.name}**: {tool.description}")
        return "\n".join(lines)

    def _get_ledger_summary(self) -> str:
        entries = self._ledger.all_entries
        txns = [e for e in entries if hasattr(e, 'date')]
        if txns:
            dates = [e.date for e in txns]
            date_range = f"{min(dates)} to {max(dates)}"
        else:
            date_range = "N/A"

        options = self._ledger.options
        currencies = options.get("operating_currency", ["USD"])
        return (
            f"- Operating currencies: {', '.join(currencies)}\n"
            f"- Transaction count: {len(txns)}\n"
            f"- Date range: {date_range}"
        )
