import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { Lock, ArrowRight, Eye, EyeOff, Check, X, Copy, ExternalLink, ShieldCheck, User, Mail, Key, Smartphone, CreditCard, Monitor, Globe } from "lucide-react";

export const Route = createFileRoute("/share/$token")({
  head: () => ({
    meta: [
      { title: "Shared Account" },
      { name: "description", content: "View a shared secured account." },
    ],
  }),
  component: ShareView,
});

function ShareView() {
  const { token } = Route.useParams();
  const [state, setState] = useState<"loading" | "password" | "view" | "error">("loading");
  const [account, setAccount] = useState<any>(null);
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetch(`/api/share/${token}/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }).then(async (res) => {
      if (res.status === 401) {
        setState("password");
      } else if (res.ok) {
        const data = await res.json();
        setAccount(data);
        setState("view");
      } else {
        const body = await res.json().catch(() => null);
        setError(body?.detail || "Link not found or expired.");
        setState("error");
      }
    }).catch(() => {
      setError("Failed to load account.");
      setState("error");
    });
  }, [token]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch(`/api/share/${token}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || "Incorrect password.");
      }
      const data = await res.json();
      setAccount(data);
      setState("view");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  function parseList(v: unknown): unknown[] | null {
    if (v == null || v === undefined) return null;
    if (Array.isArray(v)) return v.length ? v : null;
    if (typeof v === "string") {
      if (v === "[]" || v === "{}" || !v.trim()) return null;
      try { const p = JSON.parse(v); return Array.isArray(p) ? (p.length ? p : null) : [p]; }
      catch { return null; }
    }
    return null;
  }

  function CopyButton({ text }: { text: string }) {
    const [copied, setCopied] = useState(false);
    return (
      <button onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
        style={{ flexShrink: 0, width: 20, height: 20, display: "grid", placeItems: "center", borderRadius: 4, border: "none", background: "transparent", color: "var(--muted-foreground)", cursor: "pointer", transition: "all 0.15s", opacity: 0.6 }}
        onMouseEnter={e => (e.currentTarget.style.opacity = "1")}
        onMouseLeave={e => (e.currentTarget.style.opacity = "0.6")}
      >
        {copied ? <Check className="h-3 w-3" style={{ color: "var(--accent)" }} /> : <Copy className="h-3 w-3" />}
      </button>
    );
  }

  function StatBlock({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem", minWidth: 0, background: "color-mix(in oklab, var(--background) 45%, transparent)", border: "1px solid color-mix(in oklab, var(--border) 35%, transparent)", borderRadius: 8, padding: "0.4rem 0.6rem" }}>
        <div style={{ fontSize: "0.55rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "color-mix(in oklab, var(--muted-foreground) 60%, transparent)" }}>{label}</div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", minWidth: 0 }}>
          <span style={{ fontSize: "0.85rem", fontWeight: 500, color: "var(--foreground)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0, flex: 1, ...(mono ? { fontFamily: '"JetBrains Mono", monospace' } : {}) }}>{value}</span>
          <CopyButton text={value} />
        </div>
      </div>
    );
  }

  function AccordionSection({ label, items }: { label: string; items: unknown[] }) {
    const [open, setOpen] = useState(false);
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem", minWidth: 0, minHeight: 48, background: "color-mix(in oklab, var(--background) 45%, transparent)", border: "1px solid color-mix(in oklab, var(--border) 35%, transparent)", borderRadius: 8, padding: "0.4rem 0.6rem", cursor: "pointer" }} onClick={() => setOpen(!open)}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem" }}>
          <span style={{ fontSize: "0.55rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "color-mix(in oklab, var(--muted-foreground) 60%, transparent)" }}>{label}</span>
          <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 20, height: 18, padding: "0 0.4rem", borderRadius: 999, fontSize: "0.65rem", fontWeight: 700, background: "color-mix(in oklab, var(--primary) 18%, transparent)", color: "var(--primary)", flexShrink: 0 }}>{items.length}</span>
        </div>
        {open && (
          <div style={{ borderTop: "1px solid color-mix(in oklab, var(--border) 20%, transparent)", paddingTop: "0.4rem", display: "flex", flexDirection: "column", gap: "0.3rem" }}>
            {items.map((item, i) => (
              <div key={i} style={{ background: "color-mix(in oklab, var(--background) 40%, transparent)", border: "1px solid color-mix(in oklab, var(--border) 15%, transparent)", borderRadius: 6, padding: "0.4rem 0.5rem", fontSize: "0.78rem", fontFamily: '"JetBrains Mono", monospace', lineHeight: 1.5, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                {typeof item === "object" && item !== null
                  ? Object.entries(item).map(([k, v]) => `${k}: ${v}`).join("\n")
                  : String(item)}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (state === "loading") {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--background)", color: "var(--foreground)" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 32, height: 32, border: "3px solid var(--muted)", borderTopColor: "var(--primary)", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto" }} />
          <p style={{ marginTop: "1rem", fontSize: "0.9rem", color: "var(--muted-foreground)" }}>Loading shared account...</p>
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--background)", color: "var(--foreground)" }}>
        <div style={{ textAlign: "center", maxWidth: 400, padding: "0 1rem" }}>
          <X className="h-12 w-12" style={{ margin: "0 auto", color: "var(--muted-foreground)", opacity: 0.4 }} />
          <h1 style={{ marginTop: "1rem", fontSize: "1.25rem", fontWeight: 700, fontFamily: '"Space Grotesk", sans-serif' }}>Link Not Found</h1>
          <p style={{ marginTop: "0.5rem", fontSize: "0.85rem", color: "var(--muted-foreground)" }}>{error || "This share link doesn't exist or has been removed."}</p>
        </div>
      </div>
    );
  }

  if (state === "password") {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--background)", color: "var(--foreground)" }}>
        <form onSubmit={handleSubmit} style={{ width: "100%", maxWidth: 380, padding: "2rem", background: "var(--card)", border: "1px solid var(--border)", borderRadius: 16 }}>
          <div style={{ textAlign: "center", marginBottom: "1.5rem" }}>
            <Lock className="h-8 w-8" style={{ margin: "0 auto", color: "var(--accent)" }} />
            <h1 style={{ marginTop: "0.75rem", fontSize: "1.1rem", fontWeight: 700, fontFamily: '"Space Grotesk", sans-serif' }}>Password Required</h1>
            <p style={{ marginTop: "0.25rem", fontSize: "0.8rem", color: "var(--muted-foreground)" }}>This account link is protected. Enter the password to continue.</p>
          </div>
          {error && (
            <div style={{ padding: "0.5rem 0.75rem", marginBottom: "0.75rem", borderRadius: 8, background: "color-mix(in oklab, var(--primary) 15%, transparent)", color: "var(--primary)", fontSize: "0.8rem", textAlign: "center" }}>
              {error}
            </div>
          )}
          <div style={{ position: "relative" }}>
            <input
              type={showPw ? "text" : "password"}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Enter password"
              autoFocus
              style={{ width: "100%", padding: "0.6rem 2.5rem 0.6rem 0.75rem", borderRadius: 8, border: "1px solid var(--border)", background: "var(--background)", color: "var(--foreground)", fontSize: "0.9rem", outline: "none", boxSizing: "border-box" }}
            />
            <button type="button" onClick={() => setShowPw(!showPw)} style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", color: "var(--muted-foreground)", cursor: "pointer", padding: 4 }}>
              {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          <button type="submit" disabled={submitting || !password.trim()}
            style={{ marginTop: "0.75rem", width: "100%", padding: "0.6rem 1rem", borderRadius: 8, border: "none", background: "linear-gradient(135deg, var(--primary), var(--accent))", color: "var(--primary-foreground)", fontSize: "0.85rem", fontWeight: 600, cursor: submitting || !password.trim() ? "not-allowed" : "pointer", opacity: submitting || !password.trim() ? 0.6 : 1, display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem" }}
          >
            {submitting ? "Verifying..." : <>Unlock <ArrowRight className="h-4 w-4" /></>}
          </button>
        </form>
      </div>
    );
  }

  if (!account) return null;

  const subs_active = parseList(account.ms_subscriptions_active);
  const subs_canceled = parseList(account.ms_subscriptions_canceled);
  const subs_commercial = parseList(account.ms_subscriptions_commercial);
  const devices = parseList(account.ms_devices);
  const cards = parseList(account.ms_cards);
  const family = parseList(account.ms_family);

  return (
    <div style={{ minHeight: "100vh", background: "var(--background)", color: "var(--foreground)" }}>
      <div style={{ maxWidth: 900, margin: "0 auto", padding: "2rem 1.5rem 4rem", display: "flex", flexDirection: "column", gap: "1.25rem" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "0.75rem" }}>
          <ShieldCheck className="h-5 w-5" style={{ color: "var(--accent)" }} />
          <span style={{ fontSize: "0.8rem", color: "var(--muted-foreground)" }}>Shared Secured Account</span>
        </div>

        <div style={{ border: "1px solid var(--border)", borderRadius: 14, background: "linear-gradient(145deg, color-mix(in oklab, var(--card) 100%, transparent), color-mix(in oklab, var(--background) 90%, transparent))", padding: "1.5rem", display: "flex", flexDirection: "column", gap: "1rem", boxShadow: "0 0 0 1px color-mix(in oklab, var(--border) 50%, transparent), 0 4px 24px -8px rgba(0,0,0,0.3)" }}>
          <div style={{ fontSize: "1.35rem", fontWeight: 700, fontFamily: '"Space Grotesk", sans-serif', letterSpacing: "-0.02em" }}>
            {account.mc_name || account.ms_email || "Account Details"}
          </div>
          <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: 0 }} />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.85rem 1rem" }}>
            <StatBlock label="Email" value={account.ms_email || "—"} />
            <StatBlock label="Method" value={account.mc_method || "—"} />
            <StatBlock label="Capes" value={account.mc_capes || "—"} />
            <StatBlock label="Security Email" value={account.ms_security_email || "—"} />
            <StatBlock label="Password" value={account.ms_password || "—"} />
            <StatBlock label="Recovery Code" value={account.ms_recovery_code || "—"} />
            <StatBlock label="Auth Secret" value={account.ms_auth_secret || "—"} mono />
            <StatBlock label="SSID" value={account.mc_ssid && account.mc_ssid !== "false" ? account.mc_ssid : "—"} />
          </div>
        </div>

        {(account.ms_first_name || account.ms_last_name || account.ms_birthday) && (
          <div style={{ border: "1px solid var(--border)", borderRadius: 14, background: "var(--card)", padding: "1.25rem 1.5rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <div style={{ fontSize: "0.65rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted-foreground)", paddingBottom: "0.25rem", borderBottom: "1px solid var(--border)" }}>Personal Info</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "0.65rem" }}>
              {account.ms_first_name && <StatBlock label="First Name" value={account.ms_first_name} />}
              {account.ms_last_name && <StatBlock label="Last Name" value={account.ms_last_name} />}
              {account.ms_full_name && <StatBlock label="Full Name" value={account.ms_full_name} />}
              {account.ms_region && <StatBlock label="Region" value={account.ms_region} />}
              {account.ms_birthday && <StatBlock label="Birthday" value={account.ms_birthday} />}
              {account.ms_language && <StatBlock label="Language" value={account.ms_language} />}
            </div>
          </div>
        )}

        <div style={{ border: "1px solid var(--border)", borderRadius: 14, background: "var(--card)", padding: "1.25rem 1.5rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <div style={{ fontSize: "0.65rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted-foreground)", paddingBottom: "0.25rem", borderBottom: "1px solid var(--border)" }}>Subscriptions &amp; Devices</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "0.65rem" }}>
            {[
              { label: "Active Subscriptions", items: subs_active },
              { label: "Canceled Subscriptions", items: subs_canceled },
              { label: "Commercial Subscriptions", items: subs_commercial },
              { label: "Devices", items: devices },
              { label: "Payment Cards", items: cards },
              { label: "Family", items: family },
            ].map(({ label, items }) =>
              items ? (
                <AccordionSection key={label} label={label} items={items} />
              ) : (
                <div key={label} style={{ display: "flex", flexDirection: "column", gap: "0.2rem", minWidth: 0, minHeight: 48, background: "color-mix(in oklab, var(--background) 45%, transparent)", border: "1px solid color-mix(in oklab, var(--border) 35%, transparent)", borderRadius: 8, padding: "0.4rem 0.6rem" }}>
                  <div style={{ fontSize: "0.55rem", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "color-mix(in oklab, var(--muted-foreground) 60%, transparent)" }}>{label}</div>
                  <span style={{ fontSize: "0.85rem", fontWeight: 500, color: "var(--muted-foreground)", opacity: 0.6, fontStyle: "italic" }}>None</span>
                </div>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
