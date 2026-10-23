import { useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { useEnvironments, useSaveEnvironment, useValidateEnvironment } from "../api/hooks";
import { EnvironmentForm } from "../components/environment/EnvironmentForm";
import { blankEnvironment, type EnvSpec } from "../components/environment";
import { Notice, PageHeader, QueryState, btnPrimary } from "../components/ui";
import { ValidationPanel, useUnsavedGuard } from "../components/ValidationPanel";
import { useDebounced } from "../lib/useDebounced";

const VALIDATE_DELAY_MS = 400;

function Editor({ initial, initialKey, editing, startDirty }: { initial: EnvSpec; initialKey: string | null; editing: boolean; startDirty: boolean }) {
  const navigate = useNavigate();
  const save = useSaveEnvironment();
  const [spec, setSpec] = useState(initial);
  const initialJson = useRef(JSON.stringify(initial));
  const dirty = startDirty || JSON.stringify(spec) !== initialJson.current;
  const { leaving, dialog } = useUnsavedGuard(dirty, "environment");
  const settled = useDebounced(spec, VALIDATE_DELAY_MS);
  const validation = useValidateEnvironment(settled);
  const set = (p: Partial<EnvSpec>) => setSpec((s) => ({ ...s, ...p }));
  const versionNote = editing ? `Version ${initial.version} is saved. Saving a change creates the next version automatically.` : "Version 1. Saving later changes creates new versions automatically.";

  const doSave = () =>
    save.mutate(spec, {
      onSuccess: ({ key }) => {
        leaving.current = true;
        void navigate(`/environments/${key}`);
      },
    });

  return (
    <>
      <PageHeader title={editing ? `Edit ${initialKey}` : "New environment"} sub="Declare tables and the SQL-backed tools agents can call. The runtime adds isolation, a side-effect ledger and fault injection.">
        <button className={btnPrimary} disabled={!validation.data?.valid || settled !== spec || save.isPending || !dirty} onClick={doSave}>
          {save.isPending ? "Saving..." : "Save"}
        </button>
      </PageHeader>
      {dirty && <p className="-mt-3 mb-3 text-[12px] text-warn">Unsaved changes</p>}
      {save.isError && (
        <div className="mb-3">
          <Notice tone="block">{save.error.message}</Notice>
        </div>
      )}
      <div className="grid items-start gap-4 lg:grid-cols-[1fr_24rem]">
        <EnvironmentForm spec={spec} set={set} versionNote={versionNote} />
        <div className="lg:sticky lg:top-4">
          <ValidationPanel data={validation.data} error={validation.isError ? validation.error : null} settling={settled !== spec || validation.isFetching} initialKey={initialKey} editing={editing} noun="environment" />
        </div>
      </div>
      {dialog}
    </>
  );
}

export function EnvironmentEditorPage() {
  const { key } = useParams();
  const [params] = useSearchParams();
  const sourceKey = key ?? params.get("from");
  const environments = useEnvironments();
  if (!sourceKey) return <Editor key="new" initial={blankEnvironment()} initialKey={null} editing={false} startDirty={false} />;
  return (
    <QueryState query={environments}>
      {(list) => {
        const found = list.find((e) => e.key === sourceKey);
        if (!found) return <Notice tone="block">No environment {sourceKey}.</Notice>;
        const editing = key !== undefined;
        const initial = structuredClone(found.environment) as EnvSpec;
        return <Editor key={`${sourceKey}-${editing}`} initial={editing ? initial : { ...initial, id: `${initial.id}-copy`, version: 1 }} initialKey={editing ? sourceKey : null} editing={editing} startDirty={!editing} />;
      }}
    </QueryState>
  );
}
