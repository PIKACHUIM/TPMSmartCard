# 开发方式

面向要改代码、出安装包的人。工程侧更细的约定见
[架构说明](/architecture)、[开发与调试指南](/dev-guide)、[安全模型](/security)。

## 1. 技术栈与代码结构

| 维度 | 取值 |
|---|---|
| 语言 / 运行时 | Python **3.13**（x64 / arm64 线）、**3.10**（x86 / 低版本系统线）、**3.14**（Nuitka 线） |
| 界面 | Tkinter + ttkbootstrap（`pyglet` 仅用于注册字体），界面**纯代码构建**，无 `.ui` 文件 |
| 卡片操作 | `tpmvscmgr` + OpenSC（随包）+ 自研 PnP / SetupAPI 层 + `certutil` / `certreq` |
| Web 端 | Flask（`SmartCardWEB.py`，云端下发证书的接收端） |
| 打包 | cx_Freeze（主用，Inno Setup 出安装器）+ Nuitka（standalone 目录） |
| 依赖清单 | `requirements.txt`（运行）、`requirements-nuitka.txt`（追加打包依赖） |

```
SmartCardAPP.py         GUI 主程序（入口，最大文件）
SmartCardWEB.py         云端下发接收端（Flask）
Module/                 核心库：卡片、读卡、备份还原、DPAPI、多语言、路径与版本
SubApp/                 子程序：CertImport（证书导入）、MoreConfig、SystemSettings
Config/                 界面布局与文案（*.json）、locales/*.json、图标与字体
Builds/                 构建与真机调试脚本（ps1 / bat / py）
.github/workflows/      CI：cx_Freeze 线、Nuitka 线、各架构
docs/                   文档（含本站）
```

