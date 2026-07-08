"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { decidedByFromEmail } from "@/lib/allowlist";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { titleCase } from "@/lib/utils";
import type { DecisionType } from "@/lib/types";

const DECISION_LABEL: Record<DecisionType, string> = {
  accept: "Accept — pursue",
  reject: "Reject",
  watchlist: "Watchlist",
  retag: "Retag",
};

export function DecisionDialog({
  companyId,
  scoreId,
  decision,
  reasonCodes,
  open,
  onOpenChange,
  onRecorded,
}: {
  companyId: string;
  scoreId: string | null;
  decision: DecisionType;
  reasonCodes: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRecorded?: () => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [freeText, setFreeText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const supabase = createClient();

  function toggle(code: string) {
    setSelected((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]));
  }

  async function handleSubmit() {
    if (selected.length === 0) {
      setError("Pick at least one reason code.");
      return;
    }
    setSubmitting(true);
    setError(null);

    const {
      data: { user },
    } = await supabase.auth.getUser();

    const { error: insertError } = await supabase.from("decisions").insert({
      company_id: companyId,
      score_id: scoreId,
      decision,
      reasons: selected,
      free_text: freeText || null,
      decided_by: decidedByFromEmail(user?.email),
    });

    setSubmitting(false);

    if (insertError) {
      setError(insertError.message);
      return;
    }

    setSelected([]);
    setFreeText("");
    onOpenChange(false);
    onRecorded?.();
    router.refresh();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{DECISION_LABEL[decision]}</DialogTitle>
          <DialogDescription>
            Pick at least one reason code. This pairing of score + reason is the training data for the learning
            loop — be honest, &quot;gut feel&quot; is a valid reason.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {reasonCodes.map((code) => (
            <div key={code} className="flex items-center gap-2">
              <Checkbox id={`reason-${code}`} checked={selected.includes(code)} onCheckedChange={() => toggle(code)} />
              <Label htmlFor={`reason-${code}`} className="text-sm font-normal">
                {titleCase(code)}
              </Label>
            </div>
          ))}
        </div>

        <div className="space-y-2">
          <Label htmlFor="free-text">Notes (optional)</Label>
          <Textarea
            id="free-text"
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            placeholder="Anything else worth recording..."
          />
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? "Recording…" : "Record decision"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
