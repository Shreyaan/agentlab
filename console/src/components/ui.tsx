import type { UseQueryResult } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { useId, type ReactNode } from "react";
import { json } from "../lib/format";

export type Tone = "neutral" | "pass" | "block" | "warn" | "info" | "accent";

const TONES: Record<Tone, string> = {
  neutral: "bg-sunken text-ink2",
  pass: "bg-pass-bg text-pass",
  block: "bg-block-bg text-block",
  warn: "bg-warn-bg text-warn",
  info: "bg-info-bg text-info",
  accent: "bg-accent text-accent-ink",
};

export const Badge = ({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) => (
  <span
    title={title}
    className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap ${TONES[tone]}`}
  >
    {children}
  </span>
);

export const btn =
  "inline-flex items-center justify-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-[13px] font-medium text-ink hover:bg-sunken disabled:opacity-50 disabled:pointer-events-none cursor-pointer";
export const btnPrimary =
  "inline-flex items-center justify-center gap-1.5 rounded-md bg-accent px-3.5 py-1.5 text-[13px] font-semibold text-accent-ink hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none cursor-pointer";
export const field =
  "w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink3";

export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <section className={`rounded-lg border border-line bg-surface ${className}`}>{children}</section>
);

export const SectionTitle = ({ children, aside }: { children: ReactNode; aside?: ReactNode }) => (
  <div className="mb-2 flex items-center justify-between gap-3">
    <h2 className="text-[13px] font-semibold text-ink">{children}</h2>
    {aside}
  </div>
);

export const PageHeader = ({ title, children, sub }: { title: ReactNode; children?: ReactNode; sub?: ReactNode }) => (
  <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
    <div className="min-w-0">
      <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
      {sub && <p className="mt-0.5 text-ink2">{sub}</p>}
    </div>
    <div className="flex items-center gap-2">{children}</div>
  </header>
);

export const Spinner = () => (
  <span
    role="status"
    aria-label="Loading"
    className="inline-block size-4 animate-spin rounded-full border-2 border-line border-t-accent"
  />
);

export const Notice = ({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) => (
  <div className={`rounded-md px-3 py-2 text-[13px] ${TONES[tone]}`} role={tone === "block" ? "alert" : undefined}>
    {children}
  </div>
);

export const EmptyState = ({ title, children }: { title: string; children?: ReactNode }) => (
  <div className="px-4 py-12 text-center">
    <p className="font-medium">{title}</p>
    {children && <div className="mt-1 text-ink2">{children}</div>}
  </div>
);

/** Renders loading / error / empty states for a query, then `children(data)` on success. */
export function QueryState<T>({
  query,
  isEmpty,
  empty,
  children,
}: {
  query: UseQueryResult<T>;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending)
    return (
      <div className="flex items-center gap-2 p-6 text-ink2">
        <Spinner /> Loading...
      </div>
    );
  if (query.isError)
    return (
      <div className="space-y-3 p-4">
        <Notice tone="block">{query.error.message}</Notice>
        <button className={btn} onClick={() => void query.refetch()}>
          Retry
        </button>
      </div>
    );
  if (isEmpty?.(query.data)) return <>{empty}</>;
  return <>{children(query.data)}</>;
}

export const JsonBlock = ({ value, label = "JSON", open = false }: { value: unknown; label?: string; open?: boolean }) => (
  <details open={open} className="group">
    <summary className="cursor-pointer text-[12px] text-ink2 hover:text-ink">{label}</summary>
    <pre className="mt-1 max-h-72 overflow-auto rounded-md bg-sunken p-2.5 whitespace-pre-wrap break-words">
      {json(value)}
    </pre>
  </details>
);

export const Mono = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <code className={className}>{children}</code>
);

export const Table = ({ children }: { children: ReactNode }) => (
  <div className="overflow-x-auto">
    <table className="w-full border-collapse text-left">{children}</table>
  </div>
);
export const Th = ({ children, className = "" }: { children?: ReactNode; className?: string }) => (
  <th className={`border-b border-line px-3 py-2 text-[12px] font-medium whitespace-nowrap text-ink2 ${className}`}>
    {children}
  </th>
);
export const Td = ({ children, className = "" }: { children?: ReactNode; className?: string }) => (
  <td className={`border-b border-line px-3 py-2 align-middle ${className}`}>{children}</td>
);

/** A labelled control with optional plain-English help. `children` receives the id to put on the control. */
export function Labeled({ label, help, className = "", children }: { label: ReactNode; help?: ReactNode; className?: string; children: (id: string, describedBy?: string) => ReactNode }) {
  const id = useId();
  const helpId = help ? `${id}-help` : undefined;
  return (
    <div className={`space-y-1 ${className}`}>
      <label htmlFor={id} className="block font-medium">
        {label}
      </label>
      {children(id, helpId)}
      {help && (
        <p id={helpId} className="text-[12px] text-ink2">
          {help}
        </p>
      )}
    </div>
  );
}

export const CheckField = ({ checked, onChange, label, help }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; help?: ReactNode }) => (
  <label className="flex cursor-pointer items-start gap-2">
    <input type="checkbox" className="mt-1" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    <span>
      <span className="font-medium">{label}</span>
      {help && <span className="block text-[12px] text-ink2">{help}</span>}
    </span>
  </label>
);

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  children,
  confirmLabel,
  onConfirm,
  pending = false,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  pending?: boolean;
  error?: string;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(26rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-line bg-surface p-5 shadow-xl">
          <Dialog.Title className="text-[15px] font-semibold">{title}</Dialog.Title>
          <Dialog.Description asChild>
            <div className="mt-1 text-ink2">{children}</div>
          </Dialog.Description>
          {error && (
            <div className="mt-3">
              <Notice tone="block">{error}</Notice>
            </div>
          )}
          <div className="mt-4 flex justify-end gap-2">
            <Dialog.Close className={btn}>Cancel</Dialog.Close>
            <button className="inline-flex items-center rounded-md bg-block px-3.5 py-1.5 text-[13px] font-semibold text-white hover:opacity-90 disabled:opacity-50 cursor-pointer" disabled={pending} onClick={onConfirm}>
              {pending ? "Working..." : confirmLabel}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
