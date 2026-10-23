import * as Dialog from "@radix-ui/react-dialog";
import { useState, type FormEvent } from "react";
import type { Schema } from "../api/client";
import { useInfo, useSaveTarget, useTestTarget } from "../api/hooks";
import { ReachDot } from "./badges";
import { CAPABILITY_ROWS, CapabilityBadges, INVOKE_MEANING } from "./capabilities";
import { CheckField, Labeled, Notice, btn, btnPrimary, field } from "./ui";

type Caps = Schema["Capabilities"];
type Mode = Schema["TargetSpec"]["mode"];

const MODES: { value: Mode; help: string }[] = [
  { value: "native", help: "An agent served with the AgentLab adapter. Its manifest is read live from the agent." },
  { value: "http", help: "Any HTTP endpoint that takes the scenario input and returns a reply. You declare what it can do." },
  { value: "otel", help: "An agent you only observe through OpenTelemetry traces. It cannot be invoked." },
];

const meaning = (key: string): string => CAPABILITY_ROWS.find((r) => r.key === key)?.meaning ?? "";

const defaultCaps = (mode: Mode): Caps => ({
  invoke: mode !== "otel",
  observe: mode === "otel" ? "otel_partial" : "none",
  intercept_tools: "none",
  checkpoint: false,
  resume: false,
  fork: false,
});

export interface TargetForm {
  name: string;
  mode: Mode;
  url: string;
  version: string;
  adapterId: string;
  language: string;
  framework: string;
  caps: Caps;
}

export const emptyTargetForm = (): TargetForm => ({
  name: "",
  mode: "native",
  url: "",
  version: "unversioned",
  adapterId: "",
  language: "",
  framework: "custom",
  caps: defaultCaps("native"),
});

export const formFromTarget = (t: Schema["TargetHealth"]): TargetForm => ({
  name: t.name,
  mode: t.mode,
  url: t.url ?? "",
  version: t.version,
  adapterId: t.manifest?.adapter_id ?? "",
  language: t.manifest?.language ?? "",
  framework: t.manifest?.framework ?? "custom",
  caps: t.manifest?.capabilities ?? defaultCaps(t.mode),
});

const needsManifest = (mode: Mode) => mode !== "native";

const toDraft = (f: TargetForm, protocolVersion: string): Schema["TargetDraft"] => ({
  name: f.name.trim(),
  spec: {
    mode: f.mode,
    url: f.url.trim() || null,
    version: f.version.trim() || "unversioned",
    manifest: needsManifest(f.mode)
      ? { protocol_version: protocolVersion, transport: "http_json", adapter_id: f.adapterId.trim(), language: f.language.trim(), framework: f.framework.trim() || "custom", capabilities: f.caps }
      : null,
  },
});

function ManifestFields({ form, set }: { form: TargetForm; set: (patch: Partial<TargetForm>) => void }) {
  const setCaps = (patch: Partial<Caps>) => set({ caps: { ...form.caps, ...patch } });
  return (
    <fieldset className="space-y-3 rounded-md border border-line p-3">
      <legend className="px-1 font-medium">Declared manifest</legend>
      <p className="text-[12px] text-ink2">This target cannot describe itself, so you declare what it supports.</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Labeled label="Adapter id">
          {(id) => <input id={id} className={field} required value={form.adapterId} onChange={(e) => set({ adapterId: e.target.value })} />}
        </Labeled>
        <Labeled label="Language">
          {(id) => <input id={id} className={field} required value={form.language} onChange={(e) => set({ language: e.target.value })} />}
        </Labeled>
        <Labeled label="Framework">
          {(id) => <input id={id} className={field} value={form.framework} onChange={(e) => set({ framework: e.target.value })} />}
        </Labeled>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Labeled label="Observe" help={meaning("observe")}>
          {(id, d) => (
            <select id={id} aria-describedby={d} className={field} value={form.caps.observe} onChange={(e) => setCaps({ observe: e.target.value as Caps["observe"] })}>
              <option value="none">none</option>
              <option value="otel_partial">otel_partial</option>
              <option value="native_events">native_events</option>
            </select>
          )}
        </Labeled>
        <Labeled label="Intercept tools" help={meaning("intercept_tools")}>
          {(id, d) => (
            <select id={id} aria-describedby={d} className={field} value={form.caps.intercept_tools} onChange={(e) => setCaps({ intercept_tools: e.target.value as Caps["intercept_tools"] })}>
              <option value="none">none</option>
              <option value="declared_only">declared_only</option>
            </select>
          )}
        </Labeled>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <CheckField label="Invoke" help={INVOKE_MEANING} checked={form.caps.invoke} onChange={(invoke) => setCaps({ invoke })} />
        <CheckField label="Checkpoint" help={meaning("checkpoint")} checked={form.caps.checkpoint} onChange={(checkpoint) => setCaps({ checkpoint })} />
        <CheckField label="Resume" help={meaning("resume")} checked={form.caps.resume} onChange={(resume) => setCaps({ resume })} />
        <CheckField label="Fork" help={meaning("fork")} checked={form.caps.fork} onChange={(fork) => setCaps({ fork })} />
      </div>
    </fieldset>
  );
}