模块职责的完整划分见[架构说明 §3](/architecture#_3-模块分层)。

## 2. 环境准备

```powershell
# 1. 重建虚拟环境（x64/arm64 用 3.13；x86 或低版本系统用 -PythonVersion 3.10）
powershell -File Builds\NewVenv-PY313.ps1

# 2. 安装依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. 依赖自查：第三方 import 是否都能导入、发行包是否都已写入 requirements.txt
.\.venv\Scripts\python.exe Builds\check_imports.py
```

主要第三方依赖：`ttkbootstrap`、`cryptography`、`pyOpenSSL`、`Flask`、`pywin32`、`comtypes`、
`pywinpty`、`pyglet`、`tkcalendar`、`pyperclip`、`python-dateutil`、`cx_Freeze`、`pillow`、`lief`、`babel`。

## 3. 运行与自检

| 目标 | 命令 | 备注 |
|---|---|---|
| 主程序 | `python SmartCardAPP.py` | **必须管理员**；`--minimized` 只驻留托盘 |
| Web 端 | `python SmartCardWEB.py` | 监听 `0.0.0.0:1080`，浏览器访问 `http://127.0.0.1:1080/web/cert` |
| 证书导入子程序 | `python SubApp/CertImport.py` | 需要管理员 |
| 辅助配置子程序 | `python SubApp/MoreConfig.py` | `__main__` 可单独运行 |
| 备份 / 还原自检 | `python Module/TPMBackup.py` | 含 `__main__` 自检入口 |
| 语言包自检 | `python Module/I18n.py` | 校验 11 种语言包的加载与回退 |

常用环境变量：

| 变量 | 作用 |
|---|---|
| `TPMSMART_HOME` | 覆盖程序根目录判定（默认取含 `Config` 的那个目录） |
| `TPMSMART_LANG` | 强制界面语言 |
| `TPMSMART_LOCALE_DIR` | 覆盖语言包目录 |
| `TPMSMART_VERSION` | 覆盖版本号（打包时注入） |
| `TPMSMART_SIGN_REQUIRED` | 置 `1` 时签名失败即构建失败 |

## 4. 打包与发布

| 方式 | 命令 | 产物 |
|---|---|---|
| cx_Freeze（主用） | `python BuildPackage.py build`（管理员） | 3 个 exe（`SmartCardAPP` / `SmartCardWEB` / `CertImport`）+ 随包资源，构建结束自动调用签名脚本 |
| 一键 bat | `Builds/BuildPackage-PY308-Win32/Win64.bat`、`Builds/BuildPackage-PY312-Win64.bat` | 同上，自动提权 |
| Nuitka | `python BuildNuitka.py` | `build/nuitka/TPMSmartCard/`（standalone 目录，**刻意不用 `--onefile`**） |
| 安装包 | `Builds/Build-Installer.ps1`（内部调 `iscc install.iss`） | `dist\<PackageName>-setup.exe` |
| 签名 | `Builds/Sign-Windows.ps1` + `CertumSigning.ps1` | signtool + Certum 云签名，TSA `http://time.certum.pl`；未配置证书时优雅跳过 |

* **版本号单一来源**：`Module/Version.py` 的 `VERSION`（当前 `1.6.0`，可用 `TPMSMART_VERSION` 覆盖）；
  `install.iss` 有环境变量兜底（`TPMSMART_VERSION` / `TPMSMART_VERSION4`）；
* **CI 工作流**：

  | 工作流 | 触发 | 产物 |
  |---|---|---|
  | `build-client-release.yml` | push `main` → 覆盖发布到滚动预发布 `beta`；手动触发可发正式 Release（可草稿） | 绿色版 zip + Inno 安装包；含版本唯一性校验 |
  | `build-client-release-x86.yml` / `-arm64.yml` | 各架构线 | 对应架构的 zip 与安装包 |
  | `build-client-nuitka.yml` | 改动 `BuildNuitka.py` / `requirements-nuitka.txt` / 该 yml | `TPMSmartCard-nuitka-beta-win64.zip` |
  | `build-docs.yml` | 改动 `docs/**` | 文档站（GitHub Pages），见 [文档站部署](/guide/deploy-docs) |

## 5. 代码约定（改代码前先看）

1. **失败不得伪装成"没有"**：读不到数据要么报错、要么给出明确告警；禁止静默返回空值后当作正常继续。
   读取类接口建议「失败返回 `None`、确实为空返回 `[]`」。
2. **结果要三段可读**：结论（可执行的一句话）+ 逐条日志（过程）+ 现场诊断（可复核的事实），
   并落盘到 `%APPDATA%\TPMSmartCard\logs\`。成功的重复细节收敛成一行，失败保留完整原因。
3. **Win32 互操作**：句柄跨函数传递前包 `c_void_p` 或声明 `argtypes`（64 位句柄按 `int` 传给 ctypes
   会抛 `OverflowError`）；`ctypes` 的数组（如 `c_byte * 16`）不是 `bytes`，格式化前先 `bytes(...)`。
4. **权限**：需要管理员的功能要在清单 / 入口声明，缺权限时给出明确提示而不是崩溃。
5. **多语言**：新增界面文案必须走 `Config/locales/*.json`，键名遵循既有前缀
   （`msg_*` / `b_*` / `theme_*` / `web_*`），至少同步 `zh-Hans` / `zh-Hant` / `en`。
6. **文档同步**：行为变化同时更新 `docs/` 下对应文档；过程与证据写进 `devlog-*`。
7. **提交信息**：`type(scope): 中文描述`（`type` 用 `feat/fix/docs/build/chore` 等）。

## 6. 真机调试：本项目最容易踩的部分

Windows 的智能卡子系统对**会话类型**与**调用者身份**很敏感，本地复现不了的坑基本都在这里：

| 事项 | 限制 | 正确做法 |
|---|---|---|
| 建卡 / 删卡（`tpmvscmgr`） | 远程会话、SSH 会话、服务会话都会被拒（`0x800704d3` / `0x80070005`） | 在本机控制台执行；脚本化时用计划任务并勾选「只在用户登录时运行」落到交互会话 |
| 枚举读卡器（PC/SC） | 非交互会话返回 `ERROR_ACCESS_DENIED` | 同上；把探针结果写到文件再读 |
| 读设备属性（`{2065F23D-…}` / `{2BEED4A8-…}`） | `Enum\…\Properties` 受 ACL 保护，`reg query` / `reg export` 读不到 | 走 PnP 属性接口：`SetupDiGetDevicePropertyKeys` / `SetupDiGetDevicePropertyW` |
| DPAPI（卡上 `keymaps` 等） | 数据由服务账户（SYSTEM）写入，管理员直接解密会失败 | 借一次 SYSTEM 令牌再调 `CryptProtectData` / `CryptUnprotectData`，借到后做往返探针 |
| 判断设备节点是否真被创建 | `reg import` 返回成功**不代表**设备存在 | 用 `CM_Locate_DevNodeW` 查 PnP 设备树，或 `pnputil /enum-devices` |
| 判断"是否同一颗 TPM" | — | 比对 EK 指纹（备份清单里记录了源机的型号 / 厂商 / EK 指纹） |

**调试脚本的卫生要求**：临时脚本不得把口令、密钥写进仓库或长期留在磁盘上，用完即删；
留在测试机上的计划任务要禁用或删除，避免被定时触发。相关约定见
[开发与调试指南 §6](/dev-guide#_6-真机调试方法-本项目最容易踩的部分)。

## 7. 文档与本站

* 工程文档统一放在 `docs/`，文件名用小写英文 + 连字符，**结论与过程分离**
  （结论进正式文档，逐日过程进 `devlog-*`）；
* 本文档站（VitePress）的源码就在 `docs/` 下：新增页面 = 在 `docs/guide/` 里加一个 `.md`，
  再到 `docs/.vitepress/config.mts` 的 `sidebar` 里登记；
* 本地预览：`cd docs && npm install && npm run docs:dev`；
* 部署方式见 [文档站部署](/guide/deploy-docs)。
