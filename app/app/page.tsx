import { createClient } from "@/lib/supabase/server";
import { ShortlistTable } from "@/components/shortlist-table";
import type { ShortlistRow } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function ShortlistPage() {
  const supabase = createClient();
  const { data, error } = await supabase
    .from("v_shortlist")
    .select("*")
    .order("total_score", { ascending: false, nullsFirst: false });

  if (error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        Couldn&apos;t load the shortlist: {error.message}
      </div>
    );
  }

  const rows = (data ?? []) as ShortlistRow[];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Shortlist</h1>
        <p className="text-sm text-muted-foreground">
          Gate-passing companies ranked by score. Click a row, or use j/k + enter, to open a profile.
        </p>
      </div>
      {rows.length === 0 ? (
        <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
          No scores yet. Once the scoring worker runs and companies pass the gate, they&apos;ll appear here ranked by
          score.
        </div>
      ) : (
        <ShortlistTable rows={rows} />
      )}
    </div>
  );
}
