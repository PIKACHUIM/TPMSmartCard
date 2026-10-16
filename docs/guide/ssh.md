# SSH2 登录

用卡上的私钥登录远程服务器，代替"把私钥文件放在硬盘上"的传统做法：**私钥留在 TPM 里**，
登录时由卡完成签名。

## 原理

```
ssh 客户端 ──(签名请求)──▶ SSH 代理（WinCryptSSHAgent）
                              │ 通过 CSP / CryptoAPI 调用智能卡
                              ▼
                         TPM 虚拟智能卡（私钥在 TPM 内，PIN 解锁）
```

远端服务器只需要你的**公钥**（放进 `~/.ssh/authorized_keys`），它永远看不到私钥。

## 前提条件

| 项 | 要求 |
|---|---|
| 卡片 | 已创建，且卡上有 **RSA** 证书与私钥（SSH 服务端普遍支持 RSA；SM2 / ECC 视服务端而定） |
| 证书路径 | 推荐用 [创建 CSR](/guide/usage-certs#_2-创建-csr-在卡内生成密钥并申请证书) 的方式让 CA 签发（私钥不出卡） |
| 代理 | WinCryptSSHAgent（随包分发的 `SSHCardAgent.exe`） |
| 远端 | 已把公钥写入 `~/.ssh/authorized_keys`（权限 `600`，目录 `700`） |

## 步骤

### 1. 准备卡上的 RSA 证书与私钥

按 [证书与密钥管理](/guide/usage-certs) 操作，建议：

* 加密算法选 **RSA2048**，摘要 **SHA256**；
* 密钥用途勾选「数字签名」（SSH 认证需要签名能力）。

### 2. 安装并启动 SSH 代理

打开 **⚙️ 系统设置 → WinSSH 代理**：

| 按钮 | 行为 |
|---|---|
| 安装 | `choco install wincrypt-sshagent`（需要 Chocolatey；安装包里的 `SSH 密钥代理` 组件也可达到同样效果） |
| 启动 | 运行随包的 `SSHCardAgent.exe` |

如果希望开机自动可用，在 **系统设置 → 启动与托盘** 里打开「自启 WinSSH 代理」
（以计划任务方式注册，避免每次弹 UAC）。

### 3. 把公钥放到远端

1. 在主界面选中卡片上那张证书 → **💾 导出证书**，得到一个证书文件；
2. 取出其中的公钥并转成 OpenSSH 格式（需要 OpenSSL，任意版本均可）：

   ```bash
   # 导出 PEM 公钥
   openssl x509 -in my-cert.cer -pubkey -noout > pub.pem
   # 转成 OpenSSH 单行格式（输出形如 ssh-rsa AAAAB3Nz... ）
   ssh-keygen -i -m PKCS8 -f pub.pem
   ```

3. 把输出的那一行追加到远端：

   ```bash
   # 在远端服务器上
   echo "ssh-rsa AAAAB3Nz... 你的备注" >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```

### 4. 连接测试

* **OpenSSH 客户端**（Windows 自带 `ssh.exe`）：代理启动后用 `ssh-add -L` 查看是否能列出卡上的公钥，
  能列出就说明代理在正常工作，直接 `ssh user@host` 即可（首次使用会提示输入**卡 PIN**）；
* **PuTTY 系客户端**：在连接配置里勾选"Attempt authentication using Pageant"，
  并确认 WinCryptSSHAgent 已作为 Pageant 代理运行。

## 排错

| 现象 | 原因与处理 |
|---|---|
| 连接提示 `post-quantum key exchange algorithm` 警告 | 与本工具无关：当前 Windows OpenSSH 9.5 不含后量子 KEX 算法，属客户端/服务端版本差异，可忽略 |
| 服务器仍要求输入密码 | 公钥没生效（格式/路径/权限问题），或服务端禁用了公钥认证 |
| `ssh-add -L` 列不出密钥 | 代理没启动，或客户端与代理的 agent 协议不匹配（不同版本的 WinCryptSSHAgent 对 OpenSSH 原生 agent 协议支持不同；可换 PuTTY/Pageant 方式验证） |
| 每次都提示找不到卡 / 读卡失败 | 确认卡片在列表里、`certutil -scinfo -silent` 正常；卡上密钥打不开的根因见 [故障排查手册](/troubleshooting) §4 |
| 连接时反复要求 PIN | 部分代理需要手动"记住 PIN"；也可在代理设置里开启 PIN 缓存 |

::: warning 别在 SSH 会话里建卡 / 删卡
`tpmvscmgr` 在 SSH、服务等非交互会话里会被系统拒绝（`0x800704d3` / `0x80070005`）。
准备卡片请在本地控制台完成。
:::

下一步：[备份与还原](/guide/backup)。
