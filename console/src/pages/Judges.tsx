import { useJudges } from "../api/hooks";
import type { Schema } from "../api/client";
import { Badge, Card, EmptyState, Mono, PageHeader, QueryState, Table, Td, Th } from "../components/ui";
import { cost, count, percent } from "../lib/format";

/** Wilson 95% interval for correct/samples, so a judge with 3 samples does not look as sure as one with 300. */
function wilson(correct: number, n: number): [number, number] {
  const z = 1.96;
  const p = correct / n;
  const d = 1 + (z * z) / n;
  const centre = (p + (z * z) / (2 * n)) / d;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [Math.max(0, centre - half), Math.min(1, centre + half)];
}

function AccuracyBar({ j }: { j: Schema["JudgeStats"] }) {
  if (j.accuracy == null || j.samples === 0) return <span className="text-ink3">no samples yet</span>;
  const [lo, hi] = wilson(j.correct, j.samples);
  return (
    <div className="min-w-40 space-y-1">
      <div className="relative h-2 rounded-full bg-sunken" role="img" aria-label={`Accuracy ${percent(j.accuracy)}, 95% interval ${percent(lo)} to ${percent(hi)}`}>
        <div className="absolute inset-y-0 rounded-full bg-accent/35" style={{ left: `${lo * 100}%`, width: `${Math.max((hi - lo) * 100, 1)}%` }} />
        <div className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-accent" style={{ left: `${j.accuracy * 100}%` }} />
        <div className="absolute inset-y-[-2px] w-px bg-ink3" style={{ left: "90%" }} title="90% bar" />
      </div>
      <div className="text-[11px] text-ink3 tabular-nums">
        {percent(j.accuracy)} (95% {percent(lo)} to {percent(hi)})
      </div>
    </div>
  );
}

export function JudgesPage() {
  const query = useJudges();
  return (
    <>
      <PageHeader title="Judges" sub="Models that answer decision checks, and how often they are right." />
      <Card className="mb-4 p-4 text-ink2">
        <p>
          Judges are scored automatically against recorded facts: each decision check can carry a calibration question whose true answer comes from
          SQL over the run, and every judge answers it alongside its verdict. A critical decision check can only block a release once its judge is
          calibrated: at least 20 samples and at least 90% accuracy. Until then it can only warn.
        </p>
      </Card>
      <Card>
        <QueryState query={query} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No judge has been scored yet">Add a calibration question to a decision check and run it.</EmptyState>}>
          {(judges) => (
            <Table>
              <thead>
                <tr>
                  <Th>Model</Th>
                  <Th className="text-right">Samples</Th>
                  <Th className="text-right">Correct</Th>
                  <Th>Accuracy</Th>
                  <Th className="text-right">Cost</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {judges.map((j) => (
                  <tr key={j.model}>
                    <Td>
                      <Mono>{j.model}</Mono>
                    </Td>
                    <Td className="text-right tabular-nums">{count(j.samples)}</Td>
                    <Td className="text-right tabular-nums">{count(j.correct)}</Td>
                    <Td>
                      <AccuracyBar j={j} />
                    </Td>
                    <Td className="text-right tabular-nums">{cost(j.cost_usd)}</Td>
                    <Td>
                      <Badge tone={j.calibrated ? "pass" : "warn"} title="Calibrated = at least 20 samples and at least 90% accuracy">
                        {j.calibrated ? "calibrated" : "not calibrated"}
                      </Badge>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </QueryState>
      </Card>
    </>
  );
}
