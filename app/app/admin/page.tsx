import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import type { AppConfigRow, JobRow, RubricVersionRow } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AdminConfigEditor } from "@/components/admin-config-editor";
import { AdminIntake } from "@/components/admin-intake";
import { formatDate, titleCase } from "@/lib/utils";

export const dynamic = "force-dynamic";

const JOB_STATUS_VARIANT: Record<string, "success" | "warning" | "destructive"> = {
  succeeded: "success",
  running: "warning",
  failed: "destructive",
};

export default async function AdminPage() {
  const supabase = createClient();

  const [{ data: rubrics }, { data: configs }, { data: jobs }] = await Promise.all([
    supabase.from("rubric_versions").select("*").order("created_at", { ascending: false }),
    supabase.from("app_config").select("*").order("key"),
    supabase.from("jobs").select("*").order("started_at", { ascending: false }).limit(50),
  ]);

  const rubricRows = (rubrics ?? []) as RubricVersionRow[];
  const active = rubricRows.find((r) => r.active);
  const configRows = (configs ?? []) as AppConfigRow[];
  const jobRows = (jobs ?? []) as JobRow[];
  const provisional = Boolean(configRows.find((c) => c.key === "rubric_provisional")?.value);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Admin</h1>
        <p className="text-sm text-muted-foreground">Rubric, config, run history, and intake — Julia/Ben only.</p>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Rubric</h2>
        {provisional && (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            Provisional — pending Ben. These weights and gate thresholds are the seeded defaults and haven&apos;t been
            manually confirmed yet.
          </div>
        )}
        {!active ? (
          <p className="text-sm text-muted-foreground">No active rubric version found.</p>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                Version {active.version}
                <Badge variant="success">active</Badge>
              </CardTitle>
              {active.notes && <p className="text-xs text-muted-foreground">{active.notes}</p>}
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Weights</h3>
                <ul className="space-y-1 text-sm">
                  {Object.entries(active.weights).map(([dim, weight]) => (
                    <li key={dim} className="flex items-center justify-between">
                      <span>{titleCase(dim)}</span>
                      <span className="tabular-nums">{weight}%</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Gate config</h3>
                <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">
                  {JSON.stringify(active.gate_config, null, 2)}
                </pre>
              </div>
            </CardContent>
          </Card>
        )}
        {rubricRows.length > 1 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground">
              {rubricRows.length - 1} other version(s)
            </summary>
            <ul className="mt-2 space-y-1">
              {rubricRows
                .filter((r) => !r.active)
                .map((r) => (
                  <li key={r.id} className="flex items-center gap-2">
                    <Badge variant="outline">{r.version}</Badge>
                    <span className="text-muted-foreground">{r.notes}</span>
                  </li>
                ))}
            </ul>
          </details>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Config</h2>
        <AdminConfigEditor configs={configRows} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Runs</h2>
        {jobRows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No job runs recorded yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Job</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Finished</TableHead>
                <TableHead>Stats</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobRows.map((j) => (
                <TableRow key={j.id}>
                  <TableCell>{j.job_name}</TableCell>
                  <TableCell>
                    <Badge variant={JOB_STATUS_VARIANT[j.status] ?? "outline"}>{j.status}</Badge>
                  </TableCell>
                  <TableCell className="text-xs">{formatDate(j.started_at)}</TableCell>
                  <TableCell className="text-xs">{formatDate(j.finished_at)}</TableCell>
                  <TableCell className="max-w-xs truncate text-xs text-muted-foreground" title={JSON.stringify(j.stats)}>
                    {j.error ? <span className="text-destructive">{j.error}</span> : JSON.stringify(j.stats)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Intake</h2>
        <p className="text-sm text-muted-foreground">
          Paste company names or numbers, one per line. Writes directly to <code>companies</code> for now (a
          Python CLI resolves and enriches them on the next scheduled run).
        </p>
        <AdminIntake />
      </section>

      <section>
        <Link href="/admin/learning" className="text-sm underline">
          Learning loop panel →
        </Link>
      </section>
    </div>
  );
}
