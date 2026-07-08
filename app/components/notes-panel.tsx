"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { decidedByFromEmail } from "@/lib/allowlist";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { NoteRow } from "@/lib/types";
import { formatDate, titleCase } from "@/lib/utils";

/** Spec 05 §1: "Notes: free-text per company, author + timestamp" — backed by
 * the append-only `notes` table (0011_notes.sql), one row per entry. */
export function NotesPanel({ companyId, notes }: { companyId: string; notes: NoteRow[] }) {
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const router = useRouter();
  const supabase = createClient();

  async function addNote() {
    if (!draft.trim()) return;
    setSaving(true);
    const {
      data: { user },
    } = await supabase.auth.getUser();
    const { error } = await supabase.from("notes").insert({
      company_id: companyId,
      author: decidedByFromEmail(user?.email),
      body: draft.trim(),
    });
    setSaving(false);
    if (!error) {
      setDraft("");
      router.refresh();
    }
  }

  return (
    <div className="space-y-3">
      <Textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={3}
        placeholder="Add a note on this company..."
      />
      <Button size="sm" onClick={addNote} disabled={saving || !draft.trim()}>
        {saving ? "Saving…" : "Add note"}
      </Button>

      {notes.length > 0 && (
        <ul className="space-y-2 border-t pt-3">
          {notes.map((n) => (
            <li key={n.id} className="text-sm">
              <span className="font-medium">{titleCase(n.author)}</span>{" "}
              <span className="text-xs text-muted-foreground">({formatDate(n.created_at)})</span>
              <p className="text-muted-foreground">{n.body}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
