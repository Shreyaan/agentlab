import type { Schema } from "../../api/client";
import type { ScenarioDraft } from "../scenario";
import { Card, Labeled, SectionTitle, btn, field } from "../ui";
import { JsonField, NumberField, Select, TagInput } from "./fields";

export type Scenario = ScenarioDraft;
export type Fault = Schema["ScenarioFault"];
type Builder = Schema["BuilderInfo"];
type Row = Schema["Row"];
type Patch = (p: Partial<Scenario>) => void;

const TIERS = ["critical", "high", "normal"] as const;

export function IdentitySection({ s, set, versionNote }: { s: Scenario; set: Patch; versionNote: string }) {
  return (
    <Card className="p-4">
      <SectionTitle>Identity</SectionTitle>
      <div className="grid gap-3 sm:grid-cols-2">
        <Labeled label="Scenario id" help={versionNote}>
          {(id, d) => <input id={id} aria-describedby={d} className={field} required value={s.id} onChange={(e) => set({ id: e.target.value })} placeholder="refund.timeout" />}
        </Labeled>
        <Select label="Risk tier" help="Critical scenarios weigh most in the release gate." value={s.risk_tier} options={TIERS} onChange={(risk_tier) => set({ risk_tier })} />
        <Labeled label="Source" help="Where this case came from, e.g. synthetic or production_incident.">
          {(id, d) => <input id={id} aria-describedby={d} className={field} value={s.source} onChange={(e) => set({ source: e.target.value })} />}
        </Labeled>
        <TagInput label="Slices" help="Tags for grouping results, e.g. refund, timeout." values={s.slices} onChange={(slices) => set({ slices })} />
      </div>
    </Card>
  );
}

type SeedTable = { [K in keyof Scenario["fixture"]]: Scenario["fixture"][K] extends Row[] ? K : never }[keyof Scenario["fixture"]];

const cellValue = (column: string, text: string): string | number => (column.endsWith("_cents") && text.trim() !== "" && !Number.isNaN(Number(text)) ? Number(text) : text);

function SeedTableEditor({ table, columns, rows, onChange }: { table: string; columns: string[]; rows: Row[]; onChange: (rows: Row[]) => void }) {
  const setCell = (i: number, col: string, text: string) => onChange(rows.map((r, j) => (j === i ? { ...r, [col]: cellValue(col, text) } : r)));
  const blank = (): Row => Object.fromEntries(columns.map((c) => [c, ""]));
  return (
    <div className="space-y-1.5">
      <h3 className="font-medium">{table}</h3>
      {rows.length === 0 ? (
        <p className="text-ink2">No rows.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c} className="px-1 pb-1 text-left text-[12px] font-medium text-ink2">
                    {c}
                  </th>
                ))}
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {columns.map((c) => (
                    <td key={c} className="p-0.5">
                      <input aria-label={`${table} row ${i + 1} ${c}`} className={field} value={String(r[c] ?? "")} onChange={(e) => setCell(i, c, e.target.value)} />
                    </td>
                  ))}
                  <td className="p-0.5">
                    <button type="button" className="cursor-pointer px-1.5 text-ink2 hover:text-block" aria-label={`Remove ${table} row ${i + 1}`} onClick={() => onChange(rows.filter((_, j) => j !== i))}>
                      x
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <button type="button" className={btn} onClick={() => onChange([...rows, blank()])}>
        Add {table} row
      </button>
    </div>
  );
}

export function SeedSection({ s, set, builder }: { s: Scenario; set: Patch; builder: Builder }) {
  const fixture = s.fixture;
  const tables = Object.entries(builder.seed_columns).filter((e): e is [SeedTable & string, string[]] => Array.isArray(fixture[e[0] as SeedTable]));
  return (
    <Card className="space-y-4 p-4">
      <SectionTitle>Seed data</SectionTitle>
      <p className="text-ink2">The starting state of the environment database for every run of this scenario. Amount columns ending in _cents are numbers.</p>
      {tables.map(([table, columns]) => (
        <SeedTableEditor key={table} table={table} columns={columns} rows={fixture[table]} onChange={(rows) => set({ fixture: { ...fixture, [table]: rows } })} />
      ))}
      <div className="max-w-xs">
        <NumberField label="Approval limit (cents)" help="Refunds above this amount are denied by the approval service." min={0} value={fixture.approval_limit_cents ?? null} onChange={(v) => set({ fixture: { ...fixture, approval_limit_cents: v ?? 0 } })} />
      </div>
    </Card>
  );
}

