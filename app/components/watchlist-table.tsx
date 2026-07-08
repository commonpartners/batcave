"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import type { WatchlistRow } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate } from "@/lib/utils";

const EXTEND_DAYS = 90;

export function WatchlistTable({ rows }: { rows: WatchlistRow[] }) {
  const supabase = createClient();
  const [pending, startTransition] = useTransition();
  const [busyId, setBusyId] = useState<string | null>(null);

  function extend(row: WatchlistRow) {
    setBusyId(row.watchlist_item_id);
    startTransition(async () => {
      const base = row.deprioritise_after ? new Date(row.deprioritise_after) : new Date();
      base.setDate(base.getDate() + EXTEND_DAYS);
      await supabase
        .from("watchlist_items")
        .update({ deprioritise_after: base.toISOString(), status: "watching" })
        .eq("id", row.watchlist_item_id);
      setBusyId(null);
      window.location.reload();
    });
  }

  function promote(row: WatchlistRow) {
    setBusyId(row.watchlist_item_id);
    startTransition(async () => {
      await supabase.from("watchlist_items").update({ status: "expired" }).eq("id", row.watchlist_item_id);
      await supabase
        .from("pipeline_items")
        .update({ stage: "review", stage_changed_at: new Date().toISOString() })
        .eq("company_id", row.company_id);
      setBusyId(null);
      window.location.reload();
    });
  }

  function archive(row: WatchlistRow) {
    setBusyId(row.watchlist_item_id);
    startTransition(async () => {
      await supabase.from("watchlist_items").update({ status: "expired" }).eq("id", row.watchlist_item_id);
      await supabase
        .from("pipeline_items")
        .update({ stage: "passed", stage_changed_at: new Date().toISOString() })
        .eq("company_id", row.company_id);
      setBusyId(null);
      window.location.reload();
    });
  }

  const sorted = [...rows].sort((a, b) => {
    if (a.status === "fired" && b.status !== "fired") return -1;
    if (b.status === "fired" && a.status !== "fired") return 1;
    return (a.days_to_deprioritise ?? Infinity) - (b.days_to_deprioritise ?? Infinity);
  });

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Company</TableHead>
          <TableHead>Reason parked</TableHead>
          <TableHead>Succession status</TableHead>
          <TableHead>Days to deprioritise</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((row) => (
          <TableRow key={row.watchlist_item_id} className={row.status === "fired" ? "bg-amber-50" : undefined}>
            <TableCell>
              <Link href={`/company/${row.company_number}`} className="font-medium underline-offset-2 hover:underline">
                {row.legal_name}
              </Link>
              <div className="flex flex-wrap gap-1 pt-1">
                {(row.sector_tags ?? []).map((t) => (
                  <Badge key={t} variant="outline">
                    {t}
                  </Badge>
                ))}
              </div>
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{row.reason ?? "—"}</TableCell>
            <TableCell className="text-sm">
              {row.succession_signal_name ? (
                <>
                  <div>{row.succession_signal_name}</div>
                  <div className="text-xs text-muted-foreground">
                    {row.succession_signal_value?.toFixed(2)} — {row.succession_signal_rationale}
                  </div>
                </>
              ) : (
                "—"
              )}
            </TableCell>
            <TableCell className="tabular-nums">
              {row.days_to_deprioritise !== null ? row.days_to_deprioritise : "—"}
            </TableCell>
            <TableCell>
              <Badge variant={row.status === "fired" ? "warning" : "outline"}>{row.status}</Badge>
              <div className="text-xs text-muted-foreground">Since {formatDate(row.added_at)}</div>
            </TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1">
                <Button size="sm" variant="outline" disabled={pending && busyId === row.watchlist_item_id} onClick={() => extend(row)}>
                  Extend
                </Button>
                <Button size="sm" variant="secondary" disabled={pending && busyId === row.watchlist_item_id} onClick={() => promote(row)}>
                  Promote
                </Button>
                <Button size="sm" variant="ghost" disabled={pending && busyId === row.watchlist_item_id} onClick={() => archive(row)}>
                  Archive
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
