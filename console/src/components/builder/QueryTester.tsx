import type { Schema } from "../../api/client";
import { useTestQuery } from "../../api/hooks";
import { Notice, btn } from "../ui";

/** Runs a read-only SQL query against the draft's seed data and shows the scalar value, the rows, or the error. */
export function QueryTester({ seed, query }: { seed: Schema["Seed"]; query: string }) {
  const test = useTestQuery();
  const r = test.data;
  return (
    <div className="space-y-2">
      <button type="button" className={btn} disabled={test.isPending || !query.trim()} onClick={() => test.mutate({ seed, query })}>
        {test.isPending ? "Running..." : "Test query"}
      </button>
      {test.isError && <Notice tone="block">{test.error.message}</Notice>}
      {r && (r.ok ? (
        <div className="space-y-1 rounded-md bg-sunken p-2.5">
          <p>
            Value: <code>{JSON.stringify(r.value)}</code>
          </p>
          <details>
            <summary className="cursor-pointer text-[12px] text-ink2">{r.rows.length} row(s)</summary>
            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap">{JSON.stringify(r.rows)}</pre>
          </details>
        </div>
      ) : (
        <Notice tone="block">{r.error ?? "Query failed."}</Notice>
      ))}
    </div>
  );
}
