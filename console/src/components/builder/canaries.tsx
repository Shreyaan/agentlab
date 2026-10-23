import { useState } from "react";
import type { Schema } from "../../api/client";
import { Labeled, btn, field } from "../ui";
import { JsonField } from "./fields";

type Canary = Schema["Canary"];
type Evidence = Canary["evidence"];

export const CANARY_HELP = "Labelled examples that measure whether a judge reaches the right verdict; a critical check can only block once its judge is right on them.";

const EXPECTED: readonly Canary["expected"][] = ["pass", "fail"];

const blankCanary = (n: number): Canary => ({ label: `Example ${n}`, expected: "pass", evidence: {} });

/** Sets or removes one evidence key, so an emptied field is not sent as an empty value. */
const withKey = (evidence: Evidence, key: string, value: unknown): Evidence => {
  const { [key]: _old, ...rest } = evidence;
  return value === undefined ? rest : { ...rest, [key]: value };
};

function EvidenceEditor({ evidence, onChange, name }: { evidence: Evidence; onChange: (e: Evidence) => void; name: string }) {
  const [raw, setRaw] = useState(false);
  return (
    <div className="space-y-2">
      {raw ? (
        <JsonField object rows={8} label={`${name}: evidence (raw JSON)`} help="Exactly what the judge sees, keyed by evidence kind." value={evidence} onChange={(v) => onChange(v as Evidence)} />
      ) : (
        <>
          <Labeled label={`${name}: output`} help="The agent's final reply, as the judge would see it.">
            {(id, h) => <textarea id={id} aria-describedby={h} rows={3} className={field} value={typeof evidence.output === "string" ? evidence.output : ""} onChange={(e) => onChange(withKey(evidence, "output", e.target.value || undefined))} />}
          </Labeled>
          <JsonField object rows={5} label={`${name}: final_state`} help="Database tables after the run, as a JSON object." value={evidence.final_state ?? {}} onChange={(v) => onChange(withKey(evidence, "final_state", v))} />
        </>
      )}
      <button type="button" className={btn} aria-pressed={raw} onClick={() => setRaw(!raw)}>
        {raw ? "Back to fields" : "Advanced: raw JSON"}
      </button>
    </div>
  );
}

export function CanariesEditor({ canaries, onChange }: { canaries: Canary[]; onChange: (c: Canary[]) => void }) {
  const update = (i: number, p: Partial<Canary>) => onChange(canaries.map((c, j) => (j === i ? { ...c, ...p } : c)));
  return (
    <fieldset className="space-y-3 rounded-md border border-line p-3">
      <legend className="px-1 font-medium">Canaries</legend>
      <p className="text-[12px] text-ink2">{CANARY_HELP}</p>
      {canaries.map((c, i) => {
        const name = c.label || `Canary ${i + 1}`;
        return (
          <div key={i} className="space-y-2 rounded-md bg-sunken p-3">
            <div className="flex flex-wrap items-end gap-2">
              <Labeled label="Label" className="min-w-40 flex-1">
                {(id) => <input id={id} className={field} value={c.label} onChange={(e) => update(i, { label: e.target.value })} />}
              </Labeled>
              <fieldset className="flex gap-3 pb-1.5">
                <legend className="sr-only">Expected verdict for {name}</legend>
                {EXPECTED.map((x) => (
                  <label key={x} className="flex cursor-pointer items-center gap-1.5">
                    <input type="radio" name={`expected-${i}`} checked={c.expected === x} onChange={() => update(i, { expected: x })} />
                    expected {x}
                  </label>
                ))}
              </fieldset>
              <button type="button" className={btn} aria-label={`Remove ${name}`} onClick={() => onChange(canaries.filter((_, j) => j !== i))}>
                Remove
              </button>
            </div>
            <EvidenceEditor name={name} evidence={c.evidence} onChange={(evidence) => update(i, { evidence })} />
          </div>
        );
      })}
      <button type="button" className={btn} onClick={() => onChange([...canaries, blankCanary(canaries.length + 1)])}>
        Add canary
      </button>
    </fieldset>
  );
}
