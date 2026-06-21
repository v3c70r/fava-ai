# Fava AI Agent Platform — Implementation Plan

> **Context:** This is a self-contained implementation plan. A fresh session should be able to read this and start building.

---

## Project Overview

Build an extensible AI agent platform integrated into Fava (Beancount web frontend). The system must be:

1. **Local-first** — no cloud dependencies required
2. **Read-only** — never modify beancount files
3. **Ledger-aware** — analyze, don't just chat
4. **Multi-provider** — Ollama, OpenAI, Anthropic, OpenAI-compatible
5. **Transparent** — every response includes provenance
6. **Lightweight** — SQLite + markdown wiki, no Postgres/Redis/Docker
7. **Extensible** — plugin-based tools, installable prompts, external tool plugins

## Technology Choices

| Component | Choice | Rationale |
|---|---|---|
| LLM provider abstraction | **litellm** | 100+ providers, sync API, tool calling, well-maintained (51k stars) |
| Knowledge base | **Markdown wiki** (Karpathy llm-wiki pattern) | Human-readable, git-friendly, transferable by copy, LLM-native |
| Operational storage | **SQLite** | Zero-dependency, single file, per-ledger isolation |
| Chat UI | **Jinja2 + vanilla JS** | No build step, Fava-native extension module pattern |
| Configuration | **YAML + beancount custom directive** | Two-layer: global options in beancount file, overrides in .fava-ai/config.yaml |

## Package Layout

```
fava_ai/
├── __init__.py                   # FavaAI(FavaExtensionBase) — main extension class
├── _version.py                   # __version__ = "0.1.0"
├── config.py                     # ConfigManager — YAML + beancount config merging
├── storage/
│   ├── __init__.py
│   ├── database.py               # SQLite connection pool + schema migrations
│   ├── schema.py                 # DDL statements
│   ├── conversations.py          # Conversation + message CRUD
│   └── traces.py                 # Execution trace storage
├── models/
│   ├── __init__.py
│   ├── base.py                   # BaseProvider, Message, ToolCall, ChatResponse
│   ├── ollama.py                 # Ollama via litellm
│   ├── openai.py                 # OpenAI via litellm
│   ├── openai_compat.py          # Generic OpenAI-compatible (vLLM, LM Studio, OpenRouter)
│   ├── anthropic.py              # Anthropic via litellm
│   └── registry.py               # ProviderRegistry — discover, configure, test
├── agent/
│   ├── __init__.py
│   ├── runtime.py                # AgentRuntime — orchestration loop
│   ├── context.py                # ContextBuilder — system prompt + KB injection
│   └── limits.py                 # ExecutionLimits dataclass
├── tools/
│   ├── __init__.py
│   ├── base.py                   # BaseTool, ToolResult, ToolDefinition, ToolError
│   ├── registry.py               # ToolRegistry — register, discover, execute
│   ├── builtin/
│   │   ├── __init__.py
│   │   ├── ledger.py             # run_bql, list_accounts, account_details, search_transactions, ledger_info
│   │   ├── wiki.py               # wiki_search, wiki_read, wiki_write, wiki_list
│   │   └── dashboard.py          # list_dashboards, generate_dashboard, generate_chart
│   └── loader.py                 # External tool plugin loader (from .fava-ai/tools/)
├── knowledge/
│   ├── __init__.py
│   ├── engine.py                 # KnowledgeEngine — extraction orchestrator
│   ├── wiki.py                   # WikiManager — read/write/search markdown wiki pages
│   ├── templates/                # Jinja2 templates for wiki page generation
│   │   ├── account.md.j2
│   │   ├── merchant.md.j2
│   │   ├── overview.md.j2
│   │   ├── period.md.j2
│   │   └── recurring.md.j2
│   └── extractors/
│       ├── __init__.py
│       ├── accounts.py           # Account graph → wiki/accounts/
│       ├── merchants.py          # Merchant catalog → wiki/merchants/
│       ├── recurring.py          # Recurring transaction detection → wiki/recurring/
│       ├── portfolio.py          # Portfolio structure → wiki/portfolio/
│       ├── spending.py           # Spending patterns → wiki/patterns/
│       └── cashflow.py           # Cash flow analysis → wiki/patterns/
├── prompts/
│   ├── __init__.py
│   ├── registry.py               # PromptRegistry — load, discover, search
│   └── builtin/
│       ├── __init__.py
│       ├── default.py            # Default system prompt
│       ├── monthly_review.py
│       └── investment_review.py
├── provenance/
│   ├── __init__.py
│   └── tracker.py                # ExecutionTracker — per-response audit trail
├── api/
│   ├── __init__.py
│   ├── chat.py                   # POST /chat, POST /chat/stream
│   ├── conversations.py          # CRUD conversations + messages
│   ├── config.py                 # GET/PUT configuration
│   ├── providers.py              # List providers, test connection, list models
│   ├── tools.py                  # List tools, tool detail
│   ├── knowledge.py              # Knowledge base status + browsing
│   └── prompts.py                # List prompts, get prompt content
├── templates/
│   ├── FavaAI.html               # Main chat page
│   └── _macros.html              # Jinja2 macros
└── FavaAI.js                     # JavaScript ES module for chat UI
```

