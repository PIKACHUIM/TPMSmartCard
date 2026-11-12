import { useEffect, useState, type FormEvent } from "react";
import { Plus, ShieldCheck, UserCog } from "lucide-react";
import { api } from "@/lib/api";
import type { AdminRole, AdminUser } from "@/lib/types";
import { useAppStore } from "@/lib/store";
import { Badge, Button, Field, Panel } from "@/components/ui/primitives";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Modal } from "@/components/ui/Modal";

export function UsersPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [roles, setRoles] = useState<AdminRole[]>([]);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ username: "", password: "", display_name: "", roles: ["operator"] });
  const [error, setError] = useState<string | null>(null);
  const can = useAppStore((state) => state.can);
  const pushToast = useAppStore((state) => state.pushToast);
  const demo = useAppStore((state) => state.demo);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([api.users(), api.roles()])
      .then(([userResult, roleResult]) => {
        if (cancelled) return;
        setUsers(userResult.users);
        setRoles(roleResult.roles);
      })
      .catch((err) => console.error("users load failed", err));
    return () => {
      cancelled = true;
    };
  }, []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (demo) {
      const next: AdminUser = {
        id: `usr_demo_${Date.now()}`,
        username: form.username,
        display_name: form.display_name || form.username,
        email: null,
        roles: form.roles,
        status: "active",
        must_change_password: 1,
        created_at: new Date().toISOString(),
        last_login_at: null,
      };
      setUsers((current) => (current ? [...current, next] : [next]));
      setCreating(false);
      setForm({ username: "", password: "", display_name: "", roles: ["operator"] });
      pushToast({ kind: "ok", title: `已创建用户 ${next.username}`, detail: "演示模式：首次登录需修改口令" });
      return;
    }
    api
      .createUser(form)
      .then(() => {
        pushToast({ kind: "ok", title: `已创建用户 ${form.username}` });
        setCreating(false);
        setForm({ username: "", password: "", display_name: "", roles: ["operator"] });
        return api.users().then((result) => setUsers(result.users));
      })
      .catch((err: Error) => setError(err.message));
  };

  const toggleStatus = (user: AdminUser) => {
    const nextStatus = user.status === "active" ? "disabled" : "active";
    if (demo) {
      setUsers((current) =>
        (current ?? []).map((item) => (item.id === user.id ? { ...item, status: nextStatus } : item)),
      );
      pushToast({ kind: "info", title: `${user.username} 已${nextStatus === "active" ? "启用" : "停用"}` });
      return;
    }
    api
      .updateUser(user.id, { status: nextStatus })
      .then(() => {
        setUsers((current) =>
          (current ?? []).map((item) => (item.id === user.id ? { ...item, status: nextStatus } : item)),
        );
        pushToast({ kind: "ok", title: "状态已更新", detail: "该用户的会话已被吊销，需要重新登录" });
      })
      .catch((err: Error) => pushToast({ kind: "err", title: "更新失败", detail: err.message }));
  };

  if (!users) return <div className="py-16 text-center text-[12.5px] text-ink-2">正在读取用户与角色…</div>;

  const columns: Column<AdminUser>[] = [
    {
      key: "user",
      header: "用户",
      render: (row) => (
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-line bg-graphite-2 text-[11px] text-ink-1">
            {(row.display_name ?? row.username).slice(0, 1).toUpperCase()}
          </span>
          <div className="min-w-0">
            <p className="truncate text-[13px] text-ink-0">{row.display_name ?? row.username}</p>
            <p className="truncate font-mono text-[10.5px] text-ink-3">{row.username}</p>
          </div>
        </div>
      ),
    },
    {
      key: "roles",
      header: "角色",
      width: "200px",
      render: (row) => (
        <div className="flex flex-wrap gap-1">
          {row.roles.map((role) => (
            <Badge key={role} tone={role === "super_admin" ? "warn" : "muted"}>
              {role}
            </Badge>
          ))}
        </div>
      ),
    },
    {
      key: "status",
      header: "状态",
      width: "100px",
      render: (row) => (
        <Badge tone={row.status === "active" ? "ok" : "danger"}>{row.status === "active" ? "启用" : "停用"}</Badge>
      ),
    },
    {
      key: "login",
      header: "最近登录",
      width: "160px",
      render: (row) => (
        <span className="mono-num text-[11px] text-ink-3">
          {row.last_login_at ? new Date(row.last_login_at).toLocaleString() : "从未"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "110px",
      align: "right",
      render: (row) => (
        <Button
          variant="outline"
          size="sm"
          disabled={!can("user:write")}
          onClick={() => toggleStatus(row)}
          icon={<UserCog className="h-3.5 w-3.5" />}
        >
          {row.status === "active" ? "停用" : "启用"}
        </Button>
      ),
    },
  ];

  return (
    <div className="grid gap-5">
      <Panel className="p-0">
        <div className="flex items-center justify-between border-b border-line/70 px-4 py-3">
          <div>
            <p className="label-caps">用户</p>
            <p className="mono-num text-[13px] text-ink-1">{users.length} 个账号</p>
          </div>
          <Button
            size="sm"
            variant="primary"
            disabled={!can("user:write")}
            onClick={() => setCreating(true)}
            icon={<Plus className="h-3.5 w-3.5" />}
          >
            新建用户
          </Button>
        </div>
        <div className="p-2">
          <DataTable columns={columns} rows={users} rowKey={(row) => row.id} caption="用户列表" dense />
        </div>
      </Panel>

      <Modal
        open={creating}
        title="新建用户"
        description="新用户首次登录必须修改口令；角色决定可见页面与可执行操作。"
        onClose={() => setCreating(false)}
        footer={
          <>
            <Button size="sm" onClick={() => setCreating(false)}>
              取消
            </Button>
            <Button size="sm" variant="primary" type="submit" form="create-user">
              创建
            </Button>
          </>
        }
      >
        <form id="create-user" className="grid gap-4" onSubmit={submit}>
          <Field
            label="用户名"
            value={form.username}
            onChange={(event) => setForm({ ...form, username: event.target.value })}
            placeholder="3~32 位字母、数字或 ._-"
            required
          />
          <Field
            label="显示名"
            value={form.display_name}
            onChange={(event) => setForm({ ...form, display_name: event.target.value })}
            placeholder="例如：刘运维"
          />
          <Field
            label="初始口令"
            type="password"
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            hint="至少 10 位，不能是纯数字"
            required
          />
          <fieldset className="grid gap-1.5">
            <legend className="label-caps mb-1">角色</legend>
            <div className="flex flex-wrap gap-2">
              {roles.map((role) => {
                const active = form.roles.includes(role.name);
                return (
                  <button
                    key={role.id}
                    type="button"
                    onClick={() =>
                      setForm({
                        ...form,
                        roles: active
                          ? form.roles.filter((item) => item !== role.name)
                          : [...form.roles, role.name],
                      })
                    }
                    className={
                      active
                        ? "rounded-full border border-copper-400/60 bg-copper-400/10 px-3 py-1 font-mono text-[11px] text-copper-300"
                        : "rounded-full border border-line px-3 py-1 font-mono text-[11px] text-ink-2 hover:border-line/80"
                    }
                  >
                    {role.name}
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
          <p className="flex items-center gap-2 text-[11.5px] text-ink-3">
            <ShieldCheck className="h-3.5 w-3.5 text-teal" />
            创建与修改都会写入审计日志。
          </p>
        </form>
      </Modal>
    </div>
  );
}
