import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schema } from "./client";

const SLOW_POLL_MS = 15_000;
const LIVE_POLL_MS = 2_000;

export const useInfo = () => useQuery({ queryKey: ["info"], queryFn: async () => unwrap(await api.GET("/v1/info")) });

export const useTargets = () =>
  useQuery({ queryKey: ["targets"], queryFn: async () => unwrap(await api.GET("/v1/targets")) });

export const useScenarios = () =>
  useQuery({ queryKey: ["scenarios"], queryFn: async () => unwrap(await api.GET("/v1/scenarios")) });

const anyRunning = (list: Schema["ExperimentSummary"][] | undefined) => list?.some((e) => e.status === "running");

export const useExperiments = () =>
  useQuery({
    queryKey: ["experiments"],
    queryFn: async () => unwrap(await api.GET("/v1/experiments", { params: { query: { limit: 50 } } })),
    refetchInterval: (q) => (anyRunning(q.state.data) ? LIVE_POLL_MS : SLOW_POLL_MS),
  });

export const useExperiment = (id: string) =>
  useQuery({
    queryKey: ["experiment", id],
    queryFn: async () =>
      unwrap(await api.GET("/v1/experiments/{exp_id}", { params: { path: { exp_id: id } } })),
    refetchInterval: (q) => (q.state.data?.summary.status === "running" ? LIVE_POLL_MS : false),
  });

export const useCanaries = (id: string) =>
  useQuery({
    queryKey: ["canaries", id],
    queryFn: async () => unwrap(await api.GET("/v1/experiments/{exp_id}/canaries", { params: { path: { exp_id: id } } })),
  });

export const useTrial = (id: string) =>
  useQuery({
    queryKey: ["trial", id],
    queryFn: async () => unwrap(await api.GET("/v1/trials/{trial_id}", { params: { path: { trial_id: id } } })),
    refetchInterval: (q) => (q.state.data?.status === "running" ? LIVE_POLL_MS : false),
  });

function useStartExperiment<T>(post: (body: T) => Promise<Schema["Accepted"]>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: post,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["experiments"] }),
  });
}

export const useStartRun = () =>
  useStartExperiment(async (body: Schema["RunRequest"]) => unwrap(await api.POST("/v1/experiments", { body })));

export const useStartFork = () =>
  useStartExperiment(async (body: Schema["ForkRequest"]) => unwrap(await api.POST("/v1/forks", { body })));

// openapi-fetch widens tuples (ci95) to arrays in response data, so these derive from what the hook returns.
export type ExperimentData = NonNullable<ReturnType<typeof useExperiment>["data"]>;
export type Decision = NonNullable<ExperimentData["experiment"]["decision"]>;
export type TargetStats = Decision["stats"][string];
export type Paired = NonNullable<Decision["paired"]>;

// --- Builders ---

export const useEnvironments = () =>
  useQuery({ queryKey: ["environments"], queryFn: async () => unwrap(await api.GET("/v1/environments")) });

/** Vocabulary (tools, seed columns, assertion types, judges) for one environment key; disabled until a key is chosen. */
export const useBuilder = (environment: string) =>
  useQuery({
    queryKey: ["builder", environment],
    queryFn: async () => unwrap(await api.GET("/v1/environments/{key}/builder", { params: { path: { key: environment } } })),
    enabled: environment !== "",
    staleTime: Infinity,
  });

export const useValidateEnvironment = (environment: Schema["EnvironmentDraft"]["environment"]) =>
  useQuery({
    queryKey: ["validate-environment", environment],
    queryFn: async () => unwrap(await api.POST("/v1/environments/validate", { body: { environment } })),
    placeholderData: (prev) => prev,
    retry: false,
  });

export const useSaveEnvironment = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (environment: Schema["EnvironmentDraft"]["environment"]) => unwrap(await api.POST("/v1/environments", { body: { environment } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["environments"] }),
  });
};

/** Long-running (30-90 s) and billed: always an explicit user action, never retried automatically. */
export const useAuthor = () =>
  useMutation({ mutationFn: async (body: Schema["AuthorRequest"]) => unwrap(await api.POST("/v1/author", { body })), retry: false });

export const useJudges = () =>
  useQuery({ queryKey: ["judges"], queryFn: async () => unwrap(await api.GET("/v1/judges")) });

/** Live validation: the caller passes an already-debounced draft. Errors are part of the result, not thrown. */
export const useValidateScenario = (scenario: Schema["Scenario-Input"]) =>
  useQuery({
    queryKey: ["validate", scenario],
    queryFn: async () => unwrap(await api.POST("/v1/scenarios/validate", { body: { scenario } })),
    placeholderData: (prev) => prev,
    retry: false,
  });

export const useSaveScenario = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (scenario: Schema["Scenario-Input"]) => unwrap(await api.POST("/v1/scenarios", { body: { scenario } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scenarios"] }),
  });
};

export const useTestQuery = () =>
  useMutation({
    mutationFn: async (body: Schema["QueryTest"]) => unwrap(await api.POST("/v1/scenarios/test-query", { body })),
  });

export const useDryRun = () => useStartExperiment(async (body: Schema["DryRunRequest"]) => unwrap(await api.POST("/v1/scenarios/dry-run", { body })));

export const useTestTarget = () =>
  useMutation({
    mutationFn: async (body: Schema["TargetDraft"]) => unwrap(await api.POST("/v1/targets/test", { body })),
  });

export const useSaveTarget = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (draft: Schema["TargetDraft"]) =>
      unwrap(await api.PUT("/v1/targets/{name}", { params: { path: { name: draft.name } }, body: draft })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["targets"] }),
  });
};

export const useDeleteTarget = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => {
      const result = await api.DELETE("/v1/targets/{name}", { params: { path: { name } } });
      if (!result.response.ok) unwrap(result); // 204 has no body, so only failures are unwrapped
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["targets"] }),
  });
};
