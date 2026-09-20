# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- CI workflow (GitHub Actions): ruff lint, mypy, pytest with coverage on Python 3.10–3.12.
- `dev` optional dependency group (`pip install -e ".[dev]"` now works).
- `LICENSE` (MIT) and `CHANGELOG.md`.
- `scripts/fetch_sample_ledgers.sh` to clone external sample Beancount ledgers for local analysis.
- `scripts/` directory for manual analysis and provider smoke-test scripts.
- Endpoint-level (Flask test client) test layer under `tests/integration/`.
- Agent error taxonomy (`agent/errors.py`): `NoProviderError`, `ProviderError`,
  `EmptyResponseError`, `ToolLoopError`, `LimitExceeded`, mapped to HTTP status codes.

### Changed
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
