import { createClient } from "@/lib/supabase/server";
import { HeldQueue } from "@/components/held-queue";
import type { CompanyRow } from "@/lib/types";

export const dynamic = "force-dynamic";

interface HeldScoreRow {
  id: string;
  company_id: string;
  gate_detail: Record<string, { result: string; reason: string }> | null;
  scored_at: string;
  companies: CompanyRow;
}

export default async function HeldPage() {
  const supabase = createClient();

  // No dedicated "latest hold score" view exists yet (spec 01 §8 only ships
  // v_shortlist/v_company_detail/v_watchlist) - pull recent scores ordered by
  // scored_at desc and keep the first (latest) row per company in JS, then
  // filter to gate_result = 'hold'.
  const { data, error } = await supabase
    .from("scores")
    .select("id, company_id, gate_result, gate_detail, scored_at, companies(*)")
    .order("scored_at", { ascending: false })
    .limit(500);

  if (error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        Couldn&apos;t load the held queue: {error.message}
      </div>
    );
  }

  const seen = new Set<string>();
  const latestHolds: HeldScoreRow[] = [];
  for (const row of data ?? []) {
    if (seen.has(row.company_id)) continue;
    seen.add(row.company_id);
    if (row.gate_result === "hold") {
      latestHolds.push(row as unknown as HeldScoreRow);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Held</h1>
        <p className="text-sm text-muted-foreground">
          Companies whose latest gate result is &quot;hold&quot;, grouped by the failing test. Override to push through to
          scoring, fix the underlying data, or reject outright.
        </p>
      </div>
      {latestHolds.length === 0 ? (
        <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
          Nothing held right now.
        </div>
      ) : (
        <HeldQueue rows={latestHolds} />
      )}
    </div>
  );
}