function TestResult({ result }: { result: Schema["TargetHealth"] }) {
  return (
    <div className="space-y-2 rounded-md bg-sunken p-3">
      <div className="flex items-center gap-2 font-medium">
        <ReachDot reachable={result.reachable} />
        {result.reachable ? "Reachable" : "Unreachable"}
      </div>
      {result.error && <Notice tone="block">{result.error}</Notice>}
      {result.manifest && (
        <>
          <p className="text-ink2">
            <code>{result.manifest.adapter_id}</code> ({result.manifest.language}, {result.manifest.framework}), protocol v{result.manifest.protocol_version}
          </p>
          <CapabilityBadges caps={result.manifest.capabilities} />
        </>
      )}
    </div>
  );
}

/** Add (initial = null) or edit a target. The trigger is supplied by the caller through `open`/`onOpenChange`. */
export function TargetDialog({ open, onOpenChange, initial }: { open: boolean; onOpenChange: (o: boolean) => void; initial: TargetForm | null }) {
  const editing = initial !== null;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 max-h-[90vh] w-[min(40rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-line bg-surface p-5 shadow-xl">
          <Dialog.Title className="text-[15px] font-semibold">{editing ? `Edit ${initial.name}` : "Add target"}</Dialog.Title>
          <Dialog.Description className="mt-1 text-ink2">Saved to targets.yaml. Test the connection before saving.</Dialog.Description>
          {/* Remount per open so the form state always starts from `initial`. */}
          {open && <TargetFormBody initial={initial ?? emptyTargetForm()} editing={editing} close={() => onOpenChange(false)} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function TargetFormBody({ initial, editing, close }: { initial: TargetForm; editing: boolean; close: () => void }) {
  const [form, setForm] = useState(initial);
  const test = useTestTarget();
  const protocolVersion = useInfo().data?.protocol_version ?? "";
  const save = useSaveTarget();
  const set = (patch: Partial<TargetForm>) => {
    setForm((f) => ({ ...f, ...patch }));
    test.reset();
  };
  const setMode = (mode: Mode) => set({ mode, caps: defaultCaps(mode) });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(toDraft(form, protocolVersion), { onSuccess: close });
  };

  return (
    <form onSubmit={submit} className="mt-4 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Labeled label="Name" help="Letters, digits, dot, dash, underscore.">
          {(id, d) => (
            <input id={id} aria-describedby={d} className={field} required readOnly={editing} pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}" value={form.name} onChange={(e) => set({ name: e.target.value })} />
          )}
        </Labeled>
        <Labeled label="Version" help="Recorded with every result, e.g. my-agent/v2.">
          {(id, d) => <input id={id} aria-describedby={d} className={field} value={form.version} onChange={(e) => set({ version: e.target.value })} />}
        </Labeled>
      </div>
      <fieldset className="space-y-1.5">
        <legend className="mb-1 font-medium">Mode</legend>
        {MODES.map((m) => (
          <label key={m.value} className="flex cursor-pointer items-start gap-2">
            <input type="radio" name="mode" className="mt-1" checked={form.mode === m.value} onChange={() => setMode(m.value)} />
            <span>
              <span className="font-medium">{m.value}</span>
              <span className="block text-[12px] text-ink2">{m.help}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {form.mode !== "otel" && (
        <Labeled label="URL" help={form.mode === "native" ? "Base URL of the adapter, e.g. http://127.0.0.1:7401" : "Endpoint AgentLab POSTs the scenario input to, e.g. http://127.0.0.1:7601/chat"}>
          {(id, d) => <input id={id} aria-describedby={d} className={field} type="url" required value={form.url} onChange={(e) => set({ url: e.target.value })} />}
        </Labeled>
      )}
      {needsManifest(form.mode) && <ManifestFields form={form} set={set} />}
      {test.data && <TestResult result={test.data} />}
      {test.isError && <Notice tone="block">{test.error.message}</Notice>}
      {save.isError && <Notice tone="block">{save.error.message}</Notice>}
      <div className="flex flex-wrap justify-end gap-2">
        <button type="button" className={btn} disabled={test.isPending || !form.name} onClick={() => test.mutate(toDraft(form, protocolVersion))}>
          {test.isPending ? "Testing..." : "Test connection"}
        </button>
        <Dialog.Close className={btn}>Cancel</Dialog.Close>
        <button type="submit" className={btnPrimary} disabled={save.isPending}>
          {save.isPending ? "Saving..." : "Save target"}
        </button>
      </div>
    </form>
  );
}
