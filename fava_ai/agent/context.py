from fava_ai.tools.registry import ToolRegistry


class ContextBuilder:
    def __init__(self, ledger, tool_registry: ToolRegistry, wiki_manager=None):
        self._ledger = ledger
        self._tool_registry = tool_registry
        self._wiki = wiki_manager

    def build_system_prompt(self, user_message: str | None = None) -> str:
        tools_desc = self._build_tools_description()
        ledger_info = self._get_ledger_summary()
        kb_context = self._get_kb_context(user_message) if user_message and self._wiki else ""

        prompt = f"""You are an AI assistant for a Beancount/Fava personal finance ledger.
Your role is to help the user understand and analyze their financial data.

## Ledger Summary
{ledger_info}
"""
        if kb_context:
            prompt += f"""## Knowledge Base Context
The following information was extracted from the wiki knowledge base:

{kb_context}

"""
        prompt += f"""## Available Tools
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
9. Use wiki_search to find relevant knowledge before querying the ledger directly.
"""
        return prompt

    def _get_kb_context(self, user_message: str) -> str:
        if not self._wiki:
            return ""
        try:
            results = self._wiki.search(user_message, max_results=5)
            if not results:
                return ""
            lines = []
            for r in results:
                page = self._wiki.read(r["path"])
                lines.append(f"### {r['title']}")
                body = page.content
                if len(body) > 500:
                    body = body[:500] + "..."
                lines.append(body)
                lines.append("")
            return "\n".join(lines)
        except Exception:
            return ""

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
