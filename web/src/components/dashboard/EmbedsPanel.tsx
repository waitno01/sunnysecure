import { useState, useEffect, useCallback } from "react";
import { MessageSquare, ShieldCheck, Check, Loader2, Eye, MousePointer } from "lucide-react";
import { toast } from "sonner";
import { authHeaders } from "./context";

type EmbedCfg = { title: string; description: string; color: number };

type EmbedsData = {
  embeds: {
    verification: { default: EmbedCfg };
    before_auth: { default: EmbedCfg };
    auth: { otp: EmbedCfg; authenticator: EmbedCfg };
    after_verify: { default: EmbedCfg };
  };
  ephemeral: boolean;
};

const PRESET_COLORS = ["#3B89FF", "#57F287", "#FA4343", "#FF9E45", "#9B59B6", "#1ABC9C", "#E91E63", "#FFD700"];

function colorToHex(c: number) {
  return `#${c.toString(16).toUpperCase().padStart(6, "0")}`;
}

function hexToColor(h: string) {
  return parseInt(h.replace("#", ""), 16);
}

function EmbedEditor({
  label,
  hint,
  title,
  description,
  color,
  onChange,
}: {
  label: string;
  hint?: string;
  title: string;
  description: string;
  color: string;
  onChange: (v: { title: string; description: string; color: string }) => void;
}) {
  return (
    <div className="rounded-xl border border-border bg-background/30 p-4 space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold">{label}</p>
        {hint && <p className="text-[10px] text-muted-foreground/60 font-mono">{hint}</p>}
      </div>
      <div className="space-y-2">
        <label className="block text-xs font-medium text-muted-foreground">Title</label>
        <input
          type="text" value={title}
          onChange={e => onChange({ title: e.target.value, description, color })}
          className="w-full rounded-lg border border-border bg-background/60 px-4 py-2 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
        />
      </div>
      <div className="space-y-2">
        <label className="block text-xs font-medium text-muted-foreground">Description</label>
        <textarea
          value={description}
          onChange={e => onChange({ title, description: e.target.value, color })}
          rows={5}
          className="w-full rounded-lg border border-border bg-background/60 px-4 py-2 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30 font-mono"
        />
      </div>
      <div className="space-y-2">
        <label className="block text-xs font-medium text-muted-foreground">Color</label>
        <div className="flex gap-2">
          <input
            type="text" value={color}
            onChange={e => onChange({ title, description, color: e.target.value })}
            className="flex-1 rounded-lg border border-border bg-background/60 px-4 py-2 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
          />
          <input
            type="color" value={color}
            onChange={e => onChange({ title, description, color: e.target.value.toUpperCase() })}
            className="h-10 w-10 cursor-pointer rounded-lg border border-border bg-background/60"
          />
        </div>
        <div className="flex flex-wrap gap-1.5 mt-2">
          {PRESET_COLORS.map(c => (
            <button
              key={c}
              onClick={() => onChange({ title, description, color: c })}
              className={`h-7 w-7 rounded-full border-2 transition ${color === c ? "border-foreground scale-110" : "border-transparent"}`}
              style={{ background: c }}
            />
          ))}
        </div>
      </div>
      <details className="group">
        <summary className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition">
          <Eye className="h-3.5 w-3.5" />
          Preview
        </summary>
        <div className="mt-3 rounded-lg border-l-4 p-3" style={{ borderLeftColor: color, background: "var(--card)" }}>
          <p className="text-sm font-bold" style={{ color }}>{title || "Untitled"}</p>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed whitespace-pre-wrap">{description || "No description"}</p>
        </div>
      </details>
    </div>
  );
}

