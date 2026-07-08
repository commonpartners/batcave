"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { ScoreDimensionRow } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { cn, titleCase } from "@/lib/utils";

export function DimensionBar({ dimension, weight }: { dimension: ScoreDimensionRow; weight?: number }) {
  const [open, setOpen] = useState(false);
  const raw = dimension.raw_score;
  const pct = raw !== null ? (raw / 5) * 100 : 0;

  const evidence = Array.isArray(dimension.evidence)
    ? (dimension.evidence as unknown[])
    : dimension.evidence && typeof dimension.evidence === "object"
      ? Object.entries(dimension.evidence as Record<string, unknown>)
      : [];

  return (
    <div className="border-b py-2 last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 text-left"
        aria-expanded={open}
      >
        <span className="w-40 shrink-0 text-sm font-medium">{titleCase(dimension.dimension)}</span>
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            className={cn("h-full rounded-full", raw === null ? "bg-muted" : "bg-primary")}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="w-16 shrink-0 text-right text-sm tabular-nums">{raw !== null ? raw.toFixed(1) : "—"}/5</span>
        {weight !== undefined && (
          <Badge variant="outline" className="shrink-0">
            {weight}%
          </Badge>
        )}
        <Badge variant={dimension.method === "llm" ? "secondary" : "outline"} className="shrink-0">
          {dimension.method ?? "n/a"}
        </Badge>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="ml-0 mt-2 space-y-2 rounded-md bg-muted/50 p-3 text-sm sm:ml-40">
          {raw === null ? (
            <p className="text-muted-foreground">Not scored (missing data or LLM call failed twice).</p>
          ) : (
            <>
              <p>{dimension.rationale ?? "No rationale recorded."}</p>
              {Array.isArray(evidence) && evidence.length > 0 && (
                <ul className="list-inside list-disc space-y-1 text-muted-foreground">
                  {evidence.map((item, i) => (
                    <li key={i}>
                      <EvidenceItem item={item} />
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function EvidenceItem({ item }: { item: unknown }) {
  if (Array.isArray(item)) {
    const [key, value] = item as [string, unknown];
    return (
      <span>
        <strong>{titleCase(key)}:</strong> <EvidenceValue value={value} />
      </span>
    );
  }
  return <EvidenceValue value={item} />;
}

function EvidenceValue({ value }: { value: unknown }) {
  if (value && typeof value === "object" && "source_url" in (value as Record<string, unknown>)) {
    const v = value as { source_url?: string; quote?: string; text?: string };
    return (
      <>
        {v.quote ?? v.text ?? JSON.stringify(v)}{" "}
        {v.source_url && (
          <a href={v.source_url} target="_blank" rel="noreferrer" className="underline">
            source
          </a>
        )}
      </>
    );
  }
  if (typeof value === "string") return <>{value}</>;
  return <>{JSON.stringify(value)}</>;
}
