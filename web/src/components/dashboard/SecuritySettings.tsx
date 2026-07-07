import { useState, useEffect } from "react";
import { Shield, Eye, EyeOff, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { authHeaders } from "./context";

export function SecuritySettings() {
  const [pwCurrent, setPwCurrent]   = useState("");
  const [pwNew, setPwNew]           = useState("");
  const [pwConfirm, setPwConfirm]   = useState("");
  const [showPw, setShowPw]         = useState(false);
  const [pwStatus, setPwStatus]     = useState<{ ok: boolean; msg: string } | null>(null);
  const [pwLoading, setPwLoading]   = useState(false);
  const [totpSecret, setTotpSecret] = useState("");
  const [totpStatus, setTotpStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [totpLoading, setTotpLoading] = useState(false);
  const [totpEnabled, setTotpEnabled] = useState(false);
  const [totpCode, setTotpCode] = useState("");

  useEffect(() => {
    fetch("/api/auth/2fa-status", { headers: authHeaders() })
      .then(r => r.json())
      .then(d => setTotpEnabled(d.configured));
  }, []);

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    if (pwNew !== pwConfirm) { setPwStatus({ ok: false, msg: "Passwords don't match." }); return; }
    setPwLoading(true); setPwStatus(null);
    const res = await fetch("/api/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ current_password: pwCurrent, new_password: pwNew, totp_code: totpCode || null }),
    });
    if (res.ok) { setPwCurrent(""); setPwNew(""); setPwConfirm(""); setTotpCode(""); toast.success("Password updated"); }
    setPwStatus(res.ok ? { ok: true, msg: "Password updated." } : { ok: false, msg: (await res.json().catch(() => null))?.detail || "Failed." });
    setPwLoading(false);
  }

  async function saveTotpSecret(e: React.FormEvent) {
    e.preventDefault();
    setTotpLoading(true); setTotpStatus(null);
    const res = await fetch("/api/auth/setup-2fa", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ secret: totpSecret }),
    });
    const data = res.ok ? null : await res.json().catch(() => null);
    if (res.ok) { setTotpEnabled(true); toast.success("2FA secret saved"); }
    setTotpStatus(res.ok ? { ok: true, msg: "2FA secret saved." } : { ok: false, msg: data?.detail || "Failed." });
    setTotpLoading(false);
  }

  async function removeTotpSecret() {
    setTotpLoading(true); setTotpStatus(null);
    const res = await fetch("/api/auth/remove-2fa", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
    });
    if (res.ok) { setTotpEnabled(false); setTotpSecret(""); toast("2FA removed"); }
    setTotpStatus(res.ok ? { ok: true, msg: "2FA removed." } : { ok: false, msg: "Failed to remove 2FA." });
    setTotpLoading(false);
  }

  return (
    <>
      <div className="flex items-center gap-2">
        <Shield className="h-5 w-5 text-[--primary]" />
        <h1 className="font-display text-2xl font-bold tracking-tight">Security</h1>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">Manage your account credentials and authentication.</p>

      <div className="space-y-5 rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
        <h2 className="font-display text-base font-semibold text-muted-foreground uppercase tracking-wider text-xs">Change Password</h2>
        <form onSubmit={changePassword} className="max-w-sm space-y-4">
          <div className="space-y-2">
            <label className="block text-sm font-medium">Current Password</label>
            <div className="relative">
              <input
                type={showPw ? "text" : "password"}
                value={pwCurrent}
                onChange={e => setPwCurrent(e.target.value)}
                className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 pr-10 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                required
              />
              <button type="button" onClick={() => setShowPw(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-medium">New Password</label>
            <input
              type={showPw ? "text" : "password"}
              value={pwNew}
              onChange={e => setPwNew(e.target.value)}
              className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-medium">Confirm New Password</label>
            <input
              type={showPw ? "text" : "password"}
              value={pwConfirm}
              onChange={e => setPwConfirm(e.target.value)}
              className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
              required
            />
          </div>
          {totpEnabled && (
            <div className="space-y-2">
              <label className="block text-sm font-medium">2FA Code</label>
              <input
                type="text"
                value={totpCode}
                onChange={e => setTotpCode(e.target.value)}
                placeholder="000000"
                className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
              />
            </div>
          )}
          {pwStatus && (
            <div className={cn("rounded-lg border px-4 py-3 text-sm", pwStatus.ok
              ? "border-[--accent]/40 bg-[--accent]/10 text-[--accent]"
              : "border-destructive/40 bg-destructive/10 text-red-400"
            )}>
              {pwStatus.msg}
            </div>
          )}
          <button
            type="submit"
            disabled={pwLoading}
            className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
          >
            {pwLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
            {pwLoading ? "Saving\u2026" : "Update Password"}
          </button>
        </form>
      </div>

      <div className="space-y-5 rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
        <h2 className="font-display text-base font-semibold text-muted-foreground uppercase tracking-wider text-xs">Two-Factor Authentication</h2>
        <p className="text-sm text-muted-foreground">
          {totpEnabled ? "2FA is currently enabled." : "Store your TOTP secret here to enable 2FA for dashboard login. Use an authenticator app (Google Authenticator, Authy) to scan the secret."}
        </p>
        <form onSubmit={saveTotpSecret} className="max-w-sm space-y-4">
          <div className="space-y-2">
            <label className="block text-sm font-medium">TOTP Secret</label>
            <input
              type="text"
              value={totpSecret}
              onChange={e => setTotpSecret(e.target.value)}
              placeholder={totpEnabled ? "Enter new secret to replace existing" : "JBSWY3DPEHPK3PXP"}
              className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
            />
          </div>
          {totpStatus && (
            <div className={cn("rounded-lg border px-4 py-3 text-sm", totpStatus.ok
              ? "border-[--accent]/40 bg-[--accent]/10 text-[--accent]"
              : "border-destructive/40 bg-destructive/10 text-red-400"
            )}>
              {totpStatus.msg}
            </div>
          )}
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              type="submit"
              disabled={totpLoading || !totpSecret}
              className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
            >
              {totpLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
              {totpLoading ? "Saving\u2026" : "Save 2FA Secret"}
            </button>
            {totpEnabled && (
              <button
                type="button"
                onClick={removeTotpSecret}
                disabled={totpLoading}
                className="inline-flex items-center gap-2 rounded-lg border border-red-400/40 bg-red-400/10 px-5 py-2.5 text-sm font-semibold text-red-400 transition hover:bg-red-400/20 disabled:opacity-60"
              >
                Remove 2FA
              </button>
            )}
          </div>
        </form>
      </div>
    </>
  );
}
