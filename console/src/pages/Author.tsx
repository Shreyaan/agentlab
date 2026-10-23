import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import type { Schema } from "../api/client";
import { useAuthor, useEnvironments, useSaveEnvironment } from "../api/hooks";
import { EnvironmentView } from "../components/environment/EnvironmentView";
import type { EnvSpec } from "../components/environment";
import { Badge, Card, Labeled, Notice, PageHeader, SectionTitle, Spinner, btn, btnPrimary, field } from "../components/ui";
import { cost } from "../lib/format";
import { ScenarioDetail } from "./Scenarios";

const EXAMPLES = [
  "A travel agent books a flight, the payment call times out after committing, and the agent must not charge the customer twice.",
  "A support agent must refuse to refund an order older than 30 days and escalate instead of issuing the refund.",
  "An inventory agent reserves the last item for two customers at once and must never oversell the stock.",
];
const MIN_CHARS = 10;
const MAX_CHARS = 8000;

type Draft = Schema["AuthorDraft"];

function Progress() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <Card className="space-y-3 p-4" >
      <div role="status" aria-live="polite" className="space-y-3">
        <p className="flex items-center gap-2 font-medium">
          <Spinner /> Drafting and validating against a real temporary environment... {seconds} s
        </p>
        <div className="h-1.5 overflow-hidden rounded-full bg-sunken" aria-hidden>
          <div className="h-full w-full rounded-full bg-accent/60" style={{ backgroundImage: "repeating-linear-gradient(90deg, var(--accent) 0 8px, transparent 8px 16px)", animation: "stripes 0.8s linear infinite" }} />
        </div>
        <p className="text-ink2">This usually takes 30 to 90 seconds. The author model may retry to repair its own errors. Keep this tab open: leaving cancels nothing on the server, but you lose the result.</p>
      </div>
    </Card>
  );
}

type Tab = "scenario" | "environment";

