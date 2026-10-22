import * as Dialog from "@radix-ui/react-dialog";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import type { Schema } from "../api/client";
import { useStartFork, useTargets } from "../api/hooks";
import { canFork } from "./capabilities";
import { Notice, btn, btnPrimary, field } from "./ui";

type Faults = Schema["ForkRequest"]["faults"];

export function ForkDialog({ trial, checkpointId }: { trial: Schema["Trial"]; checkpointId: string }) {
  const navigate = useNavigate();
  const targets = useTargets();
  const fork = useStartFork();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState(trial.target);
  const [faults, setFaults] = useState<Faults>("none");

  const forkable = (targets.data ?? []).filter((t) => t.reachable && canFork(t.manifest));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    fork.mutate(
      { trial_id: trial.id, checkpoint_id: checkpointId, target, faults },
      { onSuccess: ({ experiment_id }) => void navigate(`/experiments/${experiment_id}`) },
    );
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger className={btn}>Fork from here</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-line bg-surface p-5 shadow-xl">
          <Dialog.Title className="text-[15px] font-semibold">Fork from checkpoint</Dialog.Title>
          <Dialog.Description className="mt-1 text-ink2">
            Starts a new experiment that resumes from <code>{checkpointId}</code>.
          </Dialog.Description>
          <form onSubmit={submit} className="mt-4 space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="fork-target" className="font-medium">
                Target
              </label>
              <select id="fork-target" className={field} value={target} onChange={(e) => setTarget(e.target.value)}>
                {!forkable.some((t) => t.name === trial.target) && <option value={trial.target}>{trial.target}</option>}
                {forkable.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
            <fieldset className="space-y-2">
              <legend className="mb-1 font-medium">Faults</legend>
              {(
                [
                  ["none", "none", "Counterfactual: replay without the scenario's faults."],
                  ["scenario", "scenario", "Keep the scenario's faults active after the checkpoint."],
                ] as const
              ).map(([value, label, help]) => (
                <label key={value} className="flex cursor-pointer items-start gap-2">
                  <input type="radio" name="faults" className="mt-1" checked={faults === value} onChange={() => setFaults(value)} />
                  <span>
                    <span className="font-medium">{label}</span>
                    <span className="block text-[12px] text-ink2">{help}</span>
                  </span>
                </label>
              ))}
            </fieldset>
            {fork.isError && <Notice tone="block">{fork.error.message}</Notice>}
            <div className="flex justify-end gap-2">
              <Dialog.Close className={btn}>Cancel</Dialog.Close>
              <button type="submit" className={btnPrimary} disabled={fork.isPending}>
                {fork.isPending ? "Forking..." : "Start fork"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
