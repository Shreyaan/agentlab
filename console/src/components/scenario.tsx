import type { Schema } from "../api/client";
import type { Tone } from "./ui";

/** The API splits request (Input) and response (Output) shapes; the editor edits Input, the viewers read Output. */
export type Scenario = Schema["Scenario-Output"];
export type ScenarioDraft = Schema["Scenario-Input"];
export type Assertion = Schema["Assertion-Output"];
export type AssertionDraft = Schema["Assertion-Input"];

export const TIER_TONE: Record<Scenario["risk_tier"], Tone> = { critical: "block", high: "warn", normal: "neutral" };

export const faultLabel = (f: Schema["ScenarioFault"]): string => `${f.action} on ${f.tool}`;

export const faultSummary = (s: Scenario): string =>
  s.faults.length ? s.faults.map(faultLabel).join(", ") : "no faults";
