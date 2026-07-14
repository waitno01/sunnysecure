import { useState, useEffect, useRef, useLayoutEffect, useCallback, useMemo } from "react";
import { ReactSkinview3d } from "react-skinview3d";
import {
  Search, Download, Check, Copy, Link2, Lock, X, Power, ArrowLeft,
  Loader2, RotateCcw, Mail, ChevronRight, Trash2, CheckSquare, Filter,
} from "lucide-react";
import { toast } from "sonner";
import { cn, simplify } from "@/lib/utils";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { useNotifications, authHeaders } from "./context";
import type { EmailEntry, EmailMessage } from "./types";

export type Account = {
  account_id: string;
  ms_email: string;
  mc_name: string;
  mc_method: string;
  mc_gamertag: string;
  mc_capes: string;
  secured_at: string;
  ms_security_email?: string;
  ms_password?: string;
  ms_recovery_code?: string;
  ms_auth_secret?: string;
  ms_first_name?: string;
  ms_last_name?: string;
  ms_full_name?: string;
  ms_region?: string;
  ms_birthday?: string;
  ms_language?: string;
  ms_family?: string;
  ms_devices?: string;
  ms_cards?: string;
  ms_subscriptions_active?: string;
  ms_subscriptions_canceled?: string;
  ms_subscriptions_commercial?: string;
  mc_ssid?: string;
  mc_uchange?: string;
};

/** gamepass | owned (purchased / java) | no_mc (none or check failed) */
type McCategory = "gamepass" | "owned" | "no_mc";
type McFilter = "all" | McCategory;
type SortMode = "newest" | "oldest" | "mc_type" | "mc_type_rev";

const LS_EXCLUDE_DUPES = "autosecure.accounts.excludeDuplicates";
const LS_MC_FILTER = "autosecure.accounts.mcFilter";
const LS_SORT = "autosecure.accounts.sortMode";

function readLs<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    if (v && (allowed as readonly string[]).includes(v)) return v;
  } catch { /* ignore */ }
  return fallback;
}

function accountMcCategory(a: Account): McCategory {
  const name = (a.mc_name || "").trim();
  const method = (a.mc_method || "").trim().toLowerCase();
  const nameL = name.toLowerCase();

  if (
    !name ||
    nameL === "no minecraft" ||
    nameL.includes("mc check failed") ||
    nameL.includes("no minecraft") ||
    method.includes("mc check failed") ||
    method === "not purchased" ||
    method === "unknown"
  ) {
    return "no_mc";
  }
  if (method.includes("gamepass")) return "gamepass";
  // Purchased / has a real profile name (incl. No Java / Owned labels)
  if (
    method.includes("purchased") ||
    method.includes("mc_purchase") ||
    nameL.includes("no java") ||
    nameL.startsWith("owned")
  ) {
    return "owned";
  }
  // Has a username but method unknown → treat as owned (MC present)
  if (name && !nameL.includes("failed")) return "owned";
  return "no_mc";
}

const MC_TYPE_ORDER: Record<McCategory, number> = {
  gamepass: 0,
  owned: 1,
  no_mc: 2,
};

function dedupeLatestByEmail(list: Account[]): Account[] {
  // API already returns secured_at DESC — keep first seen per email
  const seen = new Set<string>();
  const out: Account[] = [];
  for (const a of list) {
    const key = (a.ms_email || "").trim().toLowerCase();
    if (!key) {
      out.push(a);
      continue;
    }
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(a);
  }
  return out;
}

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

