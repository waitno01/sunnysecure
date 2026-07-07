import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff, Lock, Loader as Loader2, ShieldCheck, X } from "lucide-react";
import { AUTH_EVENT } from "@/lib/auth";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Sign in" },
      { name: "description", content: "Sign in to your autosecure account." },
    ],
  }),
  component: LoginPage,
});

function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showTOTPModal, setShowTOTPModal] = useState(false);

  async function doLogin(totp_code?: string) {
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, totp_code: totp_code || null }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || body?.message || "Invalid credentials.");
      }

      const data = await res.json();

      if (data.require_2fa) {
        setShowTOTPModal(true);
        setTotpCode("");
        return;
      }

      window.dispatchEvent(new Event(AUTH_EVENT));
      navigate({ to: "/dashboard" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!username || !password) {
      setError("Please enter your username and password.");
      return;
    }
    await doLogin();
  }

  async function handleTOTPSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!totpCode || totpCode.length !== 6) {
      setError("Please enter a valid 6-digit code.");
      return;
    }
    await doLogin(totpCode);
  }

  return (
    <div className="relative min-h-screen overflow-hidden">
      <div className="pointer-events-none absolute inset-0 grid-bg" aria-hidden />

      <header className="relative z-10">
        <div className="mx-auto flex max-w-6xl items-center justify-center px-6 py-8">
          <a href="/" className="flex items-center gap-2 font-display text-xl font-bold tracking-tight">
            <span className="grid h-8 w-8 place-items-center rounded-md bg-gradient-to-br from-[--primary] to-[--accent] text-primary-foreground">
              <Lock className="h-4 w-4" />
            </span>
            Open Source<span className="text-gradient">Autosecure</span>
          </a>
        </div>
      </header>

      <main className="relative flex items-start justify-center px-6 pb-20 pt-6 sm:pt-10">
        <div className="w-full max-w-md">
          <div className="relative overflow-hidden rounded-2xl border border-border bg-card/60 p-8 shadow-[var(--shadow-glow)] backdrop-blur">
            <div
              className="pointer-events-none absolute inset-0 -z-10"
              style={{ background: "var(--gradient-radial)" }}
              aria-hidden
            />

            <div className="text-center">
              <h1 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">
                Welcome <span className="text-gradient">Back</span>
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Sign in to your account to continue
              </p>
            </div>

            <form onSubmit={handleSubmit} className="mt-8 space-y-5" noValidate>
              <div className="space-y-2">
                <label htmlFor="username" className="block text-sm font-medium text-foreground">
                  Username
                </label>
                <input
                  id="username"
                  type="text"
                  autoComplete="username"
                  required
                  maxLength={255}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Example"
                  className="w-full rounded-xl border border-border bg-background/60 px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground/70 outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                />
              </div>

              <div className="space-y-2">
                <label htmlFor="password" className="block text-sm font-medium text-foreground">
                  Password
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPw ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    minLength={1}
                    maxLength={128}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full rounded-xl border border-border bg-background/60 px-4 py-3 pr-12 text-sm text-foreground placeholder:text-muted-foreground/70 outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="absolute inset-y-0 right-0 grid w-12 place-items-center text-muted-foreground transition hover:text-foreground"
                    aria-label={showPw ? "Hide password" : "Show password"}
                  >
                    {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {error && (
                <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive-foreground">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-[--primary] to-[--accent] px-4 py-3 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Signing in…
                  </>
                ) : (
                  <>
                    Sign in
                    <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
                  </>
                )}
              </button>


            </form>
          </div>

        </div>
      </main>

      {showTOTPModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm animate-in fade-in duration-200" onClick={() => setShowTOTPModal(false)}>
          <div className="w-full max-w-sm rounded-2xl border border-border bg-card shadow-2xl backdrop-blur animate-in fade-in zoom-in-95 duration-200" onClick={e => e.stopPropagation()}>
            <div className="h-1 rounded-t-2xl bg-gradient-to-r from-[--primary] to-[--accent]" />
            <form onSubmit={handleTOTPSubmit} className="p-6 space-y-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-display text-lg font-bold">Two-Factor Authentication</h2>
                  <p className="mt-0.5 text-sm text-muted-foreground">Enter the 6-digit code from your authenticator app.</p>
                </div>
                <button type="button" onClick={() => setShowTOTPModal(false)} className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="space-y-2">
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="000000"
                  autoFocus
                  className="w-full rounded-xl border border-border bg-background/60 px-4 py-3 text-center font-mono text-2xl tracking-[0.5em] text-foreground placeholder:text-muted-foreground/40 outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                />
              </div>
              {error && (
                <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive-foreground">
                  {error}
                </div>
              )}
              <button
                type="submit"
                disabled={loading || !totpCode}
                className="group inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-[--primary] to-[--accent] px-4 py-3 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Verifying…
                  </>
                ) : (
                  <>
                    <ShieldCheck className="h-4 w-4" />
                    Verify
                  </>
                )}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
