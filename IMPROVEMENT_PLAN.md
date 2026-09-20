# Fava AI — Improvement & Test Plan

> **Status: implemented (0.2.0).** Stages 0–6 below were carried out. Stage 7 remains
> deferred backlog. See `CHANGELOG.md` for the concrete changes. The plan is kept as
> the design record; line/file references describe the pre-0.2.0 state.

> **Audience:** an implementing agent. This document is a staged plan, not a design doc.
> Each stage lists: goals, concrete changes (with file references), and acceptance criteria.
> Stages are ordered by priority; within a stage, items are independent unless noted.
> **Do not skip the test plan sections — each stage must land with its tests in the same PR/commit.**

---

## Part A — Current State Assessment

### What exists and works

- Fava extension (`__init__.py`, `FavaAI.js`, `templates/FavaAI.html`): chat UI, conversation list, side panel (tools/config/providers tabs)
- Agent loop (`agent/runtime.py`): provider → tool-calls → synthesis, with limits (iterations/tool-calls/timeout) and provenance tracking
- 5 LLM providers via a shared `LiteLLMProvider` base (ollama, openai, anthropic, deepseek, openai_compat)
- 13 built-in tools: 5 ledger tools (BQL, accounts, search, info), 4 wiki tools, 4 dashboard tools
- Knowledge base: 6 extractors → markdown wiki with frontmatter, hash-based rebuild detection
- SQLite storage: conversations, messages, traces, config, prompt_registry tables with a migration framework
- 125 tests across unit/fixture/llm layers

### Findings (verified against the code)

**Bugs / dead code (verified by grep):**

| # | Issue | Location | Severity |
|---|---|---|---|
| F1 | `chat_stream` endpoint is **fake streaming**: runs the entire agent loop, then yields all SSE events at the end. Frontend never calls it (uses `POST chat` only). Real token streaming is absent. | `__init__.py` `api_chat_stream`; `FavaAI.js` `sendMessage` | High |
| F2 | **Traces are never persisted.** `save_trace()` has zero production callers; the `traces` endpoint returns empty forever; provenance is lost on page reload; `token_count` and `metadata` columns unused. | `storage/traces.py`, `__init__.py` `api_chat` | High |
| F3 | **Config round-trip data loss:** `GET config` masks `api_key` as `***`; `PUT config` writes the JSON body straight to `config.yaml`. A UI save round-trip destroys `${OPENAI_API_KEY}` env references and any real key. PUT also has no validation/schema check. | `__init__.py` `api_get_config`/`api_update_config` | High |
| F4 | Misleading terminal error: when the model returns neither tool calls nor content, the loop `break`s and then raises `LimitExceeded("max_iterations")` — wrong message. No retry/backoff on provider errors. | `agent/runtime.py` end of `run()` | Medium |
| F5 | BQL tool errors are invisible to provenance: `RunBQLTool.execute` catches exceptions itself and returns a normal `ToolResult` (error only in metadata), so the tracker records `error=None`. | `tools/builtin/ledger.py`, `agent/runtime.py` | Medium |
| F6 | Message ordering by `created_at` (1-second granularity, no seq column): rapid tool-call/tool-result saves can interleave wrongly on reload. | `storage/schema.py`, `conversations.py` | Medium |
| F7 | `ProviderRegistry._connection_cache` is never invalidated — a provider that connects once shows "connected" forever. `LiteLLMProvider.test_connection` sends a real chat completion ("hi") — costs tokens on hosted providers. | `models/registry.py`, `models/litellm_base.py` | Medium |
| F8 | `ContextBuilder.set_prompt()` exists but no endpoint or UI ever calls it; `prompt_id` is instance state — a race condition if it were used. Prompts feature is backend-only. | `agent/context.py`, `__init__.py` | Medium |
| F9 | Silent fallback to `OllamaProvider()` when no provider is configured — user with a typo'd provider name gets a confusing "connection refused to localhost:11434" instead of "provider not configured". | `models/registry.py` `_init_from_config` | Medium |
| F10 | `api_conversations` GET handler checks `request.method == "GET"` inside a GET-registered route (dead branch); `create_conversation` with explicit `id` can raise unhandled `IntegrityError` (duplicate id). | `__init__.py`, `storage/conversations.py` | Low |
| F11 | `LiteLLMProvider.chat`: `if "timeout" in kwargs: params["timeout"] = kwargs["timeout"]` is redundant (`params.update(kwargs)` already did it). Runtime's `except TypeError` fallback for providers without a timeout kwarg is a hack. | `models/litellm_base.py`, `agent/runtime.py` | Low |
| F12 | `ConfigManager.get()` ignores falsy-but-present YAML values (`false`, `0`, `""`) due to `if yaml_val and ...`. | `config.py` | Low |
| F13 | Knowledge hash only covers date/payee/narration/account/units — ignores cost, price, tags, links, metadata. Edits that don't change those fields won't trigger rebuild. | `knowledge/engine.py` `_compute_hash` | Low |
| F14 | `after_load_file` swallows extraction exceptions with bare `except Exception: pass` — extraction failures are invisible. | `__init__.py` | Low |
| F15 | Dashboard tools are stubs: `generate_dashboard`/`generate_chart` echo JSON back to the model; nothing is created in Fava. Misleading tool descriptions. | `tools/builtin/dashboard.py` | Low |
| F16 | `tools/loader.py` does `sys.path.insert(0, tools_dir.parent)` and never removes it — global path pollution; also loads external tool code unconditionally (arbitrary code execution by default, should be opt-in). | `tools/loader.py` | Medium |
| F17 | Root-level strays: `test_deepseek.py`, `implementation.md` (1000-line planning doc), `opencode.json`; `tests/fixture/` (test code) vs `tests/fixtures/` (data) naming collision; `tests/analyze_*.py` are scripts collected by pytest's testpaths. | repo root, `tests/` | Low |
| F18 | No LICENSE file (README claims MIT), no CHANGELOG, no CI, no lint/type config, README documents `pip install -e ".[dev]"` but pyproject has no `[dev]` extras; `requests` used by `models/ollama.py` but not declared as a dependency. | repo root, `pyproject.toml` | Medium |

