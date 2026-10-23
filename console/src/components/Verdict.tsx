import type { Schema } from "../api/client";
import { cost, percent } from "../lib/format";
import { ProbBar } from "./charts";
import type { Assertion } from "./scenario";
import { Badge, Mono, Notice, type Tone } from "./ui";

type Judge = Schema["JudgeAnswer"];
export type Decision = Extract<Assertion, { type: "decision" }>;

const VERDICT_TONE: Record<Schema["JudgeVerdict"]["verdict"], Tone> = { pass: "pass", fail: "block", abstain: "warn" };

const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const probabilities = (v: unknown): [string, number][] =>
  typeof v === "object" && v !== null ? Object.entries(v).flatMap(([k, p]) => (typeof p === "number" ? [[k, p] as [string, number]] : [])) : [];

/** One judge's typed answer: a probability bar (noul), per-choice bars, or a score with its legend. */
function Answer({ answer, decision }: { answer: Schema["JsonObject"]; decision: Decision | undefined }) {
  switch (answer.type) {
    case "noul":
      return <ProbBar label="P(true)" value={num(answer.noul) ?? 0} />;
    case "choice": {
      const choice = String(answer.choice);
      const probs = probabilities(answer.probabilities);
      return (
        <div className="space-y-1">
          <p>
            Chose <Mono className="font-medium">{choice}</Mono> with confidence {percent(num(answer.confidence))}
          </p>
          {probs.map(([k, p]) => (
            <ProbBar key={k} label={k} value={p} tone={k === choice ? "accent" : "pass"} />
          ))}
        </div>
      );
    }
    case "score": {
      const score = num(answer.score);
      const legend = decision?.question.type === "score" ? decision.question.criteria : [];
      return (
        <div className="space-y-1">
          <p>
            Score <span className="font-semibold tabular-nums">{score ?? "-"}</span>
            {score !== null && legend[score] ? <span className="text-ink2"> ({legend[score]})</span> : null}, confidence {percent(num(answer.confidence))}
          </p>
          <ProbBar label="Confidence" value={num(answer.confidence) ?? 0} />
          {legend.length > 0 && (
            <ol className="text-[12px] text-ink2">
              {legend.map((l, i) => (
                <li key={i} className={i === score ? "font-medium text-ink" : ""}>
                  {i}: {l}
                </li>
              ))}
            </ol>
          )}
        </div>
      );
    }
    case "error":
      return <Notice tone="warn">Judge failed: {String(answer.error)}</Notice>;
    default:
      return <Mono className="break-all">{JSON.stringify(answer)}</Mono>;
  }
}

/** What a judge said to the calibration question, in one short phrase. */
function calibrationText(a: Schema["JsonObject"]): string {
  if (a.type === "noul") return `P(true) ${percent(num(a.noul))}`;
  if (a.type === "choice") return `chose ${String(a.choice)}`;
  return JSON.stringify(a);
}

function Calibration({ judge, truth }: { judge: Schema["JudgeVerdict"]; truth: string }) {
  const rows = judge.judges.filter((j) => j.calibration_answer);
  return (
    <div className="space-y-1">
      <p className="font-medium">
        Calibration: true answer is <Mono>{truth}</Mono>
      </p>
      <ul className="space-y-0.5">
        {rows.map((j) => {
          const ok = judge.calibration_correct[j.model];
          return (
            <li key={j.model} className="flex flex-wrap items-center gap-2">
              <Mono>{j.model}</Mono>
              <span className="text-ink2">{j.calibration_answer ? calibrationText(j.calibration_answer) : ""}</span>
              {ok !== undefined && <Badge tone={ok ? "pass" : "block"}>{ok ? "correct" : "incorrect"}</Badge>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const JudgeCard = ({ j, decision }: { j: Judge; decision: Decision | undefined }) => (
  <li className="space-y-1.5 rounded-md border border-line p-2.5">
    <div className="flex items-center gap-2">
      <Mono className="font-medium">{j.model}</Mono>
      <span className="ml-auto text-ink2 tabular-nums">{cost(j.cost_usd)}</span>
    </div>
    <Answer answer={j.answer} decision={decision} />
  </li>
);

export function VerdictDetail({ judge, decision }: { judge: Schema["JudgeVerdict"]; decision?: Decision }) {
  const total = judge.judges.reduce((sum, j) => sum + (j.cost_usd ?? 0), 0);
  return (
    <div className="mt-2 space-y-2 text-[12px]">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={VERDICT_TONE[judge.verdict]} title={judge.verdict === "abstain" ? "Low confidence, judges disagreed, or not calibrated. An abstention is not a pass." : undefined}>
          verdict: {judge.verdict}
        </Badge>
        {judge.reason && <span className="text-ink2">{judge.reason}</span>}
        <span className="ml-auto text-ink2 tabular-nums">judge cost {cost(total)}</span>
      </div>
      <ul className="grid gap-2 md:grid-cols-2">
        {judge.judges.map((j) => (
          <JudgeCard key={j.model} j={j} decision={decision} />
        ))}
      </ul>
      {judge.calibration_truth != null && <Calibration judge={judge} truth={judge.calibration_truth} />}
    </div>
  );
}