## Ledger-Local Runtime Data

```
{ledger_directory}/.fava-ai/
├── config.yaml                   # User overrides
├── prompts/                      # User-installed prompts
│   └── my_custom_review.yaml
├── tools/                        # User-installed external tool plugins
│   └── market_data.py
├── conversations.db              # SQLite — conversation history + traces + config
└── wiki/                         # THE KNOWLEDGE BASE (markdown)
    ├── AGENTS.md                 # Schema + rules for the LLM
    ├── index.md                  # Auto-generated page catalog
    ├── log.md                    # Append-only chronological audit log
    ├── overview.md               # Ledger summary
    ├── accounts/                 # One .md per account
    │   ├── _index.md
    │   ├── Assets.md
    │   ├── Expenses-Food-Restaurant.md
    │   └── ...
    ├── merchants/                # One .md per detected merchant
    │   ├── _index.md
    │   ├── amazon.md
    │   └── ...
    ├── recurring/                # Detected recurring transactions
    │   └── ...
    ├── portfolio/                # Holdings, commodities, allocations
    │   └── ...
    ├── patterns/                 # Spending trends, cash flow
    │   ├── spending.md
    │   └── cashflow.md
    └── periods/                  # Monthly snapshots
        ├── 2025-01.md
        └── ...
```

## Storage Schema (SQLite — conversations.db only)

```sql
CREATE TABLE conversations (
    id            TEXT PRIMARY KEY,
    title         TEXT,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK(role IN ('system','user','assistant','tool')),
    content         TEXT,
    tool_calls      TEXT,           -- JSON array of tool calls
    tool_call_id    TEXT,           -- For tool-role messages
    name            TEXT,           -- Tool name for tool-role messages
    token_count     INTEGER,
    metadata        TEXT,           -- JSON: model, finish_reason, usage
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);

CREATE TABLE traces (
    id              TEXT PRIMARY KEY,
    message_id      TEXT NOT NULL REFERENCES messages(id),
    step_index      INTEGER NOT NULL,
    step_type       TEXT NOT NULL CHECK(step_type IN ('plan','tool_call','synthesis')),
    tool_name       TEXT,
    tool_input      TEXT,           -- JSON summary
    tool_output     TEXT,           -- JSON summary
    bql_query       TEXT,
    wiki_sources    TEXT,           -- JSON array of wiki page paths used
    started_at      TEXT,
    completed_at    TEXT,
    error           TEXT
);

CREATE INDEX idx_traces_message ON traces(message_id);

CREATE TABLE config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE prompt_registry (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    version     TEXT,
    description TEXT,
    category    TEXT,
    file_path   TEXT,
    metadata    TEXT,
    enabled     INTEGER DEFAULT 1
);
```

## Configuration Model

### Layer 1 — Beancount file (inline config)

```beancount
2010-01-01 custom "fava-extension" "fava_ai" "{
    'provider': 'ollama',
    'model': 'llama3',
    'max_iterations': 10,
    'max_tool_calls': 20,
    'config_dir': '.fava-ai'
}"
```

