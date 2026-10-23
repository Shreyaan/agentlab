import type { Schema } from "../api/client";

/** Provisional aliases: regenerate types (`bun run gen:api`) and these resolve to the backend's EnvironmentSpec. */
export type EnvSpec = Schema["EnvironmentSpec"];
export type EnvSpecView = Schema["EnvironmentInfo"]["environment"];
export type EnvColumn = EnvSpec["tables"][number]["columns"][number];
export type EnvTable = EnvSpec["tables"][number];
export type EnvTool = EnvSpec["tools"][number];
export type EnvParam = NonNullable<EnvTool["params"]>[number];
export type EnvRule = NonNullable<EnvTool["rules"]>[number];

export const COLUMN_TYPES = ["text", "integer", "bigint", "numeric", "boolean", "timestamptz", "jsonb"] as const satisfies readonly EnvColumn["type"][];
export const PARAM_TYPES = ["string", "integer", "number", "boolean"] as const satisfies readonly EnvParam["type"][];
export const RETURNS = ["row", "rows", "none"] as const satisfies readonly NonNullable<EnvTool["returns"]>[];

export const blankColumn = (): EnvColumn => ({ name: "", type: "text", primary_key: false, nullable: true, unique: false, serial: false, references: null });
export const blankTable = (): EnvTable => ({ name: "", columns: [{ ...blankColumn(), name: "id", type: "integer", primary_key: true, nullable: false, serial: true }] });
export const blankParam = (): EnvParam => ({ name: "", type: "string", description: "", required: true, enum: null });
export const blankRule = (): EnvRule => ({ sql: "", status: 409, error: "" });
export const blankTool = (): EnvTool => ({ name: "", description: "", params: [], rules: [], sql: "", returns: "row", success_status: 200, idempotent: false, mutates: true });
export const blankEnvironment = (): EnvSpec => ({ id: "", version: 1, description: "", tables: [blankTable()], tools: [blankTool()] });

export const envOf = (key: string): string => key.split("@")[0] ?? key;

/** What an agent connects to: the base URL native adapters receive (req.environment.base_url) plus two endpoints under it. */
export const CONNECT_PATTERNS = {
  catalog: "<fixture-url>/env/<trial-env-id>/tools",
  mcp: "<fixture-url>/env/<trial-env-id>/mcp",
} as const;
