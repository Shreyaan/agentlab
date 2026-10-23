# Security

AgentLab runs scenarios that mutate state, executes SQL from spec files, and sends evidence to third-party models. This page lists the controls that exist in code, the escapes they are tested against, and the limits. Defaults are built for a developer's machine: loopback only.

## Allowed hosts

Only hosts listed in `allowed_hosts` in `targets.yaml` may receive scenarios (default: `127.0.0.1`, `localhost`, `::1`). The check compares the hostname of the target URL. Any other host fails with `UNSAFE_TARGET`, because scenarios mutate state and must never reach a non-test endpoint. `otel` targets have no URL and are never invoked. Saving a target through the console API also refuses a host outside the list.

## Console access

`agentlab serve` is protected by four independent controls.

| Control | What it does |
|---|---|
| **Bearer token** | Set `--token` or `AGENTLAB_CONSOLE_TOKEN`. Every `/v1` route, including `/v1/author`, then requires `Authorization: Bearer <token>`, compared in constant time. Without a token the API is open |
| **Refuses unsafe binds** | `serve` refuses a non-loopback `--bind` without a token, unless you pass `--allow-no-token` (or `AGENTLAB_ALLOW_NO_TOKEN=1`). Use that only when exposure is restricted elsewhere, for example a container port published on host loopback, as in `docker-compose.yml` |
| **CSRF header** | Every write (`POST`, `PUT`, `DELETE`) needs `X-AgentLab-Request: 1`, otherwise `403`. A custom header forces a CORS preflight, which is never granted: the console sets no CORS headers and is same-origin only |
| **Trusted hosts** | Requests whose `Host` header is not `localhost` or `127.0.0.1` are rejected, which stops DNS rebinding from turning a hostile website into a same-origin client. Add names with `--allowed-host` (repeatable) or `AGENTLAB_CONSOLE_HOSTS` (comma-separated) |

The console UI keeps the token in `sessionStorage` for that browser tab only.

```bash
AGENTLAB_CONSOLE_TOKEN=$(openssl rand -hex 32) uv run agentlab serve --bind 0.0.0.0 --allowed-host agentlab.internal
curl -H "Authorization: Bearer $AGENTLAB_CONSOLE_TOKEN" http://127.0.0.1:8800/v1/info
```

There is **no TLS**: put a reverse proxy in front for any remote use. The token is a single shared secret with no users or roles, and anyone holding it can start runs, edit target, scenario and environment files on the server, and spend the server's `OPENROUTER_API_KEY`.

## The environment service

Agents call the environment service (default port 8900, `--fixture-bind` 127.0.0.1). It has **no authentication**.

- The runner's server exposes only tool routes (`/env/<id>/tools`, `/env/<id>/tools/{name}` and `/env/<id>/mcp`). The `reset` and `state` admin routes exist **only** on the standalone `agentlab fixture` server. Agents under test share the runner's server, so otherwise an agent could wipe its own evidence or read other environments.
- Per-trial environment ids are random (16 hex characters). They are not secrets: do not expose the port to untrusted networks.
- Keep it on localhost unless network controls are in place.

## Sandboxed SQL

Environment and scenario files contain SQL. It runs under three separate Postgres identities, none of which can reach another's privileges:

| Identity | Runs | Limits |
|---|---|---|
| Owner (the pool's role) | Schema setup, ledger and idempotency writes | AgentLab's own code only |
| Writer (`agentlab_w_<id>`) | Tool SQL (rules and effects) | DML on the environment's tables. 5 s statement timeout |
| Reader (`agentlab_r_<id>`) | `sql` checks, `truth_sql`, the console's **Test query** | `SELECT` on the environment's tables and the ledger. Read-only transaction, 5 s statement timeout |

Both roles are `LOGIN NOINHERIT` with a random 32-byte password generated per trial and a connection limit of 4, and are dropped with the schema. Because they are *login* roles, a statement cannot shed their privileges for the owner's. The writer's grants are issued before the runtime tables exist, so `ALL TABLES` can never include the ledger or the idempotency table.

The test suite (`tests/test_fixture.py`) runs hostile SQL against these roles and asserts each attempt fails with a database error and leaves state untouched:

- reading or deleting the ledger, reading or writing the idempotency table;
- reading the results store (`agentlab.trials`);
- reading another trial's schema;
- `TRUNCATE`, `CREATE TABLE`, and calling a ledger sequence;
- `SET ROLE NONE`, `RESET ROLE`, and `set_config('role', ...)`;
- nested SQL through `query_to_xml(...)` that tries any of the above (it still executes as the restricted role);
- multiple statements in one tool or check (a tool with two statements is rejected; check SQL is one prepared statement wrapped as a subquery).

Tool **parameters** are bound by the driver and never interpolated, so `ORD-1'; DELETE FROM orders; --` is just a string that matches nothing.

!!! warning "Honest limits of the sandbox"
    The roles are real Postgres roles created on your server, so AgentLab's database user needs the privilege to create them: run it against a dedicated Postgres, not one that holds data you care about. The sandbox is tested against specific escapes; it is not a promise against every possible one. Treat environment and scenario files as code you review, and do not load untrusted ones.

## Redaction

Everything is scrubbed **before it is written to Postgres**, and before evidence is sent to a judge. It is a backstop, not the primary control: keep credentials out of recorded data in the first place.

| What | Replaced with `[REDACTED]` |
|---|---|
| Values under secret-looking keys: any key containing `secret`, `token`, `password`, `authorization`, `api_key` / `api-key` / `apikey`, `cookie` (case-insensitive) | The value, unless it is a number or null (so `input_tokens` survives) |
| URL query parameters whose name contains `token`, `key`, `secret`, `sig` or `password` | The value, up to the next `&`, whitespace or quote |
| Credentials in URLs (`scheme://user:pass@host`) | Everything up to the last `@` before the next `/` or whitespace |
| Bearer tokens in free text | The token |
| Common API key formats: `sk-`, `pk-`, `rk-` prefixes (16+ characters), GitHub `ghp_`-style tokens, AWS `AKIA...` keys | The key |

The same scrubbing applies to persisted experiments, trials, decisions and canary results, to error messages shown by the console, and to the evidence a judge receives.

## Judge injection defences

The agent's reply is attacker-controlled text from a judge's point of view. Evidence is framed as untrusted, chat judges are restricted on critical checks, and decision models are used by default. Details and the measured result are in [Judges](../concepts/judges.md#untrusted-evidence).

## Data that leaves your machine

- **Judges:** the (redacted, size-capped) evidence of every decision check goes to OpenRouter.
- **Authoring:** the description you type, and the environment spec, go to the author model through OpenRouter.
- **Example agents:** they call OpenRouter.

Do not put secrets or customer data in scenarios, descriptions or seeds.

## Hardening checklist

- Keep `allowed_hosts` to the test endpoints you own.
- Run `serve` on loopback. For remote use: a token, a TLS reverse proxy, `--allowed-host` for the public name, and network restrictions.
- Keep the environment service port (8900) off untrusted networks.
- Use a dedicated Postgres and a real password (the compose password is a local-dev value).
- Review environment and scenario files like code; keep them in git.
- Use the Docker image or Node CLI if you want the runner as an unprivileged container user (uid 10001).
- Never put credentials in scenario `input`, seed rows or tool descriptions.
