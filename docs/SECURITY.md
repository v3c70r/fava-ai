# Security

Fava AI is designed as a **local, single-user** extension for [Fava](https://github.com/beancount/fava).
It is not a hardened multi-tenant service. This document describes the threat model
and the controls that are in place.

## Threat model

- **Trusted operator.** Whoever can edit the Beancount ledger or `.fava-ai/config.yaml`
  already controls the machine, so the config file is treated as trusted input.
- **Untrusted model output.** The LLM's answers and tool-call arguments are treated as
  untrusted: they can influence which tools run, but not read outside the ledger/wiki
  or execute arbitrary code.
- **The ledger is read-only.** No tool modifies Beancount files.
- **HTTP surface is Fava's.** All endpoints are served under Fava's own routes and inherit
  whatever authentication/reverse-proxy setup you run. Do not expose Fava directly to the
  public internet.

## Controls

### Path traversal
`WikiManager._safe_path` resolves every requested path and rejects anything that escapes
the wiki directory, including `..` segments, absolute paths, and symlinks that point
outside. Callers (`wiki_read`, `wiki_write`, `wiki_exists`, knowledge API) go through it.

### Model-influenced writes
- `wiki_write` refuses to overwrite auto-generated pages (`accounts/`, `merchants/`,
  `recurring/`, `portfolio/`, `patterns/`, `overview.md`, `index.md`, `log.md`,
  `AGENTS.md`) unless the model explicitly passes `overwrite=true`.
- All tool output fed back to the model is size-capped (`MAX_TOOL_ROWS` /
  `MAX_TOOL_CHARS` in `tools/builtin/ledger.py`) so a broad query cannot exhaust the
  context window or the provider budget.

### Configuration writes (`PUT /config`)
- The request body is validated with a strict allow-list (`config.validate_config`):
  known top-level keys, known provider names, known per-section keys, and type checks.
  Invalid documents are rejected with `400` and the file is left untouched.
- Masked secrets round-trip safely: `GET /config` returns `"***"` for API keys, and
  `PUT /config` restores the original value — including unresolved `${ENV_VAR}`
  references — instead of writing the mask back to disk.

### External tool plugins
Loading arbitrary Python from `.fava-ai/tools/` is **disabled by default**. Enable it
explicitly:

```yaml
tools:
  external_enabled: true
```

When enabled, those files execute with the same privileges as Fava. Only enable this if
you trust every file in that directory. The loader no longer mutates `sys.path`, and load
failures are logged rather than printed to stderr.

### Provider requests
- Provider connection checks use a 1-token completion with a short timeout, and results
  are cached. `POST /providers_test` refreshes the cache for a single provider.
- Provider errors are normalised into `ProviderError` and returned as `502`, avoiding
  leakage of raw provider payloads into the UI.

## Known limitations / non-goals

- No sandboxing of external tool plugins (opt-in, trusted code).
- No rate limiting or per-user quotas; single-user assumption.
- No encryption of `conversations.db` or `config.yaml` at rest — protect them with file
  permissions and keep `config.yaml` out of version control.
- The BQL tool executes read-only queries via beanquery; it is not a general SQL engine.

## Reporting

Open a private security advisory on the repository, or email the maintainers, rather than
filing a public issue for anything exploitable.
