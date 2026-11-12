/**
 * /card/web/cert 上传页（服务端渲染，无外部依赖）。
 *
 * 这个页面是给「没有安装桌面端、只想把 PFX 交给平台」的用户用的，
 * 因此必须能在任何浏览器打开、不依赖前端构建产物，也不加载第三方脚本。
 * 视觉与桌面端保持同一套石墨 + 紫铜令牌。
 */
export function renderUploadPage(origin: string): string {
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>TPMSmartCard · 证书投递</title>
<style>
  :root {
    --graphite-0:#0E1116; --graphite-1:#151A21; --graphite-2:#1C232C;
    --line:#2A333D; --text:#E6EAEF; --muted:#8B98A6; --copper:#D98324;
    --ok:#3E8E7E; --warn:#D9A441; --danger:#C9524B;
    --mono: ui-monospace, "JetBrains Mono", "SFMono-Regular", Menlo, monospace;
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--graphite-0); color:var(--text);
    font-family: "Source Sans Pro", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size:14px; line-height:1.6; }
  .shell { max-width: 860px; margin: 0 auto; padding: 56px 24px 96px; }
  .eyebrow { font-family: var(--mono); font-size:12px; letter-spacing:.18em;
    text-transform:uppercase; color:var(--copper); }
  h1 { font-size:28px; font-weight:600; letter-spacing:-.02em; margin:8px 0 6px; }
  .lede { color:var(--muted); max-width: 62ch; margin:0 0 32px; }
  .panel { background:var(--graphite-1); border:1px solid var(--line); border-radius:10px; }
  .tabs { display:flex; gap:4px; padding:6px; border-bottom:1px solid var(--line); }
  .tab { flex:1; appearance:none; border:0; background:transparent; color:var(--muted);
    padding:10px 12px; border-radius:6px; cursor:pointer; font-size:13px; }
  .tab[aria-selected="true"] { background:var(--graphite-2); color:var(--text); }
  form { padding: 20px 20px 24px; display:grid; gap:16px; }
  label { display:grid; gap:6px; font-size:12px; color:var(--muted); letter-spacing:.02em; }
  input { width:100%; background:var(--graphite-0); border:1px solid var(--line);
    border-radius:6px; color:var(--text); padding:10px 12px; font:inherit; }
  input:focus { outline:none; border-color:var(--copper); box-shadow:0 0 0 3px rgba(217,131,36,.18); }
  .drop { border:1px dashed var(--line); border-radius:8px; padding:22px; text-align:center;
    color:var(--muted); cursor:pointer; }
  .drop.hot { border-color:var(--copper); color:var(--text); }
  .row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .actions { display:flex; align-items:center; gap:12px; }
  button.primary { background:var(--copper); color:#151A21; border:0; border-radius:6px;
    padding:11px 20px; font-weight:600; cursor:pointer; }
  button.primary:disabled { opacity:.5; cursor:not-allowed; }
  .hint { font-family:var(--mono); font-size:12px; color:var(--muted); }
  .result { margin-top:20px; padding:16px 18px; border-radius:8px; border:1px solid var(--line);
    background:var(--graphite-1); white-space:pre-wrap; font-family:var(--mono); font-size:12.5px; }
  .result[data-kind="ok"] { border-color:rgba(62,142,126,.5); }
  .result[data-kind="err"] { border-color:rgba(201,82,75,.5); }
  .code { font-family:var(--mono); font-size:20px; letter-spacing:.12em; color:var(--copper); }
  .foot { margin-top:32px; color:var(--muted); font-size:12px; }
  a { color:var(--copper); }
  @media (max-width:640px){ .row{grid-template-columns:1fr;} .shell{padding-top:32px;} }
