import { Link, useParams } from "react-router";
import type { Schema } from "../api/client";
import { useExperiment, useTrial } from "../api/hooks";
import { StatusBadge } from "../components/badges";
import { canFork } from "../components/capabilities";
import { ForkDialog } from "../components/ForkDialog";
import { VerdictDetail, type Decision } from "../components/Verdict";
import { Badge, Card, EmptyState, JsonBlock, Mono, Notice, PageHeader, QueryState, SectionTitle, type Tone } from "../components/ui";
import { cost, count, json, ms } from "../lib/format";

const ASSERTION_TONE: Record<Schema["AssertionResult"]["status"], Tone> = { pass: "pass", fail: "block", unsupported: "warn", skipped: "neutral" };

const Stat = ({ label, value }: { label: string; value: string }) => (
  <div>
    <div className="text-ink2">{label}</div>
    <div className="text-[15px] font-semibold tabular-nums">{value}</div>
  </div>
);

function Summary({ trial }: { trial: Schema["Trial"] }) {
  const { record } = trial;
  const u = record.usage;
  return (
    <Card className="mb-4 p-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Latency" value={ms(record.latency_ms)} />
        <Stat label="Cost" value={cost(u.cost_usd)} />
        <Stat label="Input tokens" value={count(u.input_tokens)} />
        <Stat label="Output tokens" value={count(u.output_tokens)} />
        <Stat label="Steps" value={count(u.steps)} />
        <Stat label="Agent status" value={record.agent_status ?? "-"} />
      </div>
      {record.resumed_from && (
        <p className="mt-3 text-ink2">
          Resumed from trial{" "}
          <Link className="text-accent underline" to={`/trials/${record.resumed_from.trial_id}`}>
            <Mono>{record.resumed_from.trial_id}</Mono>
          </Link>{" "}
          at checkpoint <Mono>{record.resumed_from.checkpoint_id}</Mono>.
        </p>
      )}
    </Card>
  );
}

function Assertions({ items, scenario }: { items: Schema["AssertionResult"][]; scenario?: Schema["Scenario-Output"] }) {
  // Results carry no index, so the decision definition (for score legends) is matched by its description.
  const decisionFor = (r: Schema["AssertionResult"]): Decision | undefined =>
    scenario?.assertions.find((a): a is Decision => a.type === "decision" && (a.description || a.question.instructions) === r.description);
  if (items.length === 0) return <EmptyState title="No assertions were graded" />;
  const ordered = [...items].sort((a, b) => Number(b.critical) - Number(a.critical));
  return (
    <ul className="divide-y divide-line">
      {ordered.map((a, i) => (
        <li key={i} className="flex items-start gap-3 px-4 py-2.5">
          <Badge tone={ASSERTION_TONE[a.status]}>{a.status}</Badge>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              {a.critical && <Badge tone="block">CRITICAL</Badge>}
              <span>{a.description}</span>
            </div>
            {a.detail && <p className="mt-0.5 break-words text-[12px] text-ink2">{a.detail}</p>}
            {a.judge && <VerdictDetail judge={a.judge} decision={decisionFor(a)} />}
          </div>
        </li>
      ))}
    </ul>
  );
}

function RowList({ rows, sign }: { rows: Schema["Row"][]; sign: "+" | "-" }) {
  const cls = sign === "+" ? "bg-pass-bg text-pass" : "bg-block-bg text-block";
  return (
    <>
      {rows.map((r, i) => (
        <pre key={i} className={`rounded px-2 py-1 whitespace-pre-wrap break-words ${cls}`}>
          {sign} {JSON.stringify(r)}
        </pre>
      ))}
    </>
  );
}

function StateDiff({ diff }: { diff: Record<string, Schema["TableDiff"]> }) {
  const tables = Object.entries(diff);
  if (tables.length === 0) return <EmptyState title="The agent changed no state" />;
  return (
    <div className="space-y-4 p-4">
      {tables.map(([table, d]) => (
        <div key={table} className="space-y-1">
          <div className="font-medium">
            <Mono>{table}</Mono>
            <span className="ml-2 text-ink3">
              +{d.added.length} / -{d.removed.length}
            </span>
          </div>
          <RowList rows={d.added} sign="+" />
          <RowList rows={d.removed} sign="-" />
        </div>
      ))}
    </div>
  );
}

