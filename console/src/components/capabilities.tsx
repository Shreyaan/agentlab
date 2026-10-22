import type { Schema } from "../api/client";
import { Badge } from "./ui";

type Caps = Schema["Capabilities"];

interface CapabilityRow {
  key: string;
  label: string;
  active: (c: Caps) => boolean;
  value: (c: Caps) => string;
  meaning: string;
}

export const CAPABILITY_ROWS: CapabilityRow[] = [
  {
    key: "observe",
    label: "observe",
    active: (c) => c.observe !== "none",
    value: (c) => c.observe,
    meaning:
      "Can the harness report what it did? native_events = full step-by-step events; otel_partial = only what OpenTelemetry traces show; none = only the outcome is visible.",
  },
  {
    key: "intercept_tools",
    label: "intercept_tools",
    active: (c) => c.intercept_tools !== "none",
    value: (c) => c.intercept_tools,
    meaning: "Can AgentLab make the harness's own tool calls fail on purpose (harness-boundary faults)?",
  },
  {
    key: "checkpoint",
    label: "checkpoint",
    active: (c) => c.checkpoint,
    value: (c) => String(c.checkpoint),
    meaning: "Can the agent save its state mid-run so a run can later be continued from that point?",
  },
  {
    key: "resume",
    label: "resume",
    active: (c) => c.resume,
    value: (c) => String(c.resume),
    meaning: "Can the agent restart from a saved checkpoint?",
  },
  {
    key: "fork",
    label: "fork",
    active: (c) => c.fork,
    value: (c) => String(c.fork),
    meaning: "Can a new run branch off a checkpoint, for example to replay with different faults?",
  },
];

export const INVOKE_MEANING = "Can AgentLab send a task to this target and get a result? Observe-only targets cannot be run.";

export const canFork = (m: Schema["Manifest"] | null): boolean => !!m && m.capabilities.resume && m.capabilities.fork;

export const CapabilityBadges = ({ caps }: { caps: Caps }) => (
  <div className="flex flex-wrap gap-1">
    <Badge tone={caps.invoke ? "accent" : "warn"} title={INVOKE_MEANING}>
      invoke
    </Badge>
    {CAPABILITY_ROWS.map((r) => (
      <Badge key={r.key} tone={r.active(caps) ? "info" : "neutral"} title={r.meaning}>
        {r.active(caps) ? r.label : `no ${r.label}`}
      </Badge>
    ))}
  </div>
);

/** A target can be run only when it is reachable and invokable (otel targets declare invoke=false). */
export const runnableProblem = (t: Schema["TargetHealth"]): string | null => {
  if (!t.reachable) return t.error ? `Unreachable: ${t.error}` : "Unreachable";
  if (t.manifest && !t.manifest.capabilities.invoke) return "Observe-only: it cannot be invoked, so it cannot be run";
  if (t.mode === "otel") return "OTel targets are observe-only: they cannot be invoked";
  return null;
};
