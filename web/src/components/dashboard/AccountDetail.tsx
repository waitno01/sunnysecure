import { useState, useEffect, useRef, useLayoutEffect, useCallback } from "react";
import { ReactSkinview3d } from "react-skinview3d";
import {
  Check, Link2, Lock, X, ArrowLeft, Loader2, RotateCcw, Mail, ChevronRight, Download,
} from "lucide-react";
import { toast } from "sonner";
import { cn, simplify } from "@/lib/utils";
import { authHeaders } from "./context";
import type { EmailEntry, EmailMessage } from "./types";
import type { Account } from "./Accounts";

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

export function AccountDetail({ account, onBack }: { account: Account; onBack: () => void }) {
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
