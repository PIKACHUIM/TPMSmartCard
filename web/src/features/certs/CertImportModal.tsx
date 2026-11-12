import { useState, type ChangeEvent, type FormEvent } from "react";
import { FileUp } from "lucide-react";
import { api } from "@/lib/api";
import type { CardInfo } from "@/lib/types";
import { useAppStore } from "@/lib/store";
import { Button, Field } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";

interface Props {
  open: boolean;
  cards: CardInfo[];
  defaultCardId?: string;
  onClose: () => void;
  onImported: () => void;
}

export function CertImportModal({ open, cards, defaultCardId, onClose, onImported }: Props) {
  const [cardId, setCardId] = useState(defaultCardId ?? cards[0]?.id ?? "");
  const [pem, setPem] = useState("");
  const [fileName, setFileName] = useState("");
  const [pin, setPin] = useState("");
  const [label, setLabel] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pushToast = useAppStore((state) => state.pushToast);

  const reset = () => {
    setPem("");
    setFileName("");
    setPin("");
    setLabel("");
    setError(null);
    setPending(false);
  };

  const close = () => {
    reset();
    onClose();
  };

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 256 * 1024) {
      setError("证书文件超过 256 KiB，请确认选择的是证书而不是 PKCS#12");
      return;
    }
    setFileName(file.name);
    setError(null);
    // .cer 可能是 DER：先按文本读，交给后端报错并提示转换
    file
      .text()
      .then((text) => setPem(text))
      .catch((err: Error) => console.error("read cert failed", err));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!cardId) {
      setError("请选择目标卡片");
      return;
    }
    if (!pem.includes("BEGIN CERTIFICATE")) {
      setError("需要 PEM 格式（BEGIN CERTIFICATE）。DER 证书请先转换：certutil -encode 或 openssl x509 -inform der -outform pem");
      return;
    }
    setPending(true);
    api
      .importCertificate({ card_id: cardId, pem, pin: pin || undefined, label: label || undefined })
      .then((result) => {
        pushToast({ kind: "ok", title: "证书已写入卡片", detail: result.subject });
        onImported();
        close();
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setPending(false));
  };

  return (
    <Modal
      open={open}
      title="导入证书"
      description="只导入公钥证书（PEM）；私钥必须留在 TPM / Secure Enclave 内，本工具不会接收私钥。"
      onClose={close}
      width={520}
      footer={
        <>
          <Button size="sm" onClick={close}>
            取消
          </Button>
          <Button size="sm" variant="primary" type="submit" form="import-cert" disabled={pending}>
            {pending ? "正在写入…" : "写入卡片"}
          </Button>
        </>
      }
    >
      <form id="import-cert" className="grid gap-4" onSubmit={submit}>
        <label className="grid gap-1.5">
          <span className="label-caps">目标卡片</span>
          <select
            value={cardId}
            onChange={(event) => setCardId(event.target.value)}
            className="h-10 rounded-control border border-line bg-graphite-0 px-3 text-[12.5px] text-ink-0 focus:border-copper-400 focus:outline-none"
          >
            {cards.length === 0 ? <option value="">没有可用卡片</option> : null}
            {cards.map((card) => (
              <option key={card.id} value={card.id}>
                {card.name}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1.5">
          <span className="label-caps">证书文件（.pem / .crt）</span>
          <span className="flex h-10 items-center gap-2 rounded-control border border-line bg-graphite-0 px-3">
            <FileUp className="h-4 w-4 shrink-0 text-ink-3" />
            <input
              type="file"
              accept=".pem,.crt,.cer"
              onChange={onFile}
              aria-label="选择证书文件"
              className="w-full border-none bg-transparent text-[12px] text-ink-1 file:mr-3 file:cursor-pointer file:rounded file:border-0 file:bg-graphite-2 file:px-2 file:py-1 file:text-[11px] file:text-ink-1 focus:outline-none"
            />
          </span>
          {fileName ? <span className="font-mono text-[10.5px] text-ink-3">{fileName}</span> : null}
        </label>

        <Field
          label="卡片 PIN"
          type="password"
          value={pin}
          onChange={(event) => setPin(event.target.value)}
          placeholder="写入证书通常需要用户 PIN"
          autoComplete="off"
        />

        <Field
          label="标签（可选）"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="默认取证书 CN"
          maxLength={64}
        />

        {error ? (
          <p role="alert" className="rounded-control border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
            {error}
          </p>
        ) : null}
      </form>
    </Modal>
  );
}
