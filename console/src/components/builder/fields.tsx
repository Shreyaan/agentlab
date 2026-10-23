import { useEffect, useState, type KeyboardEvent } from "react";
import { Badge, Labeled, field } from "../ui";

/** Text that edits a JSON value. In `object` mode invalid JSON is reported; otherwise it falls back to a plain string. */
const reparsesAsOther = (s: string): boolean => {
  try {
    JSON.parse(s);
    return true;
  } catch {
    return false;
  }
};

export function JsonField({
  value,
  onChange,
  object = false,
  rows = 1,
  label,
  help,
}: {
  value: unknown;
  onChange: (v: unknown) => void;
  object?: boolean;
  rows?: number;
  label: string;
  help?: string;
}) {
  // A string that would re-parse as other JSON (e.g. "1", "true") is shown quoted so editing round-trips.
  const pretty = (v: unknown): string => {
    if (object) return JSON.stringify(v, null, 2);
    if (typeof v === "string" && !reparsesAsOther(v)) return v;
    return JSON.stringify(v);
  };
  const [text, setText] = useState(() => pretty(value));
  const [error, setError] = useState<string | null>(null);

  const parse = (t: string): { ok: true; v: unknown } | { ok: false; message: string } => {
    try {
      const v: unknown = JSON.parse(t);
      if (object && (typeof v !== "object" || v === null || Array.isArray(v))) return { ok: false, message: "Must be a JSON object." };
      return { ok: true, v };
    } catch (e) {
      return object ? { ok: false, message: e instanceof Error ? e.message : "Invalid JSON" } : { ok: true, v: t };
    }
  };

  // Resync when the value changes from outside (e.g. the message field) and no longer matches what is typed.
  useEffect(() => {
    const parsed = parse(text);
    if (!parsed.ok || JSON.stringify(parsed.v) !== JSON.stringify(value)) {
      setText(pretty(value));
      setError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const edit = (t: string) => {
    setText(t);
    const parsed = parse(t);
    if (parsed.ok) {
      setError(null);
      onChange(parsed.v);
    } else setError(parsed.message);
  };

  return (
    <Labeled label={label} help={error ?? help}>
      {(id, d) =>
        rows > 1 ? (
          <textarea id={id} aria-describedby={d} aria-invalid={!!error} rows={rows} spellCheck={false} className={`${field} font-mono text-[12px]`} value={text} onChange={(e) => edit(e.target.value)} />
        ) : (
          <input id={id} aria-describedby={d} aria-invalid={!!error} spellCheck={false} className={`${field} font-mono text-[12px]`} value={text} onChange={(e) => edit(e.target.value)} />
        )
      }
    </Labeled>
  );
}

export function TagInput({ label, help, values, onChange }: { label: string; help?: string; values: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  };
  const key = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !draft && values.length) onChange(values.slice(0, -1));
  };
  return (
    <Labeled label={label} help={help}>
      {(id, d) => (
        <div className="space-y-1.5">
          <input id={id} aria-describedby={d} className={field} value={draft} placeholder="Type and press Enter" onChange={(e) => setDraft(e.target.value)} onKeyDown={key} onBlur={add} />
          {values.length > 0 && (
            <ul className="flex flex-wrap gap-1">
              {values.map((v) => (
                <li key={v}>
                  <Badge tone="info">
                    {v}
                    <button type="button" aria-label={`Remove ${v}`} className="cursor-pointer" onClick={() => onChange(values.filter((x) => x !== v))}>
                      x
                    </button>
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Labeled>
  );
}

export function Select<T extends string>({ label, help, value, options, onChange }: { label: string; help?: string; value: T; options: readonly T[]; onChange: (v: T) => void }) {
  return (
    <Labeled label={label} help={help}>
      {(id, d) => (
        <select id={id} aria-describedby={d} className={field} value={value} onChange={(e) => onChange(e.target.value as T)}>
          {!options.includes(value) && <option value={value}>{value}</option>}
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      )}
    </Labeled>
  );
}

export function NumberField({ label, help, value, onChange, min, max, step }: { label: string; help?: string; value: number | null; onChange: (v: number | null) => void; min?: number; max?: number; step?: number }) {
  return (
    <Labeled label={label} help={help}>
      {(id, d) => (
        <input id={id} aria-describedby={d} type="number" className={field} min={min} max={max} step={step} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
      )}
    </Labeled>
  );
}
