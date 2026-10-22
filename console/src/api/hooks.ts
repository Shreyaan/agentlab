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
