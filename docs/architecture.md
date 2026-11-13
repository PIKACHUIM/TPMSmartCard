# 架构说明

> 定位：把「TPM 虚拟智能卡管理工具」的结构讲清楚 —— 有哪些进程、代码怎么分层、界面与配置怎么驱动、
> 依赖哪些系统组件、数据落在哪里。设计细节见 [`design-backup-restore.md`](design-backup-restore.md)。

## 1. 项目定位

Windows 桌面工具，用于**创建与管理 TPM 虚拟智能卡**（TPM Virtual Smart Card），
并管理卡上的 X.509 证书与密钥：建卡 / 删卡 / 改 PIN、导入与导出证书、本地生成密钥与 CSR、
云端安全下发证书、借助 OpenSC 与 WinCryptSSHAgent 把卡用于 SSH 登录等场景。
底层依赖 Windows 自带的 `tpmvscmgr`、`certutil` 与 TPM 硬件。

## 2. 进程与入口

| 入口 | 形态 | 说明 |
|---|---|---|
| `SmartCardAPP.py` ★ | GUI 主程序（`Win32GUI` + `uac_admin=True`） | 启动流程：`Paths.ensure_workdir()` → `SmartCardAPP()` → `tk.Tk()` / 读配置 / 初始化 i18n / `SmartCardAPI` / `TPMSmartCard` / 注册字体 / 托盘图标（`--minimized` 只驻留托盘） |
| `SmartCardWEB.py` | 控制台程序（Flask） | 监听 `0.0.0.0:1080`，用于**云端证书下发**的接收端；带证书缓存 `Caches/PullCerts.pkl`；语言按 `?lang=` > Cookie > `Accept-Language` > 程序语言协商 |
| `SubApp/CertImport.py` | 独立子程序（`CertImport.exe`，GUI + 管理员） | 导入 PFX / CER / CSR |
| `SubApp/MoreConfig.py` | 模块（主程序内以 `from SubApp.MoreConfig import MoreConfig` 复用，`__main__` 也可单独运行） | OpenSC 安装、SSH 代理安装与启动等辅助配置。仓库**不再随包分发 `MoreConfig.exe`**（历史遗留已清理） |
| `SubApp/SystemSettings.py` | 主程序内对话框 | 外观 / OpenSC / WinSSH 代理 / TPM 状态 / 关于与更新；`__main__` 仅供开发调试 |
| `Module/TPMBackup.py` | 库 + CLI | 备份 / 还原核心；`python -m` 方式可做命令行自检 |
| `Module/I18n.py` | 库 + CLI | 语言包加载与自检 |

## 3. 模块分层

`Module/` 是核心库，界面与子程序都复用它。

| 分层 | 模块 | 职责 |
|---|---|---|
| **基础设施** | `Paths.py` ★ | 程序根目录与资源绝对路径解析、工作目录归位（`TPMSMART_HOME` 可覆盖） |
| | `Version.py` ★ | 版本与仓库信息**单一来源**、版本比较；当前 `VERSION = 1.6.0` |
| | `I18n.py` | 多语言核心（桌面 + Web 共用）：加载 / 回退 / 继承（`_extends`）/ 单例 |
| | `AppConfigure.py` | 子界面的布局与文案入口（读 `Config/*.json`） |
| | `Theme.py`、`TrayIcon.py` | 主题、托盘图标（纯 ctypes 封装 `Shell_NotifyIcon`）；日期控件统一用 ttkbootstrap 的 `DateEntry` |
| **智能卡与 TPM** | `TPMSmartCard.py` | `tpmvscmgr.exe` 封装：建卡 / 删卡 / 改 PIN / CSR / 证书导入导出 / TPM 状态 |
| | `SmartCardAPI.py` | 读卡与证书读取门面（默认 OpenSC，可回退 Certutil） |
| | `OpenSCDealer.py` / `CertutilDeal.py` | 两种读取后端的解析实现 |
| | `Certificates.py` / `SmartCardObj.py` | X.509 解析数据类、卡片与证书数据对象 |
| **备份与还原** | `TPMBackup.py` ★ | `.tsb` 打包 / 还原、设备节点重建、设备属性读写、诊断与日志 |
| | `DPAPI.py` ★ | DPAPI 加解密与**令牌借用**（SYSTEM / LOCAL SERVICE / NETWORK SERVICE） |
| **云端下发** | `Cryptography.py` | 取件码规范化 + PBKDF2-SHA256 派生 + AES-256-CBC |
| **系统集成** | `AutoStart.py` | 开机自启（登录触发计划任务提权 + `HKCU\...\Run` 兜底） |

