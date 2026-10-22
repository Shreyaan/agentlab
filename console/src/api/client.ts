import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schema = components["schemas"];

const TOKEN_KEY = "agentlab.token";
const UNAUTHORIZED_EVENT = "agentlab:unauthorized";

export const tokenStore = {
  get: (): string | null => {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (token: string): void => {
    try {
      sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* storage unavailable: the prompt will reappear on the next 401 */
    }
  },
};

export const onUnauthorized = (handler: () => void): (() => void) => {
  window.addEventListener(UNAUTHORIZED_EVENT, handler);
  return () => window.removeEventListener(UNAUTHORIZED_EVENT, handler);
};

const middleware: Middleware = {
  onRequest({ request }) {
    const token = tokenStore.get();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    if (request.method === "POST") request.headers.set("X-AgentLab-Request", "1");
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(middleware);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Unwraps an openapi-fetch result: returns data, or throws an ApiError carrying FastAPI's `detail`. */
export function unwrap<T>({ data, error, response }: Result<T>): T {
  if (data !== undefined) return data;
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  const message = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : response.statusText;
  throw new ApiError(message || `HTTP ${response.status}`, response.status);
}

export const reportUrl = (experimentId: string): string => `/v1/experiments/${experimentId}/report.html`;