### Layer 2 — `.fava-ai/config.yaml` (takes precedence)

```yaml
providers:
  ollama:
    base_url: http://localhost:11434
  openai:
    api_key: ${OPENAI_API_KEY}

agent:
  max_iterations: 10
  max_tool_calls: 20
  timeout_seconds: 120
  system_prompt: default

knowledge:
  auto_extract: true
```

ConfigManager merges both layers. YAML overrides the beancount directive. `${ENV_VAR}` substitution supported.

## Provider Interface (via litellm)

```python
@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

@dataclass
class ToolCall:
    id: str
    function: FunctionCall

@dataclass
class FunctionCall:
    name: str
    arguments: str

@dataclass
class ChatResponse:
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: dict | None = None

class BaseProvider(ABC):
    @property
    def provider_name(self) -> str: ...
    def chat(self, messages: list[Message], tools: list[ToolDefinition] | None = None,
             model: str | None = None, **kwargs) -> ChatResponse: ...
    def chat_stream(self, messages: list[Message], tools: list[ToolDefinition] | None = None,
                    model: str | None = None, **kwargs) -> Iterator[StreamChunk]: ...
    def list_models(self) -> list[str]: ...
    def test_connection(self) -> bool: ...
```

Providers use `litellm.completion()` internally with model prefix (`ollama/`, `openai/`, `anthropic/`, `openai/`). The abstraction handles format conversion, tool calling, and error normalization.

## Tool Interface

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict      # JSON Schema

@dataclass
class ToolResult:
    content: str           # Text for the model
    metadata: dict | None = None   # Structured provenance data

class BaseTool(ABC):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> dict: ...
    @property
    def permission(self) -> str:
        return "readonly"
    def execute(self, **kwargs) -> ToolResult: ...
    def to_definition(self) -> ToolDefinition: ...
```

## Built-in Tool Catalog

| Tool | Category | Source | Description |
|---|---|---|---|
| `run_bql` | Ledger | Fava | Execute BQL query against the ledger |
| `list_accounts` | Ledger | Fava | List accounts matching optional prefix filter |
| `account_details` | Ledger | Fava | Metadata + balance + recent postings for an account |
| `search_transactions` | Ledger | Fava | Full-text search across payee + narration |
| `ledger_info` | Ledger | Fava | Summary: date range, currencies, account count |
| `wiki_search` | Knowledge | Wiki files | Search wiki pages by keyword |
| `wiki_read` | Knowledge | Wiki files | Read a specific wiki page by path |
| `wiki_write` | Knowledge | Wiki files | Create/update a wiki page |
| `wiki_list` | Knowledge | Wiki files | List wiki directory structure |
| `list_dashboards` | Dashboard | Fava | List existing Fava dashboards |
| `generate_dashboard` | Dashboard | Fava | Create dashboard definition from parameters |
| `generate_chart` | Dashboard | Fava | Create chart configuration |

## Wiki Page Format

Every wiki page uses YAML frontmatter + markdown body:

```markdown
---
title: Amazon
type: merchant
category: Shopping
total_transactions: 47
total_spent: 2847.32 USD
first_seen: 2023-01-15
last_seen: 2025-05-20
tags: [shopping, online, recurring]
related: [Expenses-Shopping, Prime-Subscription]
updated: 2025-05-20
---

# Amazon

## Summary
Amazon is a frequent merchant with 47 transactions totaling $2,847.32 since 2023.

## Transaction Patterns
- Average transaction: $60.58
- Most common day: Friday
- Monthly frequency: ~1.6 transactions/month

## Related
- [[Prime-Subscription]] - $14.99/month recurring
- [[Expenses-Shopping]] - Primary category

