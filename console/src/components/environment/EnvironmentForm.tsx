import { COLUMN_TYPES, PARAM_TYPES, RETURNS, blankColumn, blankParam, blankRule, blankTable, blankTool, type EnvColumn, type EnvParam, type EnvRule, type EnvSpec, type EnvTable, type EnvTool } from "../environment";
import { Card, CheckField, Labeled, SectionTitle, btn, field } from "../ui";
import { NumberField, Select } from "../builder/fields";

const mono = `${field} font-mono text-[12px]`;
const replaceAt = <T,>(list: T[], i: number, item: T): T[] => list.map((x, j) => (j === i ? item : x));
const removeAt = <T,>(list: T[], i: number): T[] => list.filter((_, j) => j !== i);

function ColumnRow({ column, onChange, onRemove, tableName }: { column: EnvColumn; onChange: (c: EnvColumn) => void; onRemove: () => void; tableName: string }) {
  const label = `${tableName || "table"}.${column.name || "column"}`;
  const set = (p: Partial<EnvColumn>) => onChange({ ...column, ...p });
  return (
    <li className="space-y-2 rounded-md border border-line p-2.5">
      <div className="grid gap-2 sm:grid-cols-[1fr_9rem_1fr_auto]">
        <input aria-label={`${label} name`} className={mono} placeholder="column_name" value={column.name} onChange={(e) => set({ name: e.target.value })} />
        <select aria-label={`${label} type`} className={field} value={column.type} onChange={(e) => set({ type: e.target.value as EnvColumn["type"] })}>
          {COLUMN_TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        <input aria-label={`${label} references`} className={mono} placeholder="references table.column" value={column.references ?? ""} onChange={(e) => set({ references: e.target.value || null })} />
        <button type="button" className={btn} aria-label={`Remove column ${label}`} onClick={onRemove}>
          Remove
        </button>
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1">
        <CheckField label="Primary key" checked={column.primary_key ?? false} onChange={(primary_key) => set({ primary_key, ...(primary_key ? { nullable: false } : {}) })} />
        <CheckField label="Unique" checked={column.unique ?? false} onChange={(unique) => set({ unique })} />
        <CheckField label="Nullable" checked={column.nullable ?? true} onChange={(nullable) => set({ nullable })} />
        <CheckField label="Serial" help="Auto-increment integer" checked={column.serial ?? false} onChange={(serial) => set({ serial })} />
      </div>
    </li>
  );
}

function TableEditor({ table, onChange, onRemove }: { table: EnvTable; onChange: (t: EnvTable) => void; onRemove: () => void }) {
  return (
    <li className="space-y-3 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-end gap-2">
        <Labeled label="Table name" className="min-w-48 flex-1">
          {(id) => <input id={id} className={mono} placeholder="orders" value={table.name} onChange={(e) => onChange({ ...table, name: e.target.value })} />}
        </Labeled>
        <button type="button" className={btn} onClick={onRemove}>
          Remove table
        </button>
      </div>
      <ul className="space-y-2">
        {table.columns.map((c, i) => (
          <ColumnRow key={i} tableName={table.name} column={c} onChange={(nc) => onChange({ ...table, columns: replaceAt(table.columns, i, nc) })} onRemove={() => onChange({ ...table, columns: removeAt(table.columns, i) })} />
        ))}
      </ul>
      <button type="button" className={btn} onClick={() => onChange({ ...table, columns: [...table.columns, blankColumn()] })}>
        Add column
      </button>
    </li>
  );
}

function ParamRow({ param, toolName, onChange, onRemove }: { param: EnvParam; toolName: string; onChange: (p: EnvParam) => void; onRemove: () => void }) {
  const label = `${toolName || "tool"}.${param.name || "param"}`;
  const set = (p: Partial<EnvParam>) => onChange({ ...param, ...p });
  return (
    <li className="grid gap-2 sm:grid-cols-[1fr_8rem_1fr_1fr_auto_auto] sm:items-center">
      <input aria-label={`${label} name`} className={mono} placeholder="name" value={param.name} onChange={(e) => set({ name: e.target.value })} />
      <select aria-label={`${label} type`} className={field} value={param.type} onChange={(e) => set({ type: e.target.value as EnvParam["type"] })}>
        {PARAM_TYPES.map((t) => (
          <option key={t}>{t}</option>
        ))}
      </select>
      <input aria-label={`${label} description`} className={field} placeholder="description" value={param.description ?? ""} onChange={(e) => set({ description: e.target.value })} />
      <input aria-label={`${label} allowed values`} className={mono} placeholder="enum: a, b, c" value={(param.enum ?? []).join(", ")} onChange={(e) => set({ enum: e.target.value.trim() ? e.target.value.split(",").map((v) => v.trim()).filter(Boolean) : null })} />
      <label className="flex items-center gap-1.5">
        <input type="checkbox" checked={param.required ?? true} onChange={(e) => set({ required: e.target.checked })} />
        required
      </label>
      <button type="button" className={btn} aria-label={`Remove parameter ${label}`} onClick={onRemove}>
        Remove
      </button>
    </li>
  );
}

function RuleRow({ rule, label, onChange, onRemove }: { rule: EnvRule; label: string; onChange: (r: EnvRule) => void; onRemove: () => void }) {
  return (
    <li className="space-y-2 rounded-md border border-line p-2.5">
      <textarea aria-label={`${label} SQL`} rows={2} spellCheck={false} className={mono} placeholder="SELECT ... (one boolean cell; true = reject)" value={rule.sql} onChange={(e) => onChange({ ...rule, sql: e.target.value })} />
      <div className="grid gap-2 sm:grid-cols-[6rem_1fr_auto]">
        <input aria-label={`${label} status`} type="number" min={400} max={499} className={field} value={rule.status ?? 409} onChange={(e) => onChange({ ...rule, status: Number(e.target.value) })} />
        <input aria-label={`${label} error message`} className={field} placeholder="error message returned to the agent" value={rule.error} onChange={(e) => onChange({ ...rule, error: e.target.value })} />
        <button type="button" className={btn} onClick={onRemove}>
          Remove rule
        </button>
      </div>
    </li>
  );
}

function ToolEditor({ tool, onChange, onRemove }: { tool: EnvTool; onChange: (t: EnvTool) => void; onRemove: () => void }) {
  const set = (p: Partial<EnvTool>) => onChange({ ...tool, ...p });
  const params = tool.params ?? [];
  const rules = tool.rules ?? [];
  return (
    <li className="space-y-3 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-end gap-2">
        <Labeled label="Tool name" className="min-w-48 flex-1">
          {(id) => <input id={id} className={mono} placeholder="create_order" value={tool.name} onChange={(e) => set({ name: e.target.value })} />}
        </Labeled>
        <button type="button" className={btn} onClick={onRemove}>
          Remove tool
        </button>
      </div>
      <Labeled label="Description" help="Shown to agents in the tool catalog: say what it does and when to use it.">
        {(id, d) => <textarea id={id} aria-describedby={d} rows={2} className={field} value={tool.description} onChange={(e) => set({ description: e.target.value })} />}
      </Labeled>
      <fieldset className="space-y-2">
        <legend className="font-medium">Parameters</legend>
        <ul className="space-y-2">
          {params.map((p, i) => (
            <ParamRow key={i} toolName={tool.name} param={p} onChange={(np) => set({ params: replaceAt(params, i, np) })} onRemove={() => set({ params: removeAt(params, i) })} />
          ))}
        </ul>
        <button type="button" className={btn} onClick={() => set({ params: [...params, blankParam()] })}>
          Add parameter
        </button>
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="font-medium">Rules</legend>
        <p className="text-[12px] text-ink2">Preconditions run before the effect, with parameters bound as %(name)s. When a rule's SELECT returns true the call fails with its status and message and changes nothing.</p>
        <ul className="space-y-2">
          {rules.map((r, i) => (
            <RuleRow key={i} label={`${tool.name || "tool"} rule ${i + 1}`} rule={r} onChange={(nr) => set({ rules: replaceAt(rules, i, nr) })} onRemove={() => set({ rules: removeAt(rules, i) })} />
          ))}
        </ul>
        <button type="button" className={btn} onClick={() => set({ rules: [...rules, blankRule()] })}>
          Add rule
        </button>
      </fieldset>
      <Labeled label="Effect SQL" help="One statement. Bind parameters as %(name)s and use RETURNING to send rows back.">
        {(id, d) => <textarea id={id} aria-describedby={d} rows={4} spellCheck={false} className={mono} value={tool.sql} onChange={(e) => set({ sql: e.target.value })} />}
      </Labeled>
      <div className="grid gap-3 sm:grid-cols-3">
        <Select label="Returns" help="row: first row or 404. rows: a list. none: {}." value={tool.returns ?? "row"} options={RETURNS} onChange={(returns) => set({ returns })} />
        <NumberField label="Success status" min={200} max={299} value={tool.success_status ?? 200} onChange={(v) => set({ success_status: v ?? 200 })} />
        <div className="space-y-2">
          <CheckField label="Mutates" help="Off for read-only tools." checked={tool.mutates ?? true} onChange={(mutates) => set({ mutates })} />
          <CheckField label="Idempotent" help="A repeated idempotency_key replays the first response." checked={tool.idempotent ?? false} onChange={(idempotent) => set({ idempotent })} />
        </div>
      </div>
    </li>
  );
}

type Patch = (p: Partial<EnvSpec>) => void;

export function EnvironmentForm({ spec, set, versionNote }: { spec: EnvSpec; set: Patch; versionNote: string }) {
  return (
    <div className="min-w-0 space-y-4">
      <Card className="space-y-3 p-4">
        <SectionTitle>Identity</SectionTitle>
        <Labeled label="Environment id" help={versionNote}>
          {(id, d) => <input id={id} aria-describedby={d} className={mono} required placeholder="refund" value={spec.id} onChange={(e) => set({ id: e.target.value })} />}
        </Labeled>
        <Labeled label="Description" help="Also given to agents as context about the world they operate in.">
          {(id, d) => <textarea id={id} aria-describedby={d} rows={3} className={field} value={spec.description} onChange={(e) => set({ description: e.target.value })} />}
        </Labeled>
      </Card>
      <Card className="space-y-3 p-4">
        <SectionTitle aside={<button type="button" className={btn} onClick={() => set({ tables: [...spec.tables, blankTable()] })}>Add table</button>}>Tables</SectionTitle>
        <ul className="space-y-3">
          {spec.tables.map((t, i) => (
            <TableEditor key={i} table={t} onChange={(nt) => set({ tables: replaceAt(spec.tables, i, nt) })} onRemove={() => set({ tables: removeAt(spec.tables, i) })} />
          ))}
        </ul>
      </Card>
      <Card className="space-y-3 p-4">
        <SectionTitle aside={<button type="button" className={btn} onClick={() => set({ tools: [...spec.tools, blankTool()] })}>Add tool</button>}>Tools</SectionTitle>
        <ul className="space-y-3">
          {spec.tools.map((t, i) => (
            <ToolEditor key={i} tool={t} onChange={(nt) => set({ tools: replaceAt(spec.tools, i, nt) })} onRemove={() => set({ tools: removeAt(spec.tools, i) })} />
          ))}
        </ul>
      </Card>
    </div>
  );
}
