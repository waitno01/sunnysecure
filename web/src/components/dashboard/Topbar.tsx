import { useState, useEffect, useRef } from "react";
import { Bell } from "lucide-react";
import { useNotifications } from "./context";

function formatRelativeTime(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function Topbar() {
  const [open, setOpen] = useState(false);
  const { notifications, clearNotifications } = useNotifications();
  const ref = useRef<HTMLDivElement>(null);
  const lastReadCount = useRef(0);
  const unread = Math.max(0, notifications.length - lastReadCount.current);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center justify-end gap-4 border-b border-border bg-background/80 px-6 backdrop-blur lg:px-8">
      <div className="flex items-center gap-3">
        <div ref={ref} className="relative">
          <button
            onClick={() => {
              setOpen(!open);
              if (!open) lastReadCount.current = notifications.length;
            }}
            className="relative grid h-9 w-9 place-items-center rounded-lg border border-border bg-card/60 text-muted-foreground transition hover:text-foreground"
          >
            <Bell className="h-4 w-4" />
            {unread > 0 && (
              <span className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                {unread > 99 ? "99+" : unread}
              </span>
            )}
          </button>
          {open && (
            <div className="absolute right-0 top-full mt-2 w-80 rounded-xl border border-border bg-card shadow-2xl animate-in fade-in zoom-in-95 duration-200 origin-top-right">
              <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Notifications</span>
                {notifications.length > 0 && (
                  <button
                    onClick={clearNotifications}
                    className="text-xs text-muted-foreground underline-offset-2 hover:underline hover:text-foreground transition"
                  >
                    Clear all
                  </button>
                )}
              </div>
              <div className="max-h-80 overflow-y-auto">
                {notifications.length === 0 ? (
                  <div className="px-4 py-8 text-center text-xs text-muted-foreground">No notifications yet</div>
                ) : (
                  notifications.map(n => (
                    <div key={n.id} className="border-l-2 border-l-[--primary]/40 border-b border-border/50 px-4 py-3 last:border-b-0 bg-[--primary]/[0.02] hover:bg-[--primary]/[0.04] transition-colors">
                      <div className="text-sm font-medium">{n.title}</div>
                      {n.description && <div className="mt-0.5 text-xs text-muted-foreground">{n.description}</div>}
                      <div className="mt-1 text-[10px] text-muted-foreground/60">{formatRelativeTime(n.time)}</div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