## Recent Transactions
| Date | Amount | Description |
|------|--------|-------------|
| 2025-05-15 | $42.97 | Amazon.com - Books |
| 2025-04-30 | $89.99 | Amazon.com - Electronics |
```

## Agent Runtime Main Loop

```
run(user_message, conversation_id):
    tracker = new ExecutionTracker()
    messages = load_conversation(conversation_id)
    messages.insert(0, context_builder.build_system_prompt())
    messages.append(Message(role="user", content=user_message))
    total_tool_calls = 0

    for iteration in 1..max_iterations:
        tracker.record_step("plan", iteration)

        response = provider.chat(messages, tools=registry.get_definitions())
        messages.append(response.as_message())
        save_messages(conversation_id, messages)

        if response.has_tool_calls():
            total_tool_calls += len(response.tool_calls)
            if total_tool_calls > max_tool_calls:
                raise LimitExceeded("max_tool_calls")

            for tool_call in response.tool_calls:
                result = registry.execute(tool_call)
                tracker.record_tool_call(tool_call, result)
                messages.append(result.as_tool_message())

        elif response.content:
            tracker.record_synthesis(response)
            save_trace(conversation_id, tracker)
            return AgentResponse(content=response.content, trace=tracker)

    raise LimitExceeded("max_iterations")
```

## Fava Lifecycle Integration

```python
class FavaAI(FavaExtensionBase):
    report_title = "AI Assistant"
    has_js_module = True

    def __init__(self, ledger, config):
        super().__init__(ledger, config)
        # 1. Resolve config directory (default: "{ledger_dir}/.fava-ai")
        # 2. Initialize ConfigManager (merge beancount config + YAML)
        # 3. Initialize SQLite database
        # 4. Initialize ProviderRegistry from config
        # 5. Initialize ToolRegistry (built-in + external plugins)
        # 6. Initialize WikiManager
        # 7. Initialize KnowledgeEngine
        # 8. Initialize AgentRuntime

    def after_load_file(self):
        """Fires on ledger load/reload. Rebuild knowledge base if changed."""
        if self.knowledge_engine.needs_rebuild():
            self.knowledge_engine.extract_all()
```

## API Endpoints (registered via @extension_endpoint)

| Method | Path | Purpose |
|---|---|---|
| GET | `/<bfile>/extension/FavaAI/` | Chat UI page |
| POST | `/<bfile>/extension/FavaAI/chat` | Send message (non-streaming) |
| POST | `/<bfile>/extension/FavaAI/chat/stream` | Send message (SSE streaming) |
| GET | `/<bfile>/extension/FavaAI/conversations` | List conversations |
| GET | `/<bfile>/extension/FavaAI/conversations/<id>` | Get conversation + messages |
| DELETE | `/<bfile>/extension/FavaAI/conversations/<id>` | Delete conversation |
| GET | `/<bfile>/extension/FavaAI/tools` | List available tools |
| GET | `/<bfile>/extension/FavaAI/tools/<name>` | Tool details (schema, description) |
| PUT | `/<bfile>/extension/FavaAI/config` | Update configuration |
| GET | `/<bfile>/extension/FavaAI/providers` | List configured providers |
| GET | `/<bfile>/extension/FavaAI/providers/<name>/models` | List models for a provider |
| POST | `/<bfile>/extension/FavaAI/providers/test` | Test provider connectivity |
| GET | `/<bfile>/extension/FavaAI/knowledge/status` | Knowledge base extraction status |
| GET | `/<bfile>/extension/FavaAI/knowledge/accounts` | Browse account graph |
| GET | `/<bfile>/extension/FavaAI/knowledge/merchants` | Browse merchant catalog |
| GET | `/<bfile>/extension/FavaAI/knowledge/recurring` | Browse recurring transactions |
| GET | `/<bfile>/extension/FavaAI/prompts` | List available prompts |
| GET | `/<bfile>/extension/FavaAI/prompts/<name>` | Get prompt content |
| GET | `/<bfile>/extension/FavaAI/traces/<message_id>` | Get execution trace for a message |

## Frontend Architecture

### Chat UI Template — `templates/FavaAI.html`

Three-panel layout:
- **Left sidebar:** conversation list, new conversation button, knowledge base status indicator
- **Center:** chat messages with expandable tool-call cards and provenance footers
- **Right panel (toggleable):** tabbed view — Tools / Config / Knowledge / Prompts

### JavaScript Module — `FavaAI.js`

```javascript
export default {
    async onExtensionPageLoad(ctx) {
        // Initialize chat UI
        // Load conversations
        // Wire event handlers (send, new conversation, model switch)
        // Set up SSE listener for streaming
        // Render message history
    }
};
```

Key JS behaviors:
- SSE event stream parsing (`data:` lines → JSON → update DOM)
- Tool call cards: `<details>` elements showing tool name, args, result
- Provenance footer: expandable, shows tools used, BQL queries, wiki sources
- Uses `ctx.api.get()`, `ctx.api.post()`, `ctx.api.put()`, `ctx.api.delete()` for all API calls
- Fava's `<svelte-component>` used for rendering query results inline

### Data Flow

```
User types "How much did I spend on restaurants last month?"
  → JS: POST /chat/stream { message, conversation_id }
  → Flask: agent_runtime.run(user_message)
  → Agent loop:
      1. context_builder.build_system_prompt()            [inject ledger summary]
      2. provider.chat(messages, tools=...)               [model decides: call BQL]
      3. execute(run_bql, "SELECT sum(position)...")      [query ledger]
      4. provider.chat(messages + tool_result, tools=...)  [model synthesizes answer]
  → SSE events: tool_call → tool_result → content → done
  → JS: render message with expandable tool card + provenance footer
