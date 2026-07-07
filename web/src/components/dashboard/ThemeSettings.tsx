import { useState } from "react";
import {
  Palette, Sparkles, SlidersHorizontal, Type, RotateCcw, Check, Star, CloudRain, Waves, Monitor, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  THEME_PRESETS, DEFAULT_SETTINGS, loadSettings, saveSettings, previewColors,
  type ThemeSettings, type ThemePreset, type AnimationType,
  type InterfaceFont, type MonoFont,
} from "@/lib/theme";

const ANIMATIONS: { id: AnimationType; label: string; desc: string; icon: typeof Star }[] = [
  { id: "starfield", label: "Starfield",  desc: "Twinkling stars & drifting clouds", icon: Star },
  { id: "aurora",    label: "Aurora",     desc: "Northern lights shimmer",           icon: Sparkles },
  { id: "particles", label: "Particles",  desc: "Floating particles rising",         icon: Zap },
  { id: "rain",      label: "Rain",       desc: "Gentle digital rain",               icon: CloudRain },
  { id: "waves",     label: "Waves",      desc: "Slow undulating waves",             icon: Waves },
  { id: "none",      label: "None",       desc: "Clean, no animation",               icon: Monitor },
];

const INTERFACE_FONTS: InterfaceFont[] = [
  "Inter", "Manrope", "Poppins", "Space Grotesk", "Outfit",
  "Sora", "Plus Jakarta Sans", "DM Sans", "Figtree", "system-ui", "serif",
];
const INTERFACE_FONT_LABELS: Record<string, string> = { "system-ui": "System", "serif": "Serif" };

const MONO_FONTS: MonoFont[] = [
  "JetBrains Mono", "Fira Code", "IBM Plex Mono", "Roboto Mono", "Source Code Pro", "monospace",
];
const MONO_FONT_LABELS: Record<string, string> = { "monospace": "System Mono" };

function RangeSlider({
  label, value, min, max, unit = "", trackStyle, onChange,
}: {
  label: string; value: number; min: number; max: number;
  unit?: string; trackStyle?: React.CSSProperties; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-sm font-semibold text-[--primary]">{value}{unit}</span>
      </div>
      <div className="relative h-2 rounded-full" style={trackStyle ?? { background: "var(--muted)" }}>
        <input
          type="range"
          min={min} max={max}
          value={value}
          onChange={e => onChange(Number(e.target.value))}
          className="custom-range absolute inset-0 h-full w-full cursor-pointer opacity-0"
          style={{ zIndex: 2 }}
        />
        <div
          className="pointer-events-none absolute left-0 top-0 h-full rounded-full bg-[--primary]/70"
          style={{ width: `${((value - min) / (max - min)) * 100}%` }}
        />
        <div
          className="pointer-events-none absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full border-2 border-[--primary] bg-white shadow"
          style={{ left: `calc(${((value - min) / (max - min)) * 100}% - 8px)`, zIndex: 1 }}
        />
      </div>
    </div>
  );
}

function ThemeCard({ preset, selected, onClick }: { preset: ThemePreset; selected: boolean; onClick: () => void }) {
  const { primary, accent } = previewColors(preset.primaryHue, preset.accentHue, preset.saturation);
  return (
    <button
      onClick={onClick}
      className={cn(
        "group relative overflow-hidden rounded-xl border-2 bg-card/80 transition-all duration-200 hover:scale-[1.03]",
        selected ? "border-[--primary] shadow-[0_0_12px_-2px_color-mix(in_srgb,var(--primary)_40%,transparent)]"
                 : "border-border hover:border-muted-foreground/50"
      )}
    >
      <div className="relative h-[72px] w-full bg-background/50">
        <div
          className="absolute bottom-2.5 left-2.5 h-0.5 w-1/2 rounded-full opacity-90"
          style={{ background: `linear-gradient(90deg, ${primary}, ${accent})` }}
        />
        {selected && (
          <div
            className="absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full"
            style={{ background: primary }}
          >
            <Check className="h-3 w-3 text-white" />
          </div>
        )}
      </div>
      <p className="py-1.5 text-center text-[11px] font-medium text-muted-foreground group-hover:text-foreground transition">
        {preset.name}
      </p>
    </button>
  );
}

