import { useId, useState } from "react";
import type { Schema } from "../../api/client";
import type { AssertionDraft } from "../scenario";
import { Badge, CheckField, Labeled, btn, field } from "../ui";
import { CanariesEditor } from "./canaries";
import { NumberField, Select } from "./fields";
import { QueryTester } from "./QueryTester";

export type Assertion = AssertionDraft;
export type Decision = Extract<Assertion, { type: "decision" }>;
type Question = Decision["question"];
type QuestionType = Question["type"];
type Calibration = NonNullable<Decision["calibration"]>;
type Evidence = Decision["evidence"][number];
type Judge = Schema["JudgeSpec"];
type Seed = Schema["Seed"];

const EVIDENCE: Record<Evidence, string> = {
  input: "What the user asked.",
  output: "The agent's final reply.",
  final_state: "Every database table after the run.",
  state_diff: "Only the rows the run added or removed.",
  ledger: "The log of tool calls with status codes.",
  events: "The agent's own step-by-step events (needs native events).",
};

const QUESTION_HELP: Record<QuestionType, string> = {
  noul: "A yes/no statement. The judge returns the probability it is true.",
  choice: "Pick one of several named options, with a confidence.",
  score: "A rating from 0 upward, with a confidence.",
};

const RULE_HELP = "A judge that is not confident enough, or answers in the wrong shape, abstains. An abstention never passes.";

/** A fresh question of the given type, keeping the instructions the author already wrote. */
export function blankQuestion(type: QuestionType, instructions = ""): Question {
  switch (type) {
    case "noul":
      return { type, instructions, criteria: { true: "The statement is true.", false: "The statement is false." } };
    case "choice":
      return { type, instructions, criteria: { yes: "", no: "" } };
    case "score":
      return { type, instructions, criteria: ["Worst", "Best"] };
  }
}

export const blankRule = (q: Question): Decision["pass_rule"] => {
  switch (q.type) {
    case "noul":
      return { noul_at_least: 0.8 };
    case "choice":
      return { choices: [Object.keys(q.criteria)[0] ?? ""] };
    case "score":
      return { score_at_least: Math.max(q.criteria.length - 1, 0) };
  }
};

export const newDecision = (judgeModel: string): Decision => {
  const question = blankQuestion("noul", "");
  return {
    type: "decision",
    question,
    pass_rule: blankRule(question),
    min_confidence: 0.8,
    evidence: ["input", "output", "final_state"],
    judges: [{ model: judgeModel, api: "decisions" }],
    strategy: "cascade",
    calibration: null,
    canaries: [],
    critical: false,
    requires_faults: false,
    description: "",
  };
};

function EntryRows({ entries, onChange, nameLabel }: { entries: [string, string][]; onChange: (e: [string, string][]) => void; nameLabel: string }) {
  const set = (i: number, k: string, v: string) => onChange(entries.map((e, j) => (j === i ? [k, v] : e)));
  return (
    <div className="space-y-1.5">
      {entries.map(([k, v], i) => (
        <div key={i} className="flex gap-2">
          <input aria-label={`${nameLabel} ${i + 1}`} className={`${field} w-32! shrink-0`} value={k} onChange={(e) => set(i, e.target.value, v)} />
          <input aria-label={`${nameLabel} ${i + 1} description`} className={field} placeholder="What this means" value={v} onChange={(e) => set(i, k, e.target.value)} />
          <button type="button" className="cursor-pointer px-1.5 text-ink2 hover:text-block disabled:opacity-40" disabled={entries.length <= 2} aria-label={`Remove ${nameLabel} ${i + 1}`} onClick={() => onChange(entries.filter((_, j) => j !== i))}>
            x
          </button>
        </div>
      ))}
      <button type="button" className={btn} onClick={() => onChange([...entries, [`${nameLabel}_${entries.length + 1}`, ""]])}>
        Add {nameLabel}
      </button>
    </div>
  );
}

