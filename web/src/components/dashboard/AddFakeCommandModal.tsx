import { useState } from "react";
import { Plus, X } from "lucide-react";
import { toast } from "sonner";
import { authHeaders } from "./context";

export function AddFakeCommandModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [response, setResponse] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !description.trim() || !response.trim()) return;
    const body = { title: title.trim(), description: description.trim(), response: response.trim() };
    const res = await fetch("/api/commands/fake", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      toast.success(`Fake command "${title}" created`);
      setTitle(""); setDescription(""); setResponse("");
      onClose();
      onCreated();
    } else {
      toast.error("Failed to create fake command");
    }
  };

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm animate-in fade-in duration-200 ${open ? "" : "hidden"}`}
      onClick={onClose}
    >
      <div className="w-full max-w-lg rounded-2xl border border-border bg-card shadow-2xl backdrop-blur animate-in fade-in zoom-in-95 duration-200" onClick={e => e.stopPropagation()}>
        <div className="h-1 rounded-t-2xl bg-gradient-to-r from-[--primary] to-[--accent]" />
        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-display text-lg font-bold">Add Fake Command</h2>
              <p className="mt-0.5 text-sm text-muted-foreground">Create a command that responds with a custom message.</p>
            </div>
            <button type="button" onClick={onClose} className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-medium">Title</label>
            <input
              type="text" required value={title} onChange={e => setTitle(e.target.value)}
              placeholder="mycommand"
              className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 font-mono text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
            />
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-medium">Description</label>
            <input
              type="text" required value={description} onChange={e => setDescription(e.target.value)}
              placeholder="What the command does"
              className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
            />
          </div>
          <div className="space-y-2">
            <label className="block text-sm font-medium">Response</label>
            <textarea
              required value={response} onChange={e => setResponse(e.target.value)}
              placeholder="The message the bot will reply with"
              rows={3}
              className="w-full rounded-lg border border-border bg-background/60 px-4 py-2.5 text-sm outline-none transition focus:border-[--primary] focus:ring-2 focus:ring-[--primary]/30"
            />
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="rounded-lg border border-border bg-background/60 px-5 py-2.5 text-sm font-medium transition hover:bg-card">
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
  );
}
