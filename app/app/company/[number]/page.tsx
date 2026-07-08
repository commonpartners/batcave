import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import type { CompanyDetailRow, RubricVersionRow } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { DimensionBar } from "@/components/dimension-bar";
import { SignalsTimeline } from "@/components/signals-timeline";
import { FactsPanel } from "@/components/facts-panel";
import { NotesPanel } from "@/components/notes-panel";
import { DecisionBar } from "@/components/decision-bar";
import { titleCase } from "@/lib/utils";

export const dynamic = "force-dynamic";

const GATE_VARIANT: Record<string, "success" | "warning" | "destructive"> = {
  pass: "success",
  hold: "warning",
  fail: "destructive",
};

export default async function CompanyPage({ params }: { params: { number: string } }) {
  const supabase = createClient();

  const [{ data: company, error }, { data: rubric }, { data: reasonConfig }] = await Promise.all([
    supabase.from("v_company_detail").select("*").eq("company_number", params.number).maybeSingle(),
    supabase.from("rubric_versions").select("*").eq("active", true).maybeSingle(),
    supabase.from("app_config").select("value").eq("key", "decision_reason_codes").maybeSingle(),
  ]);

  if (error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        Couldn&apos;t load this company: {error.message}
      </div>
    );
  }
  if (!company) notFound();

  const row = company as CompanyDetailRow;
  const rubricRow = rubric as RubricVersionRow | null;
  const reasonCodes = ((reasonConfig?.value as string[] | undefined) ?? []) as string[];

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">{row.legal_name}</h1>
            <p className="text-sm text-muted-foreground">
              {row.company_number} &middot; {titleCase(row.company_status ?? "unknown")} &middot;{" "}
              {titleCase(row.lifecycle)}
            </p>
          </div>
          <div className="text-right">
            <div className="text-4xl font-bold tabular-nums">
              {row.total_score !== null ? Math.round(row.total_score) : "—"}
            </div>
            <div className="text-xs text-muted-foreground">rubric {row.rubric_version ?? "n/a"}</div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {row.gate_result && (
            <Badge variant={GATE_VARIANT[row.gate_result] ?? "outline"}>gate: {row.gate_result}</Badge>
          )}
          {row.data_completeness !== null && row.data_completeness < 1 && (
            <Badge variant="warning">scoring-incomplete</Badge>
          )}
          {(row.value_angles ?? []).map((a) => (
            <Badge key={a} variant="secondary">
              {titleCase(a)}
            </Badge>
          ))}
          {(row.red_flags ?? []).map((f) => (
            <a key={f} href="#signals">
              <Badge variant="destructive">{titleCase(f)}</Badge>
            </a>
          ))}
          {(row.sector_tags ?? []).map((t) => (
            <Badge key={t} variant="outline">
              {t}
            </Badge>
          ))}
        </div>
      </header>

      {!row.score_id && (
        <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          No scores yet for this company — it hasn&apos;t been through the scoring pipeline.
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section>
            <h2 className="mb-2 text-lg font-semibold">Why this rank</h2>
            <div className="rounded-lg border">
              {row.dimensions.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No dimension scores recorded.</p>
              ) : (
                row.dimensions.map((d) => (
                  <div key={d.id} className="px-3">
                    <DimensionBar dimension={d} weight={rubricRow?.weights?.[d.dimension]} />
                  </div>
                ))
              )}
            </div>
          </section>

          <section id="signals">
            <h2 className="mb-2 text-lg font-semibold">Signals timeline</h2>
            <SignalsTimeline signals={row.signals} />
          </section>

          <section>
            <h2 className="mb-2 text-lg font-semibold">Notes</h2>
            <NotesPanel companyId={row.id} notes={row.notes} />
          </section>
        </div>

        <aside className="space-y-6">
          <section className="rounded-lg border p-4">
            <FactsPanel company={row} />
          </section>

          <section className="rounded-lg border p-4">
            <h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Decision history</h3>
            {row.decisions.length === 0 ? (
              <p className="text-sm text-muted-foreground">No decisions recorded yet.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {row.decisions.map((d) => (
                  <li key={d.id} className="border-b pb-2 last:border-b-0">
                    <div className="flex items-center justify-between">
                      <Badge variant="outline">{titleCase(d.decision)}</Badge>
                      <span className="text-xs text-muted-foreground">{titleCase(d.decided_by)}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {d.reasons.map((r) => (
                        <span key={r} className="rounded bg-muted px-1.5 py-0.5 text-xs">
                          {titleCase(r)}
                        </span>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>

      <DecisionBar companyId={row.id} scoreId={row.score_id} reasonCodes={reasonCodes} />
    </div>
  );
}