## 4. 依赖的外部程序

| 程序 | 用途 | 来源 |
|---|---|---|
| `tpmvscmgr.exe` | 建卡 / 删卡 / 改 PIN（**必须在本地控制台会话**执行） | 只使用 `%SystemRoot%\System32\tpmvscmgr.exe`（Windows 8+ 自带）；仓库内的副本已清理，代码中**没有**回退逻辑 |
| `certutil.exe` | 证书与卡片信息查询（`certutil -scinfo`） | 系统自带 |
| OpenSC 工具（`opensc-tool.exe`、`pkcs15-tool.exe` 等） | 读卡与读证书的默认后端 | **随程序分发**（`OpenSC/` 目录），系统级安装可选 |
| `Import/TPMImport.exe`（.NET） | 证书导入辅助 | 随程序分发 |
| `SSHCardAgent.exe` | WinCryptSSHAgent，SSH 场景 | 第三方，随程序分发 |

## 5. 界面与配置驱动

* 技术栈：**Tkinter + ttkbootstrap**（另有 `pyglet` 仅用于注册字体）；界面**纯代码构建**，没有 `.ui` 文件。
* 布局与文案由 `Config/` 下的 JSON 驱动：`tables.json` / `frames.json` / `button.json` / `labels.json` / `cncode.json`；
  主程序据此生成控件（`view_frames` / `view_tables` / `view_button` / `view_labels` / `view_hint`）。
* 资源：`Config/iconer/*.ico`、`Config/myfont/*.ttf|otf`、`Config/cacert/*.cer`。
* `templates/` 与 `static/` **仅服务 Web 端**（Flask）。

## 6. 多语言机制

* 语言包：`Config/locales/<code>.json`，扁平「键 → 字符串（或字符串数组）」；`_` 前缀为元数据
  （`_name` / `_font` / `_wide` / `_extends`）。当前 **11 种**：`de en es fr it ja ko pt ru zh-Hans zh-Hant`。
* 加载：`I18n.locales_dir()` → `locale_path()` → `_read_locale_file()` → `load_locale()`（带缓存与 `_extends` 继承合并）；
  目录可用 `TPMSMART_LOCALE_DIR` 覆盖；`Config/global.json` 是旧版语言文件的回退路径。
* 选择优先级：用户设置 > `TPMSMART_LANG` > 系统语言 > `zh-Hans` > `en` > 键名本身。
* 键命名规律：`msg_set_*` / `msg_tpm_*` / `msg_bak_*` / `msg_rec_*` / `msg_cert_*`、按钮 `b_*`、`theme_*`、`web_*`、
  以及表格列名（`card_name` / `cert_guid` / `pub_length` 等）。

## 7. 运行时路径与数据

| 用途 | 路径 | 备注 |
|---|---|---|
| 程序根目录 | 含 `Config` 子目录的那个目录 | 可用 `TPMSMART_HOME` 覆盖 |
| 用户设置 | `%APPDATA%\TPMSmartCard\settings.json` | 语言、主题等 |
| 备份 / 还原日志 | `%APPDATA%\TPMSmartCard\logs\<tag>-<时间戳>.log` | 另有 `enum-orphan-<uid>.reg` 等取证文件 |
| `.tsb` 备份包 | 用户自选；默认名 `卡片名-实例编号.tsb` | 格式见 `design-backup-restore.md` §2 |
| Web 证书缓存 | `<程序根>\Caches\PullCerts.pkl` | 先写 `.tmp` 再 `os.replace` |
| 卡片数据（系统侧） | `%SystemRoot%\ServiceProfiles\LocalService\AppData\Local\Microsoft\Windows\SmartCard\Tpm\<store GUID>\` | 见 §8 |
| 设备节点（系统侧） | `HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\SMARTCARDREADER\<实例>` | `Properties` 子键受 ACL 保护 |

## 8. 卡片数据模型（本工程的核心认识）

一张可用的 TPM 虚拟智能卡由**五个部分**共同构成，缺任何一项都会表现为
「还原成功但卡片没出现 / 证书不显示」：

```
       ┌─────────────────────────────┐
       │ ① PnP 设备节点               │  Enum\ROOT\SMARTCARDREADER\<实例>
       │   （tpmvsc.dll + 模拟器驱动）│
       └──────────────┬──────────────┘
                      │ ④ 设备属性（ACL 保护）
                      │    {2065F23D-…},2 = store 路径
                      │    {2BEED4A8-…}   = 卡片名 / 驱动信息 ← 决定读卡器是否发布
                      ▼
       ┌─────────────────────────────┐        ┌──────────────────────────┐
       │ ② 卡片数据目录 store         │◀──────▶│ ③ TPM 密钥索引 *.PCPKEY   │
       │   keymaps / pinmaps /        │        │   「KSP 密钥名 → TPM 对象」│
       │   pinpolicy / blobs / fs     │        │   在 3 个候选目录下        │
       └──────────────┬──────────────┘        └──────────────────────────┘
                      │ ⑤ keymaps 等 5 个文件 = DPAPI blob（用户作用域，"TPMVSC"）
                      ▼
       ┌─────────────────────────────┐
       │ 源机 DPAPI 主密钥             │  ← 换机后不存在，必须"解密→重新加密"
       └─────────────────────────────┘