**Architectural gaps:**

| # | Gap | Impact |
|---|---|---|
| G1 | No context-window management: full history + full system prompt + all tool results sent every turn; no truncation, no token counting (column exists, unused). | Long conversations break / cost explosion |
| G2 | No provider error handling strategy: no retries, no rate-limit awareness, no user-facing error taxonomy. | Flaky UX |
| G3 | Wiki search is a linear full-scan of every `.md` on every query, and `_update_index()` re-reads every page on **every write** (O(n²) during extraction with 1000s of accounts/merchants). No search index/cache. | Slow on real ledgers |
| G4 | No per-conversation model/provider selection; UI never sends `provider` despite backend support. | Feature gap |
| G5 | Markdown rendering in UI is 3 regexes (`md()` in FavaAI.js): no lists, tables, code blocks, or links. | Poor answer quality for financial data (tables!) |
| G6 | `get_conversation` returns all messages unpaginated. | Fails on long conversations |
| G7 | Packaging: repo root *is* the package (`package-dir = {"fava_ai" = "."}`) — fragile for wheels/sdist (stray files risk, editable-install quirks). | Distribution risk |
| G8 | No integration tests against the Flask app (extension endpoints) — all endpoint code is untested. | Regression risk |

---

## Part B — Improvement Plan (Staged)

### Stage 0 — Repo hygiene & CI foundation (~half day)

**Goal:** make the repo safe to refactor, with a green CI gate.

