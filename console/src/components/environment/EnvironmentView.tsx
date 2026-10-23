import { useState } from "react";
import type { EnvSpecView } from "../environment";
import { CONNECT_PATTERNS } from "../environment";
import { Badge, Card, Mono, SectionTitle, Table, Td, Th, btn } from "../ui";

type Tool = EnvSpecView["tools"][number];
type Table_ = EnvSpecView["tables"][number];

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard.writeText(text).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => setCopied(false),
    );
  };
  return (
    <button type="button" className={btn} aria-label={`Copy ${label}`} onClick={copy}>
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function ConnectBox() {
  return (
    <Card className="space-y-3 p-4">
      <SectionTitle>How agents connect</SectionTitle>
      <p className="text-ink2">
        Agents discover the tools at runtime, so nothing is hard-coded. The runner gives each trial its own <Mono>{"<id>"}</Mono> and hands the agent that base URL as <Mono>req.environment.base_url</Mono>.
      </p>
      {(
        [
          ["Tool catalog (HTTP, JSON Schema)", CONNECT_PATTERNS.catalog],
          ["MCP server (streamable HTTP)", CONNECT_PATTERNS.mcp],
        ] as const
      ).map(([label, url]) => (
        <div key={url} className="flex flex-wrap items-center gap-2">
          <span className="w-56 text-ink2">{label}</span>
          <Mono className="min-w-0 flex-1 break-all rounded bg-sunken px-2 py-1">{url}</Mono>
          <CopyButton text={url} label={label} />
        </div>
      ))}
    </Card>
  );
}

function columnFlags(c: Table_["columns"][number]): string[] {
  return [c.primary_key && "primary key", c.unique && "unique", c.serial && "serial", c.nullable === false && "not null"].filter((f): f is string => !!f);
}

function TableCard({ t }: { t: Table_ }) {
  return (
    <div className="space-y-1">
      <h3 className="font-medium">
        <Mono>{t.name}</Mono>
      </h3>
      <Table>
        <thead>
          <tr>
            <Th>Column</Th>
            <Th>Type</Th>
            <Th>Constraints</Th>
            <Th>References</Th>
          </tr>
        </thead>
        <tbody>
          {t.columns.map((c) => (
            <tr key={c.name}>
              <Td>
                <Mono>{c.name}</Mono>
              </Td>
              <Td>{c.type}</Td>
              <Td>
                <span className="flex flex-wrap gap-1">
                  {columnFlags(c).map((f) => (
                    <Badge key={f} tone={f === "primary key" ? "accent" : "neutral"}>
                      {f}
                    </Badge>
                  ))}
                </span>
              </Td>
              <Td>{c.references ? <Mono>{c.references}</Mono> : <span className="text-ink3">-</span>}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

const sqlBlock = "mt-1 overflow-auto rounded-md bg-sunken p-2.5 whitespace-pre-wrap break-words";

function ToolCard({ t }: { t: Tool }) {
  const params = t.params ?? [];
  const rules = t.rules ?? [];
  return (
    <div className="space-y-2 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-medium">
          <Mono>{t.name}</Mono>
        </h3>
        <Badge tone={t.mutates === false ? "info" : "warn"}>{t.mutates === false ? "read-only" : "mutates"}</Badge>
        {t.idempotent && <Badge tone="pass">idempotent</Badge>}
        <Badge>returns {t.returns ?? "row"}</Badge>
        {t.success_status != null && t.success_status !== 200 && <Badge>success {t.success_status}</Badge>}
      </div>
      <p className="text-ink2">{t.description}</p>
      {params.length > 0 && (
        <div>
          <p className="text-[12px] font-medium text-ink2">Parameters</p>
          <ul className="mt-0.5 space-y-0.5">
            {params.map((p) => (
              <li key={p.name} className="flex flex-wrap items-baseline gap-1.5">
                <Mono className="font-medium">{p.name}</Mono>
                <span className="text-ink2">{p.type}</span>
                <Badge tone={p.required === false ? "neutral" : "block"}>{p.required === false ? "optional" : "required"}</Badge>
                {p.enum && p.enum.length > 0 && <span className="text-ink2">one of {p.enum.join(", ")}</span>}
                {p.description && <span className="text-ink3">{p.description}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {rules.length > 0 && (
        <div>
          <p className="text-[12px] font-medium text-ink2">Rules (checked before the effect; when the SQL returns true the call fails)</p>
          <ul className="mt-0.5 space-y-1.5">
            {rules.map((r, i) => (
              <li key={i}>
                <pre className={sqlBlock}>{r.sql}</pre>
                <p className="mt-0.5">
                  <Badge tone="block">{r.status}</Badge> <span className="text-ink2">{r.error}</span>
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <p className="text-[12px] font-medium text-ink2">Effect SQL</p>
        <pre className={sqlBlock}>{t.sql}</pre>
      </div>
    </div>
  );
}

/** Read-only rendering of an environment spec; shared by the Environments page and the author review. */
export function EnvironmentView({ spec }: { spec: EnvSpecView }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <p className="text-ink2">{spec.description}</p>
      </Card>
      <Card className="space-y-4 p-4">
        <SectionTitle>Tables ({spec.tables.length})</SectionTitle>
        {spec.tables.map((t) => (
          <TableCard key={t.name} t={t} />
        ))}
      </Card>
      <Card className="space-y-3 p-4">
        <SectionTitle>Tools ({spec.tools.length})</SectionTitle>
        {spec.tools.map((t) => (
          <ToolCard key={t.name} t={t} />
        ))}
      </Card>
    </div>
  );
}
