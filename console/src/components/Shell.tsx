import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { NavLink, Outlet } from "react-router";
import { onUnauthorized, tokenStore } from "../api/client";
import { useInfo } from "../api/hooks";
import { btnPrimary, field } from "./ui";

const NAV = [
  { to: "/", label: "Experiments", end: true },
  { to: "/new", label: "New run" },
  { to: "/targets", label: "Targets" },
  { to: "/scenarios", label: "Scenarios" },
  { to: "/author", label: "Describe a scenario" },
  { to: "/environments", label: "Environments" },
  { to: "/judges", label: "Judges" },
];

function TokenDialog() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");

  useEffect(() => onUnauthorized(() => setOpen(true)), []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    tokenStore.set(token.trim());
    setToken("");
    setOpen(false);
    void qc.invalidateQueries();
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(26rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-line bg-surface p-5 shadow-xl">
          <Dialog.Title className="text-[15px] font-semibold">API token required</Dialog.Title>
          <Dialog.Description className="mt-1 text-ink2">
            This console is protected. Paste the bearer token; it is kept for this browser tab only.
          </Dialog.Description>
          <form onSubmit={submit} className="mt-4 space-y-3">
            <input
              className={field}
              type="password"
              autoComplete="off"
              aria-label="API token"
              placeholder="Token"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              required
            />
            <div className="flex justify-end">
              <button className={btnPrimary} type="submit">
                Save token
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Shell() {
  const info = useInfo();
  return (
    <div className="min-h-screen md:grid md:grid-cols-[13rem_1fr]">
      <aside className="border-b border-line bg-surface md:sticky md:top-0 md:h-screen md:border-r md:border-b-0">
        <div className="flex items-center gap-2 px-4 py-3.5">
          <span className="grid size-5 place-items-center rounded bg-accent text-[11px] font-bold text-accent-ink" aria-hidden>
            A
          </span>
          <span className="font-semibold tracking-tight">AgentLab</span>
        </div>
        <nav aria-label="Main" className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `rounded-md px-2.5 py-1.5 whitespace-nowrap ${isActive ? "bg-sunken font-medium text-ink" : "text-ink2 hover:bg-sunken hover:text-ink"}`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="min-w-0">
        <div className="flex h-10 items-center justify-end gap-3 border-b border-line bg-surface px-4 text-[12px] text-ink2">
          {info.data ? (
            <>
              <span>
                protocol <code>v{info.data.protocol_version}</code>
              </span>
              <span>
                console <code>{info.data.version}</code>
              </span>
            </>
          ) : (
            <span>{info.isError ? "backend unreachable" : "connecting..."}</span>
          )}
        </div>
        <main className="mx-auto max-w-[78rem] p-4 md:p-6">
          <Outlet />
        </main>
      </div>
      <TokenDialog />
    </div>
  );
}
