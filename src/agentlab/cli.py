"""agentlab CLI. Exit codes for CI: 0 PASS, 1 BLOCK, 2 INSUFFICIENT_EVIDENCE, 3 usage/config error."""

import argparse
import json
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from agentlab import report
from agentlab.client import HarnessClient, load_targets
from agentlab.fixture import Fixture, create_app, serve_in_thread
from agentlab.gate import decide
from agentlab.otel import parse_otlp
from agentlab.protocol import AgentLabError, Environment, ErrorCode, InvokeRequest, json_schemas
from agentlab.runner import RunConfig, run_experiment
from agentlab.scenario import load_suite
from agentlab.store import Store

EXIT = {"PASS": 0, "BLOCK": 1, "INSUFFICIENT_EVIDENCE": 2}


def cmd_test(a: argparse.Namespace) -> int:
    scenarios = load_suite(a.suite)
    targets, allowed = load_targets(a.targets)
    names = [a.candidate] + ([a.baseline] if a.baseline else [])
    if missing := [n for n in names if n not in targets]:
        raise ValueError(f"unknown target(s): {', '.join(missing)}")

    fixture = Fixture()
    server = serve_in_thread(create_app(fixture), a.fixture_port, a.fixture_bind)
    try:
        store = Store(a.db)
        cfg = RunConfig(fixture_url=a.fixture_url or f"http://127.0.0.1:{a.fixture_port}", repeats=a.repeats, deadline_ms=a.deadline_ms)
        exp_id = run_experiment(store, fixture, scenarios, [targets[n] for n in names], allowed, cfg)
    finally:
        server.should_exit = True

    trials = store.trials(exp_id)
    decision = decide(trials, [s.key for s in scenarios], a.candidate, a.baseline, a.max_regression)
    store.set_decision(exp_id, decision)
    out = Path(a.report_dir) / f"{exp_id}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.render(store.experiment(exp_id), trials))
    print_summary(exp_id, decision, out)
    return EXIT[decision["status"]]


def print_summary(exp_id: str, d: dict, report_path: Path) -> None:
    print(f"\nexperiment {exp_id}")
    for name, s in d["stats"].items():
        rate = "n/a" if s["pass_rate"] is None else f"{s['pass_rate']:.0%} [{s['ci95'][0]:.0%}, {s['ci95'][1]:.0%}]"
        print(f"  {name:<14} passed {s['passed']}/{s['graded']}  rate {rate}  errors {s['errors']}")
    if d["paired"]:
        print(f"  paired: {d['paired']['regressions']} regression(s), {d['paired']['fixes']} fix(es) over {d['paired']['pairs']} pair(s)")
    print(f"\nDECISION: {d['status']}")
    for label, key in (("block", "block_reasons"), ("insufficient", "insufficient_reasons"), ("coverage gap", "coverage_gaps")):
        for r in d[key]:
            print(f"  - [{label}] {r}")
    print(f"\nreport: {report_path}")


def cmd_conformance(a: argparse.Namespace) -> int:
    """Protocol smoke test: manifest validates and a no-op invoke returns a schema-valid response."""
    targets, allowed = load_targets(a.targets)
    ok = True
    for name in a.names:
        try:
            client = HarnessClient(targets[name], allowed)
            m = client.manifest()
            if m.capabilities.invoke:
                resp = client.invoke(InvokeRequest(
                    trial_id=f"conformance:{name}", scenario_version="conformance@1", system_version="conformance",
                    environment=Environment(id="none", base_url="http://127.0.0.1:9"), idempotency_key=f"conformance:{name}",
                    input={"message": "hello"}, deadline_ms=10_000,
                ))
                seqs = [e.seq for e in resp.events]
                if seqs != sorted(set(seqs)):
                    raise AgentLabError(ErrorCode.TRACE_INCOMPLETE, f"event seq not strictly increasing: {seqs}")
            print(f"PASS {name}: {m.language}/{m.framework} protocol {m.protocol_version} capabilities {m.capabilities.model_dump()}")
        except (AgentLabError, KeyError) as exc:
            ok = False
            print(f"FAIL {name}: {exc}")
    return 0 if ok else 1


def cmd_fixture(a: argparse.Namespace) -> int:
    server = serve_in_thread(create_app(Fixture()), a.port, a.bind)
    print(f"fixture on http://{a.bind}:{a.port}  (POST /admin/reset, GET /admin/state)")
    try:
        while not server.should_exit:
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.should_exit = True
    return 0


def cmd_schema(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, schema in json_schemas().items():
        (out / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n")
    print(f"wrote {len(json_schemas())} schemas to {out}")
    return 0


def cmd_import_otel(a: argparse.Namespace) -> int:
    events = parse_otlp(json.loads(Path(a.file).read_text()))
    print(json.dumps({"capabilities": {"invoke": False, "observe": "otel_partial"},
                      "events": [e.model_dump(mode="json") for e in events]}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agentlab", description="Language-agnostic reliability testing for AI agents")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("test", help="run a suite against a candidate (and optional baseline) and gate the release")
    t.add_argument("suite", help="scenario YAML file or directory")
    t.add_argument("--candidate", required=True)
    t.add_argument("--baseline")
    t.add_argument("--targets", default="targets.yaml")
    t.add_argument("--repeats", type=int, default=1)
    t.add_argument("--max-regression", type=float, default=0.0, help="allowed pass-rate drop vs baseline (0-1)")
    t.add_argument("--deadline-ms", type=int, default=60_000)
    t.add_argument("--fixture-port", type=int, default=8900)
    t.add_argument("--fixture-bind", default="127.0.0.1")
    t.add_argument("--fixture-url", help="fixture URL as seen by agents (default http://127.0.0.1:PORT)")
    t.add_argument("--db", default=".agentlab/agentlab.db")
    t.add_argument("--report-dir", default=".agentlab/reports")
    t.set_defaults(fn=cmd_test)

    c = sub.add_parser("conformance", help="check targets speak the wire protocol")
    c.add_argument("names", nargs="+")
    c.add_argument("--targets", default="targets.yaml")
    c.set_defaults(fn=cmd_conformance)

    f = sub.add_parser("fixture", help="serve the reference refund environment standalone")
    f.add_argument("--port", type=int, default=8900)
    f.add_argument("--bind", default="127.0.0.1")
    f.set_defaults(fn=cmd_fixture)

    s = sub.add_parser("schema", help="write protocol JSON Schemas")
    s.add_argument("--out", default="protocol")
    s.set_defaults(fn=cmd_schema)

    o = sub.add_parser("import-otel", help="normalize an OTLP/JSON trace (observe-only)")
    o.add_argument("file")
    o.set_defaults(fn=cmd_import_otel)

    try:
        a = p.parse_args(argv)
    except SystemExit as exc:  # argparse exits 2, which would read as INSUFFICIENT_EVIDENCE in CI
        return 0 if exc.code == 0 else 3
    if getattr(a, "repeats", 1) < 1:
        print("error: --repeats must be >= 1", file=sys.stderr)
        return 3
    try:
        return a.fn(a)
    except (ValueError, ValidationError, FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