function Ledger({ entries }: { entries: Schema["LedgerEntry"][] }) {
  if (entries.length === 0) return <EmptyState title="No tool calls reached the environment" />;
  return (
    <ol className="relative ml-6 border-l border-line py-2 pr-4">
      {entries.map((e) => (
        <li key={e.seq} className="relative py-2 pl-5">
          <span
            className={`absolute top-3.5 -left-[5px] size-2.5 rounded-full ring-2 ring-surface ${e.committed ? "bg-accent" : "bg-ink3"}`}
          />
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-ink3 tabular-nums">#{e.seq}</span>
            <Mono className="font-medium">{e.tool}</Mono>
            <Badge tone={e.status < 400 ? "pass" : "block"}>HTTP {e.status}</Badge>
            <Badge tone={e.committed ? "info" : "neutral"} title="Whether the side effect persisted, even if the caller saw an error">
              {e.committed ? "committed" : "not committed"}
            </Badge>
          </div>
          <div className="mt-1 space-y-1">
            <JsonBlock label="Request" value={e.request} />
            <JsonBlock label="Response" value={e.response} />
          </div>
        </li>
      ))}
    </ol>
  );
}

const checkpointId = (e: Schema["Event"]): string | null => {
  const id = e.data["checkpoint_id"];
  return typeof id === "string" ? id : null;
};

const eventTone = (e: Schema["Event"]): Tone =>
  e.type === "checkpoint_saved" ? "accent" : e.type === "tool_failed" || e.type === "run_failed" ? "block" : e.type === "retry_scheduled" ? "warn" : e.type === "model_call" ? "info" : "neutral";

function Events({ trial, forkable }: { trial: Schema["Trial"]; forkable: boolean }) {
  const events = trial.record.events;
  if (events.length === 0) return <EmptyState title="No agent events" >This target did not report events (observe: none).</EmptyState>;
  return (
    <ol className="relative ml-6 border-l border-line py-2 pr-4">
      {events.map((e) => {
        const cp = e.type === "checkpoint_saved" ? checkpointId(e) : null;
        const injected = e.data["injected"] === true;
        return (
          <li key={e.seq} className={`relative py-1.5 pl-5 ${e.type === "checkpoint_saved" ? "-ml-px rounded-r bg-sunken" : ""}`}>
            <span className={`absolute top-3 -left-[5px] size-2.5 rounded-full ring-2 ring-surface ${e.type === "checkpoint_saved" ? "bg-accent" : "bg-ink3"}`} />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-ink3 tabular-nums">#{e.seq}</span>
              <Badge tone={eventTone(e)}>{e.type}</Badge>
              {e.name && <Mono>{e.name}</Mono>}
              {injected && (
                <Badge tone="warn" title="This failure was injected by a fault">
                  injected fault{e.data["committed"] === true ? ", committed" : ""}
                </Badge>
              )}
              {cp && <Mono className="text-ink2">{cp}</Mono>}
              {cp && forkable && <ForkDialog trial={trial} checkpointId={cp} />}
            </div>
            {Object.keys(e.data).length > 0 && !cp && <JsonBlock label="Data" value={e.data} />}
          </li>
        );
      })}
    </ol>
  );
}

const Panel = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <Card className="mb-4">
    <div className="px-4 pt-3.5">
      <SectionTitle>{title}</SectionTitle>
    </div>
    {children}
  </Card>
);

function Detail({ trial }: { trial: Schema["Trial"] }) {
  const experiment = useExperiment(trial.experiment_id);
  const manifest = experiment.data?.experiment.meta.targets[trial.target]?.manifest ?? null;
  const { record } = trial;
  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            Trial <StatusBadge status={trial.status} />
          </span>
        }
        sub={
          <span className="break-all">
            <Mono>{trial.id}</Mono>
          </span>
        }
      >
        <Link to={`/experiments/${trial.experiment_id}`} className="text-accent hover:underline">
          Back to experiment
        </Link>
      </PageHeader>
      <p className="mb-4 text-ink2">
        Target <strong className="text-ink">{trial.target}</strong>, scenario <Mono>{trial.scenario}</Mono>, repeat {trial.repeat}
      </p>

      {record.error && (
        <div className="mb-4">
          <Notice tone="warn">
            <strong>{record.error.code}</strong>: {record.error.message}
            <span className="block text-[12px]">An infrastructure error is never counted as an agent pass or fail.</span>
          </Notice>
        </div>
      )}
      <Summary trial={trial} />

      <Panel title="Agent output">
        <pre className="m-4 mt-0 max-h-80 overflow-auto rounded-md bg-sunken p-3 whitespace-pre-wrap break-words">
          {typeof record.output === "string" ? record.output : record.output == null ? "(no output)" : json(record.output)}
        </pre>
      </Panel>
      <Panel title="Assertions">
        <Assertions items={record.assertions} scenario={experiment.data?.experiment.meta.scenarios[trial.scenario]} />
      </Panel>
      <Panel title="State diff">
        <StateDiff diff={record.state_diff} />
      </Panel>
      <Panel title="Side-effect ledger">
        <Ledger entries={record.ledger} />
      </Panel>
      <Panel title="Agent events">
        <Events trial={trial} forkable={canFork(manifest)} />
      </Panel>
    </>
  );
}

export function TrialDetailPage() {
  const { id = "" } = useParams();
  const query = useTrial(id);
  return <QueryState query={query}>{(trial) => <Detail trial={trial} />}</QueryState>;
}
