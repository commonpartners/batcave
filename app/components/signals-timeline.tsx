import type { SignalRow } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { formatDate, titleCase } from "@/lib/utils";

const FAMILY_VARIANT: Record<SignalRow["family"], "default" | "secondary" | "outline"> = {
  succession: "default",
  latent_upside: "secondary",
  consolidation: "outline",
};

export function SignalsTimeline({ signals }: { signals: SignalRow[] }) {
  if (signals.length === 0) {
    return <p className="text-sm text-muted-foreground">No signals computed yet.</p>;
  }

  const sorted = [...signals].sort((a, b) => (b.computed_at ?? "").localeCompare(a.computed_at ?? ""));

  return (
    <ol className="space-y-3">
      {sorted.map((s) => (
        <li key={s.id} className="flex gap-3 border-l-2 pl-3">
          <div className="w-24 shrink-0 text-xs text-muted-foreground">{formatDate(s.computed_at)}</div>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Badge variant={FAMILY_VARIANT[s.family]}>{titleCase(s.family)}</Badge>
              <span className="text-sm font-medium">{titleCase(s.name)}</span>
              <span className="text-xs text-muted-foreground">{s.value.toFixed(2)}</span>
            </div>
            {s.rationale && <p className="text-sm text-muted-foreground">{s.rationale}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}