function ExportModal({ accounts, onClose }: { accounts: Account[]; onClose: () => void }) {
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

function CopyableValue({ value, mono, breakAll, title, muted, italic, className }: { value?: string | null; mono?: boolean; breakAll?: boolean; title?: string; muted?: boolean; italic?: boolean; className?: string }) {
  const hasValue = !!value && value !== "false" && value !== "None";
  return (
    <span
      onDoubleClick={() => { if (hasValue) { navigator.clipboard.writeText(value as string); toast.success("Copied to clipboard"); } }}
      title={title || "Double-click to copy"}
      className={className || "db-detail-stat-value"}
      style={{
        ...(mono ? { fontFamily: "var(--font-mono, monospace)" } : {}),
        ...(breakAll ? { wordBreak: "break-all", whiteSpace: "normal" } : {}),
        ...(muted ? { color: "var(--muted-foreground)", opacity: 0.6 } : {}),
        ...(italic ? { fontStyle: "italic" } : {}),
        cursor: "text",
        userSelect: "text",
        WebkitUserSelect: "text",
      }}
    >
      {hasValue ? value : (muted ? "None" : "—")}
    </span>
  );
}

function ShareLinksModal({ links, domain, onClose, onDeleted }: { links: any[]; domain: string; onClose: () => void; onDeleted: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-border bg-card shadow-2xl" onClick={e => e.stopPropagation()} style={{ maxHeight: "70vh", display: "flex", flexDirection: "column", animation: "dbIn 0.25s cubic-bezier(0.22, 1, 0.36, 1) both" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "1rem 1.25rem", borderBottom: "1px solid var(--border)" }}>
          <h2 className="db-detail-heading" style={{ fontSize: "1rem" }}>Shared Links ({links.length})</h2>
          <button onClick={onClose} style={{ display: "grid", placeItems: "center", width: 30, height: 30, borderRadius: 8, border: "none", background: "transparent", color: "var(--muted-foreground)", cursor: "pointer" }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div style={{ overflowY: "auto", padding: "0.75rem", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
          {links.map(link => (
            <div key={link.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem", padding: "0.55rem 0.7rem", background: "color-mix(in oklab, var(--background) 45%, transparent)", border: "1px solid color-mix(in oklab, var(--border) 25%, transparent)", borderRadius: 8, fontSize: "0.8rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", minWidth: 0, flex: 1 }}>
                <Link2 className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--muted-foreground)" }} />
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: '"JetBrains Mono", monospace', fontSize: "0.75rem", color: "var(--muted-foreground)" }}>
                  {domain}/share/{link.id}
                </span>
                {link.has_password && <Lock className="h-3 w-3 shrink-0" style={{ color: "var(--accent)" }} />}
                <span style={{ fontSize: "0.65rem", color: "color-mix(in oklab, var(--muted-foreground) 60%, transparent)", whiteSpace: "nowrap" }}>
                  {link.access_count} views
                </span>
              </div>
              <div style={{ display: "flex", gap: "0.35rem", flexShrink: 0 }} onClick={e => e.stopPropagation()}>
                <button onClick={(e) => {
                  navigator.clipboard.writeText(`${domain}/share/${link.id}`);
                  const btn = e.currentTarget;
                  btn.textContent = "Copied!";
                  setTimeout(() => { btn.textContent = "Copy"; }, 1200);
                }} style={{ padding: "0.25rem 0.5rem", borderRadius: 6, border: "none", background: "color-mix(in oklab, var(--primary) 15%, transparent)", color: "var(--primary)", fontSize: "0.65rem", fontWeight: 600, cursor: "pointer", transition: "all 0.2s" }}>
                  Copy
                </button>
                <button onClick={() => {
                  fetch(`/api/share/${link.id}`, { method: "DELETE", headers: authHeaders() })
                    .then(() => onDeleted())
                    .catch(() => {});
                }} style={{ flexShrink: 0, width: 26, height: 26, display: "grid", placeItems: "center", borderRadius: 6, border: "none", background: "transparent", color: "var(--muted-foreground)", cursor: "pointer", opacity: 0.5, transition: "opacity 0.15s" }}
                  onMouseEnter={e => (e.currentTarget.style.opacity = "1")}
                  onMouseLeave={e => (e.currentTarget.style.opacity = "0.5")}
                  title="Delete link"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ShareLinkModal({ accountId, domain, onClose, onCreated }: { accountId: string; domain: string; onClose: () => void; onCreated: () => void }) {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [createdLink, setCreatedLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copyAnim, setCopyAnim] = useState(false);

  async function handleGenerate() {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`/api/accounts/${accountId}/share`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ password: password.trim() || null }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || "Failed to create link.");
      }
      const data = await res.json();
      setCreatedLink(`${domain}/share/${data.link_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl overflow-hidden" onClick={e => e.stopPropagation()}>
        <div key={createdLink ? "success" : "form"} style={{ animation: "dbIn 0.25s cubic-bezier(0.22, 1, 0.36, 1) both" }}>
          {createdLink ? (
            <>
              <div style={{ textAlign: "center", marginBottom: "1rem" }}>
                <Check className="h-10 w-10" style={{ margin: "0 auto", color: "var(--accent)" }} />
                <h2 className="db-detail-heading" style={{ marginTop: "0.5rem", fontSize: "1.1rem" }}>Link Created!</h2>
                <p style={{ fontSize: "0.8rem", color: "var(--muted-foreground)", marginTop: "0.25rem" }}>Share this link to let others view the account.</p>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", padding: "0.6rem 0.75rem", background: "color-mix(in oklab, var(--background) 50%, transparent)", border: "1px solid var(--border)", borderRadius: 8, fontSize: "0.78rem", fontFamily: '"JetBrains Mono", monospace', wordBreak: "break-all" }}>
                <span style={{ flex: 1, color: "var(--foreground)", minWidth: 0 }}>{createdLink}</span>
                <button onClick={() => { navigator.clipboard.writeText(createdLink); setCopyAnim(true); setTimeout(() => setCopyAnim(false), 1200); }}
                  style={{ flexShrink: 0, padding: "0.3rem 0.6rem", borderRadius: 6, border: "none", background: copyAnim ? "color-mix(in oklab, var(--accent) 20%, transparent)" : "color-mix(in oklab, var(--primary) 15%, transparent)", color: copyAnim ? "var(--accent)" : "var(--primary)", fontSize: "0.7rem", fontWeight: 600, cursor: "pointer", transition: "background 0.25s, color 0.25s" }}>
                  {copyAnim ? "Copied!" : "Copy"}
                </button>
              </div>
              <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
                <button onClick={() => { setCreatedLink(null); setPassword(""); }} style={{ flex: 1, padding: "0.5rem", borderRadius: 8, border: "1px solid var(--border)", background: "transparent", color: "var(--foreground)", fontSize: "0.8rem", fontWeight: 600, cursor: "pointer" }}>
                  Create Another
                </button>
                <button onClick={onCreated} style={{ flex: 1, padding: "0.5rem", borderRadius: 8, border: "none", background: "linear-gradient(135deg, var(--primary), var(--accent))", color: "var(--primary-foreground)", fontSize: "0.8rem", fontWeight: 600, cursor: "pointer" }}>
                  Done
                </button>
              </div>
            </>
          ) : (
            <>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.75rem" }}>
                <h2 className="db-detail-heading" style={{ fontSize: "1.1rem" }}>Generate Share Link</h2>
                <button onClick={onClose} style={{ display: "grid", placeItems: "center", width: 30, height: 30, borderRadius: 8, border: "none", background: "transparent", color: "var(--muted-foreground)", cursor: "pointer" }}>
                  <X className="h-4 w-4" />
                </button>
              </div>

              {error && (
                <div style={{ padding: "0.5rem 0.75rem", marginBottom: "0.75rem", borderRadius: 8, background: "color-mix(in oklab, var(--primary) 15%, transparent)", color: "var(--primary)", fontSize: "0.8rem", textAlign: "center" }}>
                  {error}
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                <div style={{ fontSize: "0.8rem", color: "var(--muted-foreground)" }}>
                  Password <span style={{ opacity: 0.5 }}>(optional)</span>
                </div>
                <input
                  type="text"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="Leave empty for no password"
                  style={{ width: "100%", padding: "0.55rem 0.75rem", borderRadius: 8, border: "1px solid var(--border)", background: "var(--background)", color: "var(--foreground)", fontSize: "0.85rem", outline: "none", boxSizing: "border-box" }}
                />

                <button onClick={handleGenerate} disabled={loading}
                  style={{ padding: "0.55rem 1rem", borderRadius: 8, border: "none", background: "linear-gradient(135deg, var(--primary), var(--accent))", color: "var(--primary-foreground)", fontSize: "0.85rem", fontWeight: 600, cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.6 : 1, display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem" }}
                >
                  {loading ? "Generating..." : <><Link2 className="h-4 w-4" /> Generate Link</>}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function GameStatsSection({ accountId, mcName }: { accountId: string; mcName?: string }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<"hypixel" | "donut">("hypixel");
  const [error, setError] = useState<string | null>(null);

  const fetchStats = useCallback(() => {
    if (!mcName || mcName === "No Minecraft") return;
    setLoading(true);
    setError(null);
    fetch(`/api/accounts/${accountId}/stats`, { headers: authHeaders() })
      .then(r => r.json())
      .then(res => setData(res.stats || {}))
      .catch(() => setError("Failed to load stats"))
      .finally(() => setLoading(false));
  }, [accountId, mcName]);

  useEffect(() => { fetchStats(); }, [fetchStats]);

  if (!mcName || mcName === "No Minecraft") return null;

  const fmt = (v: any): string => {
    if (v == null || v === undefined) return "—";
    if (typeof v === "number") return simplify(v);
    const s = String(v);
    const n = parseFloat(s);
    if (!isNaN(n) && isFinite(n) && /^[-+]?[\d.eE+]+$/.test(s)) return simplify(n);
    return s;
  };

  const renderStatItem = (label: string, value: any) => (
    <div className="db-stats-item" key={label}>
      <span className="db-stats-item-label">{label}</span>
      <span className="db-stats-item-value">{fmt(value)}</span>
    </div>
  );

  const renderCategory = (label: string, items: React.ReactNode[]): React.ReactNode[] => [
    <div className="db-stats-category" key={label}>{label}</div>,
    ...items,
  ];

  const renderHypixel = () => {
    const h = data?.hypixel;
    if (!h || h.error) return <div className="db-stats-empty">{h?.error || "No Hypixel data available."}</div>;
    const items: React.ReactNode[] = [];
    items.push(...renderCategory("General", [
      renderStatItem("Rank", h.hypixel?.rank),
      renderStatItem("Level", h.hypixel?.level),
      renderStatItem("Karma", h.hypixel?.karma),
      renderStatItem("Gifted", h.hypixel?.gifted),
      renderStatItem("Points", h.hypixel?.points),
    ]));
    items.push(...renderCategory("Bedwars", [
      renderStatItem("Wins", h.bedwars?.wins),
      renderStatItem("Losses", h.bedwars?.losses),
      renderStatItem("Kills", h.bedwars?.kills),
      renderStatItem("Deaths", h.bedwars?.deaths),
      renderStatItem("Final Kills", h.bedwars?.final_kills),
      renderStatItem("K/D", h.bedwars?.kd),
    ]));
    items.push(...renderCategory("Skywars", [
      renderStatItem("Wins", h.skywars?.sw_wins),
      renderStatItem("Losses", h.skywars?.sw_losses),
      renderStatItem("Kills", h.skywars?.sw_kills),
      renderStatItem("Deaths", h.skywars?.sw_deaths),
      renderStatItem("K/D", h.skywars?.sw_kd),
    ]));
    items.push(...renderCategory("Skyblock", [
      renderStatItem("Level", h.skyblock?.level),
      renderStatItem("Networth", h.skyblock?.networth ? `${simplify(h.skyblock.networth)} Coins` : "—"),
    ]));
    return items;
  };

  const renderDonut = (): React.ReactNode => {
    const d = data?.donut;
    if (!d || d.error || d === "Failed" || d === false) return <div className="db-stats-empty" key="empty">{d?.error || "No Donut data available."}</div>;
    const r = d.result;
    if (!r) return <div className="db-stats-empty" key="empty">No Donut stats found.</div>;
    const ms = parseInt(r.playtime) || 0;
    const days = Math.floor(ms / 86400000);
    const hours = Math.floor((ms % 86400000) / 3600000);
    return [
      renderStatItem("Money", `$${simplify(r.money)}`),
      renderStatItem("Shards", simplify(r.shards)),
      renderStatItem("Kills", simplify(r.kills)),
      renderStatItem("Deaths", simplify(r.deaths)),
      renderStatItem("K/D", d.kd != null ? d.kd.toFixed(2) : "—"),
      renderStatItem("Playtime", `${days}d ${hours}h`),
      renderStatItem("Blocks Placed", simplify(r.placed_blocks)),
      renderStatItem("Blocks Broken", simplify(r.broken_blocks)),
      renderStatItem("Mobs Killed", simplify(r.mobs_killed)),
      renderStatItem("Shop Spent", `$${simplify(r.money_spent_on_shop)}`),
      renderStatItem("Sell Made", `$${simplify(r.money_made_from_sell)}`),
    ];
  };

  return (
    <div className="db-stats-card">
      <div className="db-stats-tabs">
        <button className="db-stats-tab" data-active={activeTab === "hypixel" || undefined} onClick={() => setActiveTab("hypixel")}>Hypixel</button>
        <button className="db-stats-tab" data-active={activeTab === "donut" || undefined} onClick={() => setActiveTab("donut")}>Donut SMP</button>
        <button
          onClick={fetchStats}
          style={{ marginLeft: "auto", display: "grid", placeItems: "center", width: "26px", height: "26px", borderRadius: "6px", border: "none", background: "transparent", color: "var(--muted-foreground)", cursor: "pointer", transition: "all 0.15s" }}
          title="Refresh stats"
        >
          <RotateCcw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </button>
      </div>
      <div className="db-stats-grid" key={activeTab}>
        {loading ? (
          <div className="db-stats-empty" style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem" }}>
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading stats...
          </div>
        ) : error ? (
          <div className="db-stats-empty">Failed to load stats.</div>
        ) : (
          activeTab === "hypixel" ? renderHypixel() : renderDonut()
        )}
      </div>
    </div>
  );
}

export function AccountDetail({ account, onBack, onDeleted }: { account: Account; onBack: () => void; onDeleted: () => void }) {
  const [detail, setDetail] = useState<Account>(account);
  const [emails, setEmails] = useState<EmailEntry[]>([]);
  const [showMail, setShowMail] = useState(false);
  const [selectedMsg, setSelectedMsg] = useState<EmailMessage | null>(null);
  const [listModal, setListModal] = useState<{ label: string; items: unknown[] } | null>(null);
  const [skinSize, setSkinSize] = useState<{ width: number; height: number } | null>(null);
  const skinRef = useRef<HTMLDivElement>(null);
  const [showShareModal, setShowShareModal] = useState(false);
  const [shareLinks, setShareLinks] = useState<any[]>([]);
  const [domain, setDomain] = useState("securings.fun");
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    const label = detail.mc_name || detail.ms_email || "this account";
    if (!window.confirm(`Delete ${label} from the database? This cannot be undone.`)) return;
    setDeleting(true);
    try {
      const res = await fetch(`/api/accounts/${account.account_id}`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail || "Failed to delete account.");
      }
      toast.success("Account deleted");
      onDeleted();
      onBack();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete account.");
    } finally {
      setDeleting(false);
    }
  }

  useLayoutEffect(() => {
    const el = skinRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setSkinSize({ width: Math.round(width), height: Math.round(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const parseList = (v: unknown): unknown[] | null => {
    if (v == null || v === undefined) return null;
    if (Array.isArray(v)) return v.length ? v : null;
    if (typeof v === "string") {
      if (v === "[]" || v === "{}" || !v.trim()) return null;
      try { const p = JSON.parse(v); return Array.isArray(p) ? (p.length ? p : null) : [p]; }
      catch { return null; }
    }
    return null;
  };

  useEffect(() => {
    fetch(`/api/accounts/${account.account_id}`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => setDetail({ ...account, ...data }))
      .catch(() => {});
    fetch("/api/config", { headers: authHeaders() })
      .then(r => r.json())
      .then(cfg => setDomain(cfg.domain))
      .catch(() => {});
    fetchShareLinks();
  }, [account.account_id]);

  function fetchShareLinks() {
    fetch(`/api/accounts/${account.account_id}/links`, { headers: authHeaders() })
      .then(r => r.json())
      .then(setShareLinks)
      .catch(() => {});
  }

  useEffect(() => {
    fetch("/api/emails", { headers: authHeaders() })
      .then(r => r.json())
      .then(setEmails)
      .catch(() => {});
    const interval = setInterval(() => {
      fetch("/api/emails", { headers: authHeaders() })
        .then(r => r.json())
        .then(setEmails)
        .catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  const matchedEmail = emails.find(e => e.email === detail.ms_security_email);

  const subDevBadges = [
    { field: "ms_subscriptions_active", label: "Active", color: "var(--accent)" },
    { field: "ms_subscriptions_canceled", label: "Canceled", color: "var(--muted-foreground)" },
    { field: "ms_subscriptions_commercial", label: "Commercial", color: "var(--primary)" },
    { field: "ms_devices", label: "Devices", color: "#22c55e" },
    { field: "ms_cards", label: "Cards", color: "#f59e0b" },
  ].map(({ field, label, color }) => {
    const items = parseList((detail as any)[field]);
    return items ? (
      <span key={field} style={{ padding: "0.15rem 0.45rem", fontSize: "0.65rem", fontWeight: 600, borderRadius: 4, background: `color-mix(in oklab, ${color} 12%, transparent)`, color, whiteSpace: "nowrap" }}>
        {label}: {items.length}
      </span>
    ) : null;
  });

  const renderSubRow = (label: string, field: string) => {
    const items = parseList((detail as any)[field]);
    return (
      <div className={`db-detail-stat-block${!items ? " db-detail-stat-block--empty" : ""}`}
        style={{ cursor: items ? "pointer" : "default" }}
        onClick={() => items && setListModal({ label, items })}
      >
        {items ? (
          <div className="db-detail-stat-empty">
            <div className="db-detail-stat-label">{label}</div>
            <div className="db-detail-stat-value-wrapper">
              <span className="db-detail-count-badge">{items.length}</span>
              <ChevronRight className={cn("db-detail-chevron", "h-3 w-3")} style={{ marginLeft: "auto" }} />
            </div>
          </div>
        ) : (
          <div className="db-detail-stat-empty">
            <div className="db-detail-stat-label">{label}</div>
            <span className="db-detail-stat-value" style={{ fontSize: "0.75rem", color: "var(--muted-foreground)", opacity: 0.6, fontStyle: "italic" }}>
              None
            </span>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="db-detail-view">
      <button onClick={onBack} className="db-detail-back-btn">
        <ArrowLeft className="h-4 w-4" />
        Back to all accounts
      </button>

      <div className="db-detail-top">
        <div className="db-skin-viewer-card" ref={skinRef}>
          {skinSize && (
          <ReactSkinview3d
            skinUrl={`https://mc-heads.net/skin/${detail.mc_name || "MHF_Steve"}`}
            capeUrl={detail.mc_capes && detail.mc_name ? `https://mc-heads.net/cape/${detail.mc_name}` : undefined}
            width={skinSize.width}
            height={skinSize.height}
          />
          )}
        </div>

        <div className="db-detail-info-card">
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "0.75rem" }}>
            <div className="db-detail-heading" style={{ flex: 1, minWidth: 0 }}>
              {detail.mc_name || detail.ms_email || "—"}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", flexShrink: 0, marginTop: "0.15rem" }}>
              <button onClick={() => {
                const json = JSON.stringify(detail, null, 2);
                const blob = new Blob([json], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `${detail.mc_name || detail.ms_email || "account"}.json`;
                a.click();
                URL.revokeObjectURL(url);
                toast("Account exported");
              }} style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", padding: "0.35rem 0.75rem", fontSize: "0.7rem", fontWeight: 600, borderRadius: "6px", border: "1px solid color-mix(in oklab, var(--muted-foreground) 30%, transparent)", background: "color-mix(in oklab, var(--muted) 30%, transparent)", color: "var(--muted-foreground)", cursor: "pointer", transition: "all 0.2s" }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = "color-mix(in oklab, var(--muted) 50%, transparent)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = "color-mix(in oklab, var(--muted) 30%, transparent)"; }}
              >
                <Download className="h-3 w-3" />
                Export
              </button>
              <button onClick={() => setShowShareModal(true)} style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", padding: "0.35rem 0.85rem", fontSize: "0.7rem", fontWeight: 600, borderRadius: "6px", border: "1px solid color-mix(in oklab, var(--primary) 40%, transparent)", background: "color-mix(in oklab, var(--primary) 12%, transparent)", color: "var(--primary)", cursor: "pointer", transition: "all 0.2s" }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = "color-mix(in oklab, var(--primary) 22%, transparent)"; }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = "color-mix(in oklab, var(--primary) 12%, transparent)"; }}
              >
                <Link2 className="h-3 w-3" />
                Generate Link
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", padding: "0.35rem 0.75rem", fontSize: "0.7rem", fontWeight: 600, borderRadius: "6px", border: "1px solid color-mix(in oklab, #ef4444 40%, transparent)", background: "color-mix(in oklab, #ef4444 12%, transparent)", color: "#ef4444", cursor: deleting ? "not-allowed" : "pointer", opacity: deleting ? 0.6 : 1, transition: "all 0.2s" }}
              >
                {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                Delete
              </button>
            </div>
          </div>
          <hr className="border-t border-border/30" />
          <div className="db-detail-info-grid">
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Email</div>
              <CopyableValue value={detail.ms_email} title={detail.ms_email} />
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Method</div>
              <CopyableValue value={detail.mc_method} />
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Secured</div>
              <CopyableValue value={detail.secured_at?.slice(0, 16).replace("T", " ")} />
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Password</div>
              <div className="db-detail-stat-value-wrapper">
                <CopyableValue value={detail.ms_password} mono />
              </div>
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Security Email</div>
              <div className="db-detail-stat-value-wrapper">
                <CopyableValue value={detail.ms_security_email} title={detail.ms_security_email} />
              </div>
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Capes</div>
              <CopyableValue value={detail.mc_capes} />
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Recovery Code</div>
              <div className="db-detail-stat-value-wrapper">
                <CopyableValue value={detail.ms_recovery_code} breakAll />
              </div>
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Auth Secret</div>
              <div className="db-detail-stat-value-wrapper">
                <CopyableValue value={detail.ms_auth_secret} mono />
              </div>
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">SSID</div>
              {detail.mc_ssid && detail.mc_ssid !== "false" ? (
                <div className="db-detail-stat-value-wrapper">
                  <CopyableValue value={detail.mc_ssid} mono title={detail.mc_ssid} />
                </div>
              ) : (
                <div className="db-detail-stat-value-wrapper">
                  <CopyableValue value={null} muted italic />
                </div>
              )}
            </div>
          </div>
          <hr className="border-t border-border/30" />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
            <button onClick={() => setShowMail(true)} style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem", padding: "0.5rem 1.1rem", fontSize: "0.8rem", fontWeight: 600, borderRadius: "8px", border: "1px solid color-mix(in oklab, var(--accent) 40%, transparent)", background: "color-mix(in oklab, var(--accent) 12%, transparent)", color: "var(--accent)", cursor: "pointer", transition: "all 0.2s" }}
              onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = "color-mix(in oklab, var(--accent) 22%, transparent)"; }}
              onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = "color-mix(in oklab, var(--accent) 12%, transparent)"; }}
            >
              <Mail className="h-3.5 w-3.5" />
              Access Mail
            </button>
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: "1.25rem", flexWrap: "wrap" }}>
        <div className="db-detail-section" style={{ flex: 1 }}>
          <div className="db-detail-section-title">Personal Info</div>
          <div className="db-detail-section-grid" style={{ flex: 1, alignContent: "flex-start" }}>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">First Name</div>
              <CopyableValue value={detail.ms_first_name} />
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Last Name</div>
              <CopyableValue value={detail.ms_last_name} />
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Full Name</div>
              <CopyableValue value={detail.ms_full_name} />
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Birthday</div>
              <CopyableValue value={detail.ms_birthday} />
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Region</div>
              <CopyableValue value={detail.ms_region} />
            </div>
            <div className="db-detail-stat-block">
              <div className="db-detail-stat-label">Language</div>
              <CopyableValue value={detail.ms_language} />
            </div>
          </div>
        </div>
        <div className="db-detail-section" style={{ flex: 1 }}>
          <div className="db-detail-section-title">Subscriptions &amp; Devices</div>
          <div className="db-detail-section-grid" style={{ flex: 1, alignContent: "flex-start" }}>
            {renderSubRow("Active Subscriptions", "ms_subscriptions_active")}
            {renderSubRow("Canceled Subscriptions", "ms_subscriptions_canceled")}
            {renderSubRow("Commercial Subscriptions", "ms_subscriptions_commercial")}
            {renderSubRow("Devices", "ms_devices")}
            {renderSubRow("Cards", "ms_cards")}
            {renderSubRow("Family", "ms_family")}
          </div>
        </div>
      </div>

      <GameStatsSection accountId={detail.account_id} mcName={detail.mc_name} />

      {shareLinks.length > 0 && (
        <div className="db-detail-section">
          <div className="db-detail-section-title">Shared Links ({shareLinks.length})</div>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            {shareLinks.map(link => (
              <div key={link.id} style={{ display: "flex", flexDirection: "column", gap: "0.35rem", padding: "0.5rem 0.7rem", background: "color-mix(in oklab, var(--background) 45%, transparent)", border: "1px solid color-mix(in oklab, var(--border) 25%, transparent)", borderRadius: 8, fontSize: "0.8rem" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", minWidth: 0, flex: 1 }}>
                    <Link2 className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--muted-foreground)" }} />
                    <span
                      onDoubleClick={() => { navigator.clipboard.writeText(`${domain}/share/${link.id}`); toast.success("Link copied to clipboard"); }}
                      title="Double-click to copy"
                      style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: '"JetBrains Mono", monospace', fontSize: "0.75rem", color: "var(--muted-foreground)", cursor: "text", userSelect: "text" }}
                    >
                      {domain}/share/{link.id}
                    </span>
                    {link.has_password && <Lock className="h-3 w-3 shrink-0" style={{ color: "var(--accent)" }} />}
                    <span style={{ fontSize: "0.65rem", color: "color-mix(in oklab, var(--muted-foreground) 60%, transparent)", whiteSpace: "nowrap" }}>
                      {link.access_count} views
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: "0.35rem", flexShrink: 0 }}>
            <button onClick={() => {
              fetch(`/api/share/${link.id}`, { method: "DELETE", headers: authHeaders() })
                .then(() => { fetchShareLinks(); toast("Link deleted"); })
                .catch(() => {});
            }} style={{ flexShrink: 0, width: 20, height: 20, display: "grid", placeItems: "center", borderRadius: 4, border: "none", background: "transparent", color: "var(--muted-foreground)", cursor: "pointer", opacity: 0.6, transition: "all 0.15s" }}
                    onMouseEnter={e => (e.currentTarget.style.opacity = "1")}
                    onMouseLeave={e => (e.currentTarget.style.opacity = "0.6")}
                    title="Delete link"
                  >
                    <X className="h-3 w-3" />
                  </button>
                  </div>
                </div>
                <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
                  {subDevBadges}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {showShareModal && (
        <ShareLinkModal
          accountId={detail.account_id}
          domain={domain}
          onClose={() => setShowShareModal(false)}
          onCreated={() => { fetchShareLinks(); setShowShareModal(false); }}
        />
      )}

      {showMail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm" onClick={() => { setShowMail(false); setSelectedMsg(null); }}>
          <div className="flex h-[80vh] w-[90vw] max-w-5xl overflow-hidden rounded-2xl border border-border bg-card shadow-2xl backdrop-blur" onClick={e => e.stopPropagation()}>
            <div className="flex w-80 shrink-0 flex-col border-r border-border">
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <p className="text-sm font-semibold truncate">{detail.ms_security_email}</p>
                <div className="flex items-center gap-1">
                  <button onClick={() => { fetch("/api/emails", { headers: authHeaders() }).then(r => r.json()).then(setEmails).catch(() => {}); }} className="grid h-7 w-7 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground" title="Refresh">
                    <RotateCcw className="h-3.5 w-3.5" />
                  </button>
                  <button onClick={() => { setShowMail(false); setSelectedMsg(null); }} className="grid h-7 w-7 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground">
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
              <div className="flex-1 divide-y divide-border/50 overflow-y-auto">
                {matchedEmail && matchedEmail.inbox.length > 0 ? (
                  matchedEmail.inbox.map(msg => (
                    <button
                      key={msg.id}
                      onClick={() => setSelectedMsg(msg)}
                      className={`w-full px-4 py-3 text-left transition hover:bg-background/40 ${selectedMsg?.id === msg.id ? "bg-[--primary]/10" : ""}`}
                    >
                      <p className="truncate text-sm font-medium">{msg.subject || "(no subject)"}</p>
                      <p className="truncate text-xs text-muted-foreground">{msg.from_address}</p>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground/60">{msg.body?.slice(0, 80)}</p>
                      <p className="mt-1 text-[11px] text-muted-foreground/40">{msg.received_at?.slice(0, 16).replace("T", " ")}</p>
                    </button>
                  ))
                ) : (
                  <p className="px-4 py-8 text-center text-sm text-muted-foreground">{matchedEmail ? "No messages." : "No managed inbox for this email."}</p>
                )}
              </div>
            </div>
            <div className="flex flex-1 flex-col overflow-y-auto">
              {selectedMsg ? (
                <div className="flex flex-col p-6">
                  <div className="flex items-start justify-between gap-4">
                    <h2 className="font-display text-xl font-bold">{selectedMsg.subject || "(no subject)"}</h2>
                    <span className="shrink-0 text-xs text-muted-foreground">{selectedMsg.received_at?.slice(0, 16).replace("T", " ")}</span>
                  </div>
                  <p className="mt-4 text-sm text-muted-foreground">From: <span className="text-foreground">{selectedMsg.from_address}</span></p>
                  <p className="mt-1 text-sm text-muted-foreground">To: <span className="text-foreground">{selectedMsg.to_address}</span></p>
                  <div className="mt-6 whitespace-pre-wrap rounded-xl border border-border bg-background/40 p-5 text-sm leading-relaxed">{selectedMsg.body}</div>
                </div>
              ) : (
                <div className="flex flex-1 items-center justify-center">
                  <div className="text-center">
                    <Mail className="mx-auto h-12 w-12 text-muted-foreground/30" />
                    <p className="mt-3 text-sm text-muted-foreground">Select a message to read</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {listModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm" onClick={() => setListModal(null)}>
          <div className="flex w-[90vw] max-w-lg flex-col rounded-2xl border border-border bg-card shadow-2xl" onClick={e => e.stopPropagation()} style={{ maxHeight: "75vh" }}>
            <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
              <h2 className="font-display text-base font-bold">{listModal.label} ({listModal.items.length})</h2>
              <button onClick={() => setListModal(null)} className="grid h-7 w-7 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex flex-col gap-1.5 overflow-y-auto p-4">
              {listModal.items.map((item, i) => (
                <div key={i} className="rounded-lg border border-border/40 bg-background/40 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-all"
                  onDoubleClick={() => { const text = typeof item === "object" && item !== null ? Object.entries(item).map(([k, v]) => `${k}: ${v}`).join("\n") : String(item); navigator.clipboard.writeText(text); toast.success("Copied to clipboard"); }}
                  title="Double-click to copy" style={{ cursor: "text", userSelect: "text" }}>
                  {typeof item === "object" && item !== null
                    ? Object.entries(item).map(([k, v]) => `${k}: ${v}`).join("\n")
                    : String(item)}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function Accounts() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Account | null>(null);
  const [showHits, setShowHits] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [showBar, setShowBar] = useState(false);
  const [barStyle, setBarStyle] = useState<React.CSSProperties>({});
  const [marquee, setMarquee] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [excludeDuplicates, setExcludeDuplicates] = useState(() =>
    readLs(LS_EXCLUDE_DUPES, "0", ["0", "1"] as const) === "1"
  );
  const [mcFilter, setMcFilter] = useState<McFilter>(() =>
    readLs(LS_MC_FILTER, "all", ["all", "gamepass", "owned", "no_mc"] as const)
  );
  const [sortMode, setSortMode] = useState<SortMode>(() =>
    readLs(LS_SORT, "newest", ["newest", "oldest", "mc_type", "mc_type_rev"] as const)
  );
  const gridRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const dragRef = useRef<{
    active: boolean;
    moved: boolean;
    startX: number;
    startY: number;
    base: Set<string>;
  } | null>(null);
  const suppressClickRef = useRef(false);
  const prevCount = useRef(0);
  const { addNotification } = useNotifications();

  const barVisible = selectMode && selectedIds.size > 0;

  useEffect(() => {
    if (barVisible) {
      setShowBar(true);
    } else {
      const timer = setTimeout(() => setShowBar(false), 300);
      return () => clearTimeout(timer);
    }
  }, [barVisible]);

  const getBarStyle = useCallback(() => {
    const main = document.querySelector("main");
    if (!main) return {};
    const rect = main.getBoundingClientRect();
    return {
      left: `${rect.left + rect.width / 2}px`,
      transform: "translateX(-50%)",
    };
  }, []);

  useEffect(() => {
    if (selectMode && selectedIds.size > 0) {
      setBarStyle(getBarStyle());
      const onResize = () => setBarStyle(getBarStyle());
      window.addEventListener("resize", onResize);
      return () => window.removeEventListener("resize", onResize);
    }
  }, [selectMode, selectedIds.size, getBarStyle]);

  useEffect(() => {
    const load = () =>
      fetch("/api/accounts", { headers: authHeaders() })
        .then(r => r.json())
        .then((data: Account[]) => {
          if (prevCount.current > 0 && data.length > prevCount.current) {
            const newCount = data.length - prevCount.current;
            addNotification(`${newCount} new account${newCount > 1 ? "s" : ""} secured`, "Added to the database.");
          }
          prevCount.current = data.length;
          setAccounts(data);
        });
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  async function deleteAccount(account: Account, e?: React.MouseEvent) {
    e?.stopPropagation();
    const label = account.mc_name || account.ms_email || "this account";
    if (!window.confirm(`Delete ${label} from the database? This cannot be undone.`)) return;
    setDeletingId(account.account_id);
    try {
      const res = await fetch(`/api/accounts/${account.account_id}`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail || "Failed to delete account.");
      }
      setAccounts(prev => prev.filter(a => a.account_id !== account.account_id));
      prevCount.current = Math.max(0, prevCount.current - 1);
      setSelectedIds(prev => {
        const next = new Set(prev);
        next.delete(account.account_id);
        return next;
      });
      toast.success("Account deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete account.");
    } finally {
      setDeletingId(null);
    }
  }

  function toggleSelect(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAllVisible() {
    setSelectedIds(new Set(filtered.map(a => a.account_id)));
    setSelectMode(true);
  }

  function toggleSelectMode() {
    const next = !selectMode;
    setSelectMode(next);
    if (!next) setSelectedIds(new Set());
  }

  function idsInMarquee(rect: { left: number; top: number; right: number; bottom: number }) {
    const hit = new Set<string>();
    for (const [id, el] of cardRefs.current) {
      const r = el.getBoundingClientRect();
      const overlaps =
        r.left < rect.right &&
        r.right > rect.left &&
        r.top < rect.bottom &&
        r.bottom > rect.top;
      if (overlaps) hit.add(id);
    }
    return hit;
  }

  function onCardClick(account: Account, e: React.MouseEvent) {
    if ((e.target as HTMLElement).closest("button")) return;
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    if (selectMode) {
      toggleSelect(account.account_id);
      return;
    }
    setSelected(account);
  }

  function onGridPointerDown(e: React.PointerEvent) {
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest("button, a, input, textarea")) return;

    // Keep existing selection as base so a tiny drag doesn't wipe / re-force select
    const additive = e.ctrlKey || e.metaKey || e.shiftKey || selectMode;
    dragRef.current = {
      active: true,
      moved: false,
      startX: e.clientX,
      startY: e.clientY,
      base: additive ? new Set(selectedIds) : new Set(),
    };
  }

  function onGridPointerMove(e: React.PointerEvent) {
    const drag = dragRef.current;
    if (!drag?.active) return;
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) < 8) return;

    if (!drag.moved) {
      drag.moved = true;
      suppressClickRef.current = true;
      setSelectMode(true);
      // Capture only once we know it's a drag (avoids eating normal clicks)
      gridRef.current?.setPointerCapture?.(e.pointerId);
    }

    const left = Math.min(drag.startX, e.clientX);
    const top = Math.min(drag.startY, e.clientY);
    const right = Math.max(drag.startX, e.clientX);
    const bottom = Math.max(drag.startY, e.clientY);
    setMarquee({ x: left, y: top, w: right - left, h: bottom - top });

    const hit = idsInMarquee({ left, top, right, bottom });
    const next = new Set(drag.base);
    for (const id of hit) next.add(id);
    setSelectedIds(next);
  }

  function onGridPointerUp(e: React.PointerEvent) {
    const drag = dragRef.current;
    dragRef.current = null;
    setMarquee(null);
    if (drag?.moved) {
      try {
        gridRef.current?.releasePointerCapture?.(e.pointerId);
      } catch {}
      // Keep suppressClickRef true so the following click is ignored
      window.setTimeout(() => { suppressClickRef.current = false; }, 0);
    }
  }

  async function handleBulkDelete() {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    setBulkDeleting(true);
    try {
      const res = await fetch("/api/accounts/bulk-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ account_ids: ids }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail || "Failed to delete accounts.");
      }
      const data = await res.json().catch(() => ({ deleted: ids.length }));
      setAccounts(prev => prev.filter(a => !selectedIds.has(a.account_id)));
      prevCount.current = Math.max(0, prevCount.current - (data.deleted ?? ids.length));
      setSelectedIds(new Set());
      setSelectMode(false);
      setShowDeleteConfirm(false);
      toast.success(`Deleted ${data.deleted ?? ids.length} account${(data.deleted ?? ids.length) !== 1 ? "s" : ""}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete accounts.");
    } finally {
      setBulkDeleting(false);
    }
  }

  useEffect(() => {
    try { localStorage.setItem(LS_EXCLUDE_DUPES, excludeDuplicates ? "1" : "0"); } catch { /* ignore */ }
  }, [excludeDuplicates]);
  useEffect(() => {
    try { localStorage.setItem(LS_MC_FILTER, mcFilter); } catch { /* ignore */ }
  }, [mcFilter]);
  useEffect(() => {
    try { localStorage.setItem(LS_SORT, sortMode); } catch { /* ignore */ }
  }, [sortMode]);

  const hits = useMemo(() => accounts.filter(a => !a.mc_name), [accounts]);

  const filtered = useMemo(() => {
    let list = showHits && !search.trim() ? hits : accounts;

    if (excludeDuplicates) {
      list = dedupeLatestByEmail(list);
    }

    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter(a =>
        a.ms_email?.toLowerCase().includes(q) ||
        a.mc_name?.toLowerCase().includes(q) ||
        a.mc_gamertag?.toLowerCase().includes(q)
      );
    }

    if (mcFilter !== "all") {
      list = list.filter(a => accountMcCategory(a) === mcFilter);
    }

    const sorted = [...list];
    sorted.sort((a, b) => {
      if (sortMode === "mc_type" || sortMode === "mc_type_rev") {
        const ca = MC_TYPE_ORDER[accountMcCategory(a)];
        const cb = MC_TYPE_ORDER[accountMcCategory(b)];
        const dir = sortMode === "mc_type" ? ca - cb : cb - ca;
        if (dir !== 0) return dir;
      } else if (sortMode === "oldest") {
        return (a.secured_at || "").localeCompare(b.secured_at || "");
      } else {
        return (b.secured_at || "").localeCompare(a.secured_at || "");
      }
      return (b.secured_at || "").localeCompare(a.secured_at || "");
    });
    return sorted;
  }, [accounts, hits, showHits, search, excludeDuplicates, mcFilter, sortMode]);

  const hiddenDupes = useMemo(
    () => (excludeDuplicates ? Math.max(0, accounts.length - dedupeLatestByEmail(accounts).length) : 0),
    [accounts, excludeDuplicates],
  );

  if (selected) {
    return (
      <AccountDetail
        account={selected}
        onBack={() => setSelected(null)}
        onDeleted={() => {
          setAccounts(prev => prev.filter(a => a.account_id !== selected.account_id));
          prevCount.current = Math.max(0, prevCount.current - 1);
        }}
      />
    );
  }

  return (
    <div className="flex-1 flex flex-col space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Secured Accounts</h1>
          <p className="mt-1 text-sm font-semibold text-muted-foreground">
            {filtered.length} shown
            {excludeDuplicates && hiddenDupes > 0 ? ` · ${hiddenDupes} older duplicate${hiddenDupes !== 1 ? "s" : ""} hidden` : ""}
            {" · "}
            {showHits ? `${hits.length} hit${hits.length !== 1 ? "s" : ""}` : `${accounts.length} total`} in database
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search email or MC username..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full rounded-lg border border-border bg-card/60 py-2.5 pl-10 pr-4 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
          />
        </div>
        <button
          onClick={() => setShowHits(!showHits)}
          className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm font-medium transition ${
            showHits
              ? "border-[--accent]/50 bg-[--accent]/15 text-[--accent]"
              : "border-border bg-card/60 text-muted-foreground hover:text-foreground"
          }`}
        >
          <Search className="h-4 w-4" />
          {showHits ? "Hits" : "Accounts"}
          <span className={`rounded-full px-1.5 py-0.5 text-[11px] font-semibold ${
            showHits ? "bg-[--accent]/20 text-[--accent]" : "bg-muted text-muted-foreground"
          }`}>
            {showHits ? hits.length : accounts.length - hits.length}
          </span>
        </button>
        <button
          type="button"
          onClick={() => setExcludeDuplicates(v => !v)}
          title="When on, only the most recent secure per email is shown"
          className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm font-medium transition ${
            excludeDuplicates
              ? "border-[--accent]/50 bg-[--accent]/15 text-[--accent]"
              : "border-border bg-card/60 text-muted-foreground hover:text-foreground"
          }`}
        >
          <Filter className="h-4 w-4" />
          No dupes
        </button>
        <select
          value={mcFilter}
          onChange={e => setMcFilter(e.target.value as McFilter)}
          title="Filter by Minecraft ownership"
          className="rounded-lg border border-border bg-card/60 px-3 py-2.5 text-sm font-medium text-foreground outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
        >
          <option value="all">All MC types</option>
          <option value="gamepass">Gamepass</option>
          <option value="owned">Minecraft owned</option>
          <option value="no_mc">No MC / check failed</option>
        </select>
        <select
          value={sortMode}
          onChange={e => setSortMode(e.target.value as SortMode)}
          title="Sort accounts"
          className="rounded-lg border border-border bg-card/60 px-3 py-2.5 text-sm font-medium text-foreground outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="mc_type">MC type: Gamepass → Owned → None</option>
          <option value="mc_type_rev">MC type: None → Owned → Gamepass</option>
        </select>
        <button
          onClick={toggleSelectMode}
          className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm font-medium transition ${
            selectMode
              ? "border-[--accent] bg-[--accent]/15 text-[--accent]"
              : "border-border bg-card/60 text-muted-foreground hover:text-foreground"
          }`}
          title={selectMode ? "Exit selection" : "Select accounts"}
        >
          <CheckSquare className="h-4 w-4" />
          {selectMode ? "Done" : "Select"}
        </button>
        <button
          onClick={() => setShowExport(true)}
          className="inline-flex items-center gap-2 rounded-lg border border-border bg-card/60 px-3 py-2.5 text-sm font-medium text-muted-foreground transition hover:text-foreground"
        >
          <Download className="h-4 w-4" />
          Export
        </button>
      </div>

      {showExport && <ExportModal accounts={filtered} onClose={() => setShowExport(false)} />}

      {filtered.length === 0 ? (
        <div className="flex-1 rounded-2xl border border-border bg-card/40 backdrop-blur flex items-center justify-center">
          <div className="mx-auto flex max-w-md flex-col items-center text-center">
            <div className="grid h-20 w-20 place-items-center rounded-full border-2 border-[--accent]/60 text-[--accent]">
              <Power className="h-9 w-9" />
            </div>
            <h2 className="mt-6 font-display text-2xl font-bold">{showHits ? "No hits yet" : "No accounts yet"}</h2>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              {showHits
                ? "Accounts without a Minecraft name appear here."
                : "Accounts appear here after being secured via the bot or the Secure tab."}
            </p>
          </div>
        </div>
      ) : (
        <>
          <div
            ref={gridRef}
            onPointerDown={onGridPointerDown}
            onPointerMove={onGridPointerMove}
            onPointerUp={onGridPointerUp}
            onPointerCancel={() => { dragRef.current = null; setMarquee(null); }}
            className="select-none"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))",
              gap: "1rem",
              position: "relative",
              WebkitUserSelect: "none",
              userSelect: "none",
            }}
          >
            {filtered.map((a, i) => {
              const isSelected = selectedIds.has(a.account_id);
              return (
                <div
                  key={a.account_id}
                  data-account-id={a.account_id}
                  ref={el => {
                    if (el) cardRefs.current.set(a.account_id, el);
                    else cardRefs.current.delete(a.account_id);
                  }}
                  onClick={e => onCardClick(a, e)}
                  className={cn(
                    "db-acct-card group relative animate-in fade-in slide-in-from-bottom-3 duration-500",
                    selectMode && "db-acct-card--select-mode",
                    isSelected && "db-acct-card--selected",
                  )}
                  style={{ animationDelay: `${i * 60}ms` }}
                >
                  <div className="db-acct-img-section" style={{ position: "relative" }}>
                    {selectMode ? (
                      <div
                        className={`absolute left-2 top-2 z-10 grid h-5 w-5 place-items-center rounded border-2 transition ${
                          isSelected
                            ? "border-[--accent] bg-[--accent] text-white"
                            : "border-muted-foreground/50 bg-background/70"
                        }`}
                      >
                        {isSelected && <CheckSquare className="h-3.5 w-3.5" />}
                      </div>
                    ) : (
                      <button
                        type="button"
                        title="Delete account"
                        onClick={e => deleteAccount(a, e)}
                        disabled={deletingId === a.account_id}
                        style={{
                          position: "absolute",
                          right: "0.5rem",
                          top: "0.5rem",
                          zIndex: 10,
                          display: "grid",
                          placeItems: "center",
                          width: "1.75rem",
                          height: "1.75rem",
                          borderRadius: "0.375rem",
                          border: "1px solid color-mix(in oklab, #ef4444 35%, transparent)",
                          background: "color-mix(in oklab, var(--background) 85%, transparent)",
                          color: "#ef4444",
                          cursor: deletingId === a.account_id ? "not-allowed" : "pointer",
                          opacity: deletingId === a.account_id ? 0.5 : 0.85,
                        }}
                      >
                        {deletingId === a.account_id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" />
                        )}
                      </button>
                    )}
                    <img
                      src={`https://mc-heads.net/player/${a.mc_name || "MHF_Steve"}`}
                      alt={a.mc_name}
                      className="db-acct-skin"
                      draggable={false}
                      onError={(e) => { (e.target as HTMLImageElement).src = "https://mc-heads.net/player/MHF_Steve"; }}
                    />
                    <span className="db-acct-time">{a.secured_at?.slice(0, 10) ?? "—"}</span>
                  </div>
                  <div className="db-acct-info-section">
                    <div className="db-acct-name">{a.mc_name || a.mc_gamertag || "—"}</div>
                    <div className="db-acct-stats">
                      <div className="db-acct-stat">
                        <div className="db-acct-stat-label">Email</div>
                        <div className="db-acct-stat-val">{a.ms_email || "—"}</div>
                      </div>
                      <div className="db-acct-stat">
                        <div className="db-acct-stat-label">Method</div>
                        <div className="db-acct-stat-val">{a.mc_method || "—"}</div>
                      </div>
                      <div className="db-acct-stat">
                        <div className="db-acct-stat-label">Capes</div>
                        <div className="db-acct-stat-val">{a.mc_capes || "—"}</div>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {marquee && (
            <div
              className="db-acct-marquee"
              style={{ left: marquee.x, top: marquee.y, width: marquee.w, height: marquee.h }}
            />
          )}

          {showBar && (
            <div
              className={`fixed bottom-6 z-50 flex w-max items-center gap-4 rounded-2xl border border-[--accent]/30 bg-card/95 px-5 py-3 shadow-xl backdrop-blur-xl ${barVisible ? "animate-in slide-in-from-bottom-4 fade-in" : "animate-out slide-out-to-bottom-4 fade-out"} duration-300`}
              style={barStyle}
            >
              <button
                onClick={selectAllVisible}
                className="inline-flex items-center gap-2 text-xs font-semibold text-muted-foreground transition hover:text-foreground"
              >
                <CheckSquare className="h-4 w-4" />
                Select all ({filtered.length})
              </button>
              <div className="h-6 w-px bg-border/40" />
              <span className="text-sm font-semibold text-foreground">
                {selectedIds.size} selected
              </span>
              <div className="h-6 w-px bg-border/40" />
              <button
                onClick={() => setShowDeleteConfirm(true)}
                className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-red-600/90 px-4 py-2 text-xs font-semibold text-white transition hover:bg-red-600"
              >
                <Trash2 className="h-4 w-4" />
                Delete
              </button>
            </div>
          )}
        </>
      )}

      <Dialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <DialogContent className="sm:max-w-md animate-in fade-in zoom-in-95 duration-200">
          <DialogHeader>
            <DialogTitle>Delete accounts</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete {selectedIds.size} account{selectedIds.size !== 1 ? "s" : ""} from the database? This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={() => setShowDeleteConfirm(false)}
              disabled={bulkDeleting}
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-card/60 px-4 py-2 text-sm font-semibold text-muted-foreground transition hover:text-foreground disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleBulkDelete}
              disabled={bulkDeleting}
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-red-600/90 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-600 disabled:opacity-60"
            >
              {bulkDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              {bulkDeleting ? "Deleting…" : "Delete"}
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