</style>
</head>
<body>
<div class="shell">
  <div class="eyebrow">TPM Virtual Smartcard</div>
  <h1>证书投递</h1>
  <p class="lede">把 PKCS#12（.pfx / .p12）交给平台加密暂存。平台只会保存密文；
    取回时必须提供传输密钥或取件码，且取件码在有效期内可限次使用。</p>

  <div class="panel">
    <div class="tabs" role="tablist">
      <button class="tab" role="tab" aria-selected="true" data-mode="key">传输密钥模式</button>
      <button class="tab" role="tab" aria-selected="false" data-mode="code">取件码模式</button>
    </div>
    <form id="upload" method="post" action="/card/put/cert" enctype="multipart/form-data" novalidate>
      <input type="hidden" name="mode" id="mode" value="key" />
      <label id="pubkey-field">传输公钥（工具端复制）
        <input name="pubkey" id="pubkey" autocomplete="off" spellcheck="false"
          placeholder="Base64，32 字节 X25519 公钥" />
      </label>
      <label id="code-field" hidden>取件码（留空由平台生成）
        <input name="code" id="code" autocomplete="off" spellcheck="false"
          placeholder="ABCD-EFGH-JKMN-PQRS，或留空自动生成" />
      </label>
      <label>PFX 口令
        <input name="pfxkey" id="pfxkey" type="password" autocomplete="new-password" placeholder="证书文件自身的保护口令" />
      </label>
      <div class="drop" id="drop">
        点击选择或拖入 .pfx / .p12 文件
        <input name="vaults" id="vaults" type="file" accept=".pfx,.p12,application/x-pkcs12" hidden />
      </div>
      <div class="row">
        <label>有效期（小时，0 = 永久）
          <input name="ttl" id="ttl" type="number" min="0" max="2160" value="24" />
        </label>
        <label>允许取回次数
          <input name="max_uses" id="max_uses" type="number" min="1" max="100" value="1" />
        </label>
      </div>
      <label>备注（可选）
        <input name="label" id="label" maxlength="128" placeholder="例如：财务部-李雷-笔记本" />
      </label>
      <div class="actions">
        <button class="primary" type="submit" id="submit">加密并投递</button>
        <span class="hint" id="hint">文件不会以明文离开本机</span>
      </div>
    </form>
  </div>

  <div class="result" id="result" hidden></div>
  <p class="foot">取回入口：<a href="${origin}/card/get/cert">/card/get/cert</a> ·
    兼容旧路径 <a href="${origin}/get/cert">/get/cert</a></p>
</div>
<script>
  const modeInput = document.getElementById('mode');
  const pubkeyField = document.getElementById('pubkey-field');
  const codeField = document.getElementById('code-field');
  const tabs = Array.from(document.querySelectorAll('.tab'));
  const form = document.getElementById('upload');
  const result = document.getElementById('result');
  const drop = document.getElementById('drop');
  const fileInput = document.getElementById('vaults');
  const submit = document.getElementById('submit');

  tabs.forEach((tab) => tab.addEventListener('click', () => {
    const mode = tab.dataset.mode;
    modeInput.value = mode;
    tabs.forEach((t) => t.setAttribute('aria-selected', String(t === tab)));
    const isCode = mode === 'code';
    pubkeyField.hidden = isCode;
    codeField.hidden = !isCode;
  }));

  drop.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) drop.textContent = fileInput.files[0].name;
  });
  ['dragenter','dragover'].forEach((evt) => drop.addEventListener(evt, (e) => {
    e.preventDefault(); drop.classList.add('hot');
  }));
  ['dragleave','drop'].forEach((evt) => drop.addEventListener(evt, (e) => {
    e.preventDefault(); drop.classList.remove('hot');
  }));
  drop.addEventListener('drop', (e) => {
    if (e.dataTransfer.files[0]) {
      fileInput.files = e.dataTransfer.files;
      drop.textContent = e.dataTransfer.files[0].name;
    }
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    result.hidden = false;
    result.dataset.kind = '';
    result.textContent = '正在加密投递…';
    submit.disabled = true;
    const response = await fetch('/card/put/cert', { method: 'POST', body: new FormData(form) });
    const body = await response.json().catch(() => null);
    submit.disabled = false;
    if (!body || !body.flag) {
      result.dataset.kind = 'err';
      result.textContent = '投递失败：' + ((body && body.data && body.data.error) || ('HTTP ' + response.status));
      return;
    }
    result.dataset.kind = 'ok';
    const data = body.data || {};
    let text = '投递成功。记录 ID：' + data.id;
    if (data.code) {
      text += '\\n取件码（只显示这一次）：';
      result.innerHTML = '';
      const head = document.createElement('div');
      head.textContent = '投递成功，请在工具端输入取件码：';
      const code = document.createElement('div');
      code.className = 'code';
      code.textContent = data.code;
      const tail = document.createElement('div');
      tail.className = 'hint';
      tail.textContent = '有效期至 ' + (data.expires_at || '永久') + '，可用 ' + data.max_uses + ' 次。';
      result.append(head, code, tail);
      return;
    }
    text += '\\n有效期至 ' + (data.expires_at || '永久') + '，可用 ' + data.max_uses + ' 次。';
    result.textContent = text;
  });
</script>
</body>
</html>`;
}
