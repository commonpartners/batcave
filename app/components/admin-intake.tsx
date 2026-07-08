"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function AdminIntake() {
  const [text, setText] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "done" | "error">("idle");
  const [result, setResult] = useState<string | null>(null);

  async function submit() {
    setStatus("sending");
    setResult(null);
    try {
      const res = await fetch("/api/intake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const json = await res.json();
      if (!res.ok) {
        setStatus("error");
        setResult(json.error ?? "Intake failed.");
        return;
      }
      setStatus("done");
      setResult(`Queued ${json.count ?? 0} row(s) for intake.`);
      setText("");
    } catch (e) {
      setStatus("error");
      setResult(e instanceof Error ? e.message : "Intake failed.");
    }
  }

  return (
    <div className="space-y-2">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        placeholder={"One company per line - name or company number, e.g.\nAcme Skincare Ltd\n01234567"}
      />
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={submit} disabled={status === "sending" || !text.trim()}>
          {status === "sending" ? "Submitting…" : "Submit for intake"}
        </Button>
        {result && (
          <span className={`text-xs ${status === "error" ? "text-destructive" : "text-muted-foreground"}`}>{result}</span>
        )}
      </div>
    </div>
  );
}
