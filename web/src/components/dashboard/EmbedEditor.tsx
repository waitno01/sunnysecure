import { Eye } from "lucide-react";

export const PRESET_COLORS = ["#3B89FF", "#57F287", "#FA4343", "#FF9E45", "#9B59B6", "#1ABC9C", "#E91E63", "#FFD700"];

export function EmbedEditor({
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
