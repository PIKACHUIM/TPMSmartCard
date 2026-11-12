import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactElement } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { useAppStore } from "@/lib/store";
import { LoginPage } from "@/features/auth/LoginPage";
import { OverviewPage } from "@/features/overview/OverviewPage";
import { CardsPage } from "@/features/cards/CardsPage";
import { CertsPage } from "@/features/certs/CertsPage";
import { BackupPage } from "@/features/backup/BackupPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { RecordsPage } from "@/features/admin/RecordsPage";
import { UsersPage } from "@/features/admin/UsersPage";
import { RolesPage } from "@/features/admin/RolesPage";
import { AuditPage } from "@/features/admin/AuditPage";

/** 管理台页面需要登录；设备页（卡片/证书/备份）由本地后端鉴权，不强制登录 */
function RequireAuth({ children }: { children: ReactElement }) {
  const user = useAppStore((state) => state.user);
  const location = useLocation();
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="cards" element={<CardsPage />} />
        <Route path="certs" element={<CertsPage />} />
        <Route path="backup" element={<BackupPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route
          path="admin/records"
          element={
            <RequireAuth>
              <RecordsPage />
            </RequireAuth>
          }
        />
        <Route
          path="admin/users"
          element={
            <RequireAuth>
              <UsersPage />
            </RequireAuth>
          }
        />
        <Route
          path="admin/roles"
          element={
            <RequireAuth>
              <RolesPage />
            </RequireAuth>
          }
        />
        <Route
          path="admin/audit"
          element={
            <RequireAuth>
              <AuditPage />
            </RequireAuth>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