1. Move strays:
   - `test_deepseek.py` → `scripts/test_deepseek.py` (it's a manual script, not a test)
   - `implementation.md` → `docs/implementation-history.md` (or delete after confirming nothing references it)
   - `tests/analyze_deep.py`, `tests/analyze_ledgers.py` → `scripts/`
   - Rename `tests/fixture/` (test code) → keep, but rename `tests/fixtures/` (data) → `tests/data/` to kill the near-collision; update `pytest.ini` `addopts` ignore path and `conftest.py` `FIXTURES_DIR`.
2. Add to `pyproject.toml`: `requests` dependency; `[project.optional-dependencies] dev = ["pytest", "pytest-cov", "ruff", "mypy"]`; `[tool.ruff]` and `[tool.mypy]` minimal configs.
3. Add `LICENSE` (MIT, per README), `CHANGELOG.md` (start at 0.1.0).
4. Add GitHub Actions CI (`.github/workflows/ci.yml`): matrix Python 3.10–3.12, `pip install -e ".[dev]"`, `ruff check .`, `pytest -q`, coverage report. Cache pip.
5. Add `pre-commit` config with ruff (implementing agent may skip if repo owner prefers).

**Acceptance:** `pytest -q` green from a clean venv; `ruff check .` clean (allow `--fix` pass first); CI badge runs.

---

### Stage 1 — Correctness fixes (high priority, ~1–1.5 days)

**Goal:** fix the verified bugs F2–F6, F9, F10, F12, F14. All small, independent, each with a regression test.

1. **Persist traces (F2):**
   - In `api_chat`, capture message ids from `save_message(...)` return values; after a successful run, call `save_trace(self._db, assistant_msg_id, result["provenance"]["steps"])`.
   - Store `message_id` in the chat response JSON so the frontend can call `traces` on reload.
   - Frontend: store `message_id` on the message DOM element; on conversation reload, fetch traces for assistant messages and re-render the provenance footer.
2. **Fix config round-trip (F3):** see Stage 2 (security) — do the validation there, but the `***` round-trip fix belongs here: `PUT config` must reject any value that equals the mask `"***"` and keep the existing key.
3. **Runtime loop fixes (F4):**
   - Empty response → raise a new `EmptyResponseError` (subclass of a `AgentError` hierarchy) with a clear message, or retry once, then surface "The model returned an empty response" to the user (HTTP 502, not 429).
   - Introduce error taxonomy in `agent/errors.py`: `LimitExceeded`, `ProviderError`, `ToolLoopError`, `NoProviderError`; map each to an HTTP status in `api_chat`.
4. **BQL error provenance (F5):** make `RunBQLTool` return `ToolResult(content=..., metadata={"error": ...})` **and** have the runtime check `result.metadata.get("error")` to set the tracker's error field. Alternatively raise `ToolError` and let the registry's handler format it — pick one convention and document it in `tools/base.py`.
5. **Message ordering (F6):** schema migration v2: add `seq INTEGER` to `messages` (monotonic per conversation, e.g. `MAX(seq)+1`), order by `(created_at, seq)` in `load_messages`/`get_conversation`. Test migration from v1 db.
6. **Provider cache invalidation (F7):** add `ProviderRegistry.invalidate(name=None)`; call it from `providers_test` POST endpoint. Change `LiteLLMProvider.test_connection` to a cheap check where possible (Ollama already overrides; for hosted providers a `models.list` call or a 1-token completion with a hard timeout — document the tradeoff, make it configurable `test_connection_method: cheap|chat`).
7. **No-provider UX (F9):** remove silent Ollama fallback in `_init_from_config`; when the registry is empty, `get_default()` returns `None` and `api_chat` returns a helpful 503 with "No provider configured — see .fava-ai/config.yaml". Keep Ollama as default only when explicitly listed or extension config says so.
8. **Dead branch + IntegrityError (F10):** remove the `request.method == "GET"` check; `create_conversation` → `INSERT OR IGNORE`-style handling or return 409 on duplicate.
9. **ConfigManager.get falsy bug (F12):** track key presence with a sentinel instead of truthiness.
10. **Extraction failure logging (F14):** `after_load_file` logs the exception (`logger.exception`) and appends `{"error": ...}` to the wiki log; still doesn't crash Fava.

**Acceptance:** every item above has a unit test (especially: trace persistence round-trip via a fake db; migration v1→v2; error taxonomy → HTTP status mapping). `pytest -q` green.

---

### Stage 2 — Security hardening (~half day)

1. **Config PUT validation (F3):** validate body against a schema (allowed top-level keys: `providers`, `agent`, `knowledge`; provider names from a known set; no unknown keys). Reject masked `***` api_key values (preserve existing). Never write the file if validation fails. Consider storing `PUT`-updated provider keys only in memory/env, not plaintext yaml (document the decision).
2. **External tool loader (F16):** gate loading behind config `tools.external_enabled: false` (default **off**); remove the `sys.path.insert` (use `spec_from_file_location` only, which already works without it — verify); log load failures via `logging` instead of `print(stderr)`.
3. **`wiki_write` tool:** keep but restrict default paths (e.g. only under `notes/`), and exclude auto-generated dirs (`accounts/`, `merchants/`, ...) from overwrite unless config allows. Document in tool description.
4. **BQL output size cap:** in `RunBQLTool`, truncate result rows (e.g. max 200 rows, max 8KB content) with a `truncated: true` flag in metadata so a `SELECT ... ` on a huge ledger doesn't blow the context window. Same cap for `search_transactions` (already has limit) and `account_details`.
5. **Verify `_safe_path`** path-traversal guard with tests for `../`, absolute paths, symlinks, URL-encoded paths.
6. Add a short `docs/SECURITY.md`: threat model (local single-user tool), what is exposed via HTTP (Fava's own auth applies), what config PUT can do.

**Acceptance:** unit tests for validation rejections, loader gating, output caps, path traversal.

---

### Stage 3 — Real streaming + conversation UX (~2 days, biggest user-visible win)

**Goal:** true token streaming in the UI, plus the missing conversation features.

1. **Real streaming pipeline:**
   - `AgentRuntime.run_stream(...)` generator: iterate `provider.chat_stream`; while the model emits tool calls, execute them and continue the loop; yield `content` deltas as SSE `data:` events; yield `tool_call` events as they happen (so the UI shows live tool activity); yield `done` with provenance/usage at the end.
   - Handle accumulated tool-call deltas (litellm streams tool calls in fragments — accumulate by `index`).
   - Rewrite `api_chat_stream` to use it. Keep `POST chat` non-streaming for API consumers/tests.
   - Respect `ExecutionLimits` inside the streaming loop too.
2. **Frontend (`FavaAI.js`):**
   - Use `fetch` + `ReadableStream` (or `EventSource`-style parsing) to consume SSE; progressively render tokens.
   - Add a **Stop/Abort** button (`AbortController`) that cancels the request.
   - Show tool calls as they stream in (live "Running run_bql..." chips), replacing the current post-hoc footer.
   - Replace `md()` with a small but correct markdown renderer: **use `marked` or `markdown-it` loaded from Fava's own bundled libs if available, otherwise vendored minimal renderer** covering fenced code blocks, tables, lists, links, bold/italic. Must sanitize (escape HTML first or use DOMPurify-equivalent manual sanitizer). Tables matter most for financial output.
3. **Provider/model selection (G4):**
   - `GET providers` already exists; add model list to the UI (uses `providers_models`), store selection per conversation (new column `provider`/`model` already exist on conversations — populate them on first message instead of empty strings).
   - `chat`/`chat_stream` request body gains `model`; runtime passes it to `provider.chat(model=...)` (base class already supports the `model` kwarg — currently unused).
4. **Prompt selection (F8):** `chat` request gains optional `prompt_id`; pass it through to `ContextBuilder.build_system_prompt(prompt_id=...)` (change from mutable instance state to a parameter). UI: dropdown above the chat input listing `GET prompts`.
5. **Conversation list polish:** rename (new endpoint or reuse PUT), export-to-markdown (client-side), and pagination on `get_conversation` (`?limit=&offset=` on messages, G6).

**Acceptance:**
- `tests/llm/test_mock_agent.py` extended: a `MockStreamProvider` exercising `run_stream` end-to-end (tool call fragments → tool execution → final synthesis) with correct SSE event ordering.
- Flask test-client test: `POST chat_stream` yields parsable SSE frames.
- Manual E2E script (see Part C matrix) with a real Ollama model.

---

### Stage 4 — Context management & agent robustness (~1–1.5 days)

1. **Token budget:**
   - Add a `count_tokens(messages)` utility (approximate: chars/4 heuristic is fine; litellm has `token_counter` — use it when available with fallback).
   - `ContextBuilder.build_messages(history, user_message, budget)`: drop oldest turns (keep system + last N turns within budget), summarize truncated turns in one line ("... N earlier messages omitted").
   - Persist `token_count` per message on save (finally uses the column).
2. **Tool result budget:** cap each tool result fed back to the model (configurable `agent.max_tool_result_chars`, default e.g. 8k) with truncation notice; pairs with Stage 2 item 4.
3. **Provider retries:** wrap `provider.chat` with retry (config `agent.retries`, default 1–2) on transient errors (connection errors, 429/5xx); exponential backoff; never retry on auth errors. Surface final error via the taxonomy from Stage 1.
4. **History hygiene:** when loading history for a follow-up turn, strip stale `tool` messages whose parent assistant message got truncated (providers crash on orphan tool messages).
5. **Parallel tool calls:** the loop currently executes tool calls sequentially — fine, but ensure multiple `tool_calls` in one response are all appended before the next model call (they are — verify with a test; add one if missing).

**Acceptance:** unit tests for budget truncation, orphan-tool stripping, retry behavior (mock provider raising then succeeding), token counting fallback.

---

### Stage 5 — Knowledge base performance & quality (~1 day)

1. **Index maintenance (G3):** `_update_index()` currently re-reads every page on every write. During `extract_all`, batch: write all pages, then rebuild the index once (add `WikiManager.flush()` / a `defer_index` context manager).
2. **Search cache:** in-memory cache keyed by (file mtime-tuple, query) — or simpler: an in-memory search index (path → lowercase text) invalidated by directory mtime; rebuild lazily. Also avoid the double search per request (ContextBuilder `_get_kb_context` searches, then the agent often searches again — acceptable, but caching makes it cheap).
3. **Hash completeness (F13):** include cost/price/tags/links/meta in `_compute_hash`; store the hash file atomically (write temp + rename).
4. **Extractor tests on a realistic ledger:** generate a synthetic 5k-transaction ledger fixture (script in `scripts/`), assert extraction completes in < N seconds (perf smoke test, marked `slow`), wiki page counts, and idempotency (second `extract_all` is a no-op via `needs_rebuild`).
5. **Fixtures:** the current `beancount-example.beancount` is tiny; add a second fixture with investments (cost basis), multiple currencies, tags/links — needed by portfolio/spending extractors' tests.

**Acceptance:** perf smoke test passes; hash-change tests (mutate a tag → `needs_rebuild` is True).

---

### Stage 6 — Packaging, docs & polish (~half day)

1. **Standard layout (G7):** move to `src/fava_ai/` (or at minimum verify the current flat layout produces a correct wheel: `python -m build` and inspect the wheel contents for stray files; fix `package-data` and `packages` list accordingly). **Verify Fava's extension discovery still works** (module name `fava_ai` must remain importable, `templates/FavaAI.html` + `FavaAI.js` included).
2. Bump to `0.2.0` in `_version.py` + CHANGELOG entry summarizing Stages 0–5.
3. README refresh: streaming UX screenshots, prompt/model selection, `tools.external_enabled` opt-in note, corrected dev instructions (`pip install -e ".[dev]"` now real), remove stale BQL-template duplication if the prompt changed.
4. Remove/redirect now-dead code paths found during implementation (e.g. the `except TypeError` timeout hack once all providers accept `timeout`).

**Acceptance:** `pip install dist/*.whl` in a clean venv + Fava loads the extension from an installed (non-editable) package.

---

### Stage 7 — Deferred / optional (do NOT do now; record as backlog)

- Real embedding-based wiki search (sqlite-vec / chromadb) — current keyword search is adequate for v0.2
- Dashboard tools that actually create Fava dashboards (F15) — requires upstream fava-dashboard integration; until then, either delete `generate_dashboard`/`generate_chart` or rename descriptions to "compose a dashboard definition" (decide in Stage 1; recommend just fixing descriptions now)
- Multi-user / auth hardening (Fava is single-user local; out of scope)
- Prompt marketplace / installable prompt packages
- i18n of UI strings
- Streaming tool-execution progress via WebSocket instead of SSE

---

## Part C — Test Plan

### Layered strategy (extend what exists — do not rewrite)

| Layer | Location | Runs in CI | What it covers |
|---|---|---|---|
| L1 Unit | `tests/unit/` | yes | Pure logic: config, storage, wiki, extractors, tools, tracker, registry — no network, no Fava |
| L2 Agent-loop | `tests/llm/test_mock_agent.py` | yes | AgentRuntime with `MockProvider`/`MockStreamProvider`: limits, taxonomy, retries, streaming event order |
| L3 Endpoint (NEW) | `tests/integration/test_endpoints.py` | yes | Flask test client against a real `FavaAI` extension instance (or a Flask app fixture registering the blueprint): every endpoint, status codes, SSE parsing, auth-of-config-PUT |
| L4 Fixture | `tests/fixture/` + `tests/data/` | yes | Real beancount files: BQL correctness vs. known answers, extractor output snapshots |
| L5 LLM smoke | `scripts/test_deepseek.py` + new `scripts/test_ollama.py` | no (manual) | One real provider round-trip; gated behind env vars; never in CI |
| L6 Manual E2E | checklist below | no | Full UI against a real Fava + Ollama |

### Per-stage required tests (the implementing agent must add these)

**Stage 0:** CI green on existing 125 tests. Rename-proof: no test imports `tests/fixtures` path literals after data-dir rename.

**Stage 1:**
- Traces: `api_chat` (L3) with a stub runtime → messages saved → `GET traces?message_id=` returns the steps; `message_id` present in response.
- Migration: create a v1 `conversations.db` fixture (checked-in binary or generated via `MIGRATIONS[1]`), run `Database.initialize()`, assert `seq` populated and ordering correct.
- Taxonomy: parametrized test `error → HTTP status` (LimitExceeded→429, ProviderError→502, NoProviderError→503, empty response→502 with clear message).
- BQL error: fake ledger raising inside `run_query` → tracker step has `error` set.
- Registry: empty config → `get_default() is None`; `invalidate()` clears cache; duplicate conversation id → 409; `ConfigManager.get` with `false`/`0` values.
- `after_load_file` with a raising engine → no exception, log record emitted (assert via `caplog`).

**Stage 2:**
- Config PUT: rejects unknown top-level keys, rejects `***` (keeps old key), rejects non-dict providers; success case writes valid yaml and `get_provider_config` reflects it.
- Loader: `external_enabled: false` → no import attempted (assert module not in `sys.modules`); enabled → loads; broken plugin → warning logged, no crash; `sys.path` unchanged after load.
- BQL cap: query returning 500 rows → result has `row_count: 500` but ≤200 serialized rows + `truncated: true`.
- Path traversal: `wiki_read`/`wiki_write`/`wiki.exists` with `../../etc/passwd`, `/etc/passwd`, `a/../../b` — all rejected. (Some exist; verify coverage complete.)

**Stage 3:**
- `run_stream` with `MockStreamProvider`: emits content deltas; tool-call fragments across chunks accumulate into one `ToolCall`; tool executed once; SSE frames parseable (`data: {...}\n\n`); `done` frame contains provenance.
- Limits inside streaming: max_iterations exceeded mid-stream → `error` SSE frame with 429-semantics message.
- L3: `POST chat_stream` returns `text/event-stream`, ends with `done` frame.
- Prompt selection: `chat` with `prompt_id: monthly_review` → ContextBuilder receives it (assert via stub) and `set_prompt` state removed.
- Message pagination: conversation with 100 messages → `?limit=20&offset=40` returns the right slice.

**Stage 4:**
- Budget: 50-turn history with tiny budget → built messages keep system + tail, contain omission notice; token_count persisted.
- Orphan tool messages: history where an assistant-with-tool-calls is dropped but its tool reply remains → stripped before provider call.
- Retries: mock provider raising `ConnectionError` once then succeeding → run succeeds, `calls == 2`; raising auth error → no retry, `ProviderError` raised.
- Tool result cap: 100KB ToolResult content → message to model ≤ cap + notice.

**Stage 5:**
- Index batching: `extract_all` on synthetic ledger writes index once (instrument `_update_index` call count).
- Hash: mutate a tag/link/cost in entries → `needs_rebuild` True; unchanged → False.
- Perf smoke (`@pytest.mark.slow`, excluded from default run): 5k-txn ledger extraction < 10s (tune threshold on CI hardware; keep generous).

**Stage 6:**
- Wheel content test (script): built wheel contains `fava_ai/templates/FavaAI.html`, `fava_ai/FavaAI.js`, all `__init__.py` packages, and **no** tests/docs/scripts.
- Import test from installed wheel in a fresh venv: `from fava_ai import FavaAI` succeeds.

### Manual E2E checklist (L6 — run before tagging 0.2.0)

Against: Fava latest stable + `tests/data/beancount-example.beancount` + local Ollama (e.g. `qwen2.5:7b`) and one hosted provider (deepseek):

1. Fresh clone → `pip install -e ".[dev]"` → `pytest -q` → all green
2. No config.yaml present → open AI Assistant → helpful "no provider configured" message (F9)
3. Configure ollama → providers panel shows connected within seconds; model dropdown lists installed models
4. "What are my top 5 expenses?" → tokens stream visibly; tool chips appear live; final answer has a table rendered correctly
5. Follow-up in same conversation ("what about just food?") → context retained, no duplicated system prompt
6. Reload page → conversation history + provenance footers restored (F2 fix end-to-end)
7. Ask a question that makes the model run 3+ BQL queries → limits respected, provenance summary accurate
8. Stop button mid-stream → generation halts, no orphan loading spinner
9. Switch prompt to "Monthly Review" → next answer follows that persona
10. Kill Ollama mid-question → clean error message, conversation still usable
11. Config tab → edit agent.max_iterations via UI → save → verify config.yaml updated and `${ENV_VAR}` refs survive round-trip
12. Large ledger (5k txns) → first load triggers extraction (visible in wiki log), second load is a no-op

### Regression gates

- No test may require network or an LLM API key to pass CI (L1–L4 only).
- Every bug fix (F1–F18) lands with a test that fails without the fix (commit message references the F-number).
- Coverage target: **≥85% on `agent/`, `storage/`, `config.py`, `tools/registry.py`** (report via `pytest --cov=fava_ai --cov-report=term`); JS is manual-tested only for now.

---

## Part D — Suggested execution order & effort

| Stage | Effort | Depends on | Can be parallelized |
|---|---|---|---|
| 0 Hygiene/CI | 0.5d | — | — |
| 1 Correctness | 1–1.5d | 0 (CI gate) | items independent |
| 2 Security | 0.5d | 1 (error taxonomy) | yes |
| 3 Streaming/UX | 2d | 1 | backend stream & frontend render can split |
| 4 Context mgmt | 1–1.5d | 3 (streaming loop refactor) | partially |
| 5 Knowledge perf | 1d | — | fully parallel with 3/4 |
| 6 Packaging | 0.5d | all | — |

Total: ~6.5–8 days of focused agent work. Recommend one PR per stage (or per stage-half for Stage 3), each PR = code + tests + CHANGELOG entry.
