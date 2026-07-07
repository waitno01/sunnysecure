import { createContext, useContext } from "react";
import { getAuthToken } from "@/lib/auth";

export type Notification = { id: number; title: string; description?: string; time: number };

export type Tab = "overview" | "accounts" | "secure" | "emails" | "bot" | "settings";

export const NotificationContext = createContext<{
  notifications: Notification[];
  addNotification: (title: string, description?: string) => void;
  clearNotifications: () => void;
}>({ notifications: [], addNotification: () => {}, clearNotifications: () => {} });

export function useNotifications() {
  return useContext(NotificationContext);
}

export function authHeaders(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
