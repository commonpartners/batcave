"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { DecisionDialog } from "@/components/decision-dialog";
import type { DecisionType } from "@/lib/types";

export function DecisionBar({
  companyId,
  scoreId,
  reasonCodes,
}: {
  companyId: string;
  scoreId: string | null;
  reasonCodes: string[];
}) {
  const [openDecision, setOpenDecision] = useState<DecisionType | null>(null);

  return (
    <>
      <div className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 backdrop-blur decision-bar-safe-area">
        <div className="container flex gap-2 py-3">
          <Button className="flex-1" onClick={() => setOpenDecision("accept")}>
            Accept
          </Button>
          <Button variant="destructive" className="flex-1" onClick={() => setOpenDecision("reject")}>
            Reject
          </Button>
          <Button variant="secondary" className="flex-1" onClick={() => setOpenDecision("watchlist")}>
            Watchlist
          </Button>
          <Button variant="outline" className="flex-1" onClick={() => setOpenDecision("retag")}>
            Retag
          </Button>
        </div>
      </div>

      {openDecision && (
        <DecisionDialog
          companyId={companyId}
          scoreId={scoreId}
          decision={openDecision}
          reasonCodes={reasonCodes}
          open={!!openDecision}
          onOpenChange={(open) => !open && setOpenDecision(null)}
        />
      )}
    </>
  );
}
