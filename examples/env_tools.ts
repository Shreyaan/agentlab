// Tool layer shared by the TypeScript example agents: tools come from the environment's catalog at runtime.
export type CatalogTool = { name: string; description: string; parameters: Record<string, unknown> };
export type Catalog = { environment: string; description: string; tools: CatalogTool[] };

const base = (url: string) => url.replace(/\/+$/, "");

export async function loadCatalog(baseUrl: string): Promise<Catalog> {
  const r = await fetch(`${base(baseUrl)}/tools`, { signal: AbortSignal.timeout(10_000) });
  if (!r.ok) throw new Error(`GET /tools -> HTTP ${r.status}`);
  return (await r.json()) as Catalog;
}

/** Prompt file plus the environment's own description as context. */
export async function systemPrompt(prompt: string, catalog: Catalog): Promise<string> {
  const text = await Bun.file(new URL(`./prompts/${prompt}.md`, import.meta.url)).text();
  return `${text.trim()}\n\nEnvironment: ${catalog.description}`;
}

/** Exactly one POST. 4xx/5xx throw (a 504 may still have committed). */
export async function postTool(baseUrl: string, name: string, args: unknown): Promise<string> {
  const r = await fetch(`${base(baseUrl)}/tools/${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(args ?? {}),
    signal: AbortSignal.timeout(10_000),
  });
  const body = await r.text();
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${body.slice(0, 500)}`);
  return body;
}

/** Failures go back to the model as an `{"error": ...}` result, never crash the run. */
export async function errorAsResult(fn: () => Promise<string>): Promise<string> {
  try {
    return await fn();
  } catch (e) {
    return JSON.stringify({ error: e instanceof Error ? e.message : String(e) });
  }
}