function CriteriaEditor({ q, onChange }: { q: Question; onChange: (q: Question) => void }) {
  switch (q.type) {
    case "noul":
      return (
        <div className="space-y-1.5">
          {(["true", "false"] as const).map((k) => (
            <Labeled key={k} label={`When ${k}`}>
              {(id) => <input id={id} className={field} value={q.criteria[k] ?? ""} onChange={(e) => onChange({ ...q, criteria: { ...q.criteria, [k]: e.target.value } })} />}
            </Labeled>
          ))}
        </div>
      );
    case "choice":
      return <EntryRows nameLabel="choice" entries={Object.entries(q.criteria)} onChange={(e) => onChange({ ...q, criteria: Object.fromEntries(e) })} />;
    case "score":
      return (
        <div className="space-y-1.5">
          {q.criteria.map((c, i) => (
            <div key={i} className="flex items-center gap-2">
              <Badge>{i}</Badge>
              <input aria-label={`Score ${i} description`} className={field} value={c} onChange={(e) => onChange({ ...q, criteria: q.criteria.map((x, j) => (j === i ? e.target.value : x)) })} />
              <button type="button" className="cursor-pointer px-1.5 text-ink2 hover:text-block disabled:opacity-40" disabled={q.criteria.length <= 2} aria-label={`Remove score ${i}`} onClick={() => onChange({ ...q, criteria: q.criteria.filter((_, j) => j !== i) })}>
                x
              </button>
            </div>
          ))}
          <button type="button" className={btn} onClick={() => onChange({ ...q, criteria: [...q.criteria, ""] })}>
            Add score level
          </button>
        </div>
      );
  }
}

function QuestionEditor({ q, types, onChange }: { q: Question; types: readonly QuestionType[]; onChange: (q: Question) => void }) {
  return (
    <div className="space-y-3">
      <Select label="Question type" help={QUESTION_HELP[q.type]} value={q.type} options={types} onChange={(t) => t !== q.type && onChange(blankQuestion(t, q.instructions))} />
      <Labeled label="Instructions" help="Ask about facts the evidence shows, in plain words.">
        {(id, d) => <textarea id={id} aria-describedby={d} rows={3} className={field} value={q.instructions} onChange={(e) => onChange({ ...q, instructions: e.target.value })} />}
      </Labeled>
      <fieldset className="space-y-1">
        <legend className="font-medium">{q.type === "score" ? "Score levels (0 is the first)" : "Criteria"}</legend>
        <CriteriaEditor q={q} onChange={onChange} />
      </fieldset>
    </div>
  );
}

function PassRuleEditor({ d, set }: { d: Decision; set: (p: Partial<Decision>) => void }) {
  const q = d.question;
  const rule = d.pass_rule;
  if (q.type === "noul" && "noul_at_least" in rule)
    return <NumberField label="Pass when the probability of true is at least" min={0} max={1} step={0.05} value={rule.noul_at_least} onChange={(v) => set({ pass_rule: { noul_at_least: v ?? 0 } })} />;
  if (q.type === "choice" && "choices" in rule)
    return (
      <fieldset className="space-y-1">
        <legend className="font-medium">Pass when the judge picks one of</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {Object.keys(q.criteria).map((c) => (
            <CheckField key={c} label={c} checked={rule.choices.includes(c)} onChange={(on) => set({ pass_rule: { choices: on ? [...rule.choices, c] : rule.choices.filter((x) => x !== c) } })} />
          ))}
        </div>
      </fieldset>
    );
  if (q.type === "score" && "score_at_least" in rule)
    return (
      <Select label="Pass when the score is at least" value={String(rule.score_at_least)} options={q.criteria.map((_, i) => String(i))} onChange={(v) => set({ pass_rule: { score_at_least: Number(v) } })} />
    );
  return null;
}

const STRATEGY: Record<Decision["strategy"], string> = {
  cascade: "Ask judges in order and stop at the first confident answer. Cheapest: later judges only run when earlier ones abstain.",
  jury: "Ask every judge. The check decides only if all of them agree confidently; otherwise it abstains.",
};

