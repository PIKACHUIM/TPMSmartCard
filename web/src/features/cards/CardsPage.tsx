import { useEffect, useState, type FormEvent } from "react";
import { CreditCard, Plus, ShieldAlert, Trash2, KeyRound } from "lucide-react";
import { api } from "@/lib/api";
import type { CardInfo, SystemHealth } from "@/lib/types";
import { useAppStore } from "@/lib/store";
import { Badge, Button, EmptyState, Field, Panel, SectionTitle, Spinner } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/lib/cn";

const KIND_LABEL: Record<CardInfo["kind"], string> = {
  windows_vsc: "Windows 虚拟卡",
  tpm2: "TPM2 / PKCS#11",
  darwin_keychain: "钥匙串 + SE",
  local: "本地软件卡",
  cloud: "云端卡槽",
};

const SECURITY_LABEL: Record<CardInfo["security"], { text: string; tone: "ok" | "warn" | "danger" }> = {
  high: { text: "高：私钥不可导出", tone: "ok" },
  medium: { text: "中：芯片加密存储", tone: "warn" },
  low: { text: "低：软件密钥", tone: "danger" },
};

export function CardsPage() {
  const [cards, setCards] = useState<CardInfo[] | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", pin: "", puk: "" });
  const pushToast = useAppStore((state) => state.pushToast);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([api.cards(), api.health()])
      .then(([result, nextHealth]) => {
        if (cancelled) return;
        setCards(result.cards);
        setHealth(nextHealth);
        setSelected((current) => current ?? result.cards[0]?.id ?? null);
      })
      .catch((err) => console.error("cards load failed", err));
    return () => {
      cancelled = true;
    };
  }, []);

  if (!cards || !health) return <Spinner label="正在枚举读卡器与卡片…" />;

  const current = cards.find((card) => card.id === selected) ?? null;
  const capability = health.capability;

  const createCard = (event: FormEvent) => {
    event.preventDefault();
    setCreating(false);
    const next: CardInfo = {
      id: `local-${Date.now().toString(16)}`,
      name: form.name || "未命名卡片",
      kind: health.platform === "windows" ? "windows_vsc" : health.platform === "macos" ? "darwin_keychain" : "tpm2",
      platform: health.platform,
      security: health.capability.tpm_backed || health.capability.secure_enclave ? "high" : "low",
      reader: health.reader.readers[0] ?? null,
      certificate_count: 0,
      created_at: new Date().toISOString(),
      last_used_at: null,
    };
    setCards([next, ...cards]);
    setSelected(next.id);
    setForm({ name: "", pin: "", puk: "" });
    pushToast({
      kind: "ok",
      title: `已创建「${next.name}」`,
      detail: "演示模式：真实建卡由本地 Go 后端调用 tpmvscmgr / tpm2-pkcs11 完成",
    });
  };

  const removeCard = () => {
    if (!current) return;
    setCards(cards.filter((card) => card.id !== current.id));
    setSelected(null);
    pushToast({ kind: "err", title: `已删除「${current.name}」`, detail: "删除会清除 TPM 内的持久密钥，备份也无法还原" });
  };

  return (
    <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
      <Panel className="p-0">
        <div className="flex items-center justify-between border-b border-line/70 px-4 py-3">
          <div>
            <p className="label-caps">卡片槽</p>
            <p className="mono-num text-[13px] text-ink-1">{cards.length} 张</p>
          </div>
          <Button
            variant="primary"
            size="sm"
            disabled={!capability.create_card}
            title={capability.create_card ? "创建虚拟智能卡" : "当前平台不支持建卡"}
            onClick={() => setCreating(true)}
            icon={<Plus className="h-3.5 w-3.5" />}
          >
            新建
          </Button>
        </div>

        {cards.length === 0 ? (
          <EmptyState title="还没有卡片" hint="在 Windows 上需要本地控制台会话；远程桌面会被系统拒绝（0x800704d3）。" />
        ) : (
          <ul className="max-h-[calc(100vh-220px)] overflow-y-auto">
            {cards.map((card) => (
              <li key={card.id}>
                <button
                  type="button"
                  onClick={() => setSelected(card.id)}
                  className={cn(
                    "w-full border-b border-line/40 px-4 py-3 text-left transition-colors",
                    selected === card.id ? "bg-copper-400/[0.07]" : "hover:bg-graphite-2/50",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <CreditCard className="h-3.5 w-3.5 text-ink-3" />
                    <span className="truncate text-[13px] text-ink-0">{card.name}</span>
                  </div>
                  <p className="mt-1 truncate font-mono text-[10.5px] text-ink-3">
                    {KIND_LABEL[card.kind]} · {card.certificate_count} 证书
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {current ? (
        <div className="grid content-start gap-5">
          <Panel>
            <SectionTitle
              title={current.name}
              hint={KIND_LABEL[current.kind]}
              action={<Badge tone={SECURITY_LABEL[current.security].tone}>{SECURITY_LABEL[current.security].text}</Badge>}
            />

            <dl className="grid gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-2">
              {[
                ["卡片 ID", current.id],
                ["读卡器 / 设备", current.reader ?? "—"],
                ["平台", current.platform],
                ["证书数量", String(current.certificate_count)],
                ["创建时间", new Date(current.created_at).toLocaleString()],
                ["最近使用", current.last_used_at ? new Date(current.last_used_at).toLocaleString() : "从未使用"],
              ].map(([label, value]) => (
                <div key={label} className="bg-graphite-1 px-4 py-3">
                  <dt className="label-caps">{label}</dt>
                  <dd className="mono-num mt-1 truncate text-[12.5px] text-ink-1">{value}</dd>
                </div>
              ))}
            </dl>

            <div className="mt-5 flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={!capability.set_pin}
                title={capability.set_pin ? "修改卡片 PIN" : "macOS 无 PIN 语义，使用钥匙串访问控制"}
                icon={<KeyRound className="h-3.5 w-3.5" />}
              >
                修改 PIN
              </Button>
              <Button
                size="sm"
                variant="danger"
                disabled={!capability.delete_card}
                title={capability.delete_card ? "删除卡片" : "当前平台不支持删卡"}
                onClick={removeCard}
                icon={<Trash2 className="h-3.5 w-3.5" />}
              >
                删除卡片
              </Button>
            </div>
          </Panel>

          <Panel>
            <SectionTitle title="风险提示" hint="与 v1 文档保持一致的硬约束" />
            <ul className="grid gap-2 text-[12.5px] leading-relaxed text-ink-2">
              <li className="flex gap-2">
                <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber" />
                创建 / 删除虚拟智能卡必须在本地控制台会话执行，远程桌面会返回 0x800704d3。
              </li>
              <li className="flex gap-2">
                <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber" />
                删除卡片会清除 TPM 内的持久密钥；已有 .tsb 备份也无法还原。
              </li>
              <li className="flex gap-2">
                <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber" />
                macOS 的 Secure Enclave 私钥永不导出，换机必须重新签发证书。
              </li>
            </ul>
          </Panel>
        </div>
      ) : (
        <Panel>
          <EmptyState title="选择左侧卡片查看详情" hint="卡片列表来自本地后端枚举，不会上传到云端。" />
        </Panel>
      )}

      <Modal
        open={creating}
        title="创建虚拟智能卡"
        description="PIN / PUK 仅发往本地后端，不经过云端。"
        onClose={() => setCreating(false)}
        footer={
          <>
            <Button size="sm" onClick={() => setCreating(false)}>
              取消
            </Button>
            <Button size="sm" variant="primary" form="create-card" type="submit">
              创建
            </Button>
          </>
        }
      >
        <form id="create-card" className="grid gap-4" onSubmit={createCard}>
          <Field
            label="卡片名称"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            placeholder="例如：财务部-李雷-笔记本"
            required
          />
          <Field
            label="PIN"
            type="password"
            value={form.pin}
            onChange={(event) => setForm({ ...form, pin: event.target.value })}
            hint="至少 6 位；连续输错会锁卡"
            required
          />
          <Field
            label="PUK"
            type="password"
            value={form.puk}
            onChange={(event) => setForm({ ...form, puk: event.target.value })}
            hint="用于解锁 PIN，请与 PIN 分开保管"
            required
          />
        </form>
      </Modal>
    </div>
  );
}
