"""agentlab CLI. Exit codes for CI: 0 PASS, 1 BLOCK, 2 INSUFFICIENT_EVIDENCE, 3 usage/config/infrastructure error."""

import argparse
import ipaddress
import json
import os
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import uvicorn
from pydantic import ValidationError

from agentlab import report
from agentlab.client import HarnessClient, load_targets
from agentlab.console import LOCAL_HOSTS, Console, create_console, openapi_schema
from agentlab.db import database_url, open_pool
from agentlab.fixture import SHARED_ENV, FixturePool, Seed, create_app, serve_in_thread
from agentlab.jobs import Jobs
from agentlab.models import Decision
from agentlab.otel import parse_otlp
from agentlab.protocol import AgentLabError, Environment, ErrorCode, InvokeRequest, json_schemas
from agentlab.runner import RunConfig, Runner
from agentlab.scenario import load_suite
from agentlab.store import Store

EXIT = {"PASS": 0, "BLOCK": 1, "INSUFFICIENT_EVIDENCE": 2}
USAGE_ERROR = 3


@contextmanager
def session(a: argparse.Namespace) -> Generator[Runner]:
    """Database pool + fixture service + runner for one command."""
    db = open_pool(database_url(a.database_url), max_size=a.concurrency * 2 + 4)
    server = None
    try:
        pool = FixturePool(db)
        server = serve_in_thread(create_app(pool), a.fixture_port, a.fixture_bind)
        _, allowed = load_targets(a.targets)
        cfg = RunConfig(
            fixture_url=a.fixture_url or f"http://127.0.0.1:{a.fixture_port}",
            deadline_ms=a.deadline_ms,
            concurrency=a.concurrency,
        )
        yield Runner(Store(db), pool, allowed, cfg)
    finally:
        if server:
            server.should_exit = True
        db.close()


def finish(runner: Runner, exp_id: str, report_dir: str) -> int:
    decision = runner.conclude(exp_id)
    out = Path(report_dir) / f"{exp_id}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.render(runner.store.experiment(exp_id), runner.store.trials(exp_id)))
    print_summary(exp_id, decision, out)
    return EXIT[decision.status]


def print_summary(exp_id: str, d: Decision, report_path: Path) -> None:
    print(f"\nexperiment {exp_id}")
    for name, s in d.stats.items():
        rate = "n/a" if s.pass_rate is None else f"{s.pass_rate:.0%} [{s.ci95[0]:.0%}, {s.ci95[1]:.0%}]"
        cost = f"  cost ${s.cost_usd:.4f}" if s.cost_usd is not None else ""
        print(f"  {name:<24} passed {s.passed}/{s.graded}  rate {rate}  errors {s.errors}{cost}")
    if d.paired:
        print(f"  paired: {d.paired.regressions} regression(s), {d.paired.fixes} fix(es) over {d.paired.pairs} pair(s)")
    print(f"\nDECISION: {d.status}")
    for label, reasons in (
        ("block", d.block_reasons),
        ("insufficient", d.insufficient_reasons),
        ("coverage gap", d.coverage_gaps),
    ):
        for r in reasons:
            print(f"  - [{label}] {r}")
    print(f"\nreport: {report_path}")


def cmd_test(a: argparse.Namespace) -> int:
    scenarios = load_suite(a.suite)
    targets, _ = load_targets(a.targets)
    names = [a.candidate] + ([a.baseline] if a.baseline else [])
    if missing := [n for n in names if n not in targets]:
        raise ValueError(f"unknown target(s): {', '.join(missing)}")
    with session(a) as runner:
        exp_id = runner.run_experiment(
            scenarios,
            [targets[n] for n in names],
            repeats=a.repeats,
            candidate=a.candidate,
            baseline=a.baseline,
            max_regression=a.max_regression,
        )
        return finish(runner, exp_id, a.report_dir)


def cmd_fork(a: argparse.Namespace) -> int:
    targets, _ = load_targets(a.targets)
    with session(a) as runner:
        source = runner.store.trial(a.trial_id)
        name = a.target or source.target
        if name not in targets:
            raise ValueError(f"unknown target: {name}")
        experiment = runner.store.experiment(source.experiment_id)
        exp_id = runner.fork(source, experiment, targets[name], a.checkpoint, a.faults)
        return finish(runner, exp_id, a.report_dir)