function ThemePreview({ s }: { s: ThemeSettings }) {
  const { primary, accent } = previewColors(s.primaryHue, s.accentHue, s.saturation);
  return (
    <div className="flex h-full flex-col gap-3 rounded-xl border border-border bg-background/60 p-4">
      <div className="flex items-center gap-2">
        <div className="h-8 w-8 rounded-full" style={{ background: primary }} />
        <div className="space-y-1 flex-1">
          <div className="h-2 rounded-full" style={{ background: primary, width: "70%" }} />
          <div className="h-1.5 rounded-full bg-muted-foreground/30 w-full" />
          <div className="h-1.5 rounded-full bg-muted-foreground/20 w-4/5" />
        </div>
      </div>
      <div className="flex-1 space-y-2 rounded-lg border border-border/60 bg-card/40 p-3">
        <div className="h-1.5 rounded-full bg-muted-foreground/30 w-full" />
        <div className="h-1.5 rounded-full bg-muted-foreground/20 w-3/4" />
      </div>
      <div className="flex gap-2">
        <div className="h-5 w-5 rounded-full" style={{ background: primary }} />
        <div className="h-5 w-5 rounded-full" style={{ background: accent }} />
        <div className="h-5 w-5 rounded-full bg-muted" />
        <div className="h-5 w-5 rounded-full bg-foreground/80" />
      </div>
    </div>
  );
}

