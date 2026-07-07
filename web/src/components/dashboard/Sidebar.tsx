import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { LayoutDashboard, Users, Inbox, Bot, ShieldCheck, Settings, Lock, ChevronRight, LogOut, Menu, X } from "lucide-react";
import { clearAuthToken } from "@/lib/auth";
import type { Tab } from "./context";

export function Sidebar({ tab, setTab }: { tab: Tab; setTab: (t: Tab) => void }) {
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);

  const items: { id: Tab; label: string; icon: typeof LayoutDashboard }[] = [
    { id: "overview", label: "Overview", icon: LayoutDashboard },
    { id: "accounts", label: "Accounts", icon: Users },
    { id: "emails",   label: "Emails",   icon: Inbox },
    { id: "secure", label: "Secure", icon: ShieldCheck },
    { id: "bot",      label: "Bot Config", icon: Bot },
    { id: "settings", label: "Settings", icon: Settings },
  ];

  const select = (id: Tab) => {
    setTab(id);
    setMobileOpen(false);
  };

  const signOut = () => {
    clearAuthToken();
    navigate({ to: "/" });
  };

  const navBody = (
    <>
      <div className="flex h-16 items-center gap-2 px-6">
        <span className="grid h-8 w-8 place-items-center rounded-md bg-gradient-to-br from-[--primary] to-[--accent] text-primary-foreground">
          <Lock className="h-4 w-4" />
        </span>
        <span className="font-display text-lg font-bold tracking-tight">
          Autosecure
        </span>
      </div>

      <nav className="mt-4 flex-1 space-y-1 px-3">
        {items.map((item) => {
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => select(item.id)}
              className={`group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                active
                  ? "bg-gradient-to-r from-[--primary]/85 to-[--accent]/75 text-foreground shadow-sm border border-[--primary]/30"
                  : "text-muted-foreground hover:bg-card/85 hover:text-foreground"
              }`}
            >
              <item.icon className={`h-4 w-4 ${active ? "text-[--primary]" : ""}`} />
              {item.label}
              {active && <ChevronRight className="ml-auto h-4 w-4 text-[--primary]" />}
            </button>
          );
        })}
      </nav>

      <div className="border-t border-border p-3">
        <button
          onClick={signOut}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition hover:bg-card/60 hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </div>
    </>
  );

  return (
    <>
      <button
        onClick={() => setMobileOpen(true)}
        aria-label="Open menu"
        className="fixed left-3 top-3 z-30 grid h-10 w-10 place-items-center rounded-lg border border-border bg-card/80 text-muted-foreground backdrop-blur transition hover:text-foreground md:hidden"
      >
        <Menu className="h-5 w-5" />
      </button>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border bg-card/95 backdrop-blur transition-transform duration-200 md:sticky md:top-0 md:z-auto md:h-screen md:translate-x-0 md:bg-card/40 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <button
          onClick={() => setMobileOpen(false)}
          aria-label="Close menu"
          className="absolute right-3 top-4 grid h-8 w-8 place-items-center rounded-lg text-muted-foreground transition hover:text-foreground md:hidden"
        >
          <X className="h-4 w-4" />
        </button>
        {navBody}
      </aside>
    </>
  );
}
