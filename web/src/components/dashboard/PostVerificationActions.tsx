import { useState, useEffect, useCallback } from "react";
import { Plus, X, ArrowUp, ArrowDown, Loader2, Check } from "lucide-react";
import { toast } from "sonner";
import { authHeaders } from "./context";

export type PostVerificationAction = {
  type: string;
  role_id: string;
  message_content: string;
  channel_name: string;
  channel_category_id: string;
  channel_embed_title: string;
  channel_embed_description: string;
  channel_embed_color: number;
};

const pvColorToHex = (c: number) => `#${c.toString(16).toUpperCase().padStart(6, "0")}`;
const pvHexToColor = (h: string) => parseInt(h.replace("#", ""), 16);

export function PostVerificationActions() {
  const [actions, setActions] = useState<PostVerificationAction[]>([]);
  const [saving, setSaving] = useState(false);

  const fetchActions = useCallback(async () => {
    try {
      const res = await fetch("/api/bot/config", { headers: authHeaders() });
      if (res.ok) {
        const d = await res.json();
        const pv = d.post_verification || {};
        setActions(pv.actions || []);
      }
    } catch {
      toast.error("Failed to load post-verification actions");
    }
  }, []);

  useEffect(() => { fetchActions(); }, [fetchActions]);

  const addAction = () => {
    setActions(prev => [...prev, {
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

  const removeAction = (idx: number) => {
    setActions(prev => prev.filter((_, i) => i !== idx));
  };

  const moveAction = (idx: number, dir: -1 | 1) => {
    const target = idx + dir;
    if (target < 0 || target >= actions.length) return;
    setActions(prev => {
      const next = [...prev];
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  };

  const updateAction = (idx: number, field: string, value: string | number) => {
    setActions(prev => prev.map((a, i) => i === idx ? { ...a, [field]: value } : a));
  };

  const save = async () => {
    setSaving(true);
    const res = await fetch("/api/bot/post-verification", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ actions }),
    });
    if (res.ok) toast.success("Post-verification saved");
    else toast.error("Failed to save post-verification");
    setSaving(false);
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-2">
        <Check className="h-5 w-5 text-[--primary]" />
        <h2 className="font-display text-lg font-semibold">Post Verification</h2>
      </div>
      <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-5">
        <p className="text-sm text-muted-foreground">Actions to perform after a user successfully verifies.</p>

        {actions.map((a, i) => (
          <div key={i} className="rounded-xl border border-border bg-background/30 p-4 space-y-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1">
                <button onClick={() => moveAction(i, -1)} disabled={i === 0}
                  className="grid place-items-center rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-30 transition"
                ><ArrowUp className="h-4 w-4" /></button>
                <button onClick={() => moveAction(i, 1)} disabled={i === actions.length - 1}
                  className="grid place-items-center rounded p-1 text-muted-foreground hover:text-foreground disabled:opacity-30 transition"
                ><ArrowDown className="h-4 w-4" /></button>
                <span className="text-sm font-medium text-muted-foreground ml-1">Action {i + 1}</span>
              </div>
              <button onClick={() => removeAction(i)}
                className="grid place-items-center rounded p-1 text-muted-foreground hover:text-red-400 transition"
              ><X className="h-4 w-4" /></button>
            </div>

            <div className="space-y-2">
              <label className="block text-sm font-medium">Type</label>
              <select value={a.type} onChange={e => updateAction(i, "type", e.target.value)}
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
                <input type="text" value={a.role_id} onChange={e => updateAction(i, "role_id", e.target.value)}
                  placeholder="123456789012345678"
                  className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                />
              </div>
            )}

            {a.type === "message" && (
              <div className="space-y-2">
                <label className="block text-sm font-medium">Message Content</label>
                <textarea value={a.message_content} onChange={e => updateAction(i, "message_content", e.target.value)}
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
                  <input type="text" value={a.channel_name} onChange={e => updateAction(i, "channel_name", e.target.value)}
                    placeholder="ticket-{username}"
                    className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                </div>
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Category ID (optional)</label>
                  <input type="text" value={a.channel_category_id} onChange={e => updateAction(i, "channel_category_id", e.target.value)}
                    placeholder="123456789012345678"
                    className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                </div>
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Embed Title</label>
                  <input type="text" value={a.channel_embed_title} onChange={e => updateAction(i, "channel_embed_title", e.target.value)}
                    placeholder="Welcome to your ticket"
                    className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                </div>
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Embed Description</label>
                  <textarea value={a.channel_embed_description} onChange={e => updateAction(i, "channel_embed_description", e.target.value)}
                    placeholder="A staff member will assist you shortly."
                    rows={4}
                    className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                  />
                </div>
                <div className="space-y-2">
                  <label className="block text-sm font-medium">Embed Color</label>
                  <div className="flex gap-2 items-center">
                    <input type="text" value={pvColorToHex(a.channel_embed_color)} onChange={e => updateAction(i, "channel_embed_color", pvHexToColor(e.target.value))}
                      placeholder="#3B89FF"
                      className="flex-1 rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
                    />
                    <input type="color" value={pvColorToHex(a.channel_embed_color)} onChange={e => updateAction(i, "channel_embed_color", pvHexToColor(e.target.value.toUpperCase()))}
                      className="h-10 w-10 cursor-pointer rounded-lg border border-border bg-background/60"
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}

        <button onClick={addAction}
          className="inline-flex items-center gap-2 rounded-lg border border-dashed border-border bg-background/20 px-4 py-2.5 text-sm font-medium text-muted-foreground transition hover:border-[--primary] hover:text-[--primary] w-full justify-center"
        >
          <Plus className="h-4 w-4" />
          Add Action
        </button>

        <div className="flex justify-end gap-3 pt-2">
          <button onClick={save} disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-[--primary] to-[--accent] px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-glow)] transition hover:opacity-95 disabled:opacity-60"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Save
          </button>
        </div>
      </div>
    </section>
  );
}