function JudgesEditor({ d, set, suggestions }: { d: Decision; set: (p: Partial<Decision>) => void; suggestions: string[] }) {
  const [custom, setCustom] = useState("");
  const judges = d.judges ?? [];
  const update = (list: Judge[]) => set({ judges: list });
  const add = (model: string) => {
    const m = model.trim();
    if (m && !judges.some((j) => j.model === m)) update([...judges, { model: m, api: "decisions" }]);
  };
  const move = (i: number, by: -1 | 1) => {
    const next = [...judges];
    const [item] = next.splice(i, 1);
    if (item) next.splice(i + by, 0, item);
    update(next);
  };
  const available = suggestions.filter((m) => !judges.some((j) => j.model === m));
  return (
    <fieldset className="space-y-2">
      <legend className="font-medium">Judges</legend>
      <p className="text-[12px] text-ink2">
        <code>decisions</code> uses OpenRouter's Decisions API (typed probabilities). <code>chat</code> asks any OpenRouter chat model for structured JSON, so you can use any small or large model by its id.
        The optional min confidence (0.5 to 1) overrides the check's threshold for one judge, because probabilities are not comparable between models.
      </p>
      <ul className="space-y-1.5">
        {judges.map((j, i) => (
          <li key={j.model} className="flex flex-wrap items-center gap-2">
            <Badge>{i + 1}</Badge>
            <code className="min-w-0 flex-1 break-all">{j.model}</code>
            <input
              type="number"
              aria-label={`Min confidence for ${j.model}`}
              title="Optional. Overrides the check's minimum confidence for this judge."
              placeholder="min conf."
              min={0.5}
              max={1}
              step={0.05}
              className={`${field} w-24!`}
              value={j.min_confidence ?? ""}
              onChange={(e) => update(judges.map((x, k) => (k === i ? { ...x, min_confidence: e.target.value === "" ? null : Number(e.target.value) } : x)))}
            />
            <select aria-label={`API for ${j.model}`} className={`${field} w-28!`} value={j.api} onChange={(e) => update(judges.map((x, k) => (k === i ? { ...x, api: e.target.value as Judge["api"] } : x)))}>
              <option value="decisions">decisions</option>
              <option value="chat">chat</option>
            </select>
            <button type="button" className={btn} disabled={i === 0} aria-label={`Move ${j.model} earlier`} onClick={() => move(i, -1)}>
              Up
            </button>
            <button type="button" className={btn} disabled={i === judges.length - 1} aria-label={`Move ${j.model} later`} onClick={() => move(i, 1)}>
              Down
            </button>
            <button type="button" className={btn} disabled={judges.length <= 1} onClick={() => update(judges.filter((_, k) => k !== i))}>
              Remove
            </button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        {available.length > 0 && (
          <Labeled label="Add a suggested model">
            {(id) => (
              <select id={id} className={field} value="" onChange={(e) => add(e.target.value)}>
                <option value="">Choose...</option>
                {available.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            )}
          </Labeled>
        )}
        <Labeled label="Or any OpenRouter model id">
          {(id) => <input id={id} className={field} placeholder="vendor/model-name" value={custom} onChange={(e) => setCustom(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(custom); setCustom(""); } }} />}
        </Labeled>
        <button type="button" className={btn} disabled={!custom.trim()} onClick={() => { add(custom); setCustom(""); }}>
          Add model
        </button>
      </div>
    </fieldset>
  );
}

function CalibrationEditor({ d, set, seed }: { d: Decision; set: (p: Partial<Decision>) => void; seed: Seed }) {
  const cal = d.calibration;
  const put = (p: Partial<Calibration>) => cal && set({ calibration: { ...cal, ...p } });
  return (
    <fieldset className="space-y-3 rounded-md border border-line p-3">
      <legend className="px-1 font-medium">Calibration</legend>
      <CheckField
        label="Score the judges against a recorded fact"
        help="Each judge also answers a second question whose true answer comes from SQL over the run. This measures how well it reads the evidence. Critical checks can only block a release once their judge is calibrated."
        checked={cal !== null}
        onChange={(on) => set({ calibration: on ? { question: blankQuestion("noul", "") as Calibration["question"], truth_sql: "" } : null })}
      />
      {cal && (
        <>
          <QuestionEditor q={cal.question} types={["noul", "choice"]} onChange={(q) => put({ question: q as Calibration["question"] })} />
          <Labeled label="Truth SQL" help={cal.question.type === "noul" ? "One cell: true or false." : "One cell: the name of the correct choice."}>
            {(id, h) => <textarea id={id} aria-describedby={h} rows={2} spellCheck={false} className={`${field} font-mono text-[12px]`} value={cal.truth_sql} onChange={(e) => put({ truth_sql: e.target.value })} />}
          </Labeled>
          <QueryTester seed={seed} query={cal.truth_sql} />
          <p className="text-[12px] text-ink2">Testing runs against your seed data, so it shows the value before the agent acts.</p>
        </>
      )}
    </fieldset>
  );
}

export function DecisionForm({ d, set, seed, suggestions }: { d: Decision; set: (p: Partial<Decision>) => void; seed: Seed; suggestions: string[] }) {
  const evidenceKinds = Object.keys(EVIDENCE) as Evidence[];
  const changeQuestion = (question: Question) => set({ question, pass_rule: question.type === d.question.type ? remapChoices(d.pass_rule, d.question, question) : blankRule(question) });
  const strategyName = useId();
  return (
    <div className="space-y-4">
      <QuestionEditor q={d.question} types={["noul", "choice", "score"]} onChange={changeQuestion} />
      <div className="space-y-1">
        <PassRuleEditor d={d} set={set} />
        <p className="text-[12px] text-ink2">{RULE_HELP}</p>
      </div>
      <Labeled label={`Minimum confidence: ${d.min_confidence.toFixed(2)}`} help="Below this confidence a judge abstains instead of deciding.">
        {(id, h) => <input id={id} aria-describedby={h} type="range" min={0} max={1} step={0.05} className="w-full accent-[var(--accent)]" value={d.min_confidence} onChange={(e) => set({ min_confidence: Number(e.target.value) })} />}
      </Labeled>
      <fieldset className="space-y-1">
        <legend className="font-medium">Evidence the judge sees</legend>
        <div className="grid gap-1 sm:grid-cols-2">
          {evidenceKinds.map((k) => (
            <CheckField key={k} label={k} help={EVIDENCE[k]} checked={d.evidence.includes(k)} onChange={(on) => { const next = evidenceKinds.filter((x) => (x === k ? on : d.evidence.includes(x))); if (next.length) set({ evidence: next }); }} />
          ))}
        </div>
      </fieldset>
      <JudgesEditor d={d} set={set} suggestions={suggestions} />
      <fieldset className="space-y-1">
        <legend className="font-medium">Strategy</legend>
        {(Object.keys(STRATEGY) as Decision["strategy"][]).map((s) => (
          <label key={s} className="flex cursor-pointer items-start gap-2">
            <input type="radio" name={strategyName} className="mt-1" checked={d.strategy === s} onChange={() => set({ strategy: s })} />
            <span>
              <span className="font-medium">{s}</span>
              <span className="block text-[12px] text-ink2">{STRATEGY[s]}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <CalibrationEditor d={d} set={set} seed={seed} />
      <CanariesEditor canaries={d.canaries} onChange={(canaries) => set({ canaries })} />
    </div>
  );
}

/** Keeps a choice rule valid when choices are renamed (positionally) or removed. */
function remapChoices(rule: Decision["pass_rule"], from: Question, to: Question): Decision["pass_rule"] {
  if (!("choices" in rule) || from.type !== "choice" || to.type !== "choice") return rule;
  const before = Object.keys(from.criteria);
  const after = Object.keys(to.criteria);
  const choices = before.length === after.length ? rule.choices.map((c) => after[before.indexOf(c)] ?? c) : rule.choices.filter((c) => after.includes(c));
  return { choices };
}
