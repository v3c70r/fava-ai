# AGENTS.md

Guidance for AI agents (and humans) working in this repository. Read this before making
changes; it encodes constraints that are easy to violate and that CI will not always catch.

## What this project is

`fava-ai` is a **Fava extension**: an AI assistant for Beancount/Fava ledgers. It runs inside
the user's Fava process, reads the ledger through Fava/beancount APIs, calls an
OpenAI-compatible model (local or hosted), and exposes a chat UI plus a small REST surface.

Two properties define the product and must not regress:

1. **Local-first** — everything must work against a local endpoint with no cloud dependency.
2. **Read-only by default** — the assistant must never modify the user's beancount files.
   The only write path is opt-in and never touches the main journal (see invariants below).

## Non-negotiable invariants

| Invariant | Where it is enforced |
|---|---|
| Never write to ledger files | All tools default to `permission = "readonly"`. `file_document` returns a paste-ready snippet; appending is opt-in via `tools.allow_ledger_writes` + `tools.ledger_writes_file`, is flattened to a single filename inside the ledger dir, and **refuses** to write `ledger.beancount_file_path`. |
| Secrets never leak to the browser | `GET /config` masks every `api_key` as `***`; `PUT /config` treats `***` as "keep the stored value" (so `${ENV_VAR}` references survive a UI round-trip). |
| No path traversal | Any user-supplied name/path is sanitized (`documents.store.sanitize_filename`, `_safe_dir_name`) before touching the filesystem. |
| Portability to Python 3.10 | CI runs 3.10/3.11/3.12. Do not use 3.11+ syntax, and see the pitfalls section for the bytes-filename and text-encoding traps. |
| Tests never touch the network | Stub `requests.post` (`fava_ai.documents.embeddings`) or inject a provider. There must be no real HTTP in the default test run. |
| The repo is **public** | Never put internal hostnames/IPs, personal paths, real tokens, or real ledger data in code, tests, docs, fixtures, commit messages, or PR/issue text. Example values must be generic (`localhost`, `${API_KEY}`, `nomic-embed-text`). |

## Repository map — note the flat layout

The repository root **is** the `fava_ai` package (`package-dir = {"fava_ai" = "."}` in
`pyproject.toml`). So `documents/` at the root is imported as `fava_ai.documents`. There is no
nested `fava_ai/` directory.

| Path | Responsibility |
|---|---|
| `__init__.py` | The `FavaAI(FavaExtensionBase)` class: component wiring, every `@extension_endpoint`, streaming chat, config read/write. Start here. |
| `config.py` | `DEFAULT_CONFIG`, `ConfigManager` (precedence + `${ENV_VAR}` expansion), `validate_config` (allow-lists), provider type resolution. |
| `agent/` | `runtime.py` (`AgentRuntime.run` / `run_stream`, tool loop, limits, partial answers), `context.py` (system prompt + context budget), `tokens.py`, `limits.py`, `errors.py`. |
| `models/` | `base.py` (provider ABC), `litellm_base.py`, `openai_compat.py` (the only implementation), `registry.py` (alias → client, **and `reload()`**). |
| `tools/` | `base.py` (`BaseTool`, `ToolResult`, `ToolError`), `registry.py` (dispatch), `loader.py` (opt-in external plugins), `builtin/` (`ledger.py`, `wiki.py`, `dashboard.py`, `documents.py`). |
| `knowledge/` | `wiki.py` (markdown knowledge base under `.fava-ai/wiki/`), `engine.py` (incremental rebuild on ledger load), `extractors/` (accounts, merchants, spending, recurring, portfolio, naming). |
| `documents/` | `extract.py` (PDF via `pypdf`, text, images flagged), `chunking.py`, `store.py` (SQLite + FTS5 + optional vectors), `embeddings.py` (OpenAI-compatible `/v1/embeddings`). |
| `storage/` | `database.py` (sqlite3 + `MIGRATIONS`), `schema.py` (DDL + `SCHEMA_VERSION`), `conversations.py`, `traces.py`. |
| `prompts/`, `provenance/` | Installable system prompts; per-response provenance tracking. |
| `templates/FavaAI.html`, `FavaAI.js` | The entire frontend (no build step, no framework). |
| `tests/` | See the test architecture section. |
| `scripts/` | Manual tools: `check_wheel.py` (CI), `eval_local.py` (live-model eval), `analyze_*.py`, `fetch_sample_ledgers.sh`. |
| `docs/` | `SECURITY.md`, `implementation-history.md`, plus `IMPROVEMENT_PLAN.md` at the root. |

## Setup and commands

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"

