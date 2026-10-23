# CLI reference

!!! note
    Auto-generated from `agentlab.cli.build_parser()`; do not edit. Run `uv run python scripts/gen_reference.py`.


```text
usage: agentlab [-h] {test,fork,conformance,fixture,serve,openapi,schema,import-otel} ...

Language-agnostic reliability testing for AI agents

positional arguments:
  {test,fork,conformance,fixture,serve,openapi,schema,import-otel}
    test                run a suite against a candidate (and optional baseline) and gate the
                        release
    fork                resume a stored trial from one of its checkpoints in a restored
                        environment
    conformance         check targets speak the wire protocol
    fixture             serve one environment standalone
    serve               serve the web console (runs experiments in the background)
    openapi             print the console's OpenAPI document (no database needed)
    schema              write protocol JSON Schemas
    import-otel         normalize an OTLP/JSON trace (observe-only)

options:
  -h, --help            show this help message and exit
```

## Environment variables

| Variable | Used by |
|---|---|
| `AGENTLAB_DATABASE_URL` | Postgres URL; default of `--database-url` |
| `OPENROUTER_API_KEY` | API key for LLM judges and the authoring assistant |
| `AGENTLAB_AUTHOR_MODEL` | Model for the authoring assistant |
| `AGENTLAB_CONCURRENCY` | Default of `--concurrency` |
| `AGENTLAB_FIXTURE_PORT` | Default of `--fixture-port` |
| `AGENTLAB_FIXTURE_BIND` | Default of `--fixture-bind` |
| `AGENTLAB_FIXTURE_URL` | Default of `--fixture-url` |
| `AGENTLAB_CONSOLE_TOKEN` | Default of `serve --token` (bearer token for `/v1`) |
| `AGENTLAB_CONSOLE_HOSTS` | Comma-separated default of `serve --allow-host` |
| `AGENTLAB_ALLOW_NO_TOKEN` | `1` makes `serve --allow-no-token` the default |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | PASS (gate decision) |
| 1 | BLOCK (gate decision) |
| 2 | INSUFFICIENT_EVIDENCE (gate decision) |
| 3 | Usage, configuration or infrastructure error |

`conformance` exits 1 when a target fails the protocol checks.

## `agentlab test`

```text
usage: agentlab test [-h] --candidate CANDIDATE [--baseline BASELINE]
                     [--max-regression MAX_REGRESSION] [--targets TARGETS]
                     [--environments ENVIRONMENTS] [--database-url DATABASE_URL]
                     [--concurrency CONCURRENCY] [--deadline-ms DEADLINE_MS]
                     [--fixture-port FIXTURE_PORT] [--fixture-bind FIXTURE_BIND]
                     [--fixture-url FIXTURE_URL] [--repeats REPEATS] [--report-dir REPORT_DIR]
                     suite

positional arguments:
  suite                 scenario YAML file or directory

options:
  -h, --help            show this help message and exit
  --candidate CANDIDATE
  --baseline BASELINE
  --max-regression MAX_REGRESSION
                        allowed pass-rate drop vs baseline (0-1)
  --targets TARGETS
  --environments ENVIRONMENTS
                        directory of environment specs
  --database-url DATABASE_URL
                        Postgres URL (default $AGENTLAB_DATABASE_URL)
  --concurrency CONCURRENCY
  --deadline-ms DEADLINE_MS
  --fixture-port FIXTURE_PORT
  --fixture-bind FIXTURE_BIND
  --fixture-url FIXTURE_URL
                        fixture base URL as seen by agents (default http://127.0.0.1:PORT)
  --repeats REPEATS
  --report-dir REPORT_DIR
```

## `agentlab fork`

```text
usage: agentlab fork [-h] --checkpoint CHECKPOINT [--target TARGET] [--faults {none,scenario}]
                     [--targets TARGETS] [--environments ENVIRONMENTS]
                     [--database-url DATABASE_URL] [--concurrency CONCURRENCY]
                     [--deadline-ms DEADLINE_MS] [--fixture-port FIXTURE_PORT]
                     [--fixture-bind FIXTURE_BIND] [--fixture-url FIXTURE_URL] [--repeats REPEATS]
                     [--report-dir REPORT_DIR]
                     trial_id

positional arguments:
  trial_id

options:
  -h, --help            show this help message and exit
  --checkpoint CHECKPOINT
  --target TARGET       target to resume (default: the source trial's target)
  --faults {none,scenario}
                        none = counterfactual without the scenario's faults
  --targets TARGETS
  --environments ENVIRONMENTS
                        directory of environment specs
  --database-url DATABASE_URL
                        Postgres URL (default $AGENTLAB_DATABASE_URL)
  --concurrency CONCURRENCY
  --deadline-ms DEADLINE_MS
  --fixture-port FIXTURE_PORT
  --fixture-bind FIXTURE_BIND
  --fixture-url FIXTURE_URL
                        fixture base URL as seen by agents (default http://127.0.0.1:PORT)
  --repeats REPEATS
  --report-dir REPORT_DIR
```

## `agentlab conformance`

```text
usage: agentlab conformance [-h] [--targets TARGETS] names [names ...]

positional arguments:
  names

options:
  -h, --help         show this help message and exit
  --targets TARGETS
```

## `agentlab fixture`

```text
usage: agentlab fixture [-h] [--environment ENVIRONMENT] [--environments ENVIRONMENTS]
                        [--port PORT] [--bind BIND] [--database-url DATABASE_URL]

options:
  -h, --help            show this help message and exit
  --environment ENVIRONMENT
                        environment key (id@version)
  --environments ENVIRONMENTS
                        directory of environment specs
  --port PORT
  --bind BIND
  --database-url DATABASE_URL
```

## `agentlab serve`

```text
usage: agentlab serve [-h] [--port PORT] [--bind BIND] [--suite SUITE] [--token TOKEN]
                      [--allowed-host ALLOWED_HOST] [--allow-no-token] [--targets TARGETS]
                      [--environments ENVIRONMENTS] [--database-url DATABASE_URL]
                      [--concurrency CONCURRENCY] [--deadline-ms DEADLINE_MS]
                      [--fixture-port FIXTURE_PORT] [--fixture-bind FIXTURE_BIND]
                      [--fixture-url FIXTURE_URL]

options:
  -h, --help            show this help message and exit
  --port PORT
  --bind BIND
  --suite SUITE         scenario YAML file or directory
  --token TOKEN         bearer token for /v1
  --allowed-host ALLOWED_HOST
                        extra Host header value the console accepts (repeatable; default localhost
                        and 127.0.0.1)
  --allow-no-token      allow a non-loopback bind without a token; only when exposure is
                        restricted elsewhere (e.g. a container port published on 127.0.0.1)
  --targets TARGETS
  --environments ENVIRONMENTS
                        directory of environment specs
  --database-url DATABASE_URL
                        Postgres URL (default $AGENTLAB_DATABASE_URL)
  --concurrency CONCURRENCY
  --deadline-ms DEADLINE_MS
  --fixture-port FIXTURE_PORT
  --fixture-bind FIXTURE_BIND
  --fixture-url FIXTURE_URL
                        fixture base URL as seen by agents (default http://127.0.0.1:PORT)
```

## `agentlab openapi`

```text
usage: agentlab openapi [-h]

options:
  -h, --help  show this help message and exit
```

## `agentlab schema`

```text
usage: agentlab schema [-h] [--out OUT]

options:
  -h, --help  show this help message and exit
  --out OUT
```

## `agentlab import-otel`

```text
usage: agentlab import-otel [-h] file

positional arguments:
  file

options:
  -h, --help  show this help message and exit
```
