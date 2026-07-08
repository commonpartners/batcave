"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { ShortlistRow } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, titleCase } from "@/lib/utils";

const LAST_VISIT_KEY = "cp:shortlist:last-visit";

type SortMode = "score" | "newest" | "succession";

function successionStrength(row: ShortlistRow): number {
  return Math.max(0, ...row.signals.filter((s) => s.family === "succession").map((s) => s.value), 0);
}

export function ShortlistTable({ rows }: { rows: ShortlistRow[] }) {
  const router = useRouter();
  const [stage, setStage] = useState<string>("all");
  const [sector, setSector] = useState<string>("all");
  const [sizeBand, setSizeBand] = useState<string>("all");
  const [redFlagOnly, setRedFlagOnly] = useState(false);
  const [newOnly, setNewOnly] = useState(false);
  const [sortMode, setSortMode] = useState<SortMode>("score");
  const [focusedIdx, setFocusedIdx] = useState(0);
  const [lastVisit, setLastVisit] = useState<string | null>(null);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);

  useEffect(() => {
    setLastVisit(localStorage.getItem(LAST_VISIT_KEY));
    localStorage.setItem(LAST_VISIT_KEY, new Date().toISOString());
  }, []);

  const stages = useMemo(() => Array.from(new Set(rows.map((r) => r.pipeline_stage).filter(Boolean))) as string[], [rows]);
  const sectors = useMemo(() => Array.from(new Set(rows.flatMap((r) => r.sector_tags ?? []))), [rows]);
  const sizeBands = useMemo(() => Array.from(new Set(rows.map((r) => r.size_band).filter(Boolean))), [rows]);

  const filtered = useMemo(() => {
    let out = rows.filter((r) => {
      if (stage !== "all" && r.pipeline_stage !== stage) return false;
      if (sector !== "all" && !(r.sector_tags ?? []).includes(sector)) return false;
      if (sizeBand !== "all" && r.size_band !== sizeBand) return false;
      if (redFlagOnly && (r.red_flags ?? []).length === 0) return false;
      if (newOnly && lastVisit && !(r.scored_at > lastVisit)) return false;
      return true;
    });

    out = [...out].sort((a, b) => {
      if (sortMode === "newest") return (b.scored_at ?? "").localeCompare(a.scored_at ?? "");
      if (sortMode === "succession") return successionStrength(b) - successionStrength(a);
      return (b.total_score ?? 0) - (a.total_score ?? 0);
    });
    return out;
  }, [rows, stage, sector, sizeBand, redFlagOnly, newOnly, lastVisit, sortMode]);

  useEffect(() => {
    setFocusedIdx(0);
  }, [filtered.length]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.target instanceof HTMLElement && ["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;
      if (filtered.length === 0) return;

      if (e.key === "j") {
        e.preventDefault();
        setFocusedIdx((i) => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === "k") {
        e.preventDefault();
        setFocusedIdx((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        const row = filtered[focusedIdx];
        if (row) router.push(`/company/${row.company_number}`);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [filtered, focusedIdx, router]);

  useEffect(() => {
    rowRefs.current[focusedIdx]?.scrollIntoView({ block: "nearest" });
  }, [focusedIdx]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <FilterSelect label="Stage" value={stage} onChange={setStage} options={stages} />
        <FilterSelect label="Sector" value={sector} onChange={setSector} options={sectors} />
        <FilterSelect label="Size band" value={sizeBand} onChange={setSizeBand} options={sizeBands} />
        <FilterSelect
          label="Sort"
          value={sortMode}
          onChange={(v) => setSortMode(v as SortMode)}
          options={["score", "newest", "succession"]}
          allLabel={null}
        />
        <div className="flex items-center gap-2 pb-2">
          <Checkbox id="red-flag-only" checked={redFlagOnly} onCheckedChange={(v) => setRedFlagOnly(!!v)} />
          <Label htmlFor="red-flag-only">Red flags only</Label>
        </div>
        <div className="flex items-center gap-2 pb-2">
          <Checkbox id="new-only" checked={newOnly} onCheckedChange={(v) => setNewOnly(!!v)} />
          <Label htmlFor="new-only">New since last visit</Label>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        {filtered.length} of {rows.length} shortlisted &middot; keyboard: <kbd>j</kbd>/<kbd>k</kbd> to move,{" "}
        <kbd>enter</kbd> to open
      </p>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10">#</TableHead>
            <TableHead>Company</TableHead>
            <TableHead>Score</TableHead>
            <TableHead>Top dimensions</TableHead>
            <TableHead>Value angles</TableHead>
            <TableHead>Red flags</TableHead>
            <TableHead>Signals</TableHead>
            <TableHead>Stage</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filtered.map((row, idx) => {
            const isNew = !!lastVisit && row.scored_at > lastVisit;
            const topSignals = [...row.signals].sort((a, b) => b.value - a.value).slice(0, 2);
            return (
              <TableRow
                key={row.company_id}
                ref={(el) => {
                  rowRefs.current[idx] = el;
                }}
                onClick={() => router.push(`/company/${row.company_number}`)}
                className={cn("cursor-pointer", idx === focusedIdx && "bg-muted")}
              >
                <TableCell className="font-mono text-xs text-muted-foreground">{idx + 1}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{row.legal_name}</span>
                    {isNew && <Badge variant="success">new</Badge>}
                    {row.data_completeness !== null && row.data_completeness < 1 && (
                      <Badge variant="warning">scoring-incomplete</Badge>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1 pt-1">
                    {(row.sector_tags ?? []).map((t) => (
                      <Badge key={t} variant="outline">
                        {t}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell className="text-lg font-semibold tabular-nums">
                  {row.total_score !== null ? Math.round(row.total_score) : "—"}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {row.top_dimensions.length === 0 && <span className="text-xs text-muted-foreground">—</span>}
                    {row.top_dimensions.map((d) => (
                      <Badge key={d.dimension} variant="outline">
                        {titleCase(d.dimension)} {d.raw_score !== null ? d.raw_score.toFixed(1) : "—"}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {row.value_angles.map((a) => (
                      <Badge key={a} variant="secondary">
                        {titleCase(a)}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {row.red_flags.map((f) => (
                      <Badge key={f} variant="destructive">
                        {titleCase(f)}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
                    {topSignals.length === 0 && <span>—</span>}
                    {topSignals.map((s) => (
                      <span key={s.name} className="rounded bg-muted px-1.5 py-0.5">
                        {titleCase(s.name)} {s.value.toFixed(2)}
                      </span>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant="outline">{titleCase(row.pipeline_stage ?? "inbox")}</Badge>
                </TableCell>
              </TableRow>
            );
          })}
          {filtered.length === 0 && (
            <TableRow>
              <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                No companies match these filters.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
  allLabel = "All",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
  allLabel?: string | null;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="w-40">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {allLabel && <SelectItem value="all">{allLabel}</SelectItem>}
          {options.map((o) => (
            <SelectItem key={o} value={o}>
              {titleCase(o)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