```

依赖关系（还原顺序即由此决定）：④ 决定读卡器是否发布 → ② 提供卡内数据 →
③ 让驱动找到卡上密钥 → ⑤ 决定密钥容器能否建起来（证书才会出现）。

## 9. 版本与发布

* **版本号单一来源**：`Module/Version.py` 的 `VERSION`（可用环境变量 `TPMSMART_VERSION` 覆盖），当前 `1.6.0`；
  `install.iss` 有环境变量兜底（`TPMSMART_VERSION` / `TPMSMART_VERSION4`）。
* 两条构建线：

| 线 | 脚本 | 产物 |
|---|---|---|
| cx_Freeze | `BuildPackage.py` | 3 个 exe（`SmartCardAPP` / `SmartCardWEB` / `CertImport`）+ 随包资源；经 `install.iss`（Inno Setup 6.5+）打成安装包 |
| Nuitka | `BuildNuitka.py` | standalone **目录**（刻意不用 `--onefile`）：`build/nuitka/TPMSmartCard/` |

* 签名：`Builds/Sign-Windows.ps1` + `CertumSigning.ps1`（signtool + Certum 云签名，TSA `time.certum.pl`）；
  未配置证书时优雅跳过，`TPMSMART_SIGN_REQUIRED=1` 时失败。
* CI：`build-client-release.yml`（cx_Freeze 线，push main → 滚动 beta 预发布；手动触发可发布正式版）与
  `build-client-nuitka.yml`（Nuitka 线，产物 zip 与前者按文件名区分）。
* 依赖固化：`requirements.txt`（运行时）与 `requirements-nuitka.txt`（追加 Nuitka 相关）。

## 10. 工程约定

1. **失败不得伪装成"没有"**：读不到数据要报错或明确告警，不允许静默返回空值后继续
   （历史上因此出过"厂商卡片身份 0 项"假警告、`os.walk` 静默丢文件等问题）。
2. **诊断要能落地**：备份 / 还原结果必须同时给出「结论 + 逐条日志 + 现场诊断」并落盘到日志文件，
   保证 GUI 下也能看到失败在哪一步。
3. **Win32 句柄与指针**：跨函数传递句柄前统一包 `c_void_p` 或声明 `argtypes`（64 位句柄被当 32 位
   `int` 会抛 `OverflowError`）。
4. **权限**：涉及设备节点注册、`ProgramData` 写入、DPAPI 令牌借用的功能都要求管理员。
5. **系统限制要写进使用说明**：建卡 / 删卡不能在任何远程会话（RDP / Terminal Services）里执行。

## 11. 已知的结构性待办

| 项 | 说明 |
|---|---|
| 大文件拆分 | `SmartCardAPP.py`（约 112 KB）与 `Module/TPMBackup.py`（约 108 KB）体量大，建议按「界面 / 流程 / 平台适配」再分层 |
| 测试缺口 | 无自动化测试目录；目前依赖 `Builds/*.ps1` 真机脚本与手工验收（见 `report-backup-restore.md` §9） |
| 文档缺口 | 用户手册、发布流程、云端下发协议、Web 端说明尚未编写（见 [`README.md`](README.md) 待补清单） |
