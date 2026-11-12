import { useEffect, useState, type FormEvent } from "react";
import { Plus, ShieldCheck } from "lucide-react";
import { PERMISSIONS } from "@tpmsc/protocol";
import { api } from "@/lib/api";
import type { AdminRole } from "@/lib/types";
import { useAppStore } from "@/lib/store";
import { Badge, Button, Field, Panel, SectionTitle } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/lib/cn";

const PERMISSION_HINT: Record<string, string> = {
  "record:read": "查看下发记录",
  "record:write": "上传并生成下发记录",
  "record:delete": "删除下发记录",
  "cert:deliver": "执行证书下发",
  "user:read": "查看用户",
  "user:write": "创建与修改用户",
  "role:write": "管理角色与权限",
  "audit:read": "查看审计日志",
  "policy:write": "修改站点策略",
  "apiclient:write": "管理投递客户端",
};

export function RolesPage() {
  const [roles, setRoles] = useState<AdminRole[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", permissions: [] as string[] });
  const [error, setError] = useState<string | null>(null);
  const can = useAppStore((state) => state.can);
  const demo = useAppStore((state) => state.demo);
  const pushToast = useAppStore((state) => state.pushToast);

  useEffect(() => {
    void api
      .roles()
      .then((result) => setRoles(result.roles))
      .catch((err) => console.error("roles load failed", err));
  }, []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (demo) {
      setRoles((current) => [
        ...(current ?? []),
        {
          id: `rol_${Date.now()}`,
          name: form.name,
          description: form.description,
          builtin: 0,
          permissions: form.permissions,
        },
      ]);
      close();
      pushToast({ kind: "ok", title: `已创建角色 ${form.name}` });
      return;
    }
    api
      .createRole(form)
      .then(() => {
        pushToast({ kind: "ok", title: `已创建角色 ${form.name}` });
        close();
        return api.roles().then((result) => setRoles(result.roles));
      })
      .catch((err: Error) => setError(err.message));
  };

  const close = () => {
    setCreating(false);
    setForm({ name: "", description: "", permissions: [] });
    setError(null);
  };

  const togglePermission = (permission: string) => {
    setForm((current) => ({
      ...current,
      permissions: current.permissions.includes(permission)
        ? current.permissions.filter((item) => item !== permission)
        : [...current.permissions, permission],
    }));
  };

  if (!roles) return <div className="py-16 text-center text-[12.5px] text-ink-2">正在读取角色与权限…</div>;

  return (
    <div className="grid gap-5">
      <Panel className="p-0">
        <div className="flex items-center justify-between border-b border-line/70 px-4 py-3">
          <div>
            <p className="label-caps">角色</p>
            <p className="mono-num text-[13px] text-ink-1">{roles.length} 个角色</p>
          </div>
          <Button
            size="sm"
            variant="primary"
            disabled={!can("role:write")}
            onClick={() => setCreating(true)}
            icon={<Plus className="h-3.5 w-3.5" />}
          >
            新建角色
          </Button>
        </div>

        <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          {roles.map((role) => (
            <div key={role.id} className="rounded-control border border-line/70 bg-graphite-0/30 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[12.5px] text-ink-0">{role.name}</span>
                <Badge tone={role.builtin ? "muted" : "info"}>{role.builtin ? "内置" : "自定义"}</Badge>
              </div>
              <p className="mt-1 min-h-[18px] text-[11.5px] text-ink-3">{role.description ?? "—"}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {role.permissions.map((permission) => (
                  <span
                    key={permission}
                    title={PERMISSION_HINT[permission]}
                    className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-ink-2"
                  >
                    {permission}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel>
        <SectionTitle
          title="权限码说明"
          hint="权限码同时用于 Worker 中间件与前端菜单门控，新增权限需同步 migrations"
          action={<ShieldCheck className="h-4 w-4 text-teal" />}
        />
        <div className="grid gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-2">
          {PERMISSIONS.map((permission) => (
            <div key={permission} className="flex items-center justify-between gap-3 bg-graphite-1 px-3 py-2">
              <span className="font-mono text-[11px] text-ink-1">{permission}</span>
              <span className="text-[11px] text-ink-3">{PERMISSION_HINT[permission]}</span>
            </div>
          ))}
        </div>
      </Panel>

      <Modal
        open={creating}
        title="新建角色"
        description="自定义角色可以组合任意权限码；内置角色不可修改。"
        onClose={close}
        footer={
          <>
            <Button size="sm" onClick={close}>
              取消
            </Button>
            <Button size="sm" variant="primary" type="submit" form="create-role">
              创建
            </Button>
          </>
        }
      >
        <form id="create-role" className="grid gap-4" onSubmit={submit}>
          <Field
            label="角色名"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            placeholder="小写字母开头，例如 cert_operator"
            required
          />
          <Field
            label="说明"
            value={form.description}
            onChange={(event) => setForm({ ...form, description: event.target.value })}
            placeholder="例如：只负责证书下发，不看用户与审计"
          />
          <fieldset className="grid gap-2">
            <legend className="label-caps mb-1">权限</legend>
            <div className="grid gap-1 sm:grid-cols-2">
              {PERMISSIONS.map((permission) => {
                const active = form.permissions.includes(permission);
                return (
                  <button
                    key={permission}
                    type="button"
                    aria-pressed={active}
                    onClick={() => togglePermission(permission)}
                    className={cn(
                      "flex items-center gap-2 rounded-control border px-2.5 py-2 text-left transition",
                      active
                        ? "border-copper-400/60 bg-copper-400/10"
                        : "border-line hover:border-line/80",
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn(
                        "h-3.5 w-3.5 rounded-sm border",
                        active ? "border-copper-400 bg-copper-400" : "border-line",
                      )}
                    />
                    <span className="min-w-0">
                      <span className="block font-mono text-[11px] text-ink-1">{permission}</span>
                      <span className="block text-[10.5px] text-ink-3">{PERMISSION_HINT[permission]}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </fieldset>
          {error ? (
            <p role="alert" className="rounded-control border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
              {error}
            </p>
          ) : null}
        </form>
      </Modal>
    </div>
  );
}
