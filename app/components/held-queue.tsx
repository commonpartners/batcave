"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { decidedByFromEmail } from "@/lib/allowlist";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CompanyRow } from "@/lib/types";
import { titleCase } from "@/lib/utils";

interface HeldScoreRow {
  id: string;
  company_id: string;
  gate_detail: Record<string, { result: string; reason: string }> | null;
  scored_at: string;
  companies: CompanyRow;
}

export function HeldQueue({ rows }: { rows: HeldScoreRow[] }) {
  const supabase = createClient();
  const [busy, setBusy] = useState<string | null>(null);

  const groups = useMemo(() => {
    const byTest = new Map<string, HeldScoreRow[]>();
    for (const row of rows) {
      const failing = Object.entries(row.gate_detail ?? {}).filter(([, v]) => v.result !== "pass");
      const keys = failing.length > 0 ? failing.map(([k]) => k) : ["unknown"];
      for (const key of keys) {
        if (!byTest.has(key)) byTest.set(key, []);
        byTest.get(key)!.push(row);
      }
    }
    return byTest;
  }, [rows]);

  async function overrideGate(row: HeldScoreRow) {
    setBusy(row.id);
    const {
      data: { user },
    } = await supabase.auth.getUser();
    await supabase.from("decisions").insert({
      company_id: row.company_id,
      score_id: row.id,
      decision: "accept",
      reasons: ["gut_feel"],
      free_text: "Gate override from /held queue.",
      decided_by: decidedByFromEmail(user?.email),
    });
    await supabase
      .from("pipeline_items")
      .upsert({ company_id: row.company_id, stage: "review", stage_changed_at: new Date().toISOString() }, { onConflict: "company_id" });
    setBusy(null);
    window.location.reload();
  }

  async function reject(row: HeldScoreRow) {
    setBusy(row.id);
    const {
      data: { user },
    } = await supabase.auth.getUser();
    await supabase.from("decisions").insert({
      company_id: row.company_id,
      score_id: row.id,
      decision: "reject",
      reasons: ["sector_wrong"],
      free_text: "Rejected from /held queue.",
      decided_by: decidedByFromEmail(user?.email),
    });
    await supabase
      .from("pipeline_items")
      .upsert({ company_id: row.company_id, stage: "passed", stage_changed_at: new Date().toISOString() }, { onConflict: "company_id" });
    setBusy(null);
    window.location.reload();
  }

  return (
    <div className="space-y-6">
      {Array.from(groups.entries()).map(([testName, group]) => (
        <section key={testName}>
          <h2 className="mb-2 text-lg font-semibold">{titleCase(testName)}</h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {group.map((row) => (
              <Card key={`${testName}-${row.id}`}>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between text-base">
                    <Link href={`/company/${row.companies.company_number}`} className="hover:underline">
                      {row.companies.legal_name}
                    </Link>
                    <Badge variant="warning">hold</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <p className="text-sm text-muted-foreground">
                    {row.gate_detail?.[testName]?.reason ?? "No reason recorded."}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" disabled={busy === row.id} onClick={() => overrideGate(row)}>
                      Override gate
                    </Button>
                    <Button size="sm" variant="outline" asChild>
                      <Link href={`/company/${row.companies.company_number}`}>Fix data</Link>
                    </Button>
                    <Button size="sm" variant="destructive" disabled={busy === row.id} onClick={() => reject(row)}>
                      Reject
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