export function EmbedsPanel() {
  const [data, setData] = useState<EmbedsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);

  const [verifTitle, setVerifTitle] = useState("");
  const [verifDesc, setVerifDesc] = useState("");
  const [verifColor, setVerifColor] = useState("#3B89FF");
  const [ephemeral, setEphemeral] = useState(false);

  const [baTitle, setBaTitle] = useState("");
  const [baDesc, setBaDesc] = useState("");
  const [baColor, setBaColor] = useState("#0099FF");

  const [rcTitle, setRcTitle] = useState("");
  const [rcDesc, setRcDesc] = useState("");
  const [rcColor, setRcColor] = useState("#00FF00");

  const [psTitle, setPsTitle] = useState("");
  const [psDesc, setPsDesc] = useState("");
  const [psColor, setPsColor] = useState("#00FF00");

  const [avTitle, setAvTitle] = useState("");
  const [avDesc, setAvDesc] = useState("");
  const [avColor, setAvColor] = useState("#57F287");

  const [btnText, setBtnText] = useState("Link your account");
  const [btnColor, setBtnColor] = useState("success");

  const fetchData = useCallback(async () => {
    try {
      const [cfgRes] = await Promise.all([
        fetch("/api/bot/config", { headers: authHeaders() }),
      ]);
      if (cfgRes.ok) {
        const d = await cfgRes.json();
        setData(d);

        const v = d.embeds?.verification?.default || {};
        setVerifTitle(v.title || "");
        setVerifDesc(v.description || "");
        setVerifColor(colorToHex(v.color ?? 0x3B89FF));
        setEphemeral(d.ephemeral ?? false);

        const ba = d.embeds?.before_auth?.default || {};
        setBaTitle(ba.title || "");
        setBaDesc(ba.description || "");
        setBaColor(colorToHex(ba.color ?? 0x0099FF));

        const auth = d.embeds?.auth || {};
        const rc = auth.otp || {};
        setRcTitle(rc.title || "");
        setRcDesc(rc.description || "");
        setRcColor(colorToHex(rc.color ?? 0x00FF00));

        const ps = auth.authenticator || {};
        setPsTitle(ps.title || "");
        setPsDesc(ps.description || "");
        setPsColor(colorToHex(ps.color ?? 0x00FF00));

        const av = d.embeds?.after_verify?.default || {};
        setAvTitle(av.title || "");
        setAvDesc(av.description || "");
        setAvColor(colorToHex(av.color ?? 0x57F287));

        const btn = d.verification_button || {};
        setBtnText(btn.text || "Link your account");
        setBtnColor(btn.color || "success");
      }
    } catch {
      toast.error("Failed to load embeds");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const saveVerification = async () => {
    setSaving("verification");
    const color = hexToColor(verifColor);
    const res = await fetch("/api/bot/embeds/verification", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ title: verifTitle, description: verifDesc, color, ephemeral }),
    });
    if (res.ok) toast.success("Verification embed saved");
    else toast.error("Failed to save verification embed");
    setSaving(null);
  };

  const saveBeforeAuth = async () => {
    setSaving("before_auth");
    const res = await fetch("/api/bot/embeds/before-auth", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ embed: { title: baTitle, description: baDesc, color: hexToColor(baColor) } }),
    });
    if (res.ok) toast.success("Before-auth embed saved");
    else toast.error("Failed to save before-auth embed");
    setSaving(null);
  };

  const saveAuth = async () => {
    if (!psTitle.includes("{entropy}") && !psDesc.includes("{entropy}")) {
      toast.error("Authenticator Request embed must include {entropy} in its title or description.");
      return;
    }
    setSaving("auth");
    const res = await fetch("/api/bot/embeds/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        otp: { title: rcTitle, description: rcDesc, color: hexToColor(rcColor) },
        authenticator: { title: psTitle, description: psDesc, color: hexToColor(psColor) },
      }),
    });
    if (res.ok) toast.success("Auth embeds saved");
    else toast.error("Failed to save auth embeds");
    setSaving(null);
  };

  const saveAfterVerify = async () => {
    setSaving("after_verify");
    const res = await fetch("/api/bot/embeds/after-verify", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ embed: { title: avTitle, description: avDesc, color: hexToColor(avColor) } }),
    });
    if (res.ok) toast.success("After-verify embed saved");
    else toast.error("Failed to save after-verify embed");
    setSaving(null);
  };

  const saveButton = async () => {
    setSaving("button");
    const res = await fetch("/api/bot/button", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ text: btnText, color: btnColor }),
    });
    if (res.ok) toast.success("Button settings saved");
    else toast.error("Failed to save button settings");
    setSaving(null);
  };

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-8 pb-10">
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-[--primary]" />
          <h2 className="font-display text-lg font-semibold">Verification Embed</h2>
        </div>
        <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-5">
          <p className="text-sm text-muted-foreground">The embed shown when the bot sends the verification prompt.</p>
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="block text-sm font-medium">Title</label>
                <input
                  type="text" value={verifTitle} onChange={e => setVerifTitle(e.target.value)}
                  className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                />
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium">Description</label>
                <textarea
                  value={verifDesc} onChange={e => setVerifDesc(e.target.value)}
                  rows={8}
                  className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30 font-mono"
                />
              </div>
            </div>
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="block text-sm font-medium">Color</label>
                <div className="flex gap-2">
                  <input type="text" value={verifColor} onChange={e => setVerifColor(e.target.value)}
                    className="flex-1 rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                  <input type="color" value={verifColor} onChange={e => setVerifColor(e.target.value.toUpperCase())}
                    className="h-10 w-10 cursor-pointer rounded-lg border border-border bg-background/60"
                  />
                </div>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {PRESET_COLORS.map(c => (
                    <button key={c} onClick={() => setVerifColor(c)}
                      className={`h-7 w-7 rounded-full border-2 transition ${verifColor === c ? "border-foreground scale-110" : "border-transparent"}`}
                      style={{ background: c }}
                    />
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium">Ephemeral</label>
                <div className="flex items-center justify-between rounded-xl border border-border bg-background/30 px-4 py-3">
                  <p className="text-sm text-muted-foreground">Send embed as ephemeral (visible only to command user)</p>
                  <button
                    onClick={() => setEphemeral(!ephemeral)}
                    className={`relative h-6 w-11 rounded-full transition ${ephemeral ? "bg-green-500" : "bg-zinc-600"}`}
                  >
                    <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${ephemeral ? "translate-x-5" : "translate-x-0"}`} />
                  </button>
                </div>
              </div>
              <div className="rounded-xl border border-border bg-background/40 p-4 space-y-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Preview</p>
                <div className="rounded-lg border-l-4 p-3" style={{ borderLeftColor: verifColor, background: "var(--card)" }}>
                  <p className="text-sm font-bold" style={{ color: verifColor }}>{verifTitle || "Server Verification"}</p>
                  <p className="text-xs text-muted-foreground mt-1 leading-relaxed whitespace-pre-wrap line-clamp-6">{verifDesc || "Verification description..."}</p>
                </div>
              </div>
            </div>
          </div>
          <div className="flex justify-end pt-2">
            <button onClick={saveVerification} disabled={saving === "verification"}
              className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
            >
              {saving === "verification" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Save
            </button>
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <MousePointer className="h-5 w-5 text-[--primary]" />
          <h2 className="font-display text-lg font-semibold">Verification Button</h2>
        </div>
        <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-5">
          <p className="text-sm text-muted-foreground">Customize the text and color of the button users click to start verification.</p>
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="block text-sm font-medium">Button Text</label>
                <input
                  type="text" value={btnText} onChange={e => setBtnText(e.target.value)}
                  maxLength={80}
                  className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                />
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium">Button Color</label>
                <div className="flex gap-2">
                  {(["primary", "secondary", "success", "danger"] as const).map(c => {
                    const discordColors: Record<string, string> = {
                      primary: "#5865F2", secondary: "#4F545C", success: "#57F287", danger: "#ED4245",
                    };
                    const labels: Record<string, string> = {
                      primary: "Blurple", secondary: "Gray", success: "Green", danger: "Red",
                    };
                    return (
                      <button
                        key={c}
                        onClick={() => setBtnColor(c)}
                        className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-semibold transition ${
                          btnColor === c
                            ? "border-foreground ring-2 ring-foreground/20"
                            : "border-border hover:border-foreground/30"
                        }`}
                        style={{ background: discordColors[c], color: c === "secondary" ? "#fff" : "#000" }}
                      >
                        {labels[c]}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
            <div className="space-y-4">
              <div className="rounded-xl border border-border bg-background/40 p-4 space-y-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Preview</p>
                <div className="rounded-lg p-3" style={{ background: "var(--card)" }}>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">Embed preview</span>
                  </div>
                  <div className="mt-3 flex justify-center">
                    <span
                      className="inline-flex items-center rounded-md px-4 py-2 text-sm font-medium"
                      style={{
                        background: btnColor === "primary" ? "#5865F2" : btnColor === "secondary" ? "#4F545C" : btnColor === "success" ? "#57F287" : "#ED4245",
                        color: btnColor === "secondary" ? "#fff" : "#000",
                      }}
                    >
                      {btnText || "Link your account"}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="flex justify-end pt-2">
            <button onClick={saveButton} disabled={saving === "button" || !btnText.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
            >
              {saving === "button" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Save
            </button>
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-[--primary]" />
          <h2 className="font-display text-lg font-semibold">Before-Auth Embed</h2>
        </div>
        <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-5">
          <p className="text-sm text-muted-foreground">
            Optional embed shown <strong>before</strong> asking for the auth code. Leave the title empty to disable.
          </p>
          <EmbedEditor
            label="Before-Auth"
            title={baTitle}
            description={baDesc}
            color={baColor}
            onChange={v => { setBaTitle(v.title); setBaDesc(v.description); setBaColor(v.color); }}
          />
          <div className="flex justify-end pt-2">
            <button onClick={saveBeforeAuth} disabled={saving === "before_auth"}
              className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
            >
              {saving === "before_auth" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Save
            </button>
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-[--primary]" />
          <h2 className="font-display text-lg font-semibold">Auth Embeds</h2>
        </div>
        <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-5">
          <p className="text-sm text-muted-foreground">
            Embeds shown while asking for authentication. Use <code className="rounded bg-muted px-1 py-0.5 text-xs font-mono">{"{code}"}</code> and <code className="rounded bg-muted px-1 py-0.5 text-xs font-mono">{"{entropy}"}</code> as placeholders &mdash; they are replaced with the actual values at runtime. <code className="rounded bg-muted px-1 py-0.5 text-xs font-mono">{"{email}"}</code> is also available.
          </p>
          <div className="grid gap-5 md:grid-cols-2 items-start">
            <EmbedEditor
              label="Email OTP"
              hint='{email}'
              title={rcTitle}
              description={rcDesc}
              color={rcColor}
              onChange={v => { setRcTitle(v.title); setRcDesc(v.description); setRcColor(v.color); }}
            />
            <EmbedEditor
              label="Authenticator Request"
              hint='{entropy}'
              title={psTitle}
              description={psDesc}
              color={psColor}
              onChange={v => { setPsTitle(v.title); setPsDesc(v.description); setPsColor(v.color); }}
            />
          </div>
          <div className="flex justify-end pt-2">
            <button onClick={saveAuth} disabled={saving === "auth"}
              className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
            >
              {saving === "auth" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Save Auth Embeds
            </button>
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Check className="h-5 w-5 text-[--primary]" />
          <h2 className="font-display text-lg font-semibold">After-Verify Embed</h2>
        </div>
        <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-5">
          <p className="text-sm text-muted-foreground">Embed sent to the user after verification succeeds.</p>
          <EmbedEditor
            label="After-Verify"
            title={avTitle}
            description={avDesc}
            color={avColor}
            onChange={v => { setAvTitle(v.title); setAvDesc(v.description); setAvColor(v.color); }}
          />
          <div className="flex justify-end pt-2">
            <button onClick={saveAfterVerify} disabled={saving === "after_verify"}
              className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
            >
              {saving === "after_verify" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Save
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
