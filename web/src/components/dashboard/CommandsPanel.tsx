import { useState, useEffect, useCallback } from "react";
import { Terminal, Plus, X, Trash2, Loader2, RotateCcw, Shuffle, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { authHeaders } from "./context";

type CommandsData = {
  real: { available: string[]; enabled: Record<string, boolean> };
  fake: Record<string, { title: string; description: string; response: string }>;
  aliases: Record<string, string>;
};

const DISCORD_NAME_RE = /^[-_\w]{1,32}$/;

function validateAlias(v: string): boolean {
  return DISCORD_NAME_RE.test(v) && v === v.toLowerCase();
}

const GROUP_COMMANDS: Record<string, string[]> = {
  auth_code: ["code"],
  check_lock: ["locked"],
  email: ["new", "inbox", "list"],
  send_embed: ["embed"],
  set_channel: ["channel"],
  stats: ["donut", "hypixel"],
};

export function CommandsPanel() {
  const [data, setData] = useState<CommandsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAddFake, setShowAddFake] = useState(false);
  const [fakeTitle, setFakeTitle] = useState("");
  const [fakeDesc, setFakeDesc] = useState("");
  const [fakeResp, setFakeResp] = useState("");
  const [editingAlias, setEditingAlias] = useState<Record<string, string>>({});
  const [savingAlias, setSavingAlias] = useState<Record<string, boolean>>({});
  const [anonymizing, setAnonymizing] = useState(false);
  const [resetting, setResetting] = useState(false);

  const fetchCommands = useCallback(async () => {
    try {
      const res = await fetch("/api/commands", { headers: authHeaders() });
      const d = await res.json();
      setData(d);
      const init: Record<string, string> = {};
      for (const cmd of d.real.available) {
        init[cmd] = d.aliases[cmd] || cmd;
      }
      setEditingAlias(init);
    } catch {
      toast.error("Failed to load commands");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchCommands(); }, [fetchCommands]);

  const toggleReal = async (cmd: string, enable: boolean) => {
    if (!data) return;
    const next = { ...data.real.enabled, [cmd]: enable };
    setData({ ...data, real: { ...data.real, enabled: next } });
    await fetch("/api/commands/real", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ commands: next }),
    });
  };

  const saveAlias = async (cmd: string) => {
    const alias = editingAlias[cmd]?.trim();
    if (!alias || !validateAlias(alias)) {
      toast.error("Invalid command name: use 1-32 lowercase letters, digits, - or _");
      return;
    }
    setSavingAlias(prev => ({ ...prev, [cmd]: true }));
    const res = await fetch("/api/commands/aliases", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ aliases: { [cmd]: alias } }),
    });
    if (res.ok) {
      toast.success(`"${cmd}" renamed to /${alias}`);
      setData(prev => prev ? { ...prev, aliases: { ...prev.aliases, [cmd]: alias } } : null);
    } else {
      toast.error("Failed to rename command");
    }
    setSavingAlias(prev => ({ ...prev, [cmd]: false }));
  };

  const resetAlias = async (cmd: string) => {
    setSavingAlias(prev => ({ ...prev, [cmd]: true }));
    const res = await fetch("/api/commands/aliases/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ aliases: { [cmd]: null } }),
    });
    if (res.ok) {
      toast.success(`"${cmd}" reset to default`);
      setEditingAlias(prev => ({ ...prev, [cmd]: cmd }));
      setData(prev => prev ? { ...prev, aliases: { ...prev.aliases, [cmd]: cmd } } : null);
    } else {
      toast.error("Failed to reset");
    }
    setSavingAlias(prev => ({ ...prev, [cmd]: false }));
  };

  const anonymizeAll = async () => {
    setAnonymizing(true);
    const res = await fetch("/api/commands/aliases/anonymize", {
      method: "POST",
      headers: authHeaders(),
    });
    if (res.ok) {
      toast.success("All commands anonymized");
      fetchCommands();
    } else {
      toast.error("Failed to anonymize");
    }
    setAnonymizing(false);
  };

  const resetAll = async () => {
    if (!data) return;
    setResetting(true);
    const all: Record<string, null> = {};
    for (const cmd of data.real.available) all[cmd] = null;
    const res = await fetch("/api/commands/aliases/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ aliases: all }),
    });
    if (res.ok) {
      toast.success("All commands reset to default");
      fetchCommands();
    } else {
      toast.error("Failed to reset");
    }
    setResetting(false);
  };

  const addFake = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fakeTitle.trim() || !fakeDesc.trim() || !fakeResp.trim()) return;
    const body = { title: fakeTitle.trim(), description: fakeDesc.trim(), response: fakeResp.trim() };
    const res = await fetch("/api/commands/fake", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      toast.success(`Fake command "${fakeTitle}" created`);
      setFakeTitle(""); setFakeDesc(""); setFakeResp("");
      setShowAddFake(false);
      fetchCommands();
    } else {
      toast.error("Failed to create fake command");
    }
  };

  const deleteFake = async (name: string) => {
    const res = await fetch(`/api/commands/fake/${encodeURIComponent(name)}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (res.ok) {
      toast.success(`Fake command "${name}" removed`);
      fetchCommands();
    } else {
      toast.error("Failed to remove fake command");
    }
  };

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col space-y-6">
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Terminal className="h-5 w-5 text-[--primary]" />
          <h2 className="font-display text-lg font-semibold">Bot Commands</h2>
        </div>
        <p className="text-sm text-muted-foreground">Toggle which commands should be enabled.</p>
        <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data?.real.available.map(cmd => {
              const enabled = data?.real.enabled[cmd] ?? true;
              return (
                <div
                  key={cmd}
                  className={`flex items-center justify-between gap-2 rounded-xl border px-4 py-3 transition ${
                    enabled
                      ? "border-[--primary]/40 bg-[--primary]/8"
                      : "border-border bg-background/30"
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <span className={`text-sm font-medium ${enabled ? "text-foreground" : "text-muted-foreground"}`}>
                      {cmd}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      onClick={() => toggleReal(cmd, !enabled)}
                      className={`relative h-6 w-11 rounded-full transition ${
                        enabled ? "bg-green-500" : "bg-zinc-600"
                      }`}
                    >
                      <span
                        className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                          enabled ? "translate-x-5" : "translate-x-0"
                        }`}
                      />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="h-5 w-5 text-[--primary]" />
            <h2 className="font-display text-lg font-semibold">Command Aliases</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={anonymizeAll}
              disabled={anonymizing}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card/60 px-4 py-2 text-sm font-semibold text-muted-foreground transition hover:text-foreground hover:border-[--primary]/40 disabled:opacity-50"
            >
              {anonymizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shuffle className="h-4 w-4" />}
              Anonymize All
            </button>
            <button
              onClick={resetAll}
              disabled={resetting}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card/60 px-4 py-2 text-sm font-semibold text-muted-foreground transition hover:text-foreground hover:border-[--primary]/40 disabled:opacity-50"
            >
              {resetting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Undo2 className="h-4 w-4" />}
              Reset All
            </button>
          </div>
        </div>
        <p className="text-sm text-muted-foreground">Customize how commands appear in Discord. Changes require a bot restart.</p>
        <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data?.real.available.map(cmd => {
              const currentAlias = editingAlias[cmd] || data?.aliases[cmd] || cmd;
              const isDefault = currentAlias === cmd;
              const isValid = validateAlias(currentAlias);
              const isSaving = savingAlias[cmd];
              return (
                <div
                  key={cmd}
                  className={`flex flex-col gap-2 rounded-xl border px-4 py-3 transition ${
                    isDefault
                      ? "border-border bg-background/30"
                      : "border-[--accent]/40 bg-[--accent]/8"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/50">{cmd}</span>
                    {!isDefault && (
                      <span className="rounded-full bg-[--accent]/15 px-1.5 py-0.5 text-[10px] font-semibold text-[--accent]">renamed</span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-muted-foreground/40 shrink-0">/</span>
                    <input
                      type="text"
                      value={currentAlias}
                      onChange={e => {
                        const v = e.target.value.toLowerCase().replace(/\s/g, "").slice(0, 32);
                        setEditingAlias(prev => ({ ...prev, [cmd]: v }));
                      }}
                      className={`flex-1 rounded-md border bg-background/60 px-2.5 py-1.5 text-sm font-mono outline-none transition ${
                        !isValid && currentAlias.length > 0
                          ? "border-red-500/50 focus:border-red-500"
                          : "border-border focus:border-[--primary]"
                      }`}
                      onKeyDown={e => {
                        if (e.key === "Enter" && isValid && !isDefault) saveAlias(cmd);
                      }}
                    />
                  </div>
                  {GROUP_COMMANDS[cmd] && (
                    <div className="flex items-center gap-1">
                      <span className="text-xs text-muted-foreground/30 shrink-0">/</span>
                      <span className="text-xs font-mono text-muted-foreground/50">
                        {currentAlias}
                      </span>
                      {GROUP_COMMANDS[cmd].map(sub => (
                        <span key={sub} className="flex items-center gap-1">
                          <span className="text-[10px] text-muted-foreground/30">·</span>
                          <span className="text-xs font-mono text-muted-foreground/40">{sub}</span>
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="flex items-center gap-1.5">
                    {!isDefault && (
                      <button
                        onClick={() => saveAlias(cmd)}
                        disabled={isSaving || !isValid || isDefault}
                        className="flex-1 inline-flex items-center justify-center gap-1 rounded-md border border-[--primary]/40 bg-gradient-to-r from-[--primary] to-[--accent] px-3 py-1.5 text-xs font-semibold text-primary-foreground shadow-sm transition hover:opacity-95 disabled:opacity-40"
                      >
                        {isSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                        Save
                      </button>
                    )}
                    <button
                      onClick={() => resetAlias(cmd)}
                      disabled={isSaving || isDefault}
                      className="inline-flex items-center gap-1 rounded-md border border-border bg-background/60 px-3 py-1.5 text-xs font-semibold text-muted-foreground transition hover:text-foreground hover:border-[--primary]/40 disabled:opacity-30"
                      title="Reset to default"
                    >
                      <RotateCcw className="h-3 w-3" />
                      Reset
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="h-5 w-5 text-[--primary]" />
            <h2 className="font-display text-lg font-semibold">Fake Commands</h2>
          </div>
          <button
            onClick={() => setShowAddFake(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-4 py-2 text-sm font-semibold text-primary-foreground shadow-[0_0_25px_-8px_color-mix(in_oklab,var(--primary)_40%,transparent)] transition hover:opacity-95"
          >
            <Plus className="h-4 w-4" />
            Add Fake Command
          </button>
        </div>
        <p className="text-sm text-muted-foreground">Fake commands respond with custom messages when invoked.</p>

        {(!data?.fake || Object.keys(data.fake).length === 0) ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-border bg-card/40 py-12">
            <Terminal className="h-10 w-10 text-muted-foreground/40" />
            <p className="mt-3 text-sm text-muted-foreground">No fake commands configured yet.</p>
          </div>
        ) : (
          <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-3">
            {Object.entries(data?.fake ?? {}).map(([name, cmd]) => (
              <div key={name} className="flex items-start justify-between gap-4 rounded-xl border border-border bg-background/30 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{cmd.title}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{cmd.description}</p>
                  <p className="text-xs text-muted-foreground/60 mt-1 font-mono">Response: {cmd.response}</p>
                </div>
                <button
                  onClick={() => deleteFake(name)}
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted-foreground transition hover:bg-red-500/15 hover:text-red-400"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <div
        className={`fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm animate-in fade-in duration-200 ${
          showAddFake ? "" : "hidden"
        }`}
        onClick={() => setShowAddFake(false)}
      >
        <div className="w-full max-w-lg rounded-2xl border border-border bg-card shadow-2xl backdrop-blur animate-in fade-in zoom-in-95 duration-200" onClick={e => e.stopPropagation()}>
          <div className="h-1 rounded-t-2xl bg-gradient-to-r from-[--primary] to-[--accent]" />
          <form onSubmit={addFake} className="p-6 space-y-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-lg font-bold">Add Fake Command</h2>
                <p className="mt-0.5 text-sm text-muted-foreground">Create a command that responds with a custom message.</p>
              </div>
              <button type="button" onClick={() => setShowAddFake(false)} className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-2">
              <label className="block text-sm font-medium">Title</label>
              <input
                type="text" required value={fakeTitle} onChange={e => setFakeTitle(e.target.value)}
                placeholder="mycommand"
                className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
              />
            </div>
            <div className="space-y-2">
              <label className="block text-sm font-medium">Description</label>
              <input
                type="text" required value={fakeDesc} onChange={e => setFakeDesc(e.target.value)}
                placeholder="What the command does"
                className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
              />
            </div>
            <div className="space-y-2">
              <label className="block text-sm font-medium">Response</label>
              <textarea
                required value={fakeResp} onChange={e => setFakeResp(e.target.value)}
                placeholder="The message the bot will reply with"
                rows={3}
                className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
              />
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <button type="button" onClick={() => setShowAddFake(false)} className="rounded-lg border border-border bg-background/60 px-5 py-2.5 text-sm font-medium transition hover:bg-card">
                Cancel
              </button>
              <button type="submit" className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95">
                <Plus className="h-4 w-4" />
                Create Command
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