.venv/bin/python -m pytest -q                 # default suite (fast; slow deselected)
.venv/bin/python -m pytest -q -m slow         # performance smoke tests
.venv/bin/python -m pytest -q --cov=fava_ai --cov-report=term-missing
.venv/bin/ruff check .                        # lint (CI gate)
.venv/bin/mypy .                              # types (CI gate)
node --check FavaAI.js                        # JS syntax — NOT run by CI, run it yourself
python -m build --wheel && python scripts/check_wheel.py   # packaging (CI, 3.12 only)
```

Baseline on a clean checkout: `373 passed, 1 skipped, 1 deselected`. The skip is an optional
external sample-ledger fixture (`fetch_sample_ledgers.sh`); the deselected test is `-m slow`.

CI (`.github/workflows/ci.yml`) runs on pushes/PRs to `implementation` and `main`:
ruff → mypy → pytest with coverage on 3.10/3.11/3.12, then slow tests + wheel build on 3.12.

Config knobs and their defaults live in `config.py::DEFAULT_CONFIG`
(`agent`, `knowledge`, `tools`, `documents`). `providers` is not a default — providers come
from the ledger directive and/or `.fava-ai/config.yaml`.

## Test architecture

| Directory | What it covers | How to write one |
|---|---|---|
| `tests/unit/` | Pure logic. No Fava, no network. | Plain pytest. Use `tmp_path`; fixtures `tmp_dir`, `sample_entries`, `MockLedger`, `load_fixture` come from `tests/conftest.py`. |
| `tests/test_ledger_fixtures.py` | Checked-in `.beancount` fixtures parse and drive the extractors. | Fixtures live in `tests/data/ledgers/*.beancount`; load them with `load_fixture("name")`. |
| `tests/integration/` | HTTP endpoints through a real Flask test client. | Use fixtures `ledger`, `ext`, `client`. The `client` fixture mirrors how Fava registers endpoints, so no running Fava is needed. Replace `ext._agent_runtime` with `StubRuntime(make_result(...))` so no LLM is called. |
| `tests/llm/` | The agent loop with a `MockProvider` (scripted `ChatResponse`s). | Inject via `ProviderRegistry.register("mock", provider)`; see `tests/llm/test_mock_agent.py`. |

Markers (`pytest.ini`): `unit`, `fixture`, `integration`, `llm`, `slow`. Note the `integration`
marker's description ("requires a running Fava instance") is stale — those tests run in-process.

When you fix a bug, **the test must fail against the previous commit.** Several past bugs had
tests that passed for the wrong reason (e.g. patching an object that the fix replaces, or a
fusion test that silently degraded to the BM25-only path). Assert the mechanism, not just the
outcome.

## How a request flows

```
FavaAI.js  --fetch-->  /chat (streaming)  ->  AgentRuntime.run_stream
                                                |-> ContextBuilder (system prompt + ledger summary + extra_context)
                                                |-> ProviderRegistry.get(...)  -> OpenAICompatProvider -> /v1/chat/completions
                                                `-> ToolRegistry.execute(...)  -> builtin tools (ledger, wiki, documents)
```

Endpoints are declared with `@extension_endpoint("<name>", methods=[...])` on the `FavaAI`
class (imported from `fava.ext`); the JS calls them as `/<name>`. Chat attachments are passed
as `file_ids` and injected as system context via `extra_context` (not into the user message or
the stored history).

## Common tasks

| Task | Touch these |
|---|---|
| Add a tool | New `BaseTool` subclass in `tools/builtin/`, register it in the module's `register_*` function, call that from `_init_components()`. Add a unit test; mention it in README "Built-in Tools". |
| Add an endpoint | `@extension_endpoint` in `__init__.py` + a JS caller + an integration test using the `client` fixture. |
| Add a config key | `DEFAULT_CONFIG`, the `_ALLOWED_*` set **and** `validate_config` in `config.py`, `ConfigManager.get_*_config`, the Config panel in `FavaAI.js` (`loadConfig`/`saveConfig`, with a `<label for=…>`), and README. |
| Add a UI element | `templates/FavaAI.html` (+ CSS using Fava theme variables) and `FavaAI.js`. Expect `tests/unit/test_ui_assets.py` to need updating; run `node --check FavaAI.js`. |
| Add a provider | Nothing: all vendors are `base_url` + `api_key` + `model` through `OpenAICompatProvider`. Extend `provider_base_url`/`resolve_provider_type` only for well-known default URLs. |
| Change the DB schema | Append a new entry to `MIGRATIONS` in `storage/schema.py` and bump `SCHEMA_VERSION`; add a migration test (`tests/unit/test_migrations.py`). |
| Change the FTS index layout | Bump `documents.store.SCHEMA_VERSION` so `initialize()` rebuilds the index from the raw chunk text; add a migration test. |
| Add a document format | `documents/extract.py` (status + error message), `SCAN_SUFFIXES` in `store.py`, and tests. Unsupported formats must degrade with a clear message, never silently. |

## Pitfalls that have already caused bugs

1. **Config is read live, but clients are built once.** `ConfigManager.get_*_config()` re-reads
   on every call, yet long-lived objects (provider clients, embedding client) are constructed at
   startup. Any new "read a setting into an object" wiring needs an explicit refresh path:
   `ProviderRegistry.reload()` and `FavaAI._refresh_embedder()` are called from `PUT /config`
   for exactly this reason. Forgetting it produces "saved successfully but nothing changed".
2. **Fava's `documents` option is not on `fava_options`.** On Fava 1.30 the value lives in the
   raw beancount options map: `ledger.options["documents"]` (a **list** — the option is
   repeatable), resolved with `ledger.join_path(...)`. The `fava_options.documents` attribute is
   only a fallback. Getting this wrong silently drops the folder.
3. **FTS5 does not segment CJK.** `unicode61` treats `记账软件测试` as one token, so `记账`
   matches nothing. CJK text is indexed per character and CJK queries become a phrase; stored
   chunk text stays verbatim so snippets and `read_document` are unaffected.
4. **CI does not validate the JS.** There is no `node --check` in CI — only substring assertions
   in `tests/unit/test_ui_assets.py`. Run `node --check FavaAI.js` after every JS edit.
5. **Python escapes are literal in Jinja2 templates.** A `\U0001f4ce` pasted into
   `FavaAI.html` renders as that text. Use HTML entities. A test guards this.
6. **Python 3.10 vs newer Werkzeug.** Multipart filenames can arrive as `bytes`; sanitize them
   (`sanitize_filename` decodes). Also always pass `encoding="utf-8"` to `write_text`/`open` —
   CI is UTF-8, contributors on Windows (cp1252) are not.
7. **Retrieval floor semantics.** `documents.hybrid_min_score` (default `0.2`) drops the dense
   ranking from RRF fusion when its best cosine is *below* it. It filters clearly-unrelated
   noise; it does **not** fix a small model that is confidently wrong (~0.55). Explicit
   `mode="dense"` requests bypass the floor. Don't describe it as "prevents bad hybrid results".
8. **`documents.enabled` gates folder indexing only**, not chat uploads (those stay available
   so the upload flow works out of the box). Don't gate uploads on it without deciding that
   deliberately.
9. **Static UI assertions are brittle by design.** `tests/unit/test_ui_assets.py` greps the JS
   for specific anchors (e.g. `<label for="${id}">`, `if (indexBtn)`). If you refactor those
   parts, update the tests in the same commit — they exist to catch exactly this kind of drift.
10. **Write to the ledger only through the guarded path.** Do not add a tool that opens a
    beancount file for writing; extend `FileDocumentTool` or propose the change explicitly.

## Conventions

- **Default branch is `implementation`** (there is no `main` locally; the workflow also accepts
  `main`). Branch from `implementation`, open a PR against it, keep CI green, wait for review.
- Commit messages: imperative subject, reference the issue (`(#20)`), and explain *why* when the
  change fixes a subtle bug. Use a heredoc for messages containing backticks.
- Reference issues in the PR body as `Closes #N` **on separate lines** — a comma-separated list
  only links the first.
- Keep dependencies minimal; a new runtime dependency needs a real justification
  (`pypdf` is the one exception for PDF text).
- Do not commit `.fava-ai/` state, keys, or anything ignored by `.gitignore`.

## Documentation upkeep (required)

If you add a feature or change behaviour, update the docs **in the same PR**:

- [ ] **`AGENTS.md` (this file)** — new subsystem, new invariant, new pitfall, new command, or a
      changed convention. This is the file the next agent reads first; leaving it stale is a bug.
- [ ] **`README.md`** — user-visible behaviour: new tool, config key, endpoint, UI affordance,
      dependency, or changed default.
- [ ] **`CHANGELOG.md`** — under `## [Unreleased]`, in `Added` / `Changed` / `Fixed`. Describe
      the user-visible effect, and be precise about limits (see the hybrid-floor example).
- [ ] **`docs/SECURITY.md`** — if you touch tool permissions, writes, secret handling, or the
      external-plugin loader.
- [ ] **`tests/unit/test_ui_assets.py`** — if you touch `FavaAI.html`/`FavaAI.js`.

## Definition of done

1. `.venv/bin/ruff check .` and `.venv/bin/mypy .` clean; `node --check FavaAI.js` if JS changed.
2. `.venv/bin/python -m pytest -q` green, plus `-m slow` if you touched the agent loop or stores.
3. New behaviour has a test that fails without the change; bug fixes assert the mechanism.
4. No secrets, internal hosts, or personal paths anywhere (the repo is public).
5. Docs updated per the checklist above.
6. `python -m build --wheel && python scripts/check_wheel.py` if you added/moved/renamed a
   package or a packaged asset (`FavaAI.js`, `templates/`).
