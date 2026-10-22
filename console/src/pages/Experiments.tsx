import { Link, useNavigate } from "react-router";
import { useExperiments } from "../api/hooks";
import { DecisionBadge, StatusBadge } from "../components/badges";
import { Progress } from "../components/charts";
import { Badge, Card, EmptyState, Mono, PageHeader, QueryState, Table, Td, Th, btnPrimary } from "../components/ui";
import { absoluteTime, cost, relativeTime } from "../lib/format";

export function ExperimentsPage() {
  const query = useExperiments();
  const navigate = useNavigate();

  return (
    <>
      <PageHeader title="Experiments" sub="Gate runs of a candidate agent, optionally against a baseline.">
        <Link to="/new" className={btnPrimary}>
          New run
        </Link>
      </PageHeader>
      <Card>
        <QueryState
          query={query}
          isEmpty={(d) => d.length === 0}
          empty={
            <EmptyState title="No experiments yet">
              <Link to="/new" className="text-accent underline">
                Start the first run
              </Link>
            </EmptyState>
          }
        >
          {(rows) => (
            <Table>
              <thead>
                <tr>
                  <Th>Status</Th>
                  <Th>Decision</Th>
                  <Th>Candidate</Th>
                  <Th>Baseline</Th>
                  <Th>Created</Th>
                  <Th className="text-right">Errors</Th>
                  <Th className="text-right">Cost</Th>
                  <Th>Id</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr
                    key={e.id}
                    className="cursor-pointer hover:bg-sunken"
                    onClick={() => void navigate(`/experiments/${e.id}`)}
                  >
                    <Td>
                      {e.status === "running" ? (
                        <Progress done={e.finished} total={e.planned} />
                      ) : (
                        <StatusBadge status={e.status} />
                      )}
                    </Td>
                    <Td>
                      <DecisionBadge decision={e.decision} />
                    </Td>
                    <Td className="font-medium">{e.candidate ?? "-"}</Td>
                    <Td className="text-ink2">{e.baseline ?? "-"}</Td>
                    <Td className="whitespace-nowrap text-ink2">
                      <time dateTime={e.created_at} title={absoluteTime(e.created_at)}>
                        {relativeTime(e.created_at)}
                      </time>
                    </Td>
                    <Td className={`text-right tabular-nums ${e.errors ? "text-warn" : "text-ink3"}`}>{e.errors}</Td>
                    <Td className="text-right tabular-nums">{cost(e.cost_usd)}</Td>
                    <Td>
                      <span className="flex items-center gap-1.5">
                        <Link
                          to={`/experiments/${e.id}`}
                          className="text-accent hover:underline"
                          onClick={(ev) => ev.stopPropagation()}
                        >
                          <Mono>{e.id}</Mono>
                        </Link>
                        {e.forked_from && (
                          <Badge tone="info" title={`Forked from trial ${e.forked_from.trial_id}`}>
                            fork
                          </Badge>
                        )}
                      </span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </QueryState>
      </Card>
    </>
  );
}