export function ThemeSettingsPanel() {
  const [s, setS] = useState<ThemeSettings>(() => loadSettings());

  const update = (patch: Partial<ThemeSettings>) => {
    const next = { ...s, ...patch };
    setS(next);
    saveSettings(next);
  };

  const applyPreset = (p: ThemePreset) =>
    update({ themeId: p.id, primaryHue: p.primaryHue, accentHue: p.accentHue, saturation: p.saturation, bgLightness: p.bgLightness });

  const reset = () => { const d = { ...DEFAULT_SETTINGS }; setS(d); saveSettings(d); };

  const rainbowTrack = { background: "linear-gradient(to right, hsl(0,80%,55%), hsl(45,80%,55%), hsl(90,80%,55%), hsl(135,80%,55%), hsl(180,80%,55%), hsl(225,80%,55%), hsl(270,80%,55%), hsl(315,80%,55%), hsl(360,80%,55%))" };

  return (
    <>
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Appearance</h1>
          <p className="mt-1 text-sm text-muted-foreground">Customize your theme colors.</p>
        </div>
        <button
          onClick={reset}
          className="flex items-center gap-1.5 rounded-lg border border-border bg-card/60 px-3 py-2 text-sm text-muted-foreground transition hover:text-foreground"
        >
          <RotateCcw className="h-3.5 w-3.5" /> Reset
        </button>
      </div>

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Palette className="h-5 w-5 text-[--primary]" />
          <h2 className="font-display text-lg font-semibold">Preset Themes</h2>
        </div>
        <p className="text-sm text-muted-foreground">Pick a vibe, then tweak it to make it yours.</p>
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {THEME_PRESETS.map(p => (
            <ThemeCard key={p.id} preset={p} selected={s.themeId === p.id} onClick={() => applyPreset(p)} />
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-[--primary]" />
              <h2 className="font-display text-lg font-semibold">Animation</h2>
            </div>
            <p className="text-sm text-muted-foreground">Background mood.</p>
            <div className="space-y-2">
              {ANIMATIONS.map(a => {
                const active = s.animation === a.id;
                return (
                  <button
                    key={a.id}
                    onClick={() => update({ animation: a.id })}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition",
                      active
                        ? "border-[--primary]/60 bg-[--primary]/10"
                        : "border-border bg-card/40 hover:border-border/80 hover:bg-card/60"
                    )}
                  >
                    <div className={cn(
                      "grid h-9 w-9 shrink-0 place-items-center rounded-lg",
                      active ? "bg-gradient-to-br from-[--primary]/30 to-[--accent]/20 text-[--primary]" : "bg-muted text-muted-foreground"
                    )}>
                      <a.icon className="h-4 w-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{a.label}</p>
                      <p className="text-xs text-muted-foreground">{a.desc}</p>
                    </div>
                    {active && <Check className="h-4 w-4 shrink-0 text-[--primary]" />}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Monitor className="h-5 w-5 text-[--primary]" />
              <h2 className="font-display text-lg font-semibold">Preview</h2>
            </div>
            <p className="text-sm text-muted-foreground">What it looks like.</p>
            <ThemePreview s={s} />
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-5 w-5 text-[--primary]" />
          <h2 className="font-display text-lg font-semibold">Fine-tune</h2>
        </div>
        <p className="text-sm text-muted-foreground">Dial in the exact look you want.</p>
        <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
          <div className="grid gap-6 sm:grid-cols-2">
            <RangeSlider
              label="Primary Color" value={s.primaryHue} min={0} max={359} unit="°"
              trackStyle={rainbowTrack}
              onChange={v => update({ primaryHue: v, themeId: "custom" })}
            />
            <RangeSlider
              label="Accent Color" value={s.accentHue} min={0} max={359} unit="°"
              trackStyle={rainbowTrack}
              onChange={v => update({ accentHue: v, themeId: "custom" })}
            />
            <RangeSlider
              label="Saturation" value={s.saturation} min={0} max={100} unit="%"
              trackStyle={{ background: `linear-gradient(to right, hsl(${s.primaryHue},0%,55%), hsl(${s.primaryHue},80%,55%))` }}
              onChange={v => update({ saturation: v, themeId: "custom" })}
            />
            <RangeSlider
              label="Background" value={s.bgLightness} min={2} max={30} unit="%"
              trackStyle={{ background: "linear-gradient(to right, #000, #334)" }}
              onChange={v => update({ bgLightness: v, themeId: "custom" })}
            />
          </div>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Type className="h-5 w-5 text-[--primary]" />
          <h2 className="font-display text-lg font-semibold">Typography</h2>
        </div>
        <p className="text-sm text-muted-foreground">Choose your interface and monospace fonts, and the overall text size.</p>
        <div className="rounded-2xl border border-border bg-card/60 p-6 backdrop-blur space-y-6">
          <div className="space-y-2">
            <p className="text-sm font-medium">Interface font</p>
            <div className="flex flex-wrap gap-2">
              {INTERFACE_FONTS.map(f => (
                <button
                  key={f}
                  onClick={() => update({ interfaceFont: f })}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-sm transition",
                    s.interfaceFont === f
                      ? "border-[--primary] bg-[--primary]/15 text-foreground"
                      : "border-border bg-card/40 text-muted-foreground hover:border-border/80 hover:text-foreground"
                  )}
                  style={{ fontFamily: f === "system-ui" ? "system-ui" : f === "serif" ? "Georgia,serif" : `"${f}",sans-serif` }}
                >
                  {INTERFACE_FONT_LABELS[f] ?? f}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">Monospace font</p>
            <div className="flex flex-wrap gap-2">
              {MONO_FONTS.map(f => (
                <button
                  key={f}
                  onClick={() => update({ monoFont: f })}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-sm transition",
                    s.monoFont === f
                      ? "border-[--primary] bg-[--primary]/15 text-foreground"
                      : "border-border bg-card/40 text-muted-foreground hover:border-border/80 hover:text-foreground"
                  )}
                  style={{ fontFamily: f === "monospace" ? "monospace" : `"${f}",monospace` }}
                >
                  {MONO_FONT_LABELS[f] ?? f}
                </button>
              ))}
            </div>
          </div>

          <RangeSlider
            label="Text size" value={s.textSize} min={75} max={130} unit="%"
            onChange={v => update({ textSize: v })}
          />
        </div>
      </section>
    </>
  );
}
