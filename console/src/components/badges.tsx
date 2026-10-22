import type { Schema } from "../api/client";
import { Badge, type Tone } from "./ui";

const DECISION: Record<Schema["GateStatus"], { tone: Tone; label: string }> = {
  PASS: { tone: "pass", label: "PASS" },
  BLOCK: { tone: "block", label: "BLOCK" },
  INSUFFICIENT_EVIDENCE: { tone: "warn", label: "INSUFFICIENT EVIDENCE" },
};

export const DecisionBadge = ({ decision }: { decision: Schema["GateStatus"] | null }) =>
  decision ? <Badge tone={DECISION[decision].tone}>{DECISION[decision].label}</Badge> : <span className="text-ink3">-</span>;

export const decisionTone = (d: Schema["GateStatus"]): Tone => DECISION[d].tone;

const STATUS: Record<Schema["ExperimentStatus"] | Schema["TrialStatus"], Tone> = {
  running: "info",
  complete: "neutral",
  incomplete: "warn",
  passed: "pass",
  failed: "block",
  error: "warn",
};

export const StatusBadge = ({ status }: { status: keyof typeof STATUS }) => (
  <Badge tone={STATUS[status]}>{status}</Badge>
);

export const ReachDot = ({ reachable }: { reachable: boolean }) => (
  <span
    role="img"
    aria-label={reachable ? "reachable" : "unreachable"}
    title={reachable ? "Reachable" : "Unreachable"}
    className={`inline-block size-2 shrink-0 rounded-full ${reachable ? "bg-pass" : "bg-block"}`}
  />
);
