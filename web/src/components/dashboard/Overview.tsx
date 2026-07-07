import { useState, useEffect } from "react";
import { Users, ShieldCheck, Link2, Activity, BarChart2, X, Trophy, Calendar, Zap, TrendingUp } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { authHeaders } from "./context";

type DetailedStats = {
  best_day: string | null;
  best_day_count: number;
  best_month: string | null;
  best_month_count: number;
  daily_avg: number;
  days_active: number;
};

function StatsModal({ onClose }: { onClose: () => void }) {
  const [ds, setDs] = useState<DetailedStats | null>(null);

  useEffect(() => {
    fetch("/api/detailed-stats", { headers: authHeaders() })
      .then(r => r.json())
      .then(setDs);
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm" onClick={onClose}>
      <div className="relative w-full max-w-lg rounded-2xl border border-border bg-card/95 p-6 shadow-2xl backdrop-blur" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart2 className="h-5 w-5 text-[--primary]" />
            <h2 className="font-display text-lg font-semibold">Statistics Overview</h2>
          </div>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-border bg-background/60 p-4">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-yellow-500">
              <Trophy className="h-3.5 w-3.5" /> Best Day
            </div>
            <p className="mt-2 font-display text-2xl font-bold">{ds?.best_day ?? "N/A"}</p>
            <p className="mt-1 text-xs text-muted-foreground">{ds?.best_day ? `${ds.best_day_count} secures` : "No data yet"}</p>
          </div>

          <div className="rounded-xl border border-border bg-background/60 p-4">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-pink-500">
              <Calendar className="h-3.5 w-3.5" /> Best Month
            </div>
            <p className="mt-2 font-display text-2xl font-bold">{ds?.best_month ?? "N/A"}</p>
            <p className="mt-1 text-xs text-muted-foreground">{ds?.best_month ? `${ds.best_month_count} secures` : "No data yet"}</p>
          </div>

          <div className="rounded-xl border border-border bg-background/60 p-4">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-[--accent]">
              <Zap className="h-3.5 w-3.5" /> Daily Avg
            </div>
            <p className="mt-2 font-display text-2xl font-bold">{ds?.daily_avg ?? 0}</p>
            <p className="mt-1 text-xs text-muted-foreground">{ds?.days_active ?? 0} accounts / day</p>
          </div>

          <div className="rounded-xl border border-border bg-background/60 p-4">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-[--primary]">
              <TrendingUp className="h-3.5 w-3.5" /> Days Active
            </div>
            <p className="mt-2 font-display text-2xl font-bold">{ds?.days_active ?? 0}</p>
            <p className="mt-1 text-xs text-muted-foreground">days with at least 1 hit</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function SecureHistoryChart({ data }: { data: { day: string; secures: number }[] }) {
  const [primary, setPrimary] = useState("#888");
  const [borderColor, setBorderColor] = useState("#333");
  useEffect(() => {
    const el = document.createElement("div");
    el.style.cssText = "position:fixed;left:-999px;top:-999px;width:1px;height:1px;";
    el.style.background = "var(--primary)";
    el.style.borderColor = "var(--border)";
    document.body.appendChild(el);
    const bg = getComputedStyle(el).backgroundColor;
    const bc = getComputedStyle(el).borderColor;
    document.body.removeChild(el);
    if (bg) setPrimary(bg);
    if (bc) setBorderColor(bc);
  }, [data]);

    if (!data || data.length === 0) {
    return (
      <div className="flex h-full flex-col rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-display text-lg font-semibold">Secure History</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">Secures over the last 7 days</p>
          </div>
        </div>
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
          <Activity className="h-8 w-8 opacity-40" />
          <p>No data yet, secure your first account.</p>
      </div>
    </div>
  );
}

  return (
    <div className="flex h-full flex-col rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-lg font-semibold">Secure History</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">Secures over the last 7 days</p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background/40 px-3 py-1 text-xs font-medium text-muted-foreground">
          <Activity className="h-3 w-3 text-[--accent]" />
          Live
        </span>
      </div>
      <div className="mt-6 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 4, left: 8, bottom: 0 }}>
            <defs>
              <linearGradient id="securesFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={primary} stopOpacity={0.4} />
                <stop offset="100%" stopColor={primary} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={borderColor} vertical={false} />
            <XAxis dataKey="day" stroke="var(--muted-foreground)" fontSize={12} tickLine={false} axisLine={false} />
            <YAxis stroke="var(--muted-foreground)" fontSize={12} tickLine={false} axisLine={false} width={40} allowDecimals={false} />
            <Tooltip
              contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: "0.75rem", fontSize: "0.875rem", color: "var(--foreground)" }}
              labelStyle={{ color: "var(--muted-foreground)" }}
            />
            <Area type="monotone" dataKey="secures" stroke={primary} strokeWidth={2} fill="url(#securesFill)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function RecentSecures({ items }: { items: { ms_email: string; mc_name: string; secured_at: string }[] }) {
  return (
    <div className="flex h-full flex-col rounded-2xl border border-border bg-card/60 p-6 backdrop-blur">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg font-semibold">Recent Secures</h2>
      </div>
      {items.length === 0 ? (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-muted-foreground">No accounts secured yet.</p>
        </div>
      ) : (
        <ul className="mt-4 flex-1 space-y-1">
          {items.map((s, i) => (
            <li key={i} className="animate-in fade-in slide-in-from-right-2 duration-400 flex items-center gap-3 rounded-lg px-2 py-2.5 transition hover:bg-background/40" style={{ animationDelay: `${i * 60}ms` }}>
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-muted-foreground">
                {(s.ms_email || "?")[0].toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{s.ms_email}</p>
                <p className="text-xs text-muted-foreground">{s.mc_name}</p>
              </div>
              <span className="shrink-0 rounded-full bg-[--accent]/10 px-2.5 py-0.5 text-xs font-medium text-[--accent]">
                Secured
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Overview() {
  const [stats, setStats] = useState({ total: 0, has_minecraft: 0, shared_links: 0 });
  const [chartData, setChartData] = useState<{ day: string; secures: number }[]>([]);
  const [recent, setRecent] = useState<{ ms_email: string; mc_name: string; secured_at: string }[]>([]);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    fetch("/api/stats", { headers: authHeaders() })
      .then(r => r.json())
      .then(setStats);
    fetch("/api/chart", { headers: authHeaders() })
      .then(r => r.json())
      .then(setChartData);
    fetch("/api/accounts", { headers: authHeaders() })
      .then(r => r.json())
      .then((rows: { ms_email: string; mc_name: string; secured_at: string }[]) => setRecent(rows.slice(0, 5)));
  }, []);

  const statCards = [
    { label: "Total Secured", value: String(stats.total), icon: Users, accent: false },
    { label: "Has Minecraft", value: String(stats.has_minecraft), icon: ShieldCheck, accent: true },
    { label: "Shared Links", value: String(stats.shared_links ?? 0), icon: Link2, accent: false },
  ];

  return (
    <div className="flex flex-1 flex-col space-y-6">
      {showModal && <StatsModal onClose={() => setShowModal(false)} />}

      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-3xl">Overview</h1>
        <p className="mt-1 text-sm text-muted-foreground">Your account security at a glance.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {statCards.map((s, i) => (
          <button
            key={s.label}
            onClick={() => setShowModal(true)}
            className="animate-in fade-in slide-in-from-bottom-4 duration-500 relative overflow-hidden rounded-2xl border border-border bg-card/60 p-5 backdrop-blur text-left transition hover:border-[--primary]/40 hover:bg-card/80"
            style={{ animationDelay: `${i * 80}ms` }}
          >
            <div className="flex items-start justify-between">
              <div className={`grid h-10 w-10 place-items-center rounded-lg ${s.accent ? "bg-gradient-to-br from-[--primary] to-[--accent] text-primary-foreground shadow-[var(--shadow-glow)]" : "bg-muted text-muted-foreground"}`}>
                <s.icon className="h-5 w-5" />
              </div>
            </div>
            <p className="mt-4 font-display text-2xl font-bold">{s.value}</p>
            <p className="mt-1 text-sm text-muted-foreground">{s.label}</p>
          </button>
        ))}
      </div>

      <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-[1.6fr_1fr] animate-in fade-in duration-500 delay-200">
        <SecureHistoryChart data={chartData} />
        <RecentSecures items={recent} />
      </div>
    </div>
  );
}
