import type { Schema } from "../api/client";
import type { Tone } from "./ui";

export const TIER_TONE: Record<Schema["Scenario"]["risk_tier"], Tone> = { critical: "block", high: "warn", normal: "neutral" };

export const faultLabel = (f: Schema["ScenarioFault"]): string => `${f.action} on ${f.tool}`;

export const faultSummary = (s: Schema["Scenario"]): string =>
  s.faults.length ? s.faults.map(faultLabel).join(", ") : "no faults";
