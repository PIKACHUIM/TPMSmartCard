import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { StatusBar } from "./StatusBar";
import { CommandPalette } from "./CommandPalette";
import { Toasts } from "@/components/ui/Toasts";

/**
 * 三栏骨架：72px 图标导航 → 页面内容 → 28px 状态栏。
 * 页面自身负责「列表 + 详情」的第二栏，导航与状态栏保持全局一致。
 */
export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((value) => !value);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="min-h-screen">
      <Sidebar />
      <TopBar onOpenPalette={() => setPaletteOpen(true)} />
      <main className="min-h-screen pb-7 pl-[72px] pt-14">
        <div className="mx-auto w-full max-w-[1440px] px-6 py-6">
          <Outlet />
        </div>
      </main>
      <StatusBar />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <Toasts />
    </div>
  );
}