```

## Dependencies

```
# pyproject.toml
[project]
name = "fava-ai"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "fava>=1.27",          # Already present in environment
    "beancount>=2.3",      # Already present
    "litellm>=1.85",       # Provider abstraction
    "pyyaml>=6.0",         # Config file parsing
    "jinja2>=3.0",         # Template rendering (already via fava + litellm)
]
```

litellm's transitive dependencies (openai, httpx, pydantic, tiktoken, jinja2) are all standard Python packages. No Docker, Postgres, Redis, or external services required.

## Test Fixtures

All test fixtures are in `tests/fixtures/ledgers/`. Clone them with:

```bash
mkdir -p tests/fixtures/ledgers

# Official beancount example (single file, 7175 lines, 1146 txns)
curl -sL "https://raw.githubusercontent.com/beancount/beancount/v2/examples/example.beancount" \
  -o tests/fixtures/ledgers/beancount-example.beancount

# Chinese boilerplate (ZH, CNY, multi-currency, crypto, stocks)
gh repo clone mckelvin/beancount-boilerplate-cn tests/fixtures/ledgers/beancount-boilerplate-cn -- --depth 1

# Portuguese financeiro (PT-BR, BRL, 1741 txns, 137 accounts, event finances)
gh repo clone apyb/financeiro tests/fixtures/ledgers/financeiro -- --depth 1

# French-Canadian comptabilite (FR-CA, CAD, 12 Fava extensions, tax metadata)
gh repo clone philbeliveau/comptabilite tests/fixtures/ledgers/comptabilite -- --depth 1

# Norwegian beancounters (NO, NOK, bank+CC structure, subscriptions)
gh repo clone staticaland/beancounters tests/fixtures/ledgers/beancounters -- --depth 1

# CFO stack (EN, USD/CAD, 6 scenarios: personal/business × country)
gh repo clone MikeChongCan/cfo-stack tests/fixtures/ledgers/cfo-stack -- --depth 1

