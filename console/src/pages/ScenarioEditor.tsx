import { useEffect, useMemo, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useBlocker, useNavigate, useParams, useSearchParams } from "react-router";
import { useBuilder, useDryRun, useSaveScenario, useScenarios, useTargets, useValidateScenario } from "../api/hooks";
import { AssertionsSection, type KeyedAssertion } from "../components/builder/assertions";
import { BudgetSection, FaultsSection, IdentitySection, InputSection, SeedSection, type Scenario } from "../components/builder/sections";
import { runnableProblem } from "../components/capabilities";
import { Badge, Card, ConfirmDialog, Labeled, Notice, PageHeader, QueryState, SectionTitle, Spinner, btn, btnPrimary, field } from "../components/ui";
import { useDebounced } from "../lib/useDebounced";

const VALIDATE_DELAY_MS = 400;

const blankScenario = (): Scenario => ({
  id: "",
  version: 1,
  risk_tier: "normal",
  source: "synthetic",
  slices: [],
  fixture: { customers: [], orders: [], approval_limit_cents: 50_000 },
  input: { message: "" },
  faults: [],
  assertions: [],
  budget: { max_tool_calls: null, max_latency_ms: null, max_cost_usd: null },
});

function ValidationPanel({ scenario, initialKey, editing }: { scenario: Scenario; initialKey: string | null; editing: boolean }) {
  const debounced = useDebounced(scenario, VALIDATE_DELAY_MS);
  const v = useValidateScenario(debounced);
  const settling = debounced !== scenario || v.isFetching;
  const data = v.data;
  return (
    <Card className="space-y-3 p-4">
      <SectionTitle aside={settling ? <Spinner /> : data && <Badge tone={data.valid ? "pass" : "block"}>{data.valid ? "valid" : "invalid"}</Badge>}>Live validation</SectionTitle>
      {v.isError && <Notice tone="block">{v.error.message}</Notice>}
      {data && !data.valid && (
        <ul className="space-y-1" aria-live="polite">
          {data.errors.map((e, i) => (
            <li key={i}>
              <Notice tone="block">{e}</Notice>
            </li>
          ))}
        </ul>
      )}
      {data?.key && (
        <div className="space-y-1">
          <p>
            Saves as <code className="font-medium">{data.key}</code>
          </p>
          <p className="text-[12px] text-ink2">
            {editing && initialKey && data.key !== initialKey
              ? `Saving a change creates a new immutable version. ${initialKey} stays as it was, and experiments that ran it keep their results.`
              : editing
                ? "No change from the saved version. Saving will not create a new version."
                : "Versions are immutable: saving later changes creates a new version instead of overwriting."}
          </p>
        </div>
      )}
      {data?.yaml && (
        <details open>
          <summary className="cursor-pointer text-ink2 hover:text-ink">Normalized YAML</summary>
          <pre className="mt-1 max-h-[28rem] overflow-auto rounded-md bg-sunken p-2.5 whitespace-pre" tabIndex={0}>
            {data.yaml}
          </pre>
        </details>
      )}
    </Card>
  );
}

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

function Editor({ initial, initialKey, editing }: { initial: Scenario; initialKey: string | null; editing: boolean }) {
  const navigate = useNavigate();
  const builder = useBuilder();
  const save = useSaveScenario();
  const uid = useRef(0);
  const nextUid = () => ++uid.current;
  const [base, setBase] = useState<Omit<Scenario, "assertions">>(() => {
    const { assertions: _ignored, ...rest } = initial;
    return rest;
  });
  const [items, setItems] = useState<KeyedAssertion[]>(() => initial.assertions.map((a) => ({ uid: nextUid(), a })));
  const [dryRunOpen, setDryRunOpen] = useState(false);

  const scenario = useMemo<Scenario>(() => ({ ...base, assertions: items.map((i) => i.a) }), [base, items]);
  // Snapshot of the composed draft (not `initial`) so key order matches and a fresh form is not "dirty".
  const initialJson = useRef(JSON.stringify(scenario));
  const dirty = JSON.stringify(scenario) !== initialJson.current;
  const leaving = useRef(false); // set once a save succeeds so navigating to the scenario page is not blocked
  const blocker = useBlocker(() => dirty && !leaving.current);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const validation = useValidateScenario(useDebounced(scenario, VALIDATE_DELAY_MS));
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
      {dirty && <p className="-mt-3 mb-3 text-[12px] text-warn">Unsaved changes</p>}
      {save.isError && (
        <div className="mb-3">
          <Notice tone="block">{save.error.message}</Notice>
        </div>
      )}
      <QueryState query={builder}>
        {(b) => (
          <div className="grid items-start gap-4 lg:grid-cols-[1fr_24rem]">
            <div className="min-w-0 space-y-4">
              <IdentitySection s={scenario} set={set} versionNote={versionNote} />
              <SeedSection s={scenario} set={set} builder={b} />
              <InputSection s={scenario} set={set} />
              <FaultsSection s={scenario} set={set} builder={b} />
              <AssertionsSection items={items} onChange={setItems} builder={b} seed={scenario.fixture} nextUid={nextUid} />
              <BudgetSection s={scenario} set={set} />
            </div>
            <div className="lg:sticky lg:top-4">
              <ValidationPanel scenario={scenario} initialKey={initialKey} editing={editing} />
            </div>
          </div>
        )}
      </QueryState>
      <DryRunDialog open={dryRunOpen} onOpenChange={setDryRunOpen} scenario={scenario} />
      <ConfirmDialog
        open={blocker.state === "blocked"}
        onOpenChange={(o) => !o && blocker.state === "blocked" && blocker.reset()}
        title="Discard unsaved changes?"
        confirmLabel="Discard changes"
        onConfirm={() => blocker.state === "blocked" && blocker.proceed()}
      >
        This scenario has changes that are not saved. Leaving now loses them.
      </ConfirmDialog>
    </>
  );
}

export function ScenarioEditorPage() {
  const { key } = useParams();
  const [params] = useSearchParams();
  const sourceKey = key ?? params.get("from");
  const scenarios = useScenarios();
  if (!sourceKey) return <Editor key="new" initial={blankScenario()} initialKey={null} editing={false} />;
  return (
    <QueryState query={scenarios}>
      {(list) => {
        const found = list.find((s) => s.key === sourceKey);
        if (!found) return <Notice tone="block">No scenario {sourceKey}.</Notice>;
        const editing = key !== undefined;
        const initial: Scenario = editing ? found.scenario : { ...found.scenario, id: `${found.scenario.id}.copy`, version: 1 };
        return <Editor key={`${sourceKey}-${editing}`} initial={initial} initialKey={editing ? sourceKey : null} editing={editing} />;
      }}
    </QueryState>
  );
}
