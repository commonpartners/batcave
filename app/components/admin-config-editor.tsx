"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AppConfigRow } from "@/lib/types";

export function AdminConfigEditor({ configs }: { configs: AppConfigRow[] }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {configs.map((c) => (
        <ConfigCard key={c.key} config={c} />
      ))}
    </div>
  );
}

function ConfigCard({ config }: { config: AppConfigRow }) {
  const [value, setValue] = useState(JSON.stringify(config.value, null, 2));
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const supabase = createClient();

  async function save() {
    setStatus("saving");
    setError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(value);
    } catch {
      setStatus("error");
      setError("Not valid JSON.");
      return;
    }
    const { error: updateError } = await supabase.from("app_config").update({ value: parsed }).eq("key", config.key);
    if (updateError) {
      setStatus("error");
      setError(updateError.message);
      return;
    }
    setStatus("saved");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{config.key}</CardTitle>
        {config.description && <p className="text-xs text-muted-foreground">{config.description}</p>}
      </CardHeader>
      <CardContent className="space-y-2">
        <Textarea value={value} onChange={(e) => setValue(e.target.value)} rows={4} className="font-mono text-xs" />
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={save} disabled={status === "saving"}>
            {status === "saving" ? "Saving…" : "Save"}
          </Button>
          {status === "saved" && <span className="text-xs text-emerald-700">Saved.</span>}
          {error && <span className="text-xs text-destructive">{error}</span>}
        </div>
      </CardContent>
    </Card>
  );
}
