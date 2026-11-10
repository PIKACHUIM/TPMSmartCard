# SSH2 登录

用卡上的私钥登录远程服务器，代替"把私钥文件放在硬盘上"的传统做法：**私钥留在 TPM 里**，
登录时由卡完成签名。

## 原理

```
ssh 客户端 ──(签名请求)──▶ 内置 SSH 代理（本程序内，\\.\pipe\openssh-ssh-agent）
                              │ CryptoAPI / CNG 调用智能卡
                              ▼
                         TPM 虚拟智能卡（私钥在 TPM 内，PIN 解锁）
```

代理跑在**主程序进程内**（`Module/SSHAgent.py`），不再依赖随包的 `SSHCardAgent.exe`：

* **证书来源**：Windows「个人」证书存储里、私钥挂在智能卡提供程序上的证书；
* **签名**：`CryptAcquireCertificatePrivateKey` 取 CNG 句柄 → `NCryptSignHash`
  （RSA 走 PKCS#1，ECDSA 转成 SSH 的 `mpint r/s`），私钥始终不出卡；
* **PIN**：由 Windows 自己的智能卡对话框提示，本程序不读取、不缓存 PIN；
* **只读**：`ADD_IDENTITY` 之类会往 agent 里塞私钥的消息一律拒绝。

远端服务器只需要你的**公钥**（放进 `~/.ssh/authorized_keys`），它永远看不到私钥。

## 客户端怎么自动用上这把钥匙

管道名用的是 OpenSSH 的标准名 `\\.\pipe\openssh-ssh-agent`，所以**系统自带的 OpenSSH
客户端会自动连上本代理**，不需要任何环境变量：

| 客户端 | 是否需要额外配置 |
|---|---|
| 系统 OpenSSH（`C:\Windows\System32\OpenSSH\ssh.exe`、PowerShell、cmd 里的 `ssh`） | 不用，`SSH_AUTH_SOCK` 留空即可（它就是连默认管道） |
| Git（`core.sshCommand` 指向系统 ssh，或在 PATH 里优先找到系统 ssh） | 见下面「Git 接入」 |
| VS Code / Cursor Remote-SSH、JetBrains Gateway、WinSCP 等 | 一般不用，它们调用的就是系统 `ssh` |
| Git for Windows **自带的** `usr\bin\ssh.exe`（MSYS 版） | 连不上命名管道，必须切到系统 OpenSSH |
| PuTTY / Xshell 系（Pageant 协议） | 不支持，请改用回外挂 `SSHCardAgent.exe` 的方案 |

### Git 接入

Git for Windows 自带的 `ssh.exe` 是 MSYS 版，只认 Unix socket，把 `SSH_AUTH_SOCK`
指向命名管道会直接报错甚至卡住。所以要在 **⚙️ 系统设置 → SSH 登录** 里打开
**「让 Git 使用系统 OpenSSH」**：它把 `git config --global core.sshCommand` 指向
`C:/Windows/System32/OpenSSH/ssh.exe`，原值会记在设置里，关掉开关就原样还回去。

改完可以这样验证（代理运行中、卡上证书已导入 Windows「个人」存储）：

```bash
ssh-add -l          # 能列出 2048/SHA256 指纹就说明代理通了
ssh -T git@github.com   # 能返回 "Hi <user>!" 就说明 GitHub 侧也认这把钥匙
```

GitHub / GitLab 这类托管服务还要把**公钥**加到账号里（主界面选中证书 → **📋 复制公钥**
→ 网页里粘贴），服务器不会因为本机有代理就自动信任你。

::: tip 本程序是管理员运行时也能用
建卡要提权，所以本程序常常以管理员身份运行。Windows 会把桌面程序创建的命名管道标成
「高完整性」，普通权限的 `git`/`ssh` 连上来就是 `Permission denied`。本程序创建管道时
会显式把完整性标签降为 Low、DACL 只放当前用户/管理员/系统，因此普通窗口里的
`git`/`ssh` 一样能连上，别的 Windows 用户却签不了名。
:::

## 前提条件

