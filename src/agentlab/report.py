"""Self-contained static HTML release report: inline CSS, no JS, every data value escaped."""

import json
from html import escape

CSS = """
:root{--bg:#f7f7f8;--fg:#1b1d21;--mut:#6b7280;--card:#fff;--line:#e3e5e8;--ok:#177a3c;--ok-bg:#dff5e6;
--bad:#b42318;--bad-bg:#fde4e1;--warn:#9a6700;--warn-bg:#fff1cc;--off:#555;--off-bg:#ececef}
@media(prefers-color-scheme:dark){:root{--bg:#141517;--fg:#e8e9eb;--mut:#9aa0a8;--card:#1c1e22;--line:#2d3036;
--ok:#5fd68a;--ok-bg:#12331f;--bad:#ff8a80;--bad-bg:#3d1714;--warn:#f2c14e;--warn-bg:#3a2d0a;--off:#b4b8bf;--off-bg:#2a2d33}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:1.4rem;margin:0}h2{font-size:1.05rem;margin:28px 0 8px}h3{font-size:.85rem;margin:14px 0 4px;color:var(--mut)}
code,pre,td.m,.m{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
pre{margin:0;white-space:pre-wrap;word-break:break-word}
.sub{color:var(--mut)}
.banner{border-radius:8px;padding:14px 16px;margin-top:16px}
.banner .big{font-size:1.6rem;font-weight:700}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--card)}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:5px 9px;border-bottom:1px solid var(--line);vertical-align:top;white-space:nowrap}
td.w{white-space:normal;min-width:220px}
th{font-size:.75rem;color:var(--mut);text-transform:uppercase}
tr:last-child td{border-bottom:0}
details{background:var(--card);border:1px solid var(--line);border-radius:6px;margin:6px 0;padding:6px 10px}
summary{cursor:pointer}
.badge{display:inline-block;padding:0 7px;border-radius:9px;font-size:.75rem;font-weight:600}
.pass,.passed{color:var(--ok);background:var(--ok-bg)}
.fail,.failed,.error,.BLOCK{color:var(--bad);background:var(--bad-bg)}
.unsupported,.INSUFFICIENT_EVIDENCE,.running{color:var(--warn);background:var(--warn-bg)}
.PASS{color:var(--ok);background:var(--ok-bg)}
.none{color:var(--off);background:var(--off-bg)}
.add{background:var(--ok-bg);color:var(--ok)}.rm{background:var(--bad-bg);color:var(--bad)}
.add,.rm{padding:1px 6px;margin:2px 0;border-radius:3px}
"""


def e(v) -> str:
    return escape(str(v))


def compact(v) -> str:
    return json.dumps(v, default=str, separators=(",", ":"))


def badge(label, cls=None) -> str:
    return f'<span class="badge {e(cls or label)}">{e(label)}</span>'


def table(headers: list[str], rows: list[list[str]]) -> str:
    """Cells are raw HTML; callers escape."""
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table><tr>{head}</tr>{body}</table></div>'


def kv(row: dict) -> str:
    return e(" ".join(f"{k}={compact(v) if isinstance(v, (dict, list)) else v}" for k, v in row.items()))


def bullets(title: str, items: list[str]) -> str:
    return f"<h3>{e(title)}</h3><ul>{''.join(f'<li>{e(i)}</li>' for i in items)}</ul>" if items else ""


def pct(x) -> str:
    return "-" if x is None else f"{x:.0%}"


def ms(x) -> str:
    return "-" if x is None else f"{x:.0f} ms"


def banner(d: dict | None) -> str:
    if not d:
        return '<div class="banner none"><div class="big">NO DECISION</div>No release decision has been recorded.</div>'
    vs = f"candidate <b>{e(d['candidate'])}</b> vs baseline <b>{e(d['baseline'] or 'none')}</b>"
    return (f'<div class="banner {e(d["status"])}"><div class="big">{e(d["status"])}</div>{vs}'
            + bullets("Block reasons", d["block_reasons"]) + bullets("Insufficient evidence", d["insufficient_reasons"])
            + bullets("Coverage gaps", d["coverage_gaps"]) + "</div>"
            '<p class="sub">An offline gate is evidence, not proof of production safety.</p>')