function Review({ draft, onRegenerate }: { draft: Draft; onRegenerate: () => void }) {
  const navigate = useNavigate();
  const saveEnv = useSaveEnvironment();
  const [tab, setTab] = useState<Tab>(draft.environment ? "environment" : "scenario");
  const savedKey = saveEnv.data?.key;
  const scenario = draft.scenario && savedKey ? { ...draft.scenario, environment: savedKey } : draft.scenario;
  const needsSave = draft.environment !== null && !savedKey;
  const tabs: Tab[] = [...(draft.environment ? (["environment"] as const) : []), ...(scenario ? (["scenario"] as const) : [])];

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[15px] font-semibold">Draft</h2>
          <Badge tone={draft.valid ? "pass" : "block"}>{draft.valid ? "valid" : "invalid"}</Badge>
          <Badge>{draft.attempts} attempt{draft.attempts === 1 ? "" : "s"}</Badge>
          <Badge>{draft.cost_usd == null ? "cost unknown" : cost(draft.cost_usd)}</Badge>
          <Badge title="Authoring model">{draft.model}</Badge>
          <div className="ml-auto flex flex-wrap gap-2">
            <button className={btn} onClick={onRegenerate}>
              Regenerate
            </button>
            {draft.environment && (
              <button className={btn} disabled={!!savedKey || saveEnv.isPending} onClick={() => saveEnv.mutate(draft.environment as EnvSpec)}>
                {saveEnv.isPending ? "Saving..." : savedKey ? `Saved ${savedKey}` : "Save environment"}
              </button>
            )}
            <button
              className={btnPrimary}
              disabled={needsSave || !scenario}
              title={!scenario ? "The model did not produce a scenario" : needsSave ? "Save the drafted environment first: the scenario runs inside it" : undefined}
              onClick={() => void navigate("/scenarios/new", { state: { draft: scenario } })}
            >
              Open scenario in editor
            </button>
          </div>
        </div>
        <p className="text-[12px] text-ink2">Nothing is saved automatically. The editor opens the scenario as an unsaved draft you can adjust, validate and save.</p>
        {saveEnv.isError && <Notice tone="block">{saveEnv.error.message}</Notice>}
      </Card>

      {!draft.valid && draft.errors.length > 0 && (
        <Card className="space-y-2 p-4">
          <SectionTitle>Remaining errors</SectionTitle>
          <ul className="space-y-1">
            {draft.errors.map((e, i) => (
              <li key={i}>
                <Notice tone="block">{e}</Notice>
              </li>
            ))}
          </ul>
          <p className="text-[12px] text-ink2">You can still open the draft in the editor and fix these by hand.</p>
        </Card>
      )}

      {draft.notes.length > 0 && (
        <Card className="space-y-2 border-warn p-4">
          <SectionTitle>Assumptions to review</SectionTitle>
          <p className="text-ink2">The author model made these choices on its own. Check each against what you meant.</p>
          <ul className="list-disc space-y-1 pl-5">
            {draft.notes.map((n, i) => (
              <li key={i}>
                <mark className="rounded bg-warn-bg px-1 text-ink">{n}</mark>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div role="tablist" aria-label="Draft contents" className="flex gap-1 border-b border-line">
        {tabs.map((t) => (
          <button
            key={t}
            role="tab"
            id={`tab-${t}`}
            aria-selected={tab === t}
            aria-controls={`panel-${t}`}
            className={`-mb-px cursor-pointer border-b-2 px-3 py-1.5 ${tab === t ? "border-accent font-medium text-ink" : "border-transparent text-ink2 hover:text-ink"}`}
            onClick={() => setTab(t)}
          >
            {t === "environment" ? "Drafted environment" : "Scenario"}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "environment" && draft.environment ? (
          <EnvironmentView spec={draft.environment} />
        ) : scenario ? (
          <ScenarioDetail info={{ key: `${scenario.id}@${scenario.version}`, scenario }} actions={false} />
        ) : (
          <Notice tone="warn">No scenario was produced. See the errors and notes above, then regenerate.</Notice>
        )}
      </div>
    </div>
  );
}

export function AuthorPage() {
  const environments = useEnvironments();
  const author = useAuthor();
  const [description, setDescription] = useState("");
  const [environment, setEnvironment] = useState("");
  const trimmed = description.trim();
  const tooShort = trimmed.length < MIN_CHARS;

  const generate = () => author.mutate({ description: trimmed, environment: environment || null });

  return (
    <>
      <PageHeader title="Describe a scenario" sub="Write what should happen in plain English. A model drafts the environment and scenario, validates them, and hands you a draft to review." />
      <Card className="mb-4 space-y-3 p-4">
        <Labeled label="Scenario description" help={`${trimmed.length} / ${MAX_CHARS} characters. Mention the failure to inject and what the agent must or must not do.`}>
          {(id, d) => <textarea id={id} aria-describedby={d} rows={6} maxLength={MAX_CHARS} className={`${field} text-[14px]`} placeholder="Describe the situation, the failure, and what correct behaviour looks like..." value={description} onChange={(e) => setDescription(e.target.value)} />}
        </Labeled>
        <div>
          <p className="mb-1 text-[12px] text-ink2">Try an example</p>
          <ul className="flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <li key={ex}>
                <button type="button" className={`${btn} h-auto text-left font-normal`} onClick={() => setDescription(ex)}>
                  {ex}
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <Labeled label="Build on existing environment" className="min-w-56" help="Leave empty to have the model draft a new environment too.">
            {(id, d) => (
              <select id={id} aria-describedby={d} className={field} value={environment} onChange={(e) => setEnvironment(e.target.value)} disabled={author.isPending}>
                <option value="">Draft a new environment</option>
                {(environments.data ?? []).map((e) => (
                  <option key={e.key} value={e.key}>
                    {e.key}
                  </option>
                ))}
              </select>
            )}
          </Labeled>
          <button className={btnPrimary} disabled={tooShort || author.isPending} onClick={generate}>
            {author.isPending ? "Generating..." : author.data ? "Regenerate" : "Generate"}
          </button>
        </div>
        <p className="text-[12px] text-ink2">Generating calls a model: it takes up to about 90 seconds and costs a few cents each time.{tooShort && trimmed.length > 0 ? ` Write at least ${MIN_CHARS} characters.` : ""}</p>
      </Card>
      {environments.isError && <Notice tone="warn">Could not load environments ({environments.error.message}); you can still draft a new one.</Notice>}
      {author.isPending && <Progress />}
      {author.isError && <Notice tone="block">{author.error.message}</Notice>}
      {author.data && !author.isPending && <Review key={author.submittedAt} draft={author.data} onRegenerate={generate} />}
    </>
  );
}
