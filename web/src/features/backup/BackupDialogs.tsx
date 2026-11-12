import { useState, type FormEvent } from "react";
import { ArchiveRestore, HardDriveDownload } from "lucide-react";
import { api } from "@/lib/api";
import type { BackupEntry, CardInfo } from "@/lib/types";
import { useAppStore } from "@/lib/store";
import { Button, Field } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";

interface CreateProps {
  open: boolean;
  cards: CardInfo[];
  onClose: () => void;
  onCreated: (entry: BackupEntry) => void;
}

export function BackupCreateModal({ open, cards, onClose, onCreated }: CreateProps) {
  const [cardId, setCardId] = useState(cards[0]?.id ?? "");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pushToast = useAppStore((state) => state.pushToast);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!cardId) {
      setError("没有可备份的卡片");
      return;
    }
    setPending(true);
    api
      .createBackup(cardId)
      .then((entry) => {
        pushToast({
          kind: "ok",
          title: "备份已生成",
          detail: `${entry.file} · ${entry.certificates ?? 0} 张证书，私钥未导出`,
        });
        onCreated(entry);
        onClose();
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setPending(false));
  };

  return (
    <Modal
      open={open}
      title="新建备份"
      description="备份包含卡片上的公钥证书与元数据；TPM / Secure Enclave 的私钥不可导出，因此不在包内。"
      onClose={onClose}
      width={480}
      footer={
        <>
          <Button size="sm" onClick={onClose}>
            取消
          </Button>
          <Button size="sm" variant="primary" type="submit" form="create-backup" disabled={pending}>
            {pending ? "正在打包…" : "生成 .tsb"}
          </Button>
        </>
      }
    >
      <form id="create-backup" className="grid gap-4" onSubmit={submit}>
        <label className="grid gap-1.5">
          <span className="label-caps">来源卡片</span>
          <select
            value={cardId}
            onChange={(event) => setCardId(event.target.value)}
            className="h-10 rounded-control border border-line bg-graphite-0 px-3 text-[12.5px] text-ink-0 focus:border-copper-400 focus:outline-none"
          >
            {cards.length === 0 ? <option value="">没有可用卡片</option> : null}
            {cards.map((card) => (
              <option key={card.id} value={card.id}>
                {card.name}（{card.certificate_count} 张证书）
              </option>
            ))}
          </select>
        </label>

        <p className="flex items-start gap-2 rounded-control border border-amber/30 bg-amber/10 px-3 py-2 text-[11.5px] leading-relaxed text-ink-2">
          <HardDriveDownload className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber" />
          备份文件等同密钥材料的管理级别：请离线保管，不要放入云盘或版本库。
        </p>

        {error ? (
          <p role="alert" className="rounded-control border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
            {error}
          </p>
        ) : null}
      </form>
    </Modal>
  );
}

interface RestoreProps {
  open: boolean;
  backup: BackupEntry | null;
  cards: CardInfo[];
  onClose: () => void;
  onRestored: () => void;
}

export function BackupRestoreModal({ open, backup, cards, onClose, onRestored }: RestoreProps) {
  const [cardId, setCardId] = useState(cards[0]?.id ?? "");
  const [pin, setPin] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pushToast = useAppStore((state) => state.pushToast);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!backup) {
      setError("请先选择一个备份包");
      return;
    }
    if (!cardId) {
      setError("请选择目标卡片");
      return;
    }
    setPending(true);
    api
      .restoreBackup(backup.file, cardId, pin || undefined)
      .then((result) => {
        if (result.failures.length > 0) {
          pushToast({ kind: "info", title: `还原完成，${result.failures.length} 项失败`, detail: result.failures[0] });
        } else {
          pushToast({ kind: "ok", title: `已还原 ${result.restored} 张证书`, detail: backup.file });
        }
        onRestored();
        onClose();
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setPending(false));
  };

  return (
    <Modal
      open={open}
      title="从备份还原"
      description="还原会把备份中的公钥证书写回目标卡片；私钥需要在卡内重新生成并重新签发。"
      onClose={onClose}
      width={480}
      footer={
        <>
          <Button size="sm" onClick={onClose}>
            取消
          </Button>
          <Button size="sm" variant="primary" type="submit" form="restore-backup" disabled={pending || !backup}>
            {pending ? "正在写入…" : "开始还原"}
          </Button>
        </>
      }
    >
      <form id="restore-backup" className="grid gap-4" onSubmit={submit}>
        <div className="rounded-control border border-line/70 bg-graphite-0/40 px-3 py-2">
          <p className="label-caps">备份包</p>
          <p className="mt-1 truncate font-mono text-[12px] text-ink-0">{backup?.file ?? "未选择"}</p>
          <p className="mt-0.5 text-[11px] text-ink-3">
            {backup ? `${backup.card_name} · ${(backup.size_bytes / 1024).toFixed(0)} KiB` : "在上方列表点击一行"}
          </p>
        </div>

        <label className="grid gap-1.5">
          <span className="label-caps">目标卡片</span>
          <select
            value={cardId}
            onChange={(event) => setCardId(event.target.value)}
            className="h-10 rounded-control border border-line bg-graphite-0 px-3 text-[12.5px] text-ink-0 focus:border-copper-400 focus:outline-none"
          >
            {cards.map((card) => (
              <option key={card.id} value={card.id}>
                {card.name}
              </option>
            ))}
          </select>
        </label>

        <Field
          label="卡片 PIN"
          type="password"
          value={pin}
          onChange={(event) => setPin(event.target.value)}
          placeholder="写入证书通常需要用户 PIN"
          autoComplete="off"
        />

        <p className="flex items-start gap-2 text-[11.5px] leading-relaxed text-ink-3">
          <ArchiveRestore className="mt-0.5 h-3.5 w-3.5 shrink-0 text-teal" />
          如果目标卡片与备份来源不是同一颗 TPM，证书可以还原，但私钥无法迁移，需要重新签发。
        </p>

        {error ? (
          <p role="alert" className="rounded-control border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
            {error}
          </p>
        ) : null}
      </form>
    </Modal>
  );
}
