import { useBlocker } from "react-router";
import { useEffect, useRef } from "react";
import { Badge, Card, ConfirmDialog, Notice, SectionTitle, Spinner } from "./ui";

interface Validation {
  valid: boolean;
  errors: string[];
  yaml?: string | null;
  key?: string | null;
}

/** Live-validation side panel shared by the scenario and environment editors. */
export function ValidationPanel({
  data,
  error,
  settling,
  initialKey,
  editing,
  noun,
}: {
  data: Validation | undefined;
  error: Error | null;
  settling: boolean;
  initialKey: string | null;
  editing: boolean;
  noun: string;
}) {
  return (
    <Card className="space-y-3 p-4">
      <SectionTitle aside={settling ? <Spinner /> : data && <Badge tone={data.valid ? "pass" : "block"}>{data.valid ? "valid" : "invalid"}</Badge>}>Live validation</SectionTitle>
      {error && <Notice tone="block">{error.message}</Notice>}
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
                : `Versions are immutable: saving later changes creates a new version of this ${noun} instead of overwriting.`}
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

/** Warns before leaving with unsaved edits. Set `leaving.current` after a successful save to let navigation through. */
export function useUnsavedGuard(dirty: boolean, noun: string) {
  const leaving = useRef(false);
  const blocker = useBlocker(() => dirty && !leaving.current);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const dialog = (
    <ConfirmDialog
      open={blocker.state === "blocked"}
      onOpenChange={(o) => !o && blocker.state === "blocked" && blocker.reset()}
      title="Discard unsaved changes?"
      confirmLabel="Discard changes"
      onConfirm={() => blocker.state === "blocked" && blocker.proceed()}
    >
      This {noun} has changes that are not saved. Leaving now loses them.
    </ConfirmDialog>
  );
  return { leaving, dialog };
}
