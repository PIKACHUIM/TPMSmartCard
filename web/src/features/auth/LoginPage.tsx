import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowRight, KeyRound, ShieldHalf } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Button, Field } from "@/components/ui/primitives";
import { Toasts } from "@/components/ui/Toasts";

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const setSession = useAppStore((state) => state.setSession);
  const enterDemo = useAppStore((state) => state.enterDemo);
  const pushToast = useAppStore((state) => state.pushToast);

  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const target = (location.state as { from?: string } | null)?.from ?? "/admin/records";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setPending(true);
    api
      .login(username.trim(), password)
      .then((result) => {
        setSession(result.token, result.user);
        pushToast({ kind: "ok", title: `欢迎回来，${result.user.displayName ?? result.user.username}` });
        navigate(target, { replace: true });
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError) {
          setError(err.message);
          return;
        }
        // 后端未启动：进入演示模式，保证界面可继续评审
        console.error("login failed, entering demo mode", err);
        enterDemo();
        pushToast({
          kind: "info",
          title: "后端未连接，已进入演示模式",
          detail: "启动 Worker（npm run dev:worker）或桌面后端后重新登录",
        });
        navigate(target, { replace: true });
      })
      .finally(() => setPending(false));
  };

  return (
    <div className="relative min-h-screen overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(900px_480px_at_18%_20%,rgba(217,131,36,0.12),transparent_60%),radial-gradient(760px_420px_at_86%_80%,rgba(76,126,168,0.10),transparent_60%)]" />

      <div className="relative mx-auto grid min-h-screen w-full max-w-[1180px] grid-cols-1 items-center gap-16 px-6 py-16 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="max-w-xl">
          <div className="mb-8 flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-md border border-copper-400/50 bg-copper-400/10">
              <ShieldHalf className="h-5 w-5 text-copper-300" />
            </span>
            <div>
              <p className="label-caps">TPM Virtual Smartcard</p>
              <p className="font-mono text-[12px] text-ink-3">v2.0 · Go + Wails + Hono</p>
            </div>
          </div>

          <h1 className="text-[42px] font-semibold leading-[1.05] tracking-[-0.03em] text-ink-0">
            私钥不出芯片，
            <br />
            证书下发可审计。
          </h1>
          <p className="mt-5 max-w-[46ch] text-[15px] leading-relaxed text-ink-2">
            设备侧继续由 TPM / Secure Enclave 保护私钥；云端只负责把证书加密送达，
            每一次上传、下发与删除都有明确的权限与审计记录。
          </p>

          <dl className="mt-10 grid grid-cols-3 gap-px overflow-hidden rounded-panel border border-line bg-line">
            {[
              { label: "算法互通", value: "X25519 · AES-256" },
              { label: "取件方式", value: "传输密钥 / 取件码" },
              { label: "权限模型", value: "RBAC + 审计" },
            ].map((item) => (
              <div key={item.label} className="bg-graphite-1 px-4 py-3">
                <dt className="label-caps">{item.label}</dt>
                <dd className="mt-1 font-mono text-[12.5px] text-ink-1">{item.value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="surface mx-auto w-full max-w-[420px] p-7">
          <div className="mb-6 flex items-center gap-2 text-ink-1">
            <KeyRound className="h-4 w-4 text-copper-300" />
            <h2 className="text-subhead text-ink-0">{t("login.title")}</h2>
          </div>
          <p className="mb-6 text-[12.5px] leading-relaxed text-ink-2">{t("login.subtitle")}</p>

          <form className="grid gap-4" onSubmit={submit}>
            <Field
              label={t("login.username")}
              value={username}
              autoComplete="username"
              onChange={(event) => setUsername(event.target.value)}
              required
            />
            <Field
              label={t("login.password")}
              type="password"
              value={password}
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder="至少 10 位，不能是纯数字"
              required
            />
            {error ? (
              <p role="alert" className="rounded-control border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
                {error}
              </p>
            ) : null}
            <Button
              type="submit"
              variant="primary"
              disabled={pending}
              className="mt-1 w-full"
              icon={<ArrowRight className="h-4 w-4" />}
            >
              {pending ? "正在验证…" : t("login.submit")}
            </Button>
          </form>

          <p className="mt-6 border-t border-line/60 pt-4 font-mono text-[11px] leading-relaxed text-ink-3">
            首次部署：数据库无用户时，使用环境变量 <span className="text-copper-300">CARD_ADMIN_PASSWORD</span>
            自动创建 admin（super_admin）。
          </p>
        </section>
      </div>
      <Toasts />
    </div>
  );
}
