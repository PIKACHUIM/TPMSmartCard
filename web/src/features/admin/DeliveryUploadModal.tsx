import { useState, type ChangeEvent, type FormEvent } from "react";
import { UploadCloud } from "lucide-react";
import { api } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { Button, Field } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/lib/cn";

interface Props {
  open: boolean;
  onClose: () => void;
  onUploaded: () => void;
}

type Mode = "code" | "key";

export function DeliveryUploadModal({ open, onClose, onUploaded }: Props) {
  const [mode, setMode] = useState<Mode>("code");
  const [file, setFile] = useState<File | null>(null);
  const [pfxKey, setPfxKey] = useState("");
  const [pubkey, setPubkey] = useState("");
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [ttlHours, setTtlHours] = useState(24);
  const [maxUses, setMaxUses] = useState(1);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ id: string; code?: string; expires_at?: string; max_uses: number } | null>(null);
  const pushToast = useAppStore((state) => state.pushToast);

  const reset = () => {
    setMode("code");
    setFile(null);
    setPfxKey("");
    setPubkey("");
    setCode("");
    setLabel("");
    setTtlHours(24);
    setMaxUses(1);
    setPending(false);
    setError(null);
    setResult(null);
  };

  const close = () => {
    reset();
    onClose();
  };

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0] ?? null;
    setFile(next);
    setError(null);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!file) {
      setError("请选择 .pfx / .p12 文件");
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setError("文件超过 8 MiB 上限");
      return;
    }
    if (mode === "key" && pubkey.trim().length < 32) {
      setError("传输公钥不合法（应为 Base64 的 32 字节 X25519 公钥）");
      return;
    }
    setPending(true);
    api
      .uploadCertificate({
        mode,
        file,
        pfxKey,
        pubkey: pubkey.trim() || undefined,
        code: code.trim() || undefined,
        ttlHours,
        maxUses,
        label: label.trim() || undefined,
      })
      .then((uploaded) => {
        setResult(uploaded);
        onUploaded();
        pushToast({
          kind: "ok",
          title: "证书已加密投递",
          detail: uploaded.code ? `取件码 ${uploaded.code}（只显示这一次）` : "记录已写入下发列表",
        });
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setPending(false));
  };

  return (
    <Modal
      open={open}
      title={result ? "投递完成" : "投递证书"}
      description={result ? undefined : "PFX 在 Worker 侧用 X25519 或取件码派生的密钥加密后才落 KV；平台不保存明文口令。"}
      onClose={close}
      width={560}
      footer={
        result ? (
          <Button size="sm" variant="primary" onClick={close}>
            完成
          </Button>
        ) : (
          <>
            <Button size="sm" onClick={close}>
              取消
            </Button>
            <Button size="sm" variant="primary" type="submit" form="upload-cert" disabled={pending}>
              {pending ? "正在上传…" : "加密并投递"}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="grid gap-3">
          <p className="text-[12.5px] text-ink-2">
            记录 ID：<span className="font-mono text-ink-0">{result.id || "—"}</span>
          </p>
          {result.code ? (
            <div className="rounded-control border border-copper-400/40 bg-copper-400/10 px-4 py-3">
              <p className="label-caps mb-1">取件码（只显示这一次）</p>
              <p className="font-mono text-[20px] tracking-[0.12em] text-copper-300">{result.code}</p>
              <p className="mt-1 text-[11px] text-ink-2">
                可用 {result.max_uses} 次 · 到期 {result.expires_at ? new Date(result.expires_at).toLocaleString() : "永久"}
              </p>
            </div>
          ) : (
            <p className="text-[12.5px] text-ink-2">已按传输密钥加密；目标设备用对应私钥即可取回。</p>
          )}
        </div>
      ) : (
        <form id="upload-cert" className="grid gap-4" onSubmit={submit}>
          <div className="grid grid-cols-2 gap-2">
            {[
              { key: "code" as const, label: "取件码模式", hint: "无需预先交换密钥" },
              { key: "key" as const, label: "传输密钥模式", hint: "客户端先生成 X25519" },
            ].map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setMode(option.key)}
                aria-pressed={mode === option.key}
                className={cn(
                  "rounded-control border px-3 py-2 text-left transition",
                  mode === option.key ? "border-copper-400/60 bg-copper-400/10" : "border-line hover:border-line/80",
                )}
              >
                <span className="block text-[12.5px] text-ink-1">{option.label}</span>
                <span className="block text-[10.5px] text-ink-3">{option.hint}</span>
              </button>
            ))}
          </div>

          <label className="grid gap-1.5">
            <span className="label-caps">证书文件（.pfx / .p12）</span>
            <span className="flex h-10 items-center gap-2 rounded-control border border-line bg-graphite-0 px-3">
              <UploadCloud className="h-4 w-4 shrink-0 text-ink-3" />
              <input
                type="file"
                accept=".pfx,.p12,application/x-pkcs12"
                onChange={onFile}
                aria-label="选择证书文件"
                className="w-full border-none bg-transparent text-[12px] text-ink-1 file:mr-3 file:cursor-pointer file:rounded file:border-0 file:bg-graphite-2 file:px-2 file:py-1 file:text-[11px] file:text-ink-1 focus:outline-none"
              />
            </span>
            {file ? <span className="font-mono text-[10.5px] text-ink-3">{file.name} · {(file.size / 1024).toFixed(0)} KiB</span> : null}
          </label>

          <Field
            label="PFX 口令"
            type="password"
            value={pfxKey}
            onChange={(event) => setPfxKey(event.target.value)}
            placeholder="证书文件自身的保护口令；可留空"
            autoComplete="new-password"
          />

          {mode === "key" ? (
            <Field
              label="传输公钥"
              value={pubkey}
              onChange={(event) => setPubkey(event.target.value)}
              placeholder="Base64，32 字节 X25519 公钥"
              hint="由桌面端「云端下发 → 传输密钥」生成并复制"
            />
          ) : (
            <Field
              label="自定义取件码（可留空）"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="留空由平台生成，至少 8 个不同字符"
              hint="留空时只返回一次，请及时复制"
            />
          )}

          <div className="grid grid-cols-2 gap-3">
            <Field
              label="有效期（小时）"
              type="number"
              min={0}
              max={2160}
              value={ttlHours}
              onChange={(event) => setTtlHours(Number(event.target.value))}
              hint="0 表示永久，上限 90 天"
            />
            <Field
              label="允许取回次数"
              type="number"
              min={1}
              max={100}
              value={maxUses}
              onChange={(event) => setMaxUses(Number(event.target.value))}
            />
          </div>

          <Field
            label="备注"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="例如：财务部-李雷-笔记本"
            maxLength={128}
          />

          {error ? (
            <p role="alert" className="rounded-control border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
              {error}
            </p>
          ) : null}
        </form>
      )}
    </Modal>
  );
}