def cmd_conformance(a: argparse.Namespace) -> int:
    """Protocol smoke test: manifest validates and a no-op invoke returns a schema-valid response."""
    targets, allowed = load_targets(a.targets)
    ok = True
    for name in a.names:
        try:
            client = HarnessClient(targets[name], allowed)
            m = client.manifest()
            if m.capabilities.invoke:
                resp = client.invoke(
                    InvokeRequest(
                        trial_id=f"conformance:{name}",
                        scenario_version="conformance@1",
                        system_version="conformance",
                        environment=Environment(id="none", base_url="http://127.0.0.1:9/env/none"),
                        idempotency_key=f"conformance:{name}",
                        input={"message": "hello"},
                        deadline_ms=60_000,
                    )
                )
                seqs = [e.seq for e in resp.events]
                if seqs != sorted(set(seqs)):
                    raise AgentLabError(ErrorCode.TRACE_INCOMPLETE, f"event seq not strictly increasing: {seqs}")
            print(
                f"PASS {name}: {m.language}/{m.framework} protocol {m.protocol_version} "
                f"capabilities {m.capabilities.model_dump()}"
            )
        except (AgentLabError, KeyError) as exc:
            ok = False
            print(f"FAIL {name}: {exc}")
    return 0 if ok else 1


def cmd_fixture(a: argparse.Namespace) -> int:
    db = open_pool(database_url(a.database_url))
    pool = FixturePool(db)
    pool.create(SHARED_ENV, Seed())
    server = serve_in_thread(create_app(pool, admin=True), a.port, a.bind)
    print(f"fixture on http://{a.bind}:{a.port}/env/<id>  (POST /env/<id>/admin/reset, GET /env/<id>/admin/state)")
    try:
        while not server.should_exit:
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.should_exit = True
    finally:
        pool.drop(SHARED_ENV)
        db.close()
    return 0


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def cmd_serve(a: argparse.Namespace) -> int:
    if not a.token and not is_loopback(a.bind) and not a.allow_no_token:
        raise ValueError(
            f"refusing to bind {a.bind} without a token: pass --token or set AGENTLAB_CONSOLE_TOKEN "
            "(inside a container whose port is published only on host loopback, use --allow-no-token)"
        )
    with session(a) as runner:
        jobs = Jobs(runner)
        try:
            app = create_console(
                Console(runner=runner, jobs=jobs, targets_path=a.targets, suite_path=a.suite, token=a.token),
                allowed_hosts=[*LOCAL_HOSTS, *a.allowed_host],
            )
            uvicorn.run(app, host=a.bind, port=a.port, log_level="info")
        finally:
            jobs.shutdown()
    return 0


def cmd_openapi(_: argparse.Namespace) -> int:
    print(json.dumps(openapi_schema(), indent=2))
    return 0


