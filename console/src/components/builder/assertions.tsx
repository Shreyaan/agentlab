import type { Schema } from "../../api/client";
import { Badge, Card, CheckField, Labeled, SectionTitle, btn, field } from "../ui";
import { DecisionForm, newDecision, type Assertion, type Decision } from "./decision";
import { JsonField, Select } from "./fields";
import { QueryTester } from "./QueryTester";

type Builder = Schema["BuilderInfo"];
type Seed = Schema["Seed"];
type Of<T extends Assertion["type"]> = Extract<Assertion, { type: T }>;
type EventType = Of<"event_present">["event"];

const COMMON = { critical: false, requires_faults: false, description: "" } as const;

/** Retired types still parse (stored history) but cannot be created, so the editor offers only live ones. */
const TYPE_HELP: Record<Exclude<Assertion["type"], "output_matches">, string> = {
  sql: "Checks the database after the run. The most reliable check.",
  tool_order: "One tool must succeed before another is called.",
  forbidden_tool: "A tool must never be called.",
  event_present: "The agent must report an event. Needs a target with native events.",
  decision: "A model judges the evidence against a typed question. For wording and intent that SQL cannot see.",
};

const EVENT_SUGGESTIONS = ["tool_failed", "tool_completed", "approval_requested", "retry_scheduled", "checkpoint_saved"] as const satisfies readonly EventType[];

export function newAssertion(type: string, b: Builder): Assertion {
  const tool = b.tools[0] ?? "";
  switch (type) {
    case "sql":
      return { ...COMMON, type: "sql", query: "", equals: 1 };
    case "tool_order":
      return { ...COMMON, type: "tool_order", before: b.tools[1] ?? tool, requires: tool };
    case "forbidden_tool":
      return { ...COMMON, type: "forbidden_tool", name: tool };
    case "event_present":
      return { ...COMMON, type: "event_present", event: "tool_failed", name: null };
    default:
      return newDecision(b.judge_models[0] ?? "");
  }
}

type Patch<T> = (p: Partial<T>) => void;

function SqlForm({ a, set, seed }: { a: Of<"sql">; set: Patch<Of<"sql">>; seed: Seed }) {
  return (
    <div className="space-y-3">
      <Labeled label="Query" help="Read-only SQL over the final database state. A single cell is compared as a value.">
        {(id, d) => <textarea id={id} aria-describedby={d} rows={2} spellCheck={false} className={`${field} font-mono text-[12px]`} value={a.query} onChange={(e) => set({ query: e.target.value })} />}
      </Labeled>
      <JsonField label="Expected value" help={'A number, true/false, or text. Use quotes to force text, e.g. "1".'} value={a.equals} onChange={(equals) => set({ equals })} />
      <QueryTester seed={seed} query={a.query} />
    </div>
  );
}

function ToolSelect({ label, value, tools, onChange }: { label: string; value: string; tools: string[]; onChange: (v: string) => void }) {
  return <Select label={label} value={value} options={tools} onChange={onChange} />;
}

function AssertionBody({ a, set, b, seed }: { a: Assertion; set: Patch<Assertion>; b: Builder; seed: Seed }) {
  switch (a.type) {
    case "sql":
      return <SqlForm a={a} set={set} seed={seed} />;
    case "tool_order":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <ToolSelect label="Required tool (must succeed first)" value={a.requires} tools={b.tools} onChange={(requires) => set({ requires })} />
          <ToolSelect label="Before this tool is called" value={a.before} tools={b.tools} onChange={(before) => set({ before })} />
        </div>
      );
    case "forbidden_tool":
      return <ToolSelect label="Tool that must never be called" value={a.name} tools={b.tools} onChange={(name) => set({ name })} />;
    case "event_present":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <Labeled label="Event type">
            {(id) => (
              <>
                <input id={id} list={`${id}-events`} className={field} value={a.event} onChange={(e) => set({ event: e.target.value as EventType })} />
                <datalist id={`${id}-events`}>
                  {EVENT_SUGGESTIONS.map((e) => (
                    <option key={e} value={e} />
                  ))}
                </datalist>
              </>
            )}
          </Labeled>
          <Labeled label="Tool name (optional)">
            {(id) => (
              <select id={id} className={field} value={a.name ?? ""} onChange={(e) => set({ name: e.target.value || null })}>
                <option value="">any</option>
                {b.tools.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            )}
          </Labeled>
        </div>
      );
    case "decision":
      return <DecisionForm d={a} set={set as Patch<Decision>} seed={seed} suggestions={b.judge_models} />;
  }
}

export interface KeyedAssertion {
  uid: number;
  a: Assertion;
}

export function AssertionsSection({ items, onChange, builder, seed, nextUid }: { items: KeyedAssertion[]; onChange: (items: KeyedAssertion[]) => void; builder: Builder; seed: Seed; nextUid: () => number }) {
  const add = (type: string) => onChange([...items, { uid: nextUid(), a: newAssertion(type, builder) }]);
  const patch = (uid: number, p: Partial<Assertion>) => onChange(items.map((it) => (it.uid === uid ? { uid, a: { ...it.a, ...p } as Assertion } : it)));
  return (
    <Card className="space-y-3 p-4">
      <SectionTitle>Assertions</SectionTitle>
      {items.length === 0 && <p className="text-ink2">No assertions yet. A scenario needs at least one check to be useful.</p>}
      <ul className="space-y-3">
        {items.map(({ uid, a }, i) => (
          <li key={uid} className="space-y-3 rounded-md border border-line p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={a.critical ? "block" : "neutral"}>{a.type}</Badge>
              <span className="text-[12px] text-ink2">
                {a.type === "output_matches" ? "Retired check type: remove it and use a decision check." : TYPE_HELP[a.type]}
              </span>
              <button type="button" className={`${btn} ml-auto`} onClick={() => onChange(items.filter((it) => it.uid !== uid))}>
                Remove check {i + 1}
              </button>
            </div>
            <AssertionBody a={a} set={(p) => patch(uid, p)} b={builder} seed={seed} />
            <Labeled label="Description (optional)" help="Shown in results. Leave empty to use the default.">
              {(id, d) => <input id={id} aria-describedby={d} className={field} value={a.description} onChange={(e) => patch(uid, { description: e.target.value })} />}
            </Labeled>
            <div className="grid gap-2 sm:grid-cols-2">
              <CheckField label="Critical" help="A failure here blocks the release." checked={a.critical} onChange={(critical) => patch(uid, { critical })} />
              <CheckField label="Requires faults" help="Skipped when a run disables the scenario's faults, since there is no failure to observe." checked={a.requires_faults} onChange={(requires_faults) => patch(uid, { requires_faults })} />
            </div>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        <Labeled label="Add a check">
          {(id) => (
            <select id={id} className={field} value="" onChange={(e) => e.target.value && add(e.target.value)}>
              <option value="">Choose a type...</option>
              {builder.assertion_types.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          )}
        </Labeled>
      </div>
    </Card>
  );
}
