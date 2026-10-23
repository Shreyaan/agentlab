import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { Schema } from "../api/client";
import { useDeleteTarget, useTargets } from "../api/hooks";
import { ReachDot } from "../components/badges";
import { CAPABILITY_ROWS, INVOKE_MEANING } from "../components/capabilities";
import { ConnectPanel } from "../components/ConnectPanel";
import { TargetDialog, formFromTarget, type TargetForm } from "../components/TargetDialog";
import { Badge, Card, ConfirmDialog, EmptyState, Mono, Notice, PageHeader, QueryState, btn, btnPrimary } from "../components/ui";

function CapabilityMatrix({ caps }: { caps: Schema["Capabilities"] }) {
  const rows = [
    { key: "invoke", label: "invoke", on: caps.invoke, value: String(caps.invoke), meaning: INVOKE_MEANING },
    ...CAPABILITY_ROWS.map((r) => ({ key: r.key, label: r.label, on: r.active(caps), value: r.value(caps), meaning: r.meaning })),
  ];
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
      {rows.map((r) => (
        <div key={r.key} className="contents" title={r.meaning}>
          <dt className="cursor-help text-ink2 underline decoration-dotted decoration-ink3 underline-offset-2">{r.label}</dt>
          <dd className="flex items-center gap-1.5">
            <span className={`size-1.5 rounded-full ${r.on ? "bg-pass" : "bg-ink3"}`} aria-hidden />
            {r.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function TargetCard({ t, onEdit, onDelete }: { t: Schema["TargetHealth"]; onEdit: () => void; onDelete: () => void }) {
  const m = t.manifest;
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-2">
        <ReachDot reachable={t.reachable} />
        <h2 className="font-semibold">{t.name}</h2>
        <Badge>{t.mode}</Badge>
        <span className="ml-auto text-ink2">{t.reachable ? "reachable" : "unreachable"}</span>
      </div>
      {t.error && <Notice tone="block">{t.error}</Notice>}
      <dl className="grid grid-cols-[6rem_1fr] gap-y-0.5 text-ink2">
        <dt>version</dt>
        <dd className="break-all text-ink">{t.version || "-"}</dd>
        {t.url && (
          <>
            <dt>url</dt>
            <dd className="break-all text-ink">
              <Mono>{t.url}</Mono>
            </dd>
          </>
        )}
        {m && (
          <>
            <dt>adapter</dt>
            <dd className="text-ink">
              <Mono>{m.adapter_id}</Mono>
            </dd>
            <dt>language</dt>
            <dd className="text-ink">{m.language}</dd>
            <dt>framework</dt>
            <dd className="text-ink">{m.framework}</dd>
            <dt>protocol</dt>
            <dd className="text-ink">v{m.protocol_version}</dd>
          </>
        )}
      </dl>
      {m ? <CapabilityMatrix caps={m.capabilities} /> : <p className="text-ink3">No manifest available.</p>}
      <div className="mt-auto flex gap-2">
        <button className={btn} onClick={onEdit}>
          Edit
        </button>
        <button className={`${btn} text-block`} onClick={onDelete}>
          Delete
        </button>
      </div>
    </Card>
  );
}

export function TargetsPage() {
  const query = useTargets();
  const qc = useQueryClient();
  const remove = useDeleteTarget();
  const [editing, setEditing] = useState<{ initial: TargetForm | null } | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Targets" sub="Agent harnesses AgentLab can run scenarios against.">
        <button className={btn} disabled={query.isFetching} onClick={() => void qc.invalidateQueries({ queryKey: ["targets"] })}>
          {query.isFetching ? "Checking..." : "Refresh"}
        </button>
        <button className={btnPrimary} onClick={() => setEditing({ initial: null })}>
          Add target
        </button>
      </PageHeader>
      <QueryState query={query} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No targets configured">Add a target to start running scenarios.</EmptyState>}>
        {(targets) => (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {targets.map((t) => (
              <TargetCard key={t.name} t={t} onEdit={() => setEditing({ initial: formFromTarget(t) })} onDelete={() => { remove.reset(); setDeleting(t.name); }} />
            ))}
          </div>
        )}
      </QueryState>
      <ConnectPanel />
      <TargetDialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} initial={editing?.initial ?? null} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting ?? "target"}?`}
        confirmLabel="Delete target"
        pending={remove.isPending}
        error={remove.error?.message}
        onConfirm={() => deleting && remove.mutate(deleting, { onSuccess: () => setDeleting(null) })}
      >
        This removes the target from targets.yaml. Past experiments keep their results.
      </ConfirmDialog>
    </>
  );
}
