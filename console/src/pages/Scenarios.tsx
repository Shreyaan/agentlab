import { useState } from "react";
import { Link, useParams } from "react-router";
import type { Schema } from "../api/client";
import { useScenarios } from "../api/hooks";
import { TIER_TONE, faultLabel, faultSummary, type Assertion, type Scenario } from "../components/scenario";
import { Badge, Card, EmptyState, Labeled, JsonBlock, Mono, PageHeader, QueryState, SectionTitle, Table, Td, Th, btn, btnPrimary, field, type Tone } from "../components/ui";
import { percent } from "../lib/format";

const STATUS_NOTE = "critical first";

function Faults({ faults }: { faults: Schema["ScenarioFault"][] }) {
  if (faults.length === 0) return <p className="text-ink2">No faults: the environment behaves normally.</p>;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Boundary</Th>
          <Th>Tool</Th>
          <Th>Action</Th>
          <Th>When</Th>
        </tr>
      </thead>
      <tbody>
        {faults.map((f, i) => (
          <tr key={i} title={faultLabel(f)}>
            <Td>
              <Badge tone={f.boundary === "harness" ? "info" : "neutral"}>{f.boundary}</Badge>
            </Td>
            <Td>
              <Mono>{f.tool}</Mono>
            </Td>
            <Td>{f.action}</Td>
            <Td>{typeof f.when === "number" ? `call #${f.when}` : f.when}</Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

const assertionTone = (a: Assertion): Tone => (a.critical ? "block" : "neutral");
/** Mirrors each grader's default_description in src/agentlab/assertions.py. */
function describeAssertion(a: Assertion): string {
  switch (a.type) {
    case "sql":
      return `${a.query} == ${JSON.stringify(a.equals)}`;
    case "tool_order":
      return `${a.requires} succeeds before ${a.before}`;
    case "forbidden_tool":
      return `${a.name} is never called`;
    case "event_present":
      return `agent reports ${a.event}${a.name ? ` for ${a.name}` : ""}`;
    case "decision":
      return a.question.instructions;
    case "output_matches":
      return "retired check (no longer evaluated)";
  }
}

type Decision = Extract<Assertion, { type: "decision" }>;

export const describeRule = (a: Decision): string => {
  const r = a.pass_rule;
  if ("noul_at_least" in r) return `probability of true is at least ${percent(r.noul_at_least)}`;
  if ("choices" in r) return `judge picks ${r.choices.join(" or ")}`;
  return `score is at least ${r.score_at_least}`;
};

function DecisionDetail({ a }: { a: Decision }) {
  const q = a.question;
  const criteria = Array.isArray(q.criteria) ? q.criteria.map((c, i) => [String(i), c] as const) : Object.entries(q.criteria);
  return (
    <div className="mt-1 space-y-1.5 text-[12px] text-ink2">
      <p>
        <span className="font-medium text-ink">{q.type} question.</span> Passes when {describeRule(a)}, with confidence of at least {percent(a.min_confidence)}.
      </p>
      <ul className="list-disc pl-5">
        {criteria.map(([k, v]) => (
          <li key={k}>
            <Mono>{k}</Mono>: {v}
          </li>
        ))}
      </ul>
      <p>
        Judges ({a.strategy}):{" "}
        {(a.judges ?? []).map((j) => (
          <Badge key={j.model} title={`${j.api} API`}>
            {j.model}
          </Badge>
        ))}{" "}
        sees {a.evidence.join(", ")}.
      </p>
      {a.calibration && (
        <p>
          Calibration: {a.calibration.question.instructions} Truth from <Mono>{a.calibration.truth_sql}</Mono>.
        </p>
      )}
      <CanaryList canaries={a.canaries} />
    </div>
  );
}

const EVIDENCE_PREVIEW_CHARS = 120;

function CanaryList({ canaries }: { canaries: Decision["canaries"] }) {
  if (!canaries?.length) return null;
  return (
    <div>
      <p className="font-medium text-ink">Canaries ({canaries.length})</p>
      <ul className="mt-1 space-y-1">
        {canaries.map((c, i) => {
          const text = JSON.stringify(c.evidence);
          return (
            <li key={i} className="flex flex-wrap items-baseline gap-2">
              <Badge tone={c.expected === "pass" ? "pass" : "block"}>expected {c.expected}</Badge>
              <span className="font-medium text-ink">{c.label}</span>
              <Mono className="min-w-0 break-all text-ink3" >{text.length > EVIDENCE_PREVIEW_CHARS ? `${text.slice(0, EVIDENCE_PREVIEW_CHARS)}...` : text}</Mono>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const assertionText = (a: Assertion): string => a.description || describeAssertion(a);

/** Read-only scenario renderer; `actions` adds Edit/Duplicate for saved scenarios (the author review reuses it without). */
export function ScenarioDetail({ info, actions = true }: { info: { key: string; scenario: Scenario }; actions?: boolean }) {
  const s = info.scenario;
  const assertions = [...s.assertions].sort((a, b) => Number(b.critical) - Number(a.critical));
  const budget = Object.entries(s.budget).filter(([, v]) => v != null);
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[15px] font-semibold">
            <Mono>{info.key}</Mono>
          </h2>
          <Badge tone={TIER_TONE[s.risk_tier]}>{s.risk_tier}</Badge>
          <Badge>{s.source}</Badge>
          {s.slices.map((sl) => (
            <Badge key={sl} tone="info">
              {sl}
            </Badge>
          ))}
          <Link to={`/environments/${s.environment}`}>
            <Badge tone="accent" title="Environment">
              {s.environment}
            </Badge>
          </Link>
          {actions && (
            <div className="ml-auto flex gap-2">
              <Link className={btn} to={`/scenarios/${info.key}/edit`}>
                Edit
              </Link>
              <Link className={btn} to={`/scenarios/new?from=${info.key}`}>
                Duplicate
              </Link>
            </div>
          )}
        </div>
      </Card>
      <Card className="p-4">
        <SectionTitle>Input</SectionTitle>
        <JsonBlock label="Agent input" value={s.input} open />
      </Card>
      <Card className="p-4">
        <SectionTitle>Seed data</SectionTitle>
        {Object.keys(s.seed).length === 0 ? (
          <p className="text-ink2">No seed rows: every table starts empty.</p>
        ) : (
          <div className="space-y-1.5">
            {Object.entries(s.seed).map(([table, rows]) => (
              <JsonBlock key={table} label={`${table} (${rows.length} row${rows.length === 1 ? "" : "s"})`} value={rows} />
            ))}
          </div>
        )}
      </Card>
      <Card className="p-4">
        <SectionTitle>Faults</SectionTitle>
        <Faults faults={s.faults} />
      </Card>
      <Card className="p-4">
        <SectionTitle aside={<span className="text-ink3">{STATUS_NOTE}</span>}>Assertions</SectionTitle>
        <ul className="space-y-2">
          {assertions.map((a, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2">
              <Badge tone={assertionTone(a)}>{a.critical ? "CRITICAL" : a.type}</Badge>
              <span>{assertionText(a)}</span>
              {a.critical && <span className="text-ink3">({a.type})</span>}
              {a.type === "decision" && <div className="w-full"><DecisionDetail a={a} /></div>}
            </li>
          ))}
        </ul>
      </Card>
      <Card className="p-4">
        <SectionTitle>Budget</SectionTitle>
        {budget.length === 0 ? (
          <p className="text-ink2">No limits.</p>
        ) : (
          <dl className="flex flex-wrap gap-6">
            {budget.map(([k, v]) => (
              <div key={k}>
                <dt className="text-ink2">{k}</dt>
                <dd className="text-[15px] font-semibold tabular-nums">{String(v)}</dd>
              </div>
            ))}
          </dl>
        )}
      </Card>
    </div>
  );
}

export function ScenariosPage() {
  const query = useScenarios();
  const { key } = useParams();
  const [environment, setEnvironment] = useState("");
  return (
    <>
      <PageHeader title="Scenarios" sub="Versioned test cases the gate runs.">
        <Link className={btnPrimary} to="/author">
          Describe a scenario
        </Link>
        <Link className={btn} to="/scenarios/new">
          New scenario
        </Link>
      </PageHeader>
      <QueryState query={query} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No scenarios in the suite" />}>
        {(all) => {
          const environments = [...new Set(all.map((s) => s.scenario.environment))].sort();
          const list = environment ? all.filter((s) => s.scenario.environment === environment) : all;
          const active = all.find((s) => s.key === key);
          return (
            <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
              <Card className="h-fit">
                {environments.length > 1 && (
                  <div className="border-b border-line p-3">
                    <Labeled label="Environment">
                      {(id) => (
                        <select id={id} className={field} value={environment} onChange={(e) => setEnvironment(e.target.value)}>
                          <option value="">All environments</option>
                          {environments.map((e) => (
                            <option key={e}>{e}</option>
                          ))}
                        </select>
                      )}
                    </Labeled>
                  </div>
                )}
                {list.length === 0 && <EmptyState title={`No scenarios in ${environment}`} />}
                <ul className="divide-y divide-line">
                  {list.map((s) => (
                    <li key={s.key}>
                      <Link
                        to={`/scenarios/${s.key}`}
                        aria-current={s.key === key ? "page" : undefined}
                        className={`block px-3 py-2.5 hover:bg-sunken ${s.key === key ? "bg-sunken" : ""}`}
                      >
                        <span className="flex flex-wrap items-center gap-2">
                          <Mono className="font-medium">{s.key}</Mono>
                          <Badge tone={TIER_TONE[s.scenario.risk_tier]}>{s.scenario.risk_tier}</Badge>
                          <Badge tone="accent">{s.scenario.environment}</Badge>
                        </span>
                        <span className="block text-[12px] text-ink2">{faultSummary(s.scenario)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </Card>
              {active ? <ScenarioDetail info={active} /> : <Card><EmptyState title={key ? `No scenario ${key}` : "Select a scenario"} /></Card>}
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
