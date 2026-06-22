# Fava AI — AI Assistant for Beancount/Fava

An extensible, local-first AI agent platform integrated into [Fava](https://github.com/beancount/fava), the web frontend for [Beancount](https://github.com/beancount/beancount). Ask natural-language questions about your ledger and get answers backed by real data — not hallucinations.

- **Local-first** — no cloud required (Ollama, llama.cpp, LM Studio)
- **Read-only** — never modifies your beancount files
- **Ledger-aware** — executes BQL queries, browses accounts, searches transactions
- **Multi-provider** — Ollama, OpenAI, Anthropic, DeepSeek, or any OpenAI-compatible endpoint
- **Transparent** — every response includes full provenance (tools called, BQL queries, data sources)
- **Extensible** — plugin-based tools, installable prompts, external tool plugins

## Quick Start

### 1. Install

```bash
git clone https://github.com/v3c70r/fava-ai.git
cd fava-ai
python3 -m venv .venv && source .venv/bin/activate
uv pip install -e .
# Or: pip install -e .
```

### 2. Add the extension to your Beancount file

Add this line to your ledger file (e.g., `main.beancount`):

```beancount
2010-01-01 custom "fava-extension" "fava_ai" "{
    'provider': 'ollama',
    'model': 'llama3',
    'config_dir': '.fava-ai'
}"
```

### 3. Create provider config

```bash
mkdir -p /path/to/your/ledger/.fava-ai
cat > /path/to/your/ledger/.fava-ai/config.yaml << 'EOF'
providers:
  ollama:
    base_url: http://localhost:11434
    model: llama3
agent:
  max_iterations: 10
  max_tool_calls: 20
knowledge:
  auto_extract: true
EOF
```

### 4. Run Fava

```bash
fava /path/to/your/ledger/main.beancount
# Open http://localhost:5000 → click "AI Assistant" in sidebar
```

## Provider Configuration

### Ollama (local)

```yaml
providers:
  ollama:
    base_url: http://localhost:11434
    model: llama3
```

### llama.cpp / LM Studio (OpenAI-compatible)

```yaml
providers:
  openai_compat:
    base_url: http://localhost:8080/v1
    api_key: sk-no-key
    model: gemma-4-e2b
```

### OpenAI

```yaml
providers:
  openai:
    api_key: ${OPENAI_API_KEY}
    model: gpt-4o
```

### Anthropic

```yaml
providers:
  anthropic:
    api_key: ${ANTHROPIC_API_KEY}
    model: claude-sonnet-4-20250514
```

### DeepSeek

```yaml
providers:
  deepseek:
    api_key: ${DEEPSEEK_API_KEY}
    model: deepseek-chat
```

### Multiple providers

Configure multiple providers and switch between them in the UI or via the `provider` parameter in chat requests:

```yaml
providers:
  ollama:
    base_url: http://localhost:11434
    model: llama3
  deepseek:
    api_key: ${DEEPSEEK_API_KEY}
    model: deepseek-chat
```

## What It Can Do

### Ask questions about your finances

```
"What is the operating currency and date range of this ledger?"
"How many accounts are in this ledger?"
"What are my top 5 expenses by total amount?"
"What recurring payments do I have?"
"Show me my spending on food vs transportation by month."
"What is the total cost basis of my investments?"
```

The agent automatically uses the right tools — BQL queries, account lookups, transaction search, or the auto-generated knowledge base.

### Auto-generated Knowledge Base

On first load, the extension extracts a structured knowledge base from your ledger into markdown wiki pages:

```
.fava-ai/wiki/
├── overview.md          # Ledger summary
├── index.md             # Page catalog by type
├── accounts/            # One page per account with balance + hierarchy
├── merchants/           # Payee catalog with transaction history
├── recurring/           # Detected recurring payments
├── portfolio/           # Investment holdings
├── patterns/            # Spending trends and cashflow
└── log.md               # Chronological audit trail
```

The agent searches this knowledge base automatically before querying the ledger directly. The wiki is human-readable — open it in any markdown viewer.

### Provenance

Every response includes full provenance:

```json
{
  "provenance": {
    "total_tool_calls": 2,
    "total_bql_queries": 1,
    "total_wiki_lookups": 1,
    "steps": [
      {"step_type": "plan", "step_index": 0},
      {"step_type": "tool_call", "tool_name": "run_bql", "bql_query": "SELECT ..."},
      {"step_type": "tool_call", "tool_name": "wiki_read"},
      {"step_type": "synthesis"}
    ]
  }
}
```

## Built-in Tools

| Tool | Description |
|---|---|
| `run_bql` | Execute Beancount Query Language (BQL) queries |
| `list_accounts` | List accounts with balances, filter by prefix |
| `account_details` | Account metadata, balance, recent postings |
| `search_transactions` | Full-text search across payee and narration |
| `ledger_info` | Date range, currencies, account/transaction counts |
| `wiki_search` | Search the knowledge base wiki |
| `wiki_read` | Read a specific wiki page |
| `wiki_list` | List wiki directory structure |
| `list_dashboards` | List existing Fava dashboards |
| `generate_dashboard` | Create dashboard definitions |
| `generate_chart` | Create chart configurations |

## External Tool Plugins

Add custom tools by placing Python files in `.fava-ai/tools/`:

```python
# .fava-ai/tools/market_data.py
from fava_ai.tools.base import BaseTool, ToolResult

class MarketPriceTool(BaseTool):
    name = "market_price"
    description = "Get current market price for a ticker"
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Stock ticker symbol"}
        },
        "required": ["ticker"]
    }

    def execute(self, ticker: str) -> ToolResult:
        # Your implementation here
        price = fetch_price(ticker)
        return ToolResult(
            content=f"{ticker}: ${price}",
            metadata={"ticker": ticker, "price": price}
        )

tools = [MarketPriceTool()]
```

## Custom System Prompts

Add custom prompts as YAML files in `.fava-ai/prompts/`:

```yaml
# .fava-ai/prompts/tax_review.yaml
name: Tax Review
description: End-of-year tax preparation assistant
category: review
content: |
  You are a tax preparation assistant. Your task is to:
  1. Summarize all income by category for the tax year.
  2. Identify deductible expenses.
  3. Report capital gains and losses from investment accounts.
  4. Flag any unusual transactions that may need accountant review.
```

## BQL Query Templates

The agent uses these BQL patterns (no SQL knowledge needed — it copies them):

```sql
-- Top expenses by category
SELECT account, sum(position) WHERE account ~ 'Expenses' GROUP BY account ORDER BY sum(position) DESC LIMIT 3

-- Filter by date range
SELECT date, account, position WHERE date >= 2014-01-01 AND date <= 2014-12-31

-- Count per account
SELECT account, count(*) WHERE account ~ 'Expenses' GROUP BY account ORDER BY count(*) DESC LIMIT 10

-- Cost basis
SELECT account, sum(cost(position)) WHERE account ~ 'Assets' GROUP BY account

-- List unique payees
SELECT DISTINCT payee
```

## Directory Structure

```
my-finances/
├── main.beancount              # Your ledger with extension directive
├── fava_ai/                    # Git submodule or pip-installed package
├── .fava-ai/
│   ├── config.yaml             # Provider keys and settings
│   ├── conversations.db        # Chat history (SQLite)
│   ├── wiki/                   # Auto-generated knowledge base
│   ├── prompts/                # Custom system prompts
│   └── tools/                  # External tool plugins
```

## Recommended Deployment

### As a Git submodule

```bash
# In your ledger repo
git submodule add https://github.com/v3c70r/fava-ai.git fava_ai
uv pip install litellm pyyaml
```

Commit `fava_ai/`, `.fava-ai/config.yaml` (without secrets), `.gitignore`, and `.gitmodules`.

### What to gitignore

```gitignore
.fava-ai/config.yaml        # Contains API keys
.fava-ai/conversations.db   # Personal chat history
```

The wiki (`wiki/`) should be committed — it's versioned knowledge that compounds over time.

## Requirements

- Python >= 3.10
- [Fava](https://github.com/beancount/fava) >= 1.27
- [Beancount](https://github.com/beancount/beancount) >= 2.3
- `litellm` >= 1.85, `pyyaml` >= 6.0, `jinja2` >= 3.0

## Development

```bash
git clone https://github.com/v3c70r/fava-ai.git
cd fava-ai
python3 -m venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Run tests
pytest tests/ -q

# Run with a test fixture
mkdir -p .fava-ai
echo '
providers:
  ollama:
    base_url: http://localhost:11434
    model: llama3
' > .fava-ai/config.yaml

# Add extension directive and run
echo "2010-01-01 custom \"fava-extension\" \"fava_ai\" \"{'provider': 'ollama'}\"" | cat - tests/fixtures/ledgers/beancount-example.beancount > /tmp/test.beancount
fava /tmp/test.beancount
```

## License

MIT
