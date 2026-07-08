import { createClient } from "@/lib/supabase/server";
import type { DecisionRow, ScoreDimensionRow } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { titleCase } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function LearningPage() {
  const supabase = createClient();

  const { data: decisionsData, error: decisionsError } = await supabase
    .from("decisions")
    .select("*")
    .in("decision", ["accept", "reject"]);

  if (decisionsError) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        Couldn&apos;t load decisions: {decisionsError.message}
      </div>
    );
  }

  const decisions = (decisionsData ?? []) as DecisionRow[];
  const scoreIds = Array.from(new Set(decisions.map((d) => d.score_id).filter(Boolean))) as string[];

  const { data: dimensionsData, error: dimensionsError } =
    scoreIds.length > 0
      ? await supabase.from("score_dimensions").select("*").in("score_id", scoreIds)
      : { data: [] as ScoreDimensionRow[], error: null };

  if (dimensionsError) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        Couldn&apos;t load score dimensions: {dimensionsError.message}
      </div>
    );
  }

  const dimensions = (dimensionsData ?? []) as ScoreDimensionRow[];
  const dimByScoreId = new Map<string, ScoreDimensionRow[]>();
  for (const d of dimensions) {
    if (!dimByScoreId.has(d.score_id)) dimByScoreId.set(d.score_id, []);
    dimByScoreId.get(d.score_id)!.push(d);
  }

  // mean dimension score among accepted vs rejected companies
  const sums: Record<string, { accept: number; acceptN: number; reject: number; rejectN: number }> = {};
  for (const decision of decisions) {
    if (!decision.score_id) continue;
    const dims = dimByScoreId.get(decision.score_id) ?? [];
    for (const dim of dims) {
      if (dim.raw_score === null) continue;
      sums[dim.dimension] ??= { accept: 0, acceptN: 0, reject: 0, rejectN: 0 };
      if (decision.decision === "accept") {
        sums[dim.dimension].accept += dim.raw_score;
        sums[dim.dimension].acceptN += 1;
      } else if (decision.decision === "reject") {
        sums[dim.dimension].reject += dim.raw_score;
        sums[dim.dimension].rejectN += 1;
      }
    }
  }

  const dimensionRows = Object.entries(sums).map(([dimension, s]) => ({
    dimension,
    meanAccept: s.acceptN > 0 ? s.accept / s.acceptN : null,
    meanReject: s.rejectN > 0 ? s.reject / s.rejectN : null,
    acceptN: s.acceptN,
    rejectN: s.rejectN,
  }));

  // reason-code frequency, across all decisions (accept/reject/watchlist/retag)
  const { data: allDecisionsData } = await supabase.from("decisions").select("reasons, decision");
  const reasonCounts = new Map<string, number>();
  for (const d of (allDecisionsData ?? []) as { reasons: string[]; decision: string }[]) {
    for (const r of d.reasons ?? []) {
      reasonCounts.set(r, (reasonCounts.get(r) ?? 0) + 1);
    }
  }
  const reasonRows = Array.from(reasonCounts.entries()).sort((a, b) => b[1] - a[1]);
  const totalDecisions = (allDecisionsData ?? []).length;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Learning loop — Stage 1 (measure only)</h1>
        <p className="text-sm text-muted-foreground">
          {totalDecisions} decision(s) recorded so far. Stage 2 (assisted retune) unlocks at ~50 decisions — this
          panel never touches rubric weights, it only makes disagreement between rubric and taste visible (spec
          05 §3).
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Mean dimension score: accepted vs rejected</h2>
        {dimensionRows.length === 0 ? (
          <p className="text-sm text-muted-foreground">Not enough decisions with linked scores yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Dimension</TableHead>
                <TableHead>Mean (accepted)</TableHead>
                <TableHead>Mean (rejected)</TableHead>
                <TableHead>Gap</TableHead>
                <TableHead>n (accept / reject)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {dimensionRows.map((row) => (
                <TableRow key={row.dimension}>
                  <TableCell>{titleCase(row.dimension)}</TableCell>
                  <TableCell className="tabular-nums">{row.meanAccept?.toFixed(2) ?? "—"}</TableCell>
                  <TableCell className="tabular-nums">{row.meanReject?.toFixed(2) ?? "—"}</TableCell>
                  <TableCell className="tabular-nums">
                    {row.meanAccept !== null && row.meanReject !== null
                      ? (row.meanAccept - row.meanReject).toFixed(2)
                      : "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {row.acceptN} / {row.rejectN}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Reason-code frequency</h2>
        {reasonRows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No decisions recorded yet.</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {reasonRows.map(([reason, count]) => (
              <Card key={reason}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{titleCase(reason)}</CardTitle>
                </CardHeader>
                <CardContent className="text-2xl font-semibold tabular-nums">{count}</CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
