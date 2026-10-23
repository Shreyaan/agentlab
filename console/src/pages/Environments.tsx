import { Link, useParams } from "react-router";
import { useEnvironments } from "../api/hooks";
import { ConnectBox, EnvironmentView } from "../components/environment/EnvironmentView";
import { Badge, Card, EmptyState, Mono, PageHeader, QueryState, btn, btnPrimary } from "../components/ui";

export function EnvironmentsPage() {
  const query = useEnvironments();
  const { key } = useParams();
  return (
    <>
      <PageHeader title="Environments" sub="The simulated world a scenario runs in: tables and the tools agents call. Versions are immutable.">
        <Link className={btn} to="/author">
          Describe a scenario
        </Link>
        <Link className={btnPrimary} to="/environments/new">
          New environment
        </Link>
      </PageHeader>
      <QueryState query={query} isEmpty={(d) => d.length === 0} empty={<EmptyState title="No environments yet">Create one, or describe a scenario and let the author model draft it.</EmptyState>}>
        {(list) => {
          const active = list.find((e) => e.key === key);
          return (
            <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
              <Card className="h-fit">
                <ul className="divide-y divide-line">
                  {list.map((e) => (
                    <li key={e.key}>
                      <Link to={`/environments/${e.key}`} aria-current={e.key === key ? "page" : undefined} className={`block px-3 py-2.5 hover:bg-sunken ${e.key === key ? "bg-sunken" : ""}`}>
                        <span className="flex items-center gap-2">
                          <Mono className="font-medium">{e.key}</Mono>
                          <Badge>{e.environment.tables.length} tables</Badge>
                          <Badge>{e.environment.tools.length} tools</Badge>
                        </span>
                        <span className="line-clamp-2 block text-[12px] text-ink2">{e.environment.description}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </Card>
              {active ? (
                <div className="min-w-0 space-y-4">
                  <Card className="flex flex-wrap items-center gap-2 p-4">
                    <h2 className="text-[15px] font-semibold">
                      <Mono>{active.key}</Mono>
                    </h2>
                    <div className="ml-auto flex gap-2">
                      <Link className={btn} to={`/environments/${active.key}/edit`}>
                        Edit
                      </Link>
                      <Link className={btn} to={`/environments/new?from=${active.key}`}>
                        Duplicate
                      </Link>
                    </div>
                  </Card>
                  <EnvironmentView spec={active.environment} />
                  <ConnectBox />
                </div>
              ) : (
                <Card>
                  <EmptyState title={key ? `No environment ${key}` : "Select an environment"} />
                </Card>
              )}
            </div>
          );
        }}
      </QueryState>
    </>
  );
}
