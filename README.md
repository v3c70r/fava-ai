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

All configuration can live in the ledger — no separate config file required.
Declare one OpenAI-compatible endpoint directly in the directive:

```beancount
2010-01-01 custom "fava-extension" "fava_ai" "{
    'provider': 'local',
    'base_url': 'http://localhost:11434/v1',
    'api_key': '${OLLAMA_API_KEY}',
    'model': 'llama3',
    'agent': {'timeout_seconds': 300}
}"
```

Use `${ENV_VAR}` for secrets so the (usually committed) ledger never contains
them. Omit `api_key` entirely for local servers that don't require one.

### 3. Run Fava

```bash
fava /path/to/your/ledger/main.beancount
# Open http://localhost:5000 → click "AI Assistant" in sidebar
```

That's it — the plugin creates `.fava-ai/` next to the ledger for its
conversation database and generated knowledge base (it does **not** write to
the ledger).

### Optional: override via `.fava-ai/config.yaml`

A `config.yaml` is **optional**. If present it overrides the directive
key-by-key, which is useful for secrets you'd rather keep out of git or for
changing settings from the UI:

```bash
mkdir -p /path/to/your/ledger/.fava-ai
cat > /path/to/your/ledger/.fava-ai/config.yaml << 'EOF'
providers:
  local:
    api_key: ${LOCAL_API_KEY}
EOF
```

## Provider Configuration

Every supported vendor (OpenAI, DeepSeek, Ollama, Anthropic, llama.cpp, LM Studio,
vLLM, OpenRouter, …) is reached through a single **OpenAI-compatible** provider:
you configure a `base_url`, `api_key` and `model`.

```yaml
providers:
  local:
    base_url: http://localhost:8080/v1
    api_key: ${LOCAL_API_KEY}
    model: my-model
```

### Vendor shortcuts

Legacy vendor names are accepted as aliases for the same provider and fill in a
default base URL, so no `base_url` is needed:

| Name | Default base URL |
|---|---|
| `openai` | `https://api.openai.com/v1` |
| `deepseek` | `https://api.deepseek.com/v1` |
| `anthropic` | `https://api.anthropic.com/v1` |
| `ollama` | `http://localhost:11434/v1` |
| `openai_compat` / any name + `base_url` | (you provide it) |

```yaml
# DeepSeek: base_url inferred from the name
providers:
  deepseek:
    api_key: ${DEEPSEEK_API_KEY}
    model: deepseek-chat
```

```yaml
# Local llama.cpp / LM Studio / Ollama: explicit base_url, arbitrary name
providers:
  local:
    base_url: http://localhost:8080/v1
    api_key: ${LOCAL_API_KEY}
    model: Ternary-Bonsai-2-27B
```

> Anthropic is reached via its OpenAI-compatible endpoint; litellm's native
> Anthropic provider exposes slightly more, so prefer an OpenAI-compatible
> gateway if you hit limitations.

### Multiple providers

Configure several endpoints and switch between them in the UI (or via the
`provider` parameter in chat requests). The `provider` key selects the default:

```yaml
provider: local
providers:
  local:
    base_url: http://localhost:8080/v1
    api_key: ${LOCAL_API_KEY}
    model: my-model
  deepseek:
    api_key: ${DEEPSEEK_API_KEY}
    model: deepseek-chat
```

### Precedence

Built-in defaults → **beancount directive** → optional `.fava-ai/config.yaml`
(highest). `${ENV_VAR}` references are expanded in both the directive and the
YAML file.

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
├── main.beancount              # Your ledger; may hold the full extension config
├── fava_ai/                    # Git submodule or pip-installed package
├── .fava-ai/                   # Runtime state (created automatically)
│   ├── config.yaml             # Optional overrides / secrets
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

Commit `fava_ai/`, your ledger (with the `fava-extension` directive), `.gitignore`, and `.gitmodules`.
A `.fava-ai/config.yaml` is optional — only commit it if it contains no secrets.

### What to gitignore

```gitignore
.fava-ai/config.yaml        # Optional; may contain API keys
.fava-ai/conversations.db   # Personal chat history
```

Prefer putting provider settings (with `${ENV_VAR}` for secrets) directly in the
ledger directive, and keep `config.yaml` untracked for anything secret.

The wiki (`wiki/`) may be committed — it's generated knowledge that compounds over time.

## Requirements

- Python >= 3.10
- [Fava](https://github.com/beancount/fava) >= 1.27
- [Beancount](https://github.com/beancount/beancount) >= 2.3
- `litellm` >= 1.85, `pyyaml` >= 6.0, `jinja2` >= 3.0, `requests` >= 2.28

## Development

```bash
git clone https://github.com/v3c70r/fava-ai.git
cd fava-ai
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Lint, type-check, test
ruff check .
mypy .
pytest -q
pytest -q -m slow   # performance smoke tests (excluded by default)
pytest -q --cov=fava_ai --cov-report=term-missing

# Add extension directive and run (config lives in the directive)
cat tests/data/ledgers/beancount-example.beancount > /tmp/test.beancount
echo "2010-01-01 custom \"fava-extension\" \"fava_ai\" \"{'provider': 'local', 'base_url': 'http://localhost:11434/v1', 'model': 'llama3'}\"" >> /tmp/test.beancount
fava /tmp/test.beancount
```

### Optional: external sample ledgers

For performance and extractor testing against larger, real-world ledgers, fetch the
sample repositories (kept out of the repo for licensing reasons):

```bash
scripts/fetch_sample_ledgers.sh
FAVA_AI_SAMPLE_LEDGERS=$PWD/.sample-ledgers python3 scripts/analyze_ledgers.py
```

### Repository layout

```
tests/
  unit/        # pure logic tests
  integration/ # Flask test-client endpoint tests
  llm/         # agent loop with mock providers
  data/        # checked-in .beancount fixtures
scripts/       # manual analysis / provider smoke tests / packaging checks
docs/          # design, history & security documents
```

### Packaging

The project uses a flat layout (the repository root *is* the `fava_ai` package,
configured via `package-dir`). Wheels are verified to contain only the package
modules plus `FavaAI.js` and `templates/FavaAI.html`:

```bash
python -m build --wheel
python scripts/check_wheel.py
pip install dist/fava_ai-*.whl   # in a clean environment
```

## License

MIT
