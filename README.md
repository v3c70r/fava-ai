# Fava AI — AI Assistant for Beancount/Fava

An extensible, local-first AI agent platform integrated into [Fava](https://github.com/beancount/fava), the web frontend for [Beancount](https://github.com/beancount/beancount). Ask natural-language questions about your ledger and get answers backed by real data — not hallucinations.

- **Local-first** — no cloud required (Ollama, llama.cpp, LM Studio)
- **Read-only** — never modifies your beancount files
- **Ledger-aware** — executes BQL queries, browses accounts, searches transactions
- **Multi-provider** — OpenAI, Anthropic, DeepSeek, Google, Groq, OpenRouter, or any OpenAI-compatible endpoint (including local servers)
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

Every supported vendor is reached through a single **OpenAI-compatible** provider:
configure a `base_url`, `api_key` and `model`. Local servers (Ollama, llama.cpp,
LM Studio, vLLM, …) are no different — they are just a `base_url`.

### Local endpoints

```yaml
# Ollama (its OpenAI-compatible API is served under /v1)
providers:
  local:
    base_url: http://localhost:11434/v1
    model: llama3

# llama.cpp / LM Studio / vLLM
providers:
  local:
    base_url: http://localhost:8080/v1
    api_key: ${LOCAL_API_KEY}   # omit if the server needs none
    model: my-model
```

### Hosted providers

Well-known vendors are recognised by name and fill in a default base URL, so you
only need the key and the model. Any `${ENV_VAR}` is expanded, so secrets can
stay out of your ledger:

```yaml
providers:
  deepseek:
    api_key: ${DEEPSEEK_API_KEY}
    model: deepseek-chat
```

| Name | Default base URL | API key env var |
|---|---|---|
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `anthropic` | `https://api.anthropic.com/v1` | `ANTHROPIC_API_KEY` |
| `deepseek` | `https://api.deepseek.com/v1` | `DEEPSEEK_API_KEY` |
| `google` | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` |
| `groq` | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |
| `mistral` | `https://api.mistral.ai/v1` | `MISTRAL_API_KEY` |
| `xai` | `https://api.x.ai/v1` | `XAI_API_KEY` |
| `together` | `https://api.together.ai/v1` | `TOGETHER_API_KEY` |
| `openrouter` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| `cerebras` | `https://api.cerebras.ai/v1` | `CEREBRAS_API_KEY` |
| `nvidia` | `https://integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` |
| `moonshotai` | `https://api.moonshot.ai/v1` | `MOONSHOT_API_KEY` |
| `fireworks` | `https://api.fireworks.ai/inference/v1` | `FIREWORKS_API_KEY` |
| `baseten` | `https://inference.baseten.co/v1` | `BASETEN_API_KEY` |
| `huggingface` | `https://router.huggingface.co/v1` | `HF_TOKEN` |
| `vercel-ai-gateway` | `https://ai-gateway.vercel.sh/v1` | `AI_GATEWAY_API_KEY` |
| `meta` | `https://api.meta.ai/v1` | `META_API_KEY` |
| `xiaomi` | `https://api.xiaomimimo.com/v1` | `XIAOMI_API_KEY` |

Any other OpenAI-compatible endpoint works too — give it any name plus a
`base_url` (or an explicit `type: openai_compat`):

```yaml
providers:
  my-gateway:
    type: openai_compat
    base_url: https://llm.internal.example/v1
    api_key: ${MY_GATEWAY_KEY}
    model: llama-3.1-70b
```

> Anthropic is reached via its OpenAI-compatible endpoint. litellm's native
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
├── merchants/           # Merchant catalog (payee, else derived from narration)
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
| `search_documents` | Search indexed documents/vouchers (BM25, +dense if configured) |
| `read_document` | Read a document's extracted text by `document_id` |
| `file_document` | Compose a beancount entry linking a document to a transaction |

## Documents & Vouchers

Attach receipts, statements, contracts or payslips to a question, and let the
agent cross-check them against the ledger.

### Upload in chat

Use the paperclip (or drag files onto the input area). Files are stored under
`.fava-ai/documents/<conversation>/`, their text is extracted locally, and they
stay attached to the conversation so follow-up questions can refer to them
("and the second one?"). Small documents are inlined into the prompt; larger
ones are read on demand via the `read_document` tool.

### Index your existing documents

Point the extension at the folders your PDFs already live in:

```yaml
documents:
  enabled: true
  folders:
    - ~/Documents/finances
    - ~/Downloads/statements
  max_file_mb: 25
  max_pages: 50
```

The **Docs** tab shows the index status and has an *Index now* button (also
`POST /documents_index`). Fava's own `documents` folder option is included
automatically (both as a single value and as the list beancount actually parses
it into). Indexing is incremental — content-hashed files are skipped.

The panel also lists everything it could not use, and *Retry failed*
(`POST /documents_retry`) re-extracts those documents in place. That matters for
PDFs: if `pypdf` was missing when a file was first seen, the file is recorded as
*unsupported* and would otherwise stay unusable forever. Installing `pypdf` and
retrying heals it without re-uploading. A scanned PDF with no text layer is
recorded as *empty* rather than *indexed*, so it is visible instead of looking
like a successful import.

> Keyword search splits CJK text per character (FTS5's `unicode61` tokenizer
does not segment Chinese/Japanese), so `记账` finds an unspaced `记账软件测试`.
> Upgrading from an earlier build rebuilds the index once, automatically.

### Optional: semantic search

Add an OpenAI-compatible embeddings endpoint to enable hybrid retrieval
(BM25 + cosine, fused). Without it, search is keyword-only (FTS5/BM25), which
covers most personal-document queries:

```yaml
documents:
  embedding:
    base_url: http://192.168.0.92:8080/v1
    api_key: ${EMBEDDING_API_KEY}
    model: qwen3-4b-embedding
```

Use *Embed now* in the Docs tab (or `POST /documents_embed`). A *Test* button
calls a one-token `/embeddings` request to verify the endpoint; on failure it
reports the endpoint's actual error. The same fields are editable in the
**Config** tab (`documents.embedding.*`), so nothing has to be hand-written in
YAML.

Search results carry a `score` (BM25-negated in keyword mode, cosine in dense
mode, the fused score in hybrid mode) so the agent can tell a strong match from
a weak one.

> The endpoint must actually serve embeddings: llama.cpp needs `--embeddings`
> (and many models are loaded without it), Ollama and OpenAI work as-is.

### Filing a document into the ledger

By default the extension stays **read-only**: `file_document` returns a
paste-ready snippet — the transaction with `attachment:` metadata plus a
`Document` entry pointing at the stored file:

```beancount
2024-03-05 * "Cafe Milano" "Lunch"
  attachment: "documents/.../receipt.pdf"
  Expenses:Food:Coffee    13.50 CAD
  Assets:Bank:Checking   -13.50 CAD

2024-03-05 document Expenses:Food:Coffee "documents/.../receipt.pdf"
```

To let the agent append such entries to a dedicated file (included from your
journal), opt in explicitly:

```yaml
tools:
  allow_ledger_writes: true
  ledger_writes_file: documents.beancount
```

### Privacy

Everything is local: files, extracted text and the index live under the config
directory. Only extracted chunk text is ever sent to the model (which is your
own provider).

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
- `litellm` >= 1.85, `pyyaml` >= 6.0, `jinja2` >= 3.0, `requests` >= 2.28, `pypdf` >= 5.0

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