# Finzytrack fake test data (EN, 5389 txns, 404 payees, INR+USD, 8-year span)
gh repo clone sagarbehere/finzytrack tests/fixtures/ledgers/finzytrack -- --depth 1
```

### Fixture Summary

| Fixture | Lang | Txns | Accts | Payees | Currency | Range | Best For |
|---|---|---|---|---|---|---|---|
| `finzytrack/fake.beancount` | EN | 5,389 | 81 | 404 | INR,USD | 2018–2026 | Scale, payee diversity, recurring detection |
| `financeiro/` | PT-BR | 1,741 | 137 | 197 | BRL | 2020–2026 | Portuguese, event finances, receipt metadata |
| `beancount-example.beancount` | EN | 1,146 | 60 | 36 | USD+ETFs | 2013–2015 | Investments, commodities, prices, tags |
| `boilerplate-cn/` | ZH | 34 | 58 | 0 | CNY,USD,HKD,BTC,ETH | 2019 | Chinese accounts, multi-currency, crypto |
| `cfo-usa-company/` | EN | 34 | 24 | 14 | USD | 2025–2026 | Business, recurring patterns |
| `beancounters/` | NO | 33 | 24 | 0 | NOK | 2025 | Norwegian locale, subs |
| `cfo-can-company/` | EN | 29 | 37 | 15 | CAD | 2025–2026 | Business, balance assertions |
| `finzytrack/fake-multi/` | EN | 23 | 10 | 10 | USD | 2024–2026 | Multi-file includes |
| `comptabilite/` | FR-CA | 18 | 77 | 16 | CAD | 2026 | Fava extensions, tax metadata |
| `cfo-stack ×4` | EN | 9-10 | 15-22 | 8-9 | USD/CAD | 2025–2026 | Smoke tests |

Analysis scripts available at `tests/analyze_ledgers.py` (stats) and `tests/analyze_deep.py` (deep dive).

## Phase Plan

### Phase 1 — MVP (Core Platform)

| # | Task | Files |
|---|---|---|
| 0.1 | Package skeleton + `FavaAI` extension class | `__init__.py`, `_version.py` |
| 0.2 | `pyproject.toml` with dependencies | `pyproject.toml` |
| 1.1 | SQLite database setup + schema | `storage/database.py`, `storage/schema.py` |
| 1.2 | Config manager (YAML + beancount merging) | `config.py` |
| 1.3 | Provider base class + Ollama provider (via litellm) | `models/base.py`, `models/ollama.py`, `models/registry.py` |
| 1.4 | Tool base class + tool registry | `tools/base.py`, `tools/registry.py` |
| 1.5 | Built-in ledger tools (BQL, accounts, transactions) | `tools/builtin/ledger.py` |
| 1.6 | Basic agent runtime (single-step, no multi-turn) | `agent/runtime.py`, `agent/context.py`, `agent/limits.py` |
| 1.7 | Non-streaming chat endpoint | `api/chat.py` |
| 1.8 | Conversation storage + list/create/delete APIs | `api/conversations.py`, `storage/conversations.py` |
| 1.9 | Chat UI template + JavaScript module | `templates/FavaAI.html`, `FavaAI.js` |

### Phase 2 — Knowledge Base + Multi-Step Agent

| # | Task | Files |
|---|---|---|
| 2.1 | Wiki manager (read/write/search markdown) | `knowledge/wiki.py` |
| 2.2 | Wiki page templates (Jinja2) | `knowledge/templates/*.md.j2` |
| 2.3 | Knowledge extraction engine (on `after_load_file`) | `knowledge/engine.py` |
| 2.4 | Account graph extractor | `knowledge/extractors/accounts.py` |
| 2.5 | Merchant catalog extractor | `knowledge/extractors/merchants.py` |
| 2.6 | Recurring transaction detector | `knowledge/extractors/recurring.py` |
| 2.7 | Portfolio + Spending + Cashflow extractors | `knowledge/extractors/portfolio.py`, `spending.py`, `cashflow.py` |
| 2.8 | Knowledge wiki tools (search, read, write) | `tools/builtin/wiki.py` |
| 2.9 | Multi-step agent runtime (tool calling loop) | `agent/runtime.py` (extend) |
| 2.10 | Context builder with KB injection | `agent/context.py` (extend) |
| 2.11 | SSE streaming endpoint | `api/chat.py` (add stream) |
| 2.12 | KB status + browsing APIs + UI panels | `api/knowledge.py` |

### Phase 3 — Advanced Features

| # | Task | Files |
|---|---|---|
| 3.1 | OpenAI + Anthropic + OpenAI-compatible providers | `models/openai.py`, `models/anthropic.py`, `models/openai_compat.py` |
| 3.2 | Provenance tracking | `provenance/tracker.py`, `storage/traces.py` |
| 3.3 | Execution limits + failure recovery | `agent/runtime.py` (extend) |
| 3.4 | Prompt registry + built-in prompts | `prompts/registry.py`, `prompts/builtin/*.py` |
| 3.5 | External tool plugin loader | `tools/loader.py` |
| 3.6 | Dashboard generation tools | `tools/builtin/dashboard.py` |
| 3.7 | Configuration UI + tool inspection UI | JS panels |
| 3.8 | User memory (preferences) | `agent/memory.py` (via SQLite config) |

### Phase 4 — Polish & Ecosystem

- Semantic retrieval (optional embeddings)
- MCP server compatibility
- Comprehensive documentation
- Test suite with pytest
- Community plugin examples

## Execution Order Dependency Graph

```
0.1 ──► 0.2
         │
         ├──► 1.1 ──► 1.8
         │
         ├──► 1.2
         │
         ├──► 1.3 ──► 1.6 ──► 1.7 ──► 1.9
         │              │
         └──► 1.4 ──────┘
                │
                └──► 1.5

1.9 (UI) + 2.1 (wiki manager) ──► 2.2 ──► 2.3 ──► 2.4..2.7
                                              │
2.3 + 2.4..2.7 ──► 2.8 ──► 2.9 ──► 2.10 ──► 2.11 ──► 2.12
                                                │
3.1..3.8 depend on 2.x completion
```

## Deployment Pattern — Fork + Submodule

The recommended deployment model separates engine code from user data.

### Directory Structure in the User's Ledger Repo

```
my-finances/                          # User's personal finance repo
├── main.beancount                    # 2010-01-01 custom "fava-extension" "fava_ai"
├── ledger/                           # Beancount source files
├── fava_ai/                          # Git submodule → user's fork of fava-ai
├── .fava-ai/                         # Ledger-local AI runtime data
│   ├── config.yaml                   # Provider keys, secrets → GITIGNORED
│   ├── conversations.db              # Personal chat history → GITIGNORED
│   ├── wiki/                         # Knowledge base → COMMITTED (versioned memory)
│   ├── prompts/                      # Custom prompts → COMMITTED
│   └── tools/                        # External tool plugins → COMMITTED
├── .gitignore
└── .gitmodules
```

### What Gets Committed vs Gitignored

| Path | Action | Reason |
|---|---|---|
| `fava_ai/` (submodule) | Git tracked | Engine code — pinned to fork commit via submodule ref |
| `.fava-ai/wiki/` | **Commit** | Knowledge is the compounding artifact, versioning it is the whole point |
| `.fava-ai/wiki/log.md` | **Commit** | Chronological audit trail of all ingest/query events |
| `.fava-ai/prompts/` | **Commit** | Custom prompts are part of the user's setup |
| `.fava-ai/tools/` | **Commit** | External tool plugins are part of the setup |
| `.fava-ai/config.yaml` | **Gitignore** | Contains API keys and secrets |
| `.fava-ai/conversations.db` | **Gitignore** | Personal chat history, binary, not meant to be shared |

### `.gitignore`

```gitignore
# Fava AI — sensitive / ephemeral files
.fava-ai/config.yaml
.fava-ai/conversations.db
```

### Initial Setup

```bash
# In the user's beancount/fava repo
git submodule add https://github.com/<user>/fava-ai.git fava_ai

# Install dependencies (one-time)
uv add litellm pyyaml

# Add extension to main.beancount
echo '2010-01-01 custom "fava-extension" "fava_ai" "{\"provider\": \"ollama\", \"model\": \"llama3\"}"' >> main.beancount

# Create config
mkdir -p .fava-ai
cat > .fava-ai/config.yaml <<EOF
providers:
  ollama:
    base_url: http://localhost:11434
agent:
  max_iterations: 10
EOF

# Ignore secrets
echo ".fava-ai/config.yaml" >> .gitignore
echo ".fava-ai/conversations.db" >> .gitignore

# Commit
git add fava_ai .gitignore .gitmodules .fava-ai/wiki/
git commit -m "Add fava_ai submodule"
```

### Day-to-Day Workflow

```bash
# After ledger reload — wiki auto-generated → commit the new knowledge
git add .fava-ai/wiki/
git commit -m "Update knowledge base"

# After adding custom prompts or tools
git add .fava-ai/prompts/ .fava-ai/tools/
git commit -m "Add monthly review prompt"

# Pull engine updates from fork
cd fava_ai && git pull origin main && cd ..
git add fava_ai
git commit -m "Update fava_ai submodule"
```

### Path Resolution

Fava adds the ledger directory to `sys.path` on startup, so `import fava_ai` from the submodule works without `pip install -e .` for the extension itself. Only litellm and pyyaml need to be in the Python environment.

The config directory is resolved relative to the beancount file path:

```python
class FavaAI(FavaExtensionBase):
    def __init__(self, ledger, config):
        ledger_dir = Path(ledger.beancount_file_path).parent
        self.config_dir = ledger_dir / config.get("config_dir", ".fava-ai")
```

### Why This Pattern Works

- **Engine code is pinned** — submodule ref locks to a specific commit, upgrades are explicit
- **Knowledge is versioned** — the wiki evolves over time with git history
- **Secrets stay local** — config.yaml and conversations.db never leave the machine
- **Transferable** — clone the ledger repo anywhere that has Python + Ollama, run fava, everything works
- **Fork-friendly** — users can customize their fork without upstream conflicts

---

## Test Plan

### Per-Phase Verification

**Phase 1 checks:**
- [ ] `uv pip install -e .` succeeds
- [ ] Extension loads in Fava without errors
- [ ] Chat UI renders and sends messages
- [ ] Non-streaming chat returns correct answers for basic questions against all fixtures
- [ ] Conversations persist across Fava sessions
- [ ] 3 questions per fixture: operating currency, account count, date range

**Phase 2 checks:**
- [ ] Wiki auto-generates on ledger load for all fixtures
- [ ] Wiki pages are valid markdown with correct YAML frontmatter
- [ ] Agent executes multi-step tool calls (BQL + wiki search in sequence)
- [ ] Recurring transactions correctly detected in all fixtures
- [ ] KB survives Fava restart and ledger reload
- [ ] Check wiki page human-readability in any markdown viewer

**Phase 3 checks:**
- [ ] Multiple providers work (at minimum Ollama + 1 cloud provider)
- [ ] Provenance visible in UI for every agent response
- [ ] Prompt registry loads built-in + user-installed prompts
- [ ] External tool plugin loads and executes
- [ ] Dashboard generation creates valid Fava dashboard definitions

### Model Testing Matrix

Test across 3 capability tiers (models to be provided):

| Tier | Model Size | Capability Tested |
|---|---|---|
| Small local | 3-8B params | Basic QA, single tool selection |
| Medium local | 8-32B params | Multi-step reasoning, complex tool chains |
| Large/cloud | 70B+ / GPT-4o / Claude | Advanced analysis, NL→dashboard generation |

Each tier tested against the same 5 questions across all fixtures:
1. "What is the operating currency and date range of this ledger?"
2. "What are my top 5 expenses by total amount?"
3. "What recurring payments do I have?"
4. "Show me my spending on food vs transportation by month."
5. "Create a dashboard showing net worth, savings rate, and restaurant spending."

### Fixture-Specific Test Dimensions

| Fixture | Language Tests | Feature Tests |
|---|---|---|
| `beancount-example` | EN names, metadata | Investment holdings, commodity prices, ETF analysis, tags |
| `finzytrack/fake` | EN payees (404 unique) | Scale (5,389 txns), recurring detection (12 patterns), cost analysis |
| `boilerplate-cn` | ZH account names, ZH commodities | Multi-currency (CNY/USD/HKD/BTC/ETH/USDT), crypto, CN stocks, social insurance |
| `financeiro` | PT-BR payees, receipts | Event finances, `comprovante` metadata, close/open accounts |
| `comptabilite` | FR account roots, GIFI codes | Fava extension loading, tax metadata schema, name remapping |
| `beancounters` | NO payees, expense names | Subscription patterns, bank→CC flows |
| `cfo-stack` scenarios | Personal vs business split | Balance assertions, equity accounts, multi-scenario comparison |
