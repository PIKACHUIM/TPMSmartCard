import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Fingerprint, ShieldHalf } from "lucide-react";
import { useAppStore } from "@/lib/store";
import { cn } from "@/lib/cn";
import { NAV_ITEMS } from "./nav";

export function Sidebar() {
  const { t } = useTranslation();
  const can = useAppStore((state) => state.can);
  const demo = useAppStore((state) => state.demo);
  const user = useAppStore((state) => state.user);

  const items = NAV_ITEMS.filter((item) => !item.permission || can(item.permission));

  return (
    <aside className="fixed left-0 top-0 z-30 flex h-full w-[72px] flex-col items-center border-r border-line/70 bg-graphite-0/92 backdrop-blur">
      <NavLink
        to="/"
        aria-label="TPMSmartCard 首页"
        className="flex h-14 w-full items-center justify-center border-b border-line/70"
      >
        <span className="relative flex h-8 w-8 items-center justify-center rounded-md border border-copper-400/50 bg-copper-400/10">
          <ShieldHalf className="h-4 w-4 text-copper-300" />
        </span>
      </NavLink>

      <nav className="flex w-full flex-1 flex-col items-center gap-1 py-3" aria-label="主导航">
        {items.map((item) => {
          const Icon = item.icon;
          const label = t(item.labelKey, { defaultValue: item.fallback });
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              title={label}
              aria-label={label}
              className={({ isActive }) =>
                cn(
                  "group relative flex h-11 w-11 items-center justify-center rounded-control transition-colors duration-150 ease-precise",
                  isActive
                    ? "bg-graphite-2 text-copper-300"
                    : "text-ink-2 hover:bg-graphite-1 hover:text-ink-0",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    aria-hidden
                    className={cn(
                      "absolute left-0 top-2 h-7 w-[2px] rounded-full bg-copper-400 transition-opacity",
                      isActive ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <Icon className="h-[18px] w-[18px]" strokeWidth={1.6} />
                  <span className="pointer-events-none absolute left-[52px] z-40 hidden whitespace-nowrap rounded border border-line bg-graphite-1 px-2 py-1 text-[11.5px] text-ink-1 shadow-lift group-hover:block">
                    {label}
                  </span>
                </>
              )}
            </NavLink>
          );
        })}
      </nav>

      <div className="mb-3 flex flex-col items-center gap-2">
        {demo ? (
          <span
            title="演示数据"
            className="flex h-7 w-7 items-center justify-center rounded-full border border-amber/40 bg-amber/10 text-[10px] font-semibold text-amber"
          >
            D
          </span>
        ) : null}
        <span
          title={user?.displayName ?? user?.username ?? "未登录"}
          className="flex h-8 w-8 items-center justify-center rounded-full border border-line bg-graphite-2 text-[11px] text-ink-1"
        >
          {user ? (user.displayName ?? user.username).slice(0, 1).toUpperCase() : <Fingerprint className="h-4 w-4" />}
        </span>
      </div>
    </aside>
  );
}