def targets_section(meta: dict, decision: dict | None) -> str:
    stats = (decision or {}).get("stats", {})
    rows = []
    for name, t in meta.get("targets", {}).items():
        m = t.get("manifest")
        caps = (m or {}).get("capabilities", {})
        s = stats.get(name)
        lo, hi = s["ci95"] if s else (None, None)
        rows.append([e(name), e(t.get("mode")), e(f"{m['language']}/{m['adapter_id']}" if m else "unreachable"),
                     e(t.get("version")),
                     e(f"observe={caps.get('observe')} intercept_tools={caps.get('intercept_tools')} checkpoint={caps.get('checkpoint')}") if m else "-",
                     e(f"{s['passed']}/{s['graded']}") if s else "-",
                     e(f"{pct(s['pass_rate'])} [{pct(lo)}-{pct(hi)}]") if s else "-",
                     e(s["errors"]) if s else "-", e(f"{ms(s['p50_ms'])} / {ms(s['p95_ms'])}") if s else "-"])
    paired = (decision or {}).get("paired")
    line = (f'<p>Paired: {e(paired["pairs"])} pairs, <b>{e(paired["regressions"])}</b> regressions, '
            f'<b>{e(paired["fixes"])}</b> fixes</p>') if paired else ""
    return ("<h2>Targets</h2>" + table(["Name", "Mode", "Language/adapter", "Version", "Capabilities", "Pass k/n",
                                         "Pass rate (95% CI)", "Errors", "p50 / p95"], rows) + line)


def matrix_section(meta: dict, trials: list[dict]) -> str:
    targets = list(meta.get("targets", {}))
    rows = []
    for sc in meta.get("scenarios", []):
        cells = [f'<span class="m">{e(sc)}</span>']
        for tg in targets:
            ts = [t for t in trials if t["scenario"] == sc and t["target"] == tg]
            passed = sum(t["status"] == "passed" for t in ts)
            graded = sum(t["status"] in ("passed", "failed") for t in ts)
            errs = sum(t["status"] in ("error", "running") for t in ts)
            cls = "none" if not graded else "pass" if passed == graded else "fail"
            cells.append(badge(f"{passed}/{graded}" + (f" +{errs} err" if errs else ""), "error" if errs and cls == "pass" else cls))
        rows.append(cells)
    return "<h2>Scenario x target</h2>" + table(["Scenario"] + targets, rows)


def diff_section(diff: dict) -> str:
    if not diff:
        return "<p class='sub'>No state changes.</p>"
    out = []
    for tbl, ch in diff.items():
        lines = [f'<div class="add m">+ {kv(r)}</div>' for r in ch["added"]] + [f'<div class="rm m">- {kv(r)}</div>' for r in ch["removed"]]
        out.append(f"<div><b class='m'>{e(tbl)}</b>{''.join(lines)}</div>")
    return "".join(out)


def trial_details(t: dict, meta: dict) -> str:
    r = t["record"]
    summary = f'{e(t["target"])} &middot; {e(t["scenario"])} &middot; #{e(t["repeat"])} {badge(t["status"])}'
    body = ""
    if err := r.get("error"):
        body += f'<h3>Error</h3><div class="banner BLOCK"><b>{e(err.get("code"))}</b>: {e(err.get("message"))}</div>'
    if "output" in r:
        out = r["output"] if isinstance(r["output"], str) else json.dumps(r["output"], indent=2, default=str)
        body += f'<h3>Agent output ({e(r.get("agent_status"))})</h3><pre>{e(out)}</pre>'
    if r.get("assertions"):
        body += "<h3>Assertions</h3>" + table(["Status", "Critical", "Description", "Detail"], [
            [badge(a["status"]), "CRITICAL" if a["critical"] else "", f'<span class="m">{e(a["description"])}</span>', e(a["detail"])]
            for a in r["assertions"]])
    if "state_diff" in r:
        body += "<h3>State diff</h3>" + diff_section(r["state_diff"])
    if "ledger" in r:
        body += "<h3>Side-effect ledger</h3>" + (table(["Seq", "Tool", "Status", "Request"], [
            [e(x["seq"]), e(x["tool"]), e(x["status"]), f'<span class="m">{e(compact(x["request"]))}</span>']
            for x in r["ledger"]]) if r["ledger"] else "<p class='sub'>No side effects.</p>")
    if "events" in r:
        observe = (meta["targets"].get(t["target"], {}).get("manifest") or {}).get("capabilities", {}).get("observe")
        body += "<h3>Agent events</h3>" + (table(["Seq", "Type", "Name", "Data"], [
            [e(x["seq"]), e(x["type"]), e(x.get("name") or ""), f'<span class="m">{e(compact(x.get("data", {})))}</span>']
            for x in r["events"]]) if r["events"] else f"<p class='sub'>No native events (observe={e(observe)})</p>")
    open_attr = " open" if t["status"] in ("failed", "error") else ""
    return f"<details{open_attr}><summary>{summary}</summary>{body}</details>"


def render(experiment: dict, trials: list[dict]) -> str:
    meta, decision = experiment.get("meta") or {}, experiment.get("decision")
    order = sorted(trials, key=lambda t: (t["scenario"], t["repeat"], t["target"]))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentLab release report {e(experiment['id'])}</title><style>{CSS}</style></head><body><main>
<h1>AgentLab release report</h1>
<div class="sub m">{e(experiment['id'])} &middot; created {e(experiment.get('created_at'))}</div>
{banner(decision)}
{targets_section(meta, decision)}
{matrix_section(meta, trials)}
<h2>Trials</h2>
{''.join(trial_details(t, meta) for t in order)}
</main></body></html>"""