| 项 | 要求 |
|---|---|
| 卡片 | 已创建，且卡上有 **RSA** 证书与私钥（SSH 服务端普遍支持 RSA；ECC 需服务端支持） |
| 证书路径 | 推荐用 [创建 CSR](/guide/usage-certs#_2-创建-csr-在卡内生成密钥并申请证书) 的方式让 CA 签发（私钥不出卡） |
| 证书存储 | 证书要能在 Windows「个人」证书存储里看到（用本程序导入 PFX / 接受下发的证书时会自动写入） |
| 代理 | 本程序内置（无需安装任何组件） |
| 远端 | 已把公钥写入远端 `~/.ssh/authorized_keys`（权限 `600`，目录 `700`） |

## 步骤

### 1. 准备卡上的 RSA 证书与私钥

按 [证书与密钥管理](/guide/usage-certs) 操作，建议：

* 加密算法选 **RSA2048**，摘要 **SHA256**；
* 密钥用途勾选「数字签名」（SSH 认证需要签名能力）。

### 2. 启用内置 SSH 代理

打开 **⚙️ 系统设置 → SSH 登录**：

| 开关 | 行为 |
|---|---|
| 启用内置 SSH 代理 | 在本程序进程里监听 `\\.\pipe\openssh-ssh-agent`（替代外挂的 `SSHCardAgent.exe`） |
| 启动时登记公钥，退出时反登记 | 程序启动时把选中的证书公钥写入 `~/.ssh/authorized_keys`，关闭程序时再删掉 |
| 让 Git 使用系统 OpenSSH | 把 `core.sshCommand` 指向系统 `ssh.exe`，让 Git 也能用上本代理（见上一节） |

同一页还有 **环境自检**：一次把「代理运行状态 / 管道安全模式 / 系统 OpenSSH 能否连上 /
Git 实际用的 ssh 能否连上」列出来，连不上时照最后一行的提示改就行。

代理随程序启动，不需要单独开机自启项；启用内置代理后，**系统设置 → 启动与托盘**
里的外挂代理自启会被停用（两者抢同一个管道）。

### 3. 登记公钥（可同时登记多张）

在主界面选中卡片上的证书（**按住 Ctrl / Shift 可以多选**），按钮行会从
「导入 PFX / 导入 CER / 创建 CSR」换成：

| 按钮 | 行为 |
|---|---|
| 🔑 启用SSH | 把**选中的每张**证书的公钥写进 `~/.ssh/authorized_keys`，并记进设置 |
| 🔓 停用SSH | 选中的都已登记时显示；只摘掉这几张的公钥，别的证书不受影响 |
| 📋 复制公钥 | 把选中的公钥复制到剪贴板（一行一张），可直接贴到**远端服务器** |

写入本机 `authorized_keys` 的行带 `tpmsmartcard:` 注释前缀，反登记只删这些行，
不会动你自己添加的条目。多张证书会一起被记住：启动时全部重新登记，退出时全部摘掉。
代理本身也是把卡上**所有**带私钥的证书都报给客户端，所以 ssh/git 会自动挑服务端认可的那张。

> 如果换成别的服务器，用「复制公钥」把那一行贴到远端 `~/.ssh/authorized_keys` 即可：

```bash
# 在远端服务器上
echo "ssh-rsa AAAAB3Nz... tpmsmartcard:..." >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### 4. 连接测试

* **OpenSSH 客户端**（Windows 自带 `ssh.exe`）：代理启动后用 `ssh-add -L` 查看能否列出卡上的公钥，
  能列出就说明代理在正常工作，直接 `ssh user@host` 即可（首次使用会弹出 **卡 PIN** 对话框）；
* **Git / VS Code / JetBrains**：它们用的就是 Windows 原生 agent 通道，无需额外配置；
* **PuTTY 系客户端**：走的是 Pageant 协议，内置代理**不支持**，这类客户端请继续用外挂的
  `SSHCardAgent.exe`（把内置代理关掉即可）。

## 排错

| 现象 | 原因与处理 |
|---|---|
| 连接提示 `post-quantum key exchange algorithm` 警告 | 与本工具无关：当前 Windows OpenSSH 9.5 不含后量子 KEX 算法，属客户端/服务端版本差异，可忽略 |
| 服务器仍要求输入密码 | 公钥没生效（格式/路径/权限问题），或服务端禁用了公钥认证；GitHub 还要确认账号里加过这把公钥 |
| `ssh-add -l` 报 `Permission denied` | 程序以管理员运行时管道默认是高完整性对象，旧版本才会这样；本版本已把完整性标签降为 Low，仍报错就重启一次程序（用「环境自检」看管道安全模式是否为空/系统默认） |
| `ssh-add -l` 列不出密钥 | 内置代理没启用；或系统自带的 `ssh-agent` 服务正占着同一个管道（先 `Stop-Service ssh-agent` 并设为手动启动） |
| `git clone`/`git pull` 仍然要密码或说 agent 不可用 | Git 用的是自带的 MSYS `ssh`：打开「让 Git 使用系统 OpenSSH」，再在「环境自检」里确认 `git 使用的 ssh` 那行是 `System32\OpenSSH\ssh.exe` |
| 登记时提示"该证书不在 Windows「个人」证书存储里" | 证书只在卡上、没进 Windows 存储：导出证书后在证书管理器里导入「个人」，或重新用本程序导入 PFX |
| 每次连接都弹 PIN | 正常行为：签名后会清掉进程内的 PIN 缓存，每次认证都要重新确认（与 WinCryptSSHAgent 默认一致） |
| 每次都提示找不到卡 / 读卡失败 | 确认卡片在列表里、`certutil -scinfo -silent` 正常；卡上密钥打不开的根因见 [故障排查手册](/troubleshooting) §4 |

::: warning 别在 SSH 会话里建卡 / 删卡
`tpmvscmgr` 在 SSH、服务等非交互会话里会被系统拒绝（`0x800704d3` / `0x80070005`）。
准备卡片请在本地控制台完成。
:::

::: tip 管理员账户做 SSH 服务端
Windows OpenSSH **服务端**对管理员组账户读的是
`%ProgramData%\ssh\administrators_authorized_keys`，不是 `~/.ssh/authorized_keys`。
本程序只维护后者。
:::

下一步：[备份与还原](/guide/backup)。
