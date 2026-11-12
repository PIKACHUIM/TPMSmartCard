import { create } from "zustand";

export type ToastKind = "ok" | "err" | "info";

export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  detail?: string;
}

export interface SessionUser {
  id: string;
  username: string;
  displayName: string | null;
  roles: string[];
  permissions: string[];
  mustChangePassword: boolean;
}

interface AppState {
  token: string | null;
  user: SessionUser | null;
  online: boolean;
  demo: boolean;
  theme: "dark" | "light";
  toasts: Toast[];
  setSession: (token: string, user: SessionUser) => void;
  clearSession: () => void;
  enterDemo: () => void;
  setOnline: (online: boolean) => void;
  setDemo: (demo: boolean) => void;
  toggleTheme: () => void;
  pushToast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: number) => void;
  can: (permission: string) => boolean;
}

const storedToken = sessionStorage.getItem("tpmsc.token");
const storedUser = sessionStorage.getItem("tpmsc.user");
const storedTheme = (localStorage.getItem("tpmsc.theme") as "dark" | "light" | null) ?? "dark";

function applyTheme(theme: "dark" | "light") {
  const root = document.documentElement;
  root.classList.toggle("light", theme === "light");
  root.classList.toggle("dark", theme === "dark");
}

applyTheme(storedTheme);

let toastSeq = 1;

export const useAppStore = create<AppState>((set, get) => ({
  token: storedToken,
  user: storedUser ? (JSON.parse(storedUser) as SessionUser) : null,
  online: false,
  demo: false,
  theme: storedTheme,
  toasts: [],

  setSession: (token, user) => {
    sessionStorage.setItem("tpmsc.token", token);
    sessionStorage.setItem("tpmsc.user", JSON.stringify(user));
    set({ token, user, online: true, demo: false });
  },

  clearSession: () => {
    sessionStorage.removeItem("tpmsc.token");
    sessionStorage.removeItem("tpmsc.user");
    set({ token: null, user: null });
  },

  enterDemo: () => {
    const demoUser: SessionUser = {
      id: "demo",
      username: "demo.admin",
      displayName: "演示管理员",
      roles: ["super_admin"],
      permissions: [
        "record:read",
        "record:write",
        "record:delete",
        "cert:deliver",
        "user:read",
        "user:write",
        "role:write",
        "audit:read",
        "policy:write",
        "apiclient:write",
      ],
      mustChangePassword: false,
    };
    sessionStorage.setItem("tpmsc.token", "demo-token");
    sessionStorage.setItem("tpmsc.user", JSON.stringify(demoUser));
    set({ token: "demo-token", user: demoUser, demo: true, online: false });
  },

  setOnline: (online) => set({ online }),
  setDemo: (demo) => set({ demo }),

  toggleTheme: () => {
    const next = get().theme === "dark" ? "light" : "dark";
    localStorage.setItem("tpmsc.theme", next);
    applyTheme(next);
    set({ theme: next });
  },

  pushToast: (toast) => {
    const id = toastSeq++;
    set({ toasts: [...get().toasts, { ...toast, id }] });
    window.setTimeout(() => {
      set({ toasts: get().toasts.filter((item) => item.id !== id) });
    }, 4200);
  },

  dismissToast: (id) => set({ toasts: get().toasts.filter((item) => item.id !== id) }),

  can: (permission) => {
    const user = get().user;
    if (!user) return false;
    if (get().demo) return true;
    return user.permissions.includes(permission);
  },
}));
