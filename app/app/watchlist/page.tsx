import { createClient } from "@/lib/supabase/server";
import type { WatchlistRow } from "@/lib/types";
import { WatchlistTable } from "@/components/watchlist-table";

export const dynamic = "force-dynamic";

export default async function WatchlistPage() {
  const supabase = createClient();
  const { data, error } = await supabase.from("v_watchlist").select("*");

  if (error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        Couldn&apos;t load the watchlist: {error.message}
      </div>
    );
  }

  const rows = (data ?? []) as WatchlistRow[];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Watchlist</h1>
        <p className="text-sm text-muted-foreground">
          Companies parked pending a succession/upside signal. Fired items (signal crossed the threshold) are
          pinned to the top.
        </p>
      </div>
      {rows.length === 0 ? (
        <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
          Nothing on the watchlist right now.
        </div>
      ) : (
        <WatchlistTable rows={rows} />
      )}
    </div>
  );
}
