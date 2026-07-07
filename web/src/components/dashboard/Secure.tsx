import { useState, useContext } from "react";
import { KeyRound, Fingerprint, Layers, FileKey, ShieldCheck, ArrowLeft, Loader2, ChevronRight } from "lucide-react";
import { toast } from "sonner";
import { NotificationContext, authHeaders } from "./context";

type Method = "recovery" | "recovery-bulk" | "password" | "password-bulk";

const methods: {
  id: Method;
  title: string;
  description: string;
  icon: typeof KeyRound;
  bulk: boolean;
  needs2FA?: boolean;
}[] = [
  { id: "recovery", title: "Recovery Code", description: "Use your email and recovery code", icon: KeyRound, bulk: false },
  { id: "password", title: "Password + Secret", description: "Use your email, password and authenticator secret", icon: Fingerprint, bulk: false, needs2FA: true },
  { id: "recovery-bulk", title: "Recovery Code", description: "Secures multiple accounts via recovery code", icon: Layers, bulk: true },
  { id: "password-bulk", title: "Password + Secret", description: "Secure multiple accounts via pwd and secret", icon: FileKey, bulk: true, needs2FA: true },
];

function SecureForm({ method, onBack }: { method: (typeof methods)[number]; onBack: () => void }) {
  const { addNotification } = useContext(NotificationContext);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [email, setEmail] = useState("");
  const [secret, setSecret] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [bulk, setBulk] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    const body: Record<string, unknown> = {};
    if (method.bulk) {
      body.entries = bulk.split("\n").map(l => l.trim()).filter(Boolean);
    } else {
      body.email = email;
      if (method.id === "recovery") body.recovery_code = secret;
      if (method.id === "password") { body.password = password; body.totp_secret = totp; }
    }

    const identifier = method.bulk
      ? `${(body.entries as string[]).length} entries`
      : email;

    const toastId = toast.loading(`Securing ${identifier}…`, {
      description: `Using ${method.title}`,
    });

    const res = await fetch(`/api/secure/${method.id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      const data = await res.json();
      setResult({ ok: true, message: `Secured successfully${data.mc_name ? ` — ${data.mc_name}` : ""}.` });
      toast.success(`Secured ${identifier}`, {
        id: toastId,
        description: data.mc_name ? `Minecraft: ${data.mc_name}` : `Completed successfully`,
      });
      addNotification(`Secured ${identifier}`, data.mc_name ? `Minecraft: ${data.mc_name}` : `Completed successfully`);
    } else {
      const errData = await res.json().catch(() => null);
      const errText = errData?.detail || errData?.message || "Failed to secure account.";
      setResult({ ok: false, message: errText });
      toast.error(`Failed to secure ${identifier}`, {
        id: toastId,
        description: errText,
      });
      addNotification(`Failed to secure ${identifier}`, errText);
    }
    setLoading(false);
  }

  return (
    <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
      <button onClick={onBack} className="inline-flex items-center gap-2 text-sm text-muted-foreground transition hover:text-foreground">
        <ArrowLeft className="h-4 w-4" />
        Back to methods
      </button>

      <div className="mt-4 flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-lg bg-gradient-to-br from-[--primary]/20 to-[--accent]/10 text-[--accent]">
          <method.icon className="h-5 w-5" />
        </div>
        <div>
          <h2 className="font-display text-xl font-semibold">{method.title}</h2>
          <p className="text-sm text-muted-foreground">{method.description}</p>
        </div>
      </div>

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        {method.bulk ? (
          <div className="space-y-2">
            <label className="block text-sm font-medium">
              Entries{" "}
              <span className="text-muted-foreground">
                ({method.id === "recovery-bulk" ? "email:recovery_code" : "email:password:totp_secret"} per line)
              </span>
            </label>
            <textarea
              value={bulk}
              onChange={e => setBulk(e.target.value)}
              rows={8}
              placeholder={method.id === "recovery-bulk" ? "alex@example.com:ABCD-EFGH-IJKL" : "alex@example.com:password123:JBSWY3DPEHPK3PXP"}
              className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-xs outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
              required
            />
          </div>
        ) : (
          <>
            <div className="space-y-2">
              <label className="block text-sm font-medium">Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30" required />
            </div>
            {method.id === "recovery" && (
              <div className="space-y-2">
                <label className="block text-sm font-medium">Recovery Code</label>
                <input type="text" value={secret} onChange={e => setSecret(e.target.value)} placeholder="ABCD-EFGH-IJKL-MNOP" className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30" required />
              </div>
            )}
            {method.id === "password" && (
              <>
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Password</label>
                  <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="123456" className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30" required />
                </div>
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Authenticator Secret (TOTP)</label>
                  <input type="text" value={totp} onChange={e => setTotp(e.target.value)} placeholder="JBSWY3DPEHPK3PXP" className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30" required />
                </div>
              </>
            )}
          </>
        )}

        {result && (
          <div className={`rounded-lg border px-4 py-3 text-sm ${result.ok ? "border-[--accent]/40 bg-[--accent]/10 text-[--accent]" : "border-destructive/40 bg-destructive/10 text-destructive-foreground"}`}>
            {result.message}
          </div>
        )}

        <div className="flex justify-end gap-3 pt-2">
          <button type="button" onClick={onBack} className="rounded-lg border border-border bg-background/60 px-5 py-2.5 text-sm font-medium transition hover:bg-card">Cancel</button>
          <button type="submit" disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
            {loading ? "Securing…" : "Secure"}
          </button>
        </div>
      </form>
    </div>
  );
}

export function Secure() {
  const [selected, setSelected] = useState<Method | null>(null);
  const current = methods.find((m) => m.id === selected);

  return (
    <div className="flex flex-1 flex-col space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Secure Accounts</h1>
        <p className="mt-1 text-sm text-muted-foreground">Choose how you want to authenticate and secure your accounts.</p>
      </div>

      {!current ? (
        <div className="grid min-h-0 flex-1 gap-4 grid-cols-1 sm:grid-cols-[1fr_1fr] content-start">
          {methods.map((m, i) => (
            <button
              key={m.id}
              onClick={() => setSelected(m.id)}
              className="animate-in fade-in slide-in-from-bottom-3 duration-400 group grid w-full grid-rows-[auto_1fr_auto] rounded-2xl border border-border bg-card/60 backdrop-blur text-left transition hover:border-[--accent]/50 hover:bg-card/80"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <div className="px-6 pt-6 pb-4">
                <div className="grid h-12 w-12 place-items-center rounded-xl bg-gradient-to-br from-[--primary]/20 to-[--accent]/10 text-[--accent]">
                  <m.icon className="h-6 w-6" />
                </div>
              </div>
              <div className="flex flex-col gap-1.5 px-6 pb-4">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-display text-lg font-semibold">{m.title}</p>
                  {m.needs2FA && (
                    <span className="rounded-full bg-[--primary]/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[--primary]">Needs 2FA</span>
                  )}
                  {m.bulk && (
                    <span className="rounded-full bg-[--accent]/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[--accent]">Bulk</span>
                  )}
                </div>
                <p className="text-sm text-muted-foreground">{m.description}</p>
              </div>
              <div className="flex w-full items-center justify-between border-t border-border/40 px-6 min-h-14">
                <span className="text-xs text-muted-foreground/60">Select method</span>
                <ChevronRight className="h-4 w-4 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-[--accent]" />
              </div>
            </button>
          ))}
        </div>
      ) : (
        <SecureForm method={current} onBack={() => setSelected(null)} />
      )}
    </div>
  );
}
