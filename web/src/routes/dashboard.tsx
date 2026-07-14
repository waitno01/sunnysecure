import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState, useCallback, useRef } from "react";
import { useAuth } from "@/lib/auth";
import { NotificationContext, type Tab, type Notification } from "@/components/dashboard/context";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { Topbar } from "@/components/dashboard/Topbar";
import { Overview } from "@/components/dashboard/Overview";
import { Accounts } from "@/components/dashboard/Accounts";
import { AutobuyAccounts } from "@/components/dashboard/AutobuyAccounts";
import { EmailsPanel } from "@/components/dashboard/EmailsPanel";
import { Secure } from "@/components/dashboard/Secure";
import { SettingsPanel } from "@/components/dashboard/SettingsPanel";
import { BotConfigPanel } from "@/components/dashboard/BotConfigPanel";

export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      { title: "Dashboard" },
      { name: "description", content: "Manage your secured accounts." },
    ],
  }),
  component: DashboardPage,
});

function DashboardPage() {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("overview");
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const notifId = useRef(0);

  const addNotification = useCallback((title: string, description?: string) => {
    const id = ++notifId.current;
    setNotifications(prev => [{ id, title, description, time: Date.now() }, ...prev].slice(0, 50));
  }, []);

  const clearNotifications = useCallback(() => setNotifications([]), []);

  if (isAuthenticated === false) {
    navigate({ to: "/" });
    return null;
  }

  if (isAuthenticated === null) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[--primary] border-t-transparent" />
      </div>
    );
  }

  return (
    <NotificationContext.Provider value={{ notifications, addNotification, clearNotifications }}>
      <div className="relative min-h-screen">
        <div className="pointer-events-none absolute inset-0 grid-bg" aria-hidden />
        <div className="relative flex min-h-screen">
          <Sidebar tab={tab} setTab={setTab} />
          <div className="flex min-w-0 flex-1 flex-col">
            <Topbar />
            <main className="flex-1 overflow-y-auto p-6 lg:p-8 flex flex-col animate-in fade-in duration-300">
              {tab === "overview" && <Overview />}
              {tab === "accounts" && <Accounts />}
              {tab === "accounts-autobuy" && <AutobuyAccounts />}
              {tab === "emails" && <EmailsPanel />}
              {tab === "bot" && <BotConfigPanel />}
              {tab === "secure" && <Secure />}
              {tab === "settings" && <SettingsPanel />}
            </main>
          </div>
        </div>
      </div>
    </NotificationContext.Provider>
  );
}
