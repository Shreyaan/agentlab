import { useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { useBuilder, useDryRun, useEnvironments, useSaveScenario, useScenarios, useTargets, useValidateScenario } from "../api/hooks";
import { AssertionsSection, type KeyedAssertion } from "../components/builder/assertions";
import { BudgetSection, EnvironmentSection, FaultsSection, IdentitySection, InputSection, SeedSection, type Scenario } from "../components/builder/sections";
import { runnableProblem } from "../components/capabilities";
import { Labeled, Notice, PageHeader, QueryState, btn, btnPrimary, field } from "../components/ui";
import { ValidationPanel, useUnsavedGuard } from "../components/ValidationPanel";
import type { Schema } from "../api/client";
import { useDebounced } from "../lib/useDebounced";

const VALIDATE_DELAY_MS = 400;

const blankScenario = (environment: string): Scenario => ({
  id: "",
  environment,
  version: 1,
  risk_tier: "normal",
  source: "synthetic",
  slices: [],
  seed: {},
  input: { message: "" },
  faults: [],
  assertions: [],
  budget: { max_tool_calls: null, max_latency_ms: null, max_cost_usd: null },
});

function DryRunDialog({ open, onOpenChange, scenario }: { open: boolean; onOpenChange: (o: boolean) => void; scenario: Scenario }) {
  const navigate = useNavigate();
  const targets = useTargets();
  const dryRun = useDryRun();
  const runnable = (targets.data ?? []).filter((t) => runnableProblem(t) === null);
  const [target, setTarget] = useState("");
  const chosen = target || runnable[0]?.name || "";
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(26rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-line bg-surface p-5 shadow-xl">
          <Dialog.Title className="text-[15px] font-semibold">Dry run</Dialog.Title>
          <Dialog.Description className="mt-1 text-ink2">Runs this unsaved scenario once against a target. Nothing is saved to the suite. This starts the real agent, which can use model credits.</Dialog.Description>
          <div className="mt-4 space-y-3">
            <QueryState query={targets}>
              {() =>
                runnable.length === 0 ? (
                  <Notice tone="warn">No reachable, runnable target. Check the Targets page.</Notice>
                ) : (
                  <Labeled label="Target">
                    {(id) => (
                      <select id={id} className={field} value={chosen} onChange={(e) => setTarget(e.target.value)}>
                        {runnable.map((t) => (
                          <option key={t.name} value={t.name}>
                            {t.name}
                          </option>
                        ))}
                      </select>
                    )}
                  </Labeled>
                )
              }
            </QueryState>
            {dryRun.isError && <Notice tone="block">{dryRun.error.message}</Notice>}
            <div className="flex justify-end gap-2">
              <Dialog.Close className={btn}>Cancel</Dialog.Close>
              <button className={btnPrimary} disabled={!chosen || dryRun.isPending} onClick={() => dryRun.mutate({ scenario, target: chosen }, { onSuccess: ({ experiment_id }) => void navigate(`/experiments/${experiment_id}`) })}>
                {dryRun.isPending ? "Starting..." : "Start dry run"}
              </button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Editor({ initial, initialKey, editing, prefilled, environments }: { initial: Scenario; initialKey: string | null; editing: boolean; prefilled: boolean; environments: Schema["EnvironmentInfo"][] }) {
  const navigate = useNavigate();
  const save = useSaveScenario();
  const uid = useRef(0);
  const nextUid = () => ++uid.current;
  const [base, setBase] = useState<Omit<Scenario, "assertions">>(() => {
    const { assertions: _ignored, ...rest } = initial;
    return rest;
  });
  const [items, setItems] = useState<KeyedAssertion[]>(() => initial.assertions.map((a) => ({ uid: nextUid(), a })));
  const [dryRunOpen, setDryRunOpen] = useState(false);
  const [envChanged, setEnvChanged] = useState(false);

  const scenario = useMemo<Scenario>(() => ({ ...base, assertions: items.map((i) => i.a) }), [base, items]);
  // Snapshot of the composed draft (not `initial`) so key order matches and a fresh form is not "dirty".
  // An author draft was never saved, so it starts dirty.
  const initialJson = useRef(JSON.stringify(scenario));
  const dirty = prefilled || JSON.stringify(scenario) !== initialJson.current;
  const { leaving, dialog } = useUnsavedGuard(dirty, "scenario");

  const settled = useDebounced(scenario, VALIDATE_DELAY_MS);
  const validation = useValidateScenario(settled);
  const builder = useBuilder(scenario.environment);
  const spec = environments.find((e) => e.key === scenario.environment)?.environment;
  const columnInfo = useMemo(
    () => Object.fromEntries((spec?.tables ?? []).map((t) => [t.name, Object.fromEntries(t.columns.map((c) => [c.name, { type: c.type, nullable: c.nullable ?? true }]))])),
    [spec],
  );
  const set = (p: Partial<Scenario>) => setBase((b) => ({ ...b, ...p }));
  const versionNote = editing ? `Version ${initial.version} is saved. Editing creates a new version.` : "Version 1. Saving later changes creates new versions.";

  const doSave = () =>
    save.mutate(scenario, {
      onSuccess: ({ key }) => {
        leaving.current = true;
        void navigate(`/scenarios/${key}`);
      },
    });

  return (
    <>
      <PageHeader title={editing ? `Edit ${initialKey}` : "New scenario"} sub="Define the environment, the failure to inject, and the checks that decide pass or fail.">
        <button className={btn} disabled={!validation.data?.valid} onClick={() => setDryRunOpen(true)}>
          Dry run
        </button>
        <button className={btnPrimary} disabled={!validation.data?.valid || save.isPending || !dirty} onClick={doSave}>
          {save.isPending ? "Saving..." : "Save"}
        </button>
      </PageHeader>
      {dirty && <p className="-mt-3 mb-3 text-[12px] text-warn">{prefilled && !editing ? "Unsaved draft" : "Unsaved changes"}</p>}
      {save.isError && (
        <div className="mb-3">
          <Notice tone="block">{save.error.message}</Notice>
        </div>
      )}
      <div className="grid items-start gap-4 lg:grid-cols-[1fr_24rem]">
        <div className="min-w-0 space-y-4">
          <IdentitySection s={scenario} set={set} versionNote={versionNote} />
          <EnvironmentSection
            value={scenario.environment}
            environments={environments.map((e) => e.key)}
            onChange={(environment) => {
              set({ environment });
              setEnvChanged(true);
            }}
          />
          {envChanged && <Notice tone="warn">Environment changed. Seed tables, faults and checks that refer to tables or tools {scenario.environment} does not have must be fixed; live validation lists them.</Notice>}
          <QueryState query={builder}>
            {(b) => (
              <>
                <SeedSection s={scenario} set={set} builder={b} columnInfo={columnInfo} />
                <InputSection s={scenario} set={set} />
                <FaultsSection s={scenario} set={set} builder={b} />
                <AssertionsSection items={items} onChange={setItems} builder={b} seed={scenario.seed} environment={scenario.environment} nextUid={nextUid} />
                <BudgetSection s={scenario} set={set} />
              </>
            )}
          </QueryState>
        </div>
        <div className="lg:sticky lg:top-4">
          <ValidationPanel data={validation.data} error={validation.isError ? validation.error : null} settling={settled !== scenario || validation.isFetching} initialKey={initialKey} editing={editing} noun="scenario" />
        </div>
      </div>
      <DryRunDialog open={dryRunOpen} onOpenChange={setDryRunOpen} scenario={scenario} />
      {dialog}
    </>
  );
}

export function ScenarioEditorPage() {
  const { key } = useParams();
  const [params] = useSearchParams();
  const draft = (useLocation().state as { draft?: Scenario } | null)?.draft; // handed over by the author page, never saved
  const sourceKey = key ?? params.get("from");
  const scenarios = useScenarios();
  const environments = useEnvironments();
  return (
    <QueryState query={environments} isEmpty={(d) => d.length === 0} empty={<Notice tone="warn">Create an environment first: a scenario runs inside one.</Notice>}>
      {(envs) => {
        if (draft) return <Editor key="draft" initial={draft} initialKey={null} editing={false} prefilled environments={envs} />;
        if (!sourceKey) return <Editor key="new" initial={blankScenario(envs[0]?.key ?? "")} initialKey={null} editing={false} prefilled={false} environments={envs} />;
        return (
          <QueryState query={scenarios}>
            {(list) => {
              const found = list.find((s) => s.key === sourceKey);
              if (!found) return <Notice tone="block">No scenario {sourceKey}.</Notice>;
              const editing = key !== undefined;
              const initial: Scenario = editing ? found.scenario : { ...found.scenario, id: `${found.scenario.id}.copy`, version: 1 };
              return <Editor key={`${sourceKey}-${editing}`} initial={initial} initialKey={editing ? sourceKey : null} editing={editing} prefilled={false} environments={envs} />;
            }}
          </QueryState>
        );
      }}
    </QueryState>
  );
}
