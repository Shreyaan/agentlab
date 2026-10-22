import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import type { Schema } from "../api/client";
import { useScenarios, useStartRun, useTargets } from "../api/hooks";
import { CapabilityBadges, runnableProblem } from "../components/capabilities";
import { ReachDot } from "../components/badges";
import { TIER_TONE, faultSummary } from "../components/scenario";
import { Badge, Card, Notice, PageHeader, QueryState, SectionTitle, btnPrimary, field } from "../components/ui";
import { percent } from "../lib/format";

function ScenarioPicker({
  scenarios,
  selected,
  onChange,
}: {
  scenarios: Schema["ScenarioInfo"][];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  const all = selected.size === scenarios.length;
  const toggle = (key: string) => {
    const next = new Set(selected);
    if (!next.delete(key)) next.add(key);
    onChange(next);
  };
  return (
    <Card className="p-4">
      <SectionTitle
        aside={
          <label className="flex cursor-pointer items-center gap-1.5 text-ink2">
            <input
              type="checkbox"
              checked={all}
              onChange={() => onChange(all ? new Set() : new Set(scenarios.map((s) => s.key)))}
            />
            Select all ({selected.size}/{scenarios.length})
          </label>
        }
      >
        Scenarios
      </SectionTitle>
      <ul className="divide-y divide-line">
        {scenarios.map(({ key, scenario: s }) => (
          <li key={key}>
            <label className="flex cursor-pointer items-start gap-2.5 py-2">
              <input type="checkbox" className="mt-1" checked={selected.has(key)} onChange={() => toggle(key)} />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-1.5">
                  <code className="font-medium">{key}</code>
                  <Badge tone={TIER_TONE[s.risk_tier]}>{s.risk_tier}</Badge>
                  {s.slices.map((sl) => (
                    <Badge key={sl}>{sl}</Badge>
                  ))}
                </span>
                <span className="block text-[12px] text-ink2">{faultSummary(s)}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function TargetSelect({
  id,
  label,
  targets,
  value,
  onChange,
  optional,
}: {
  id: string;
  label: string;
  targets: Schema["TargetHealth"][];
  value: string;
  onChange: (v: string) => void;
  optional?: boolean;
}) {
  const chosen = targets.find((t) => t.name === value);
  const problem = chosen ? runnableProblem(chosen) : null;
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="font-medium">
        {label}
        {optional && <span className="font-normal text-ink3"> (optional)</span>}
      </label>
      <select id={id} className={field} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{optional ? "No baseline" : "Choose a target"}</option>
        {targets.map((t) => (
          <option key={t.name} value={t.name}>
            {t.reachable ? "● " : "○ "}
            {t.name}
            {runnableProblem(t) ? " (not runnable)" : ""}
          </option>
        ))}
      </select>
      {chosen && (
        <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink2">
          <ReachDot reachable={chosen.reachable} />
          {chosen.manifest && <CapabilityBadges caps={chosen.manifest.capabilities} />}
        </div>
      )}
      {problem && <Notice tone="warn">{problem}</Notice>}
    </div>
  );
}

function RunForm({ scenarios, targets }: { scenarios: Schema["ScenarioInfo"][]; targets: Schema["TargetHealth"][] }) {
  const navigate = useNavigate();
  const start = useStartRun();
  const [selected, setSelected] = useState(() => new Set(scenarios.map((s) => s.key)));
  const [candidate, setCandidate] = useState("");
  const [baseline, setBaseline] = useState("");
  const [repeats, setRepeats] = useState(1);
  const [maxRegressionPct, setMaxRegressionPct] = useState(0);

  const targetCount = candidate ? (baseline && baseline !== candidate ? 2 : 1) : 0;
  const trials = selected.size * repeats * targetCount;
  const byName = useMemo(() => new Map(targets.map((t) => [t.name, t])), [targets]);
  const blocked = [candidate, baseline].some((n) => n && byName.get(n)?.manifest?.capabilities.invoke === false);
  const valid = selected.size > 0 && candidate !== "" && repeats >= 1 && repeats <= 20 && !blocked;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    start.mutate(
      {
        scenarios: [...selected],
        candidate,
        baseline: baseline || null,
        repeats,
        max_regression: maxRegressionPct / 100,
      },
      { onSuccess: ({ experiment_id }) => void navigate(`/experiments/${experiment_id}`) },
    );
  };

  return (
    <form onSubmit={submit} className="grid gap-4 lg:grid-cols-[1fr_22rem]">
      <ScenarioPicker scenarios={scenarios} selected={selected} onChange={setSelected} />
      <div className="space-y-4">
        <Card className="space-y-4 p-4">
          <TargetSelect id="candidate" label="Candidate" targets={targets} value={candidate} onChange={setCandidate} />
          <TargetSelect id="baseline" label="Baseline" targets={targets} value={baseline} onChange={setBaseline} optional />
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label htmlFor="repeats" className="font-medium">
                Repeats
              </label>
              <input
                id="repeats"
                className={field}
                type="number"
                min={1}
                max={20}
                value={repeats}
                onChange={(e) => setRepeats(Number(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="maxreg" className="font-medium">
                Max regression %
              </label>
              <input
                id="maxreg"
                className={field}
                type="number"
                min={0}
                max={100}
                step={1}
                value={maxRegressionPct}
                onChange={(e) => setMaxRegressionPct(Number(e.target.value))}
              />
            </div>
          </div>
          <p className="text-[12px] text-ink2">
            The gate blocks when the candidate's pass rate drops more than {percent(maxRegressionPct / 100)} below the baseline.
          </p>
        </Card>
        <Card className="space-y-3 p-4">
          <p className="tabular-nums" aria-live="polite">
            <strong>{trials}</strong> trials = {selected.size} scenarios x {repeats} repeats x {targetCount} targets
          </p>
          {start.isError && <Notice tone="block">{start.error.message}</Notice>}
          <button type="submit" className={`${btnPrimary} w-full`} disabled={!valid || start.isPending}>
            {start.isPending ? "Starting..." : "Start run"}
          </button>
        </Card>
      </div>
    </form>
  );
}

export function NewRunPage() {
  const scenarios = useScenarios();
  const targets = useTargets();
  return (
    <>
      <PageHeader title="New run" sub="Pick scenarios and the agents to compare." />
      <QueryState query={scenarios}>
        {(s) => (
          <QueryState query={targets}>{(t) => <RunForm scenarios={s} targets={t} />}</QueryState>
        )}
      </QueryState>
    </>
  );
}
