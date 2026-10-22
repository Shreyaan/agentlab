import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { reportUrl, type Schema } from "../api/client";
import { useExperiment, type Decision, type ExperimentData, type Paired, type TargetStats } from "../api/hooks";
import { DecisionBadge, StatusBadge, decisionTone } from "../components/badges";
import { CiBar, Progress } from "../components/charts";
import {
  Badge,
  Card,
  EmptyState,
  Mono,
  Notice,
  PageHeader,
  QueryState,
  SectionTitle,
  Table,
  Td,
  Th,
  btn,
  field,
} from "../components/ui";
import { cost, count, ms, percent, relativeTime } from "../lib/format";

const CAVEAT = "An offline gate is evidence, not proof of production safety.";

function DecisionBanner({ decision }: { decision: Decision | null | undefined }) {
  if (!decision) return null;
  const tone = decisionTone(decision.status);
  const reasons = [
    ...decision.block_reasons.map((r) => ({ kind: "Block", r })),
    ...decision.insufficient_reasons.map((r) => ({ kind: "Insufficient evidence", r })),
  ];
  const border = { pass: "border-pass", block: "border-block", warn: "border-warn" }[tone as "pass" | "block" | "warn"];
  return (
    <Card className={`mb-4 border-l-4 p-4 ${border}`}>
      <div className="flex flex-wrap items-center gap-3">
        <DecisionBadge decision={decision.status} />
        <span className="text-ink2">
          <strong className="text-ink">{decision.candidate}</strong>
          {decision.baseline ? ` vs baseline ${decision.baseline}` : " (no baseline)"}
        </span>
      </div>
      {reasons.length > 0 && (
        <ul className="mt-3 space-y-1">
          {reasons.map(({ kind, r }) => (
            <li key={`${kind}${r}`} className="flex gap-2">
              <span className="text-ink3">{kind}:</span> {r}
            </li>
          ))}
        </ul>
      )}
      {decision.coverage_gaps.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 font-medium">Coverage gaps</p>
          <ul className="list-inside list-disc text-ink2">
            {decision.coverage_gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="mt-3 text-[12px] text-ink3">{CAVEAT}</p>
    </Card>
  );
}

function StatsCard({ name, stats, role }: { name: string; stats: TargetStats; role: string }) {
  const rows: [string, string][] = [
    ["p50 latency", ms(stats.p50_ms)],
    ["p95 latency", ms(stats.p95_ms)],
    ["errors", count(stats.errors)],
    ["cost", cost(stats.cost_usd)],
  ];
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="truncate font-semibold">{name}</span>
        <Badge>{role}</Badge>
      </div>
      <div className="mb-3 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">{percent(stats.pass_rate)}</span>
        <span className="text-ink2 tabular-nums">
          pass {stats.passed}/{stats.graded}
        </span>
      </div>
      <CiBar rate={stats.pass_rate} ci={stats.ci95} />
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2">
            <dt className="text-ink2">{k}</dt>
            <dd className="tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function PairedCard({ paired }: { paired: Paired }) {
  return (
    <Card className="p-4">
      <SectionTitle>Paired comparison</SectionTitle>
      <div className="flex gap-6 tabular-nums">
        <div>
          <div className={`text-2xl font-semibold ${paired.regressions ? "text-block" : ""}`}>{paired.regressions}</div>
          <div className="text-ink2">regressions</div>
        </div>
        <div>
          <div className={`text-2xl font-semibold ${paired.fixes ? "text-pass" : ""}`}>{paired.fixes}</div>
          <div className="text-ink2">fixes</div>
        </div>
        <div>
          <div className="text-2xl font-semibold">{paired.pairs}</div>
          <div className="text-ink2">pairs</div>
        </div>
      </div>
    </Card>
  );
}

interface Filters {
  target: string;
  scenario: string;
  status: string;
}

function cellOf(trials: Schema["Trial"][]) {
  const passed = trials.filter((t) => t.status === "passed").length;
  const errors = trials.filter((t) => t.status === "error").length;
  const running = trials.filter((t) => t.status === "running").length;
  const graded = trials.filter((t) => t.status === "passed" || t.status === "failed").length;
  return { passed, errors, running, graded, total: trials.length };
}

function Matrix({
  targets,
  scenarios,
  trials,
  filters,
  onPick,
}: {
  targets: string[];
  scenarios: string[];
  trials: Schema["Trial"][];
  filters: Filters;
  onPick: (target: string, scenario: string) => void;
}) {
  const byCell = useMemo(() => {
    const m = new Map<string, Schema["Trial"][]>();
    for (const t of trials) m.set(`${t.target}|${t.scenario}`, [...(m.get(`${t.target}|${t.scenario}`) ?? []), t]);
    return m;
  }, [trials]);

  return (
    <Card>
      <div className="p-4 pb-0">
        <SectionTitle>Scenario x target</SectionTitle>
      </div>
      <Table>
        <thead>
          <tr>
            <Th>Scenario</Th>
            {targets.map((t) => (
              <Th key={t}>{t}</Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {scenarios.map((s) => (
            <tr key={s}>
              <Td>
                <Mono>{s}</Mono>
              </Td>
              {targets.map((t) => {
                const c = cellOf(byCell.get(`${t}|${s}`) ?? []);
                const tone = c.total === 0 ? "" : c.graded === 0 ? "bg-warn-bg text-warn" : c.passed === c.graded ? "bg-pass-bg text-pass" : c.passed === 0 ? "bg-block-bg text-block" : "bg-warn-bg text-warn";
                const selected = filters.target === t && filters.scenario === s;
                return (
                  <Td key={t} className="p-1">
                    <button
                      type="button"
                      disabled={c.total === 0}
                      onClick={() => onPick(t, s)}
                      aria-pressed={selected}
                      title="Filter trials to this cell"
                      className={`w-full cursor-pointer rounded px-2 py-1 text-center tabular-nums disabled:cursor-default ${tone} ${selected ? "ring-2 ring-accent" : ""}`}
                    >
                      {c.total === 0 ? "-" : c.graded === 0 && c.running === 0 ? `${c.errors} err` : `${c.passed}/${c.graded}${c.errors ? ` +${c.errors} err` : ""}${c.running ? ` (${c.running}...)` : ""}`}
                    </button>
                  </Td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

const ALL = "";
const FilterSelect = ({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) => (
  <select aria-label={`Filter by ${label}`} className={`${field} !w-auto`} value={value} onChange={(e) => onChange(e.target.value)}>
    <option value={ALL}>All {label === "status" ? "statuses" : `${label}s`}</option>
    {options.map((o) => (
      <option key={o}>{o}</option>
    ))}
  </select>
);

function TrialsTable({
  trials,
  targets,
  scenarios,
  filters,
  setFilters,
}: {
  trials: Schema["Trial"][];
  targets: string[];
  scenarios: string[];
  filters: Filters;
  setFilters: (f: Filters) => void;
}) {
  const navigate = useNavigate();
  const shown = trials.filter(
    (t) =>
      (!filters.target || t.target === filters.target) &&
      (!filters.scenario || t.scenario === filters.scenario) &&
      (!filters.status || t.status === filters.status),
  );
  const filtered = filters.target || filters.scenario || filters.status;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 p-4 pb-2">
        <SectionTitle>
          Trials <span className="font-normal text-ink3">({shown.length})</span>
        </SectionTitle>
        <div className="flex flex-wrap gap-2">
          <FilterSelect label="target" value={filters.target} options={targets} onChange={(target) => setFilters({ ...filters, target })} />
          <FilterSelect label="scenario" value={filters.scenario} options={scenarios} onChange={(scenario) => setFilters({ ...filters, scenario })} />
          <FilterSelect label="status" value={filters.status} options={["passed", "failed", "error", "running"]} onChange={(status) => setFilters({ ...filters, status })} />
          {filtered && (
            <button className={btn} onClick={() => setFilters({ target: ALL, scenario: ALL, status: ALL })}>
              Clear
            </button>
          )}
        </div>
      </div>
      {shown.length === 0 ? (
        <EmptyState title={trials.length ? "No trials match these filters" : "No trials yet"} />
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Status</Th>
              <Th>Target</Th>
              <Th>Scenario</Th>
              <Th className="text-right">Repeat</Th>
              <Th className="text-right">Latency</Th>
              <Th className="text-right">Cost</Th>
              <Th>Failure</Th>
            </tr>
          </thead>
          <tbody>
            {shown.map((t) => {
              const failing = t.record.assertions.filter((a) => a.status === "fail");
              return (
                <tr key={t.id} className="cursor-pointer hover:bg-sunken" onClick={() => void navigate(`/trials/${t.id}`)}>
                  <Td>
                    <Link to={`/trials/${t.id}`} onClick={(e) => e.stopPropagation()} className="hover:underline">
                      <StatusBadge status={t.status} />
                    </Link>
                  </Td>
                  <Td>{t.target}</Td>
                  <Td>
                    <Mono>{t.scenario}</Mono>
                  </Td>
                  <Td className="text-right tabular-nums">{t.repeat}</Td>
                  <Td className="text-right tabular-nums">{ms(t.record.latency_ms)}</Td>
                  <Td className="text-right tabular-nums">{cost(t.record.usage.cost_usd)}</Td>
                  <Td className="max-w-80 truncate text-ink2" >
                    {t.record.error ? `${t.record.error.code}: ${t.record.error.message}` : failing.map((a) => a.description).join("; ")}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

function Detail({ data }: { data: ExperimentData }) {
  const { summary, experiment, trials } = data;
  const [filters, setFilters] = useState<Filters>({ target: ALL, scenario: ALL, status: ALL });
  const targets = Object.keys(experiment.meta.targets);
  const scenarios = Object.keys(experiment.meta.scenarios);
  const decision = experiment.decision;
  const stats = decision ? Object.entries(decision.stats) : [];
  const forked = experiment.meta.forked_from;
  const pick = (target: string, scenario: string) =>
    setFilters((f) => (f.target === target && f.scenario === scenario ? { ...f, target: ALL, scenario: ALL } : { ...f, target, scenario }));

  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            Experiment <Mono className="text-[15px]">{summary.id}</Mono>
            <StatusBadge status={summary.status} />
          </span>
        }
        sub={`Started ${relativeTime(summary.created_at)} - ${experiment.meta.repeats} repeats`}
      >
        <a className={btn} href={reportUrl(summary.id)} target="_blank" rel="noreferrer">
          Export report
        </a>
      </PageHeader>

      {forked && (
        <div className="mb-4">
          <Notice tone="info">
            Forked from trial{" "}
            <Link className="font-medium underline" to={`/trials/${forked.trial_id}`}>
              <Mono>{forked.trial_id}</Mono>
            </Link>{" "}
            at checkpoint <Mono>{forked.checkpoint_id}</Mono>.
          </Notice>
        </div>
      )}
      {summary.error && (
        <div className="mb-4">
          <Notice tone="block">The job stopped before a decision: {summary.error}</Notice>
        </div>
      )}
      {summary.status === "running" && (
        <Card className="mb-4 flex items-center gap-3 p-4">
          <span className="font-medium">Running</span>
          <Progress done={summary.finished} total={summary.planned} />
          <span className="text-ink2">Updating every 2 seconds.</span>
        </Card>
      )}

      <DecisionBanner decision={decision} />

      {stats.length > 0 && (
        <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {stats.map(([name, s]) => (
            <StatsCard key={name} name={name} stats={s} role={name === decision?.candidate ? "candidate" : "baseline"} />
          ))}
          {decision?.paired && <PairedCard paired={decision.paired} />}
        </div>
      )}

      <div className="space-y-4">
        <Matrix targets={targets} scenarios={scenarios} trials={trials} filters={filters} onPick={pick} />
        <TrialsTable trials={trials} targets={targets} scenarios={scenarios} filters={filters} setFilters={setFilters} />
      </div>
    </>
  );
}

export function ExperimentDetailPage() {
  const { id = "" } = useParams();
  const query = useExperiment(id);
  return <QueryState query={query}>{(data) => <Detail data={data} />}</QueryState>;
}