def cmd_schema(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    schemas = json_schemas()
    for name, schema in schemas.items():
        (out / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n")
    print(f"wrote {len(schemas)} schemas to {out}")
    return 0


def cmd_import_otel(a: argparse.Namespace) -> int:
    events = parse_otlp(json.loads(Path(a.file).read_text()))
    print(
        json.dumps(
            {
                "capabilities": {"invoke": False, "observe": "otel_partial"},
                "events": [e.model_dump(mode="json") for e in events],
            },
            indent=2,
        )
    )
    return 0


def _fixture_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--targets", default="targets.yaml")
    p.add_argument("--database-url", help="Postgres URL (default $AGENTLAB_DATABASE_URL)")
    p.add_argument("--concurrency", type=int, default=int(os.environ.get("AGENTLAB_CONCURRENCY", "4")))
    p.add_argument("--deadline-ms", type=int, default=120_000)
    p.add_argument("--fixture-port", type=int, default=int(os.environ.get("AGENTLAB_FIXTURE_PORT", "8900")))
    p.add_argument("--fixture-bind", default=os.environ.get("AGENTLAB_FIXTURE_BIND", "127.0.0.1"))
    p.add_argument(
        "--fixture-url",
        default=os.environ.get("AGENTLAB_FIXTURE_URL"),
        help="fixture base URL as seen by agents (default http://127.0.0.1:PORT)",
    )


def _run_flags(p: argparse.ArgumentParser) -> None:
    _fixture_flags(p)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--report-dir", default=".agentlab/reports")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentlab", description="Language-agnostic reliability testing for AI agents")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("test", help="run a suite against a candidate (and optional baseline) and gate the release")
    t.add_argument("suite", help="scenario YAML file or directory")
    t.add_argument("--candidate", required=True)
    t.add_argument("--baseline")
    t.add_argument("--max-regression", type=float, default=0.0, help="allowed pass-rate drop vs baseline (0-1)")
    _run_flags(t)
    t.set_defaults(fn=cmd_test)

    f = sub.add_parser("fork", help="resume a stored trial from one of its checkpoints in a restored environment")
    f.add_argument("trial_id")
    f.add_argument("--checkpoint", required=True)
    f.add_argument("--target", help="target to resume (default: the source trial's target)")
    f.add_argument(
        "--faults",
        choices=["none", "scenario"],
        default="none",
        help="none = counterfactual without the scenario's faults",
    )
    _run_flags(f)
    f.set_defaults(fn=cmd_fork)

    c = sub.add_parser("conformance", help="check targets speak the wire protocol")
    c.add_argument("names", nargs="+")
    c.add_argument("--targets", default="targets.yaml")
    c.set_defaults(fn=cmd_conformance)

    fx = sub.add_parser("fixture", help="serve the refund environment standalone")
    fx.add_argument("--port", type=int, default=8900)
    fx.add_argument("--bind", default="127.0.0.1")
    fx.add_argument("--database-url")
    fx.set_defaults(fn=cmd_fixture)

    sv = sub.add_parser("serve", help="serve the web console (runs experiments in the background)")
    sv.add_argument("--port", type=int, default=8800)
    sv.add_argument("--bind", default="127.0.0.1")
    sv.add_argument("--suite", default="scenarios", help="scenario YAML file or directory")
    sv.add_argument("--token", default=os.environ.get("AGENTLAB_CONSOLE_TOKEN"), help="bearer token for /v1")
    sv.add_argument(
        "--allowed-host",
        action="append",
        default=[h for h in os.environ.get("AGENTLAB_CONSOLE_HOSTS", "").split(",") if h],
        help="extra Host header value the console accepts (repeatable; default localhost and 127.0.0.1)",
    )
    sv.add_argument(
        "--allow-no-token",
        action="store_true",
        default=os.environ.get("AGENTLAB_ALLOW_NO_TOKEN") == "1",
        help="allow a non-loopback bind without a token; only when exposure is restricted elsewhere "
        "(e.g. a container port published on 127.0.0.1)",
    )
    _fixture_flags(sv)
    sv.set_defaults(fn=cmd_serve)

    oa = sub.add_parser("openapi", help="print the console's OpenAPI document (no database needed)")
    oa.set_defaults(fn=cmd_openapi)

    sc = sub.add_parser("schema", help="write protocol JSON Schemas")
    sc.add_argument("--out", default="protocol")
    sc.set_defaults(fn=cmd_schema)

    o = sub.add_parser("import-otel", help="normalize an OTLP/JSON trace (observe-only)")
    o.add_argument("file")
    o.set_defaults(fn=cmd_import_otel)
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        a = build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse exits 2, which would read as INSUFFICIENT_EVIDENCE in CI
        return 0 if exc.code == 0 else USAGE_ERROR
    if getattr(a, "repeats", 1) < 1 or getattr(a, "concurrency", 1) < 1:
        print("error: --repeats and --concurrency must be >= 1", file=sys.stderr)
        return USAGE_ERROR
    try:
        return a.fn(a)
    except (ValueError, ValidationError, KeyError, OSError, AgentLabError, psycopg.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return USAGE_ERROR


if __name__ == "__main__":
    sys.exit(main())
