# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Configuration is now primarily the beancount directive.** The `fava-extension`
  line accepts flat single-endpoint keys (`provider`, `base_url`, `api_key`, `model`) and
  nested `providers` / `agent` / `knowledge` / `tools` sections. `${ENV_VAR}` is expanded
  there too, so secrets can stay out of the ledger. `.fava-ai/config.yaml` is now optional
  and only overrides the directive key-by-key.
- **Providers unified into a single OpenAI-compatible implementation.** Every vendor
  (OpenAI, DeepSeek, Ollama, Anthropic, llama.cpp, LM Studio, vLLM, OpenRouter) is
  configured with `base_url` + `api_key` + `model`. Legacy names (`openai`, `deepseek`,
  `anthropic`, `ollama`) are kept as aliases that supply a default base URL. Removed
  `models/openai.py`, `models/anthropic.py`, `models/deepseek.py`, `models/ollama.py`.
- Model listing and the connection check now use the OpenAI-compatible `/models`
  endpoint (with a 1-token completion fallback), so the model picker works for every
  endpoint.

### Added
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
