import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LogIn, LogOut, Moon, Search, Sun } from "lucide-react";
import { useAppStore } from "@/lib/store";
import { LANGUAGES, setLanguage, type LanguageCode } from "@/lib/i18n";
import { api } from "@/lib/api";
import { Button, Kbd } from "@/components/ui/primitives";
import { PAGE_TITLES } from "./nav";

export function TopBar({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const theme = useAppStore((state) => state.theme);
  const toggleTheme = useAppStore((state) => state.toggleTheme);
  const user = useAppStore((state) => state.user);
  const clearSession = useAppStore((state) => state.clearSession);
  const pushToast = useAppStore((state) => state.pushToast);

  const page = PAGE_TITLES[location.pathname] ?? { title: "TPMSmartCard", hint: "" };

  const signOut = () => {
    void api.logout().finally(() => {
      clearSession();
      pushToast({ kind: "info", title: "已退出登录" });
      navigate("/login");
    });
  };

  return (
    <header className="fixed left-[72px] right-0 top-0 z-20 flex h-14 items-center gap-4 border-b border-line/70 bg-graphite-0/85 px-5 backdrop-blur">
      <div className="min-w-0">
        <h1 className="truncate text-[15px] font-medium text-ink-0">{page.title}</h1>
        {page.hint ? <p className="truncate text-[11.5px] text-ink-3">{page.hint}</p> : null}
      </div>

      <button
        type="button"
        onClick={onOpenPalette}
        className="ml-auto flex h-9 w-[min(320px,32vw)] items-center gap-2 rounded-control border border-line bg-graphite-1/70 px-3 text-left text-[12.5px] text-ink-3 transition hover:border-copper-400/40 hover:text-ink-2"
      >
        <Search className="h-3.5 w-3.5" />
        <span className="flex-1 truncate">{t("common.search")}…</span>
        <Kbd>Ctrl K</Kbd>
      </button>

      <Button
        variant="ghost"
        size="sm"
        aria-label="切换主题"
        onClick={toggleTheme}
        icon={theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      />

      <label className="sr-only" htmlFor="lang-select">
        界面语言
      </label>
      <select
        id="lang-select"
        value={i18n.language}
        onChange={(event) => setLanguage(event.target.value as LanguageCode)}
        className="h-8 rounded-control border border-line bg-graphite-1 px-2 text-[12px] text-ink-1 focus:border-copper-400 focus:outline-none"
      >
        {LANGUAGES.map((language) => (
          <option key={language.code} value={language.code}>
            {language.label}
          </option>
        ))}
      </select>

      {user ? (
        <div className="flex items-center gap-2 border-l border-line/70 pl-3">
          <div className="hidden text-right sm:block">
            <p className="text-[12.5px] leading-tight text-ink-0">{user.displayName ?? user.username}</p>
            <p className="font-mono text-[10.5px] leading-tight text-ink-3">{user.roles.join(" · ")}</p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            aria-label={t("common.logout")}
            onClick={signOut}
            icon={<LogOut className="h-4 w-4" />}
          />
        </div>
      ) : (
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate("/login")}
          icon={<LogIn className="h-3.5 w-3.5" />}
        >
          登录
        </Button>
      )}
    </header>
  );
}