export function InputSection({ s, set }: { s: Scenario; set: Patch }) {
  const message = typeof s.input.message === "string" ? s.input.message : "";
  return (
    <Card className="space-y-3 p-4">
      <SectionTitle>Input</SectionTitle>
      <Labeled label="Message" help="What the user says to the agent.">
        {(id, d) => <textarea id={id} aria-describedby={d} rows={2} className={field} value={message} onChange={(e) => set({ input: { ...s.input, message: e.target.value } })} />}
      </Labeled>
      <details>
        <summary className="cursor-pointer text-ink2 hover:text-ink">Advanced: edit the whole input object</summary>
        <div className="mt-2">
          <JsonField object rows={6} label="Input JSON" help="Sent to the agent as-is. Agents that read other fields than message need them here." value={s.input} onChange={(v) => set({ input: v as Scenario["input"] })} />
        </div>
      </details>
    </Card>
  );
}

const ACTIONS: Record<Fault["action"], string> = {
  timeout_after_commit: "The call succeeds but the agent sees a timeout. Tests whether it retries and duplicates the side effect.",
  error_before_commit: "The call fails before anything happens. Tests whether the agent recovers cleanly.",
};
const WHEN_HELP: Record<"first_call" | "always" | "nth", string> = {
  first_call: "Only the first call to this tool fails.",
  always: "Every call to this tool fails.",
  nth: "Only the Nth call (1 is the first) fails.",
};
const BOUNDARY_HELP: Record<Fault["boundary"], string> = {
  fixture: "Injected by the environment service. Works for every agent.",
  harness: "Injected by the agent's adapter. Needs a target that can intercept tools.",
};
const whenKind = (w: Fault["when"]): keyof typeof WHEN_HELP => (typeof w === "number" ? "nth" : w);

function FaultRow({ fault, tools, onChange, onRemove }: { fault: Fault; tools: string[]; onChange: (f: Fault) => void; onRemove: () => void }) {
  const kind = whenKind(fault.when);
  return (
    <li className="space-y-2 rounded-md border border-line p-3">
      <div className="grid gap-3 sm:grid-cols-4">
        <Select label="Tool" value={fault.tool} options={tools} onChange={(tool) => onChange({ ...fault, tool })} />
        <Select label="Action" value={fault.action} options={Object.keys(ACTIONS) as Fault["action"][]} onChange={(action) => onChange({ ...fault, action })} />
        <div className="space-y-1">
          <Select label="When" value={kind} options={["first_call", "always", "nth"] as const} onChange={(k) => onChange({ ...fault, when: k === "nth" ? 1 : k })} />
          {typeof fault.when === "number" && (
            <input aria-label="Call number" type="number" min={1} className={field} value={fault.when} onChange={(e) => onChange({ ...fault, when: Math.max(1, Number(e.target.value) || 1) })} />
          )}
        </div>
        <Select label="Boundary" value={fault.boundary} options={["fixture", "harness"] as const} onChange={(boundary) => onChange({ ...fault, boundary })} />
      </div>
      <p className="text-[12px] text-ink2">
        {ACTIONS[fault.action]} {WHEN_HELP[kind]} {BOUNDARY_HELP[fault.boundary]}
      </p>
      <button type="button" className={btn} onClick={onRemove}>
        Remove fault
      </button>
    </li>
  );
}

export function FaultsSection({ s, set, builder }: { s: Scenario; set: Patch; builder: Builder }) {
  const add = () => set({ faults: [...s.faults, { tool: builder.tools[0] ?? "", when: "first_call", action: "timeout_after_commit", boundary: "fixture" }] });
  return (
    <Card className="space-y-3 p-4">
      <SectionTitle aside={<button type="button" className={btn} onClick={add}>Add fault</button>}>Faults</SectionTitle>
      {s.faults.length === 0 ? (
        <p className="text-ink2">No faults: the environment behaves normally.</p>
      ) : (
        <ul className="space-y-2">
          {s.faults.map((f, i) => (
            <FaultRow key={i} fault={f} tools={builder.tools} onChange={(nf) => set({ faults: s.faults.map((x, j) => (j === i ? nf : x)) })} onRemove={() => set({ faults: s.faults.filter((_, j) => j !== i) })} />
          ))}
        </ul>
      )}
    </Card>
  );
}

export function BudgetSection({ s, set }: { s: Scenario; set: Patch }) {
  const b = s.budget;
  const put = (p: Partial<Scenario["budget"]>) => set({ budget: { ...b, ...p } });
  return (
    <Card className="p-4">
      <SectionTitle>Budget</SectionTitle>
      <p className="mb-3 text-ink2">Optional limits. Each one adds a check that fails when exceeded. Leave empty for no limit.</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <NumberField label="Max tool calls" min={0} value={b.max_tool_calls ?? null} onChange={(v) => put({ max_tool_calls: v })} />
        <NumberField label="Max latency (ms)" min={0} value={b.max_latency_ms ?? null} onChange={(v) => put({ max_latency_ms: v })} />
        <NumberField label="Max cost (USD)" min={0} step={0.001} value={b.max_cost_usd ?? null} onChange={(v) => put({ max_cost_usd: v })} />
      </div>
    </Card>
  );
}
