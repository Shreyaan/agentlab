import { percent } from "../lib/format";

export const Progress = ({ done, total }: { done: number; total: number }) => {
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0;
  const live = done < total;
  return (
    <div className="flex items-center gap-2" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-sunken">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500"
          style={{
            width: `${pct}%`,
            ...(live && {
              backgroundImage:
                "linear-gradient(90deg, rgba(255,255,255,.28) 50%, transparent 50%)",
              backgroundSize: "16px 100%",
              animation: "stripes 0.8s linear infinite",
            }),
          }}
        />
      </div>
      <span className="text-[12px] text-ink2 tabular-nums">
        {done}/{total}
      </span>
    </div>
  );
};

/** Pass rate (dot) with its 95% confidence interval (bar) on a 0-100% track. */
export const CiBar = ({ rate, ci }: { rate: number | null; ci: readonly number[] }) => {
  if (rate == null) return <span className="text-ink3">no graded trials</span>;
  const [lo = 0, hi = 1] = ci;
  return (
    <div className="space-y-1">
      <div
        className="relative h-2 rounded-full bg-sunken"
        role="img"
        aria-label={`Pass rate ${percent(rate)}, 95% CI ${percent(lo)} to ${percent(hi)}`}
      >
        <div
          className="absolute inset-y-0 rounded-full bg-accent/35"
          style={{ left: `${lo * 100}%`, width: `${Math.max((hi - lo) * 100, 1)}%` }}
        />
        <div
          className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-accent"
          style={{ left: `${rate * 100}%` }}
        />
      </div>
      <div className="text-[11px] text-ink3 tabular-nums">
        95% CI {percent(lo)} to {percent(hi)}
      </div>
    </div>
  );
};

const BAR_TONE = { accent: "bg-accent", block: "bg-block", pass: "bg-pass" } as const;

/** A 0-1 probability as a labelled bar. */
export const ProbBar = ({ label, value, tone = "accent" }: { label: string; value: number; tone?: "accent" | "block" | "pass" }) => (
  <div className="flex items-center gap-2" role="img" aria-label={`${label}: ${percent(value)}`}>
    <span className="w-24 shrink-0 truncate text-[12px] text-ink2" title={label}>
      {label}
    </span>
    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-sunken">
      <div className={`h-full rounded-full ${BAR_TONE[tone]}`} style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }} />
    </div>
    <span className="w-10 shrink-0 text-right text-[12px] tabular-nums text-ink2">{percent(value)}</span>
  </div>
);
