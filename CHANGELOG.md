# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Chat document uploads (#20).** Attach receipts/statements (PDF or images) via the
  paperclip or drag-and-drop; files are stored under `.fava-ai/documents/`, text is
  extracted locally, attachments stay with the conversation, and the agent reads them
  via `read_document` (small documents are inlined into the prompt).
- **Document knowledge base (#21, phase 1).** Index existing document folders
  (`documents.folders`, plus Fava's documents folder) into a local SQLite **FTS5
  (BM25)** index with incremental, content-hash rebuilds. New `search_documents` and
  `read_document` tools mirror the wiki tools, plus a **Docs** panel with status and
  *Index now*.
- **Optional semantic search (#21, phase 2).** An OpenAI-compatible
  `documents.embedding` block (`base_url` + `api_key` + `model`) embeds chunks into
  SQLite BLOBs and enables **hybrid retrieval** (BM25 + cosine, fused with reciprocal
  rank fusion). Without it, search degrades gracefully to keyword-only.
- **Read-only-safe filing (#20).** `file_document` returns a paste-ready beancount
  entry (transaction with `attachment:` metadata + a `Document` entry). Appending it to
  a dedicated file is opt-in via `tools.allow_ledger_writes` / `tools.ledger_writes_file`.
- New endpoints: `GET`/`DELETE /documents`, `POST /documents_upload`,
  `POST /documents_index`, `POST /documents_retry`, `POST /documents_embed`,
  `POST /documents_embed_test`.
- `pypdf` dependency for PDF text extraction (PDFs flag as unsupported if absent,
  and the Docs panel says so).
- The **Config** panel now edits `documents.enabled` and the
  `documents.embedding.*` endpoint (base_url / model / api_key) instead of leaving
  semantic search to hand-written YAML.

### Fixed
- **Fava's `documents` folder option was silently ignored.** Two rounds of wrong: first,
  joining a `Path` with the list beancount parses raised a swallowed `TypeError`; after
  that was fixed it turned out Fava 1.30 does not expose the option on `fava_options` at
  all (that attribute path was dead code), so the folder still vanished. It is now read
  from the raw beancount options map — where Fava's own documents module reads it — and
  resolved with `ledger.join_path`.
- **Failed extractions never recovered.** A file recorded as `unsupported`/`error` was
  returned from cache on re-import (matching `sha256` short-circuited extraction), so a
  PDF first seen without `pypdf` stayed unusable. Re-importing now re-extracts, and
  `POST /documents_retry` / *Retry failed* heals existing rows.
- **CJK keyword search returned nothing.** FTS5's `unicode61` tokenizer treats an
  unspaced run of Chinese/Japanese as a single token, so `记账` could not match
  `记账软件测试`. CJK characters are now indexed per character and CJK queries run as a
  phrase; single-character CJK queries work too. Existing indexes migrate on startup.
- **Uploaded files were orphaned when a conversation was deleted.** They are now removed
  with the conversation (rows and files).
- **The attach button rendered the literal text `\U0001f4ce`** — a Python escape pasted
  into a Jinja2 template, which does not interpret it.
- **The embedding *Test* button showed "unknown error"** for every failure: the panel
  read `error` while the endpoint returned `detail`.
- **An empty extraction was reported as `indexed`**, hiding scanned PDFs; it is now
  `empty` with an explanation.
- `PUT /config` rejected the `config_dir` key that `GET /config` returns, so a
  round-tripped config failed validation.
- Punctuation-only searches now say so instead of looking like "no matches"; search
  results expose a relevance `score`.
- **The embedding *Test* button tested a stale client** — it read the client built at
  startup, so an api_key just saved in the Config tab still tested the old key (401)
  until some other endpoint happened to rebuild it. *Test* and the Docs panel now
  refresh before reporting, so a saved key is the one that gets tested.
- **`documents.enabled` was decorative.** It now gates folder indexing
  (`POST /documents_index` → 403 with a hint, and the panel says so); chat uploads are
  unaffected.
- Config inputs are labelled with `for=`, so screen readers can tell the provider key
  from the embedding key.
- Document tests write UTF-8 explicitly and pass on non-UTF-8 locales (e.g. Windows).

### Changed
- **Configuration is now primarily the beancount directive.** The `fava-extension`
  line accepts flat single-endpoint keys (`provider`, `base_url`, `api_key`, `model`) and
  nested `providers` / `agent` / `knowledge` / `tools` sections. `${ENV_VAR}` is expanded
  there too, so secrets can stay out of the ledger. `.fava-ai/config.yaml` is now optional
  and only overrides the directive key-by-key.
- **Providers unified into a single OpenAI-compatible implementation.** Every vendor
  (OpenAI, Anthropic, DeepSeek, Google, Groq, Mistral, xAI, Together, OpenRouter,
  Cerebras, NVIDIA, Moonshot, Fireworks, Baseten, HuggingFace, Vercel AI Gateway, Meta,
  Xiaomi) is configured with `base_url` + `api_key` + `model`. Well-known names supply a
  default base URL. Removed `models/openai.py`, `models/anthropic.py`,
  `models/deepseek.py`, `models/ollama.py`.
- **`ollama` is no longer special-cased.** A local server is just an OpenAI-compatible
  `base_url` (e.g. `http://localhost:11434/v1`); see the README example. The default
  provider is now the configured `provider`, or the first one declared.
- Model listing and the connection check now use the OpenAI-compatible `/models`
  endpoint (with a 1-token completion fallback), so the model picker works for every
  endpoint.

### Added
- Editable Config panel (provider `base_url`/`model`/`api_key` and agent limits)
  wired to `PUT /config`, with secrets kept masked and absolute paths no longer
  dumped.
- `agent.wrap_up_seconds` (default 60) for the post-limit wrap-up call.
- `tests/data/ledgers/narration-multi-currency.beancount` and
  `tests/unit/test_real_data_issues.py` covering every issue above.
- Reasoning-model support: `reasoning_content` is captured (`ChatResponse.reasoning`),
  streamed as `reasoning_delta` SSE events, and shown as a collapsible "Thinking…"
  block in the UI. On a local reasoning model this cut time-to-first-token from
  ~7.0s to ~0.8s.
- Provider aliases: any provider name is allowed when it declares a `type`
  (e.g. `local: {type: openai_compat, ...}`); unknown names without a type are
  logged instead of silently dropped.
- `agent.max_tokens` to cap generated tokens per provider call.
- `scripts/eval_local.py` to evaluate the agent stack against a live endpoint.

### Fixed
- **Scrolling up while the answer streams no longer fights the user.** The
  message area used to jump to the bottom on every token. It now follows only
  while the user is pinned to the bottom (tracked by a scroll listener), and
  jumps to the newest content on a new turn or conversation load.
- **The `<details>` disclosure arrow no longer overlaps its label.** Fava
  styles every `<details>` globally (arrow via `summary:before` at `left:10px`
  with `padding-left:30px`, plus `min-width:400px`); the inline reasoning and
  tool-activity blocks overrode that padding without reserving the space. They
  now reset Fava's `details`/`summary` rules and reserve the arrow's room.
- **Tool calls no longer pile up below the answer.** Each `tool_call` used to
  append a visible "Tool: …" row that never collapsed; all calls now live in a
  single collapsed "Tool activity (N)" block, with only the one-line provenance
  summary visible by default.
- **The UI is now theme-aware (dark mode works).** The stylesheet hardcoded a
  light-only palette (`#fafafa`, `#fff`, `#2266cc`, …); it now uses Fava's CSS
  custom properties (`--background`, `--text-color`, `--border`, `--link-color`,
  `--code-background`, `--font-family`, …) with fallbacks, so it follows Fava's
  light/dark theme and typography.
- **Merchants & recurring pages were empty for narration-only ledgers.**
  `merchant_key()` now falls back to a merchant derived from the narration
  (stripping card/terminal numbers and delimiters) when `payee` is empty, and
  recurrence detection uses it too.
- **Account pages listed the account as its own sub-account** (and every
  descendant). Direct children are used now, and pages show both own and
  aggregate balances with subtree transaction counts.
- **Wiki paths used OS-native separators**, producing backslash Obsidian links
  and platform-dependent tool I/O on Windows. All serialized paths now use
  forward slashes (`as_posix()`).
- **`overview.md` linked to `accounts/_index.md`, `merchants/_index.md` and
  `recurring/_index.md`, which were never generated.** They are now written,
  and hidden from the main index and search.
- **Spending/cashflow pages silently dropped every currency but the first.**
  They now report each currency in its own section and list the currencies
  included; amounts are never mixed or dropped.
- **`wiki_search` had no stemming or word boundaries** — "groceries" missed
  `Expenses:Grocery`, and "net worth" matched "Internet". Search now tokenizes,
  lightly stems, scores title/body term frequency, and keeps substring matching
  only as a fallback.
- **Portfolio listed closed (zero-unit) positions as holdings and had no
  valuation.** Zero-net positions move to a "closed positions" list, and cost
  basis plus latest market value are included when price data exists.
- **`list_accounts` returned non-recursive balances** (every parent showed 0),
  with no aggregation, substring filter or cap. It now returns `balance` and
  `aggregate_balance`, supports `contains`, sorts by absolute aggregate balance
  and caps output (reporting `total_matching`/`truncated`).
- **Native `confirm()`/`prompt()` blocked the page** (hanging automation and
  embedded contexts). Conversation delete is a two-step inline confirm and
  rename is inline editing.
- **Hitting an execution limit returned a hard error with nothing persisted.**
  The runtime now makes one tool-less "wrap up" call and returns a best-effort
  answer flagged `partial` with a `stop_reason`; interrupted runs persist their
  history instead of vanishing.
- Timeouts are now bounded: the remaining budget is recomputed before every retry,
  read timeouts are no longer retried (previously a 45s budget could run 149s), and
  timeouts surface as `ProviderTimeoutError` → HTTP 504 instead of `429 LimitExceeded`.
- Streaming retries no longer duplicate rendered output: a transient failure after
  reasoning deltas have been streamed fails fast instead of retrying (which would
  duplicate the "Thinking…" text).
- `POST /providers_test` returns 404 for unknown provider names and caches the result
  under the configured alias (previously it silently tested the default provider and
  could key the cache by the provider type instead of the alias).
- `scripts/eval_local.py` no longer hardcodes an API-key default.

### Changed
- Default `agent.timeout_seconds` raised from 120 to 300 for slow local models.

## [0.2.0] - 2026-09-20

Packaging, streaming, context management and knowledge-base performance release.

### Added
- Knowledge-base performance: `index.md` is rebuilt once per extraction instead of
  per page, searches use a stat-invalidated cache, and edits to cost/price/tags/links
  now trigger a rebuild (the entries hash covers them).
- `tests/data/ledgers/rich-features.beancount` fixture (multi-currency, cost basis,
  prices, tags, links) plus a `slow`-marked 5k-transaction extraction smoke test.
- Context-window management: history is trimmed to `agent.max_context_tokens` (keeping
  the newest turns and never orphaning tool results), tool results are capped to
  `agent.max_tool_result_chars`, and per-message `token_count` is persisted.
- Provider retries with exponential backoff for transient failures (rate limits, 5xx,
  connection errors); auth errors are not retried (`agent.retries`).
- Real token streaming: `AgentRuntime.run_stream` drives litellm's streaming API,
  reassembles fragmented tool calls, and emits `content_delta` / `tool_call` / `done`
  SSE events. The UI renders tokens live with a Stop button.
- Provider, model and system-prompt selection in the UI, persisted per conversation.
- Conversation rename (double-click a title) and markdown export.
- Message pagination for `GET /conversations` (`?limit=&offset=`).
- CI workflow (GitHub Actions): ruff lint, mypy, pytest with coverage on Python 3.10–3.12.
- `dev` optional dependency group (`pip install -e ".[dev]"` now works).
- `LICENSE` (MIT) and `CHANGELOG.md`.
- `scripts/fetch_sample_ledgers.sh` to clone external sample Beancount ledgers for local analysis.
- `scripts/` directory for manual analysis and provider smoke-test scripts.
- Endpoint-level (Flask test client) test layer under `tests/integration/`.
- Agent error taxonomy (`agent/errors.py`): `NoProviderError`, `ProviderError`,
  `EmptyResponseError`, `ToolLoopError`, `LimitExceeded`, mapped to HTTP status codes.
- `docs/SECURITY.md` documenting the threat model and controls.

### Security
- `PUT /config` now validates the document against a strict allow-list and refuses
  unknown keys/provider names/types, leaving the file untouched on failure.
- Loading external tool plugins from `.fava-ai/tools/` is opt-in
  (`tools.external_enabled`, default `false`) and no longer mutates `sys.path`.
- `wiki_write` refuses to overwrite auto-generated knowledge-base pages unless
  `overwrite=true` is passed.
- Tool output is size-capped to protect the model context window.
- BQL result values are converted defensively, fixing `Decimal` serialisation errors.

### Changed
- The chat UI now consumes the streaming endpoint, renders live tool-call chips, uses a
  dependency-free markdown renderer (tables, lists, code blocks, links), and lifts
  `prompt_id`/`model` through to the runtime.
- Provenance is now persisted: chat responses include a `message_id`, traces are saved,
  and the UI restores tool-call provenance when a conversation is reloaded.
- Final assistant answers are now stored in conversation history (previously dropped).
- Message ordering is deterministic via a per-conversation `seq` column (schema v2).
- Config writes no longer destroy `${ENV_VAR}` API-key references when the UI round-trips
  the masked `***` placeholder.
- Provider connection status can be invalidated; `providers_test` refreshes the cache.
- Missing provider configuration now returns a clear 503 (`NoProviderError`) instead of
  silently attempting localhost Ollama.
- `ConfigManager.get()` honours present-but-falsy YAML values.
- Knowledge-base extraction failures are logged instead of silently swallowed.
- Moved test ledger data from `tests/fixtures/ledgers/` to `tests/data/ledgers/`.
- Moved `test_deepseek.py`, `tests/analyze_*.py` to `scripts/`.
- Moved `implementation.md` to `docs/implementation-history.md`.
- Declared `requests` as an explicit runtime dependency (used by the Ollama provider).

### Removed
- Broken gitlink entries under `tests/fixtures/ledgers/` (empty, no `.gitmodules`).

## [0.1.0] - 2025-09-19

### Added
- Initial release: Fava extension with chat UI, agent runtime, 5 LLM providers via litellm,
  13 built-in tools, markdown-wiki knowledge base, SQLite conversation storage,
  provenance tracking, prompt registry, and external tool plugin loading.
