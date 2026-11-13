# 开发与调试指南

## 1. 环境

| 项 | 值 |
|---|---|
| Python | **3.13**（x64 `exe.win-amd64-3.13`、arm64 `exe.win-arm64-3.13`）、**3.10**（x86 `exe.win32-3.10`）、**3.14**（Nuitka 线，无 cx_Freeze） |
| 重建虚拟环境 | `Builds/NewVenv-PY313.ps1`（x86 线用 `-PythonVersion 3.10`） |
| 依赖 | `pip install -r requirements.txt`；打包加 `-r requirements-nuitka.txt` |
| 主要第三方依赖 | `ttkbootstrap`、`cryptography`、`pyOpenSSL`、`Flask`、`pywin32`、`comtypes`、`pywinpty`、`pyglet`、`tkcalendar`、`pyperclip`、`python-dateutil`、`cx_Freeze`、`pillow`、`lief`、`babel` |
| 依赖自查 | `python Builds/check_imports.py`（第三方 import 是否可导入、发行包是否已写入 `requirements.txt`） |

## 2. 运行

| 目标 | 命令 | 备注 |
|---|---|---|
| 主程序 | `python SmartCardAPP.py`（**管理员**） | `--minimized` 只驻留托盘 |
| Web 端 | `python SmartCardWEB.py` | 监听 `0.0.0.0:1080`，浏览器打开 `http://127.0.0.1:1080/web/cert` |
| 证书导入子程序 | `python SubApp/CertImport.py`（管理员） | |
| 辅助配置子程序 | `python SubApp/MoreConfig.py` | |
| 备份/还原自检 | 直接运行 `Module/TPMBackup.py`（含 `__main__` 自检入口） | |
| 语言包自检 | 直接运行 `Module/I18n.py` | |

常用环境变量：

| 变量 | 作用 |
|---|---|
| `TPMSMART_HOME` | 覆盖程序根目录判定（默认取含 `Config` 的那个目录） |
| `TPMSMART_LANG` | 强制语言 |
| `TPMSMART_LOCALE_DIR` | 覆盖语言包目录 |
| `TPMSMART_VERSION` | 覆盖版本号（打包时注入） |
| `TPMSMART_SIGN_REQUIRED` | 置 `1` 时签名失败即构建失败 |

## 3. 打包

| 方式 | 命令 | 产物 |
|---|---|---|
| cx_Freeze（主用） | `python BuildPackage.py build`（管理员） | 3 个 exe + 随包资源；构建结束会自动调用签名脚本 |
| 一键 bat | `Builds/BuildPackage-PY308-Win32/Win64.bat`、`Builds/BuildPackage-PY312-Win64.bat` | 同上，自动提权 |
| Nuitka | `python BuildNuitka.py` | `build/nuitka/TPMSmartCard/`（standalone 目录，**不用** `--onefile`） |
| 安装包 | `Builds/Build-Installer.ps1`（内部调 `iscc install.iss`） | `dist\<PackageName>-setup.exe`，默认 `TPMSmartCard-win64-setup.exe` |
| 签名 | `Builds/Sign-Windows.ps1` + `CertumSigning.ps1` | signtool + Certum 云签名，TSA `http://time.certum.pl`；未配置证书时优雅跳过 |

版本号单一来源：`Module/Version.py` 的 `VERSION`（当前 `1.6.0`）；`install.iss` 有环境变量兜底。

## 4. CI

| 工作流 | 触发 | 产物 |
|---|---|---|
| `.github/workflows/build-client-release.yml` | push `main` → 覆盖发布到滚动预发布 `beta`；`workflow_dispatch` 可发正式 Release（可草稿） | 绿色版 zip + Inno 安装包；含版本唯一性校验；Certum 签名需三个 Secrets 配齐 |
| `.github/workflows/build-client-nuitka.yml` | 改动 `BuildNuitka.py` / `requirements-nuitka.txt` / 该 yml | `TPMSmartCard-nuitka-beta-win64.zip`（与 cx_Freeze 产物按文件名区分） |

## 5. 代码约定

1. **失败不得伪装成"没有"**：读不到数据要么报错、要么给出明确告警；禁止静默返回空值后当作正常继续。
   读取类接口建议「失败返回 `None`、确实为空返回 `[]`」。
2. **结果要三段可读**：结论（可执行的一句话）+ 逐条日志（过程）+ 现场诊断（可复核的事实），
   并落盘到 `%APPDATA%\TPMSmartCard\logs\`。日志里成功的重复细节收敛成一行，失败保留完整原因。
3. **Win32 互操作**：句柄跨函数传递前包 `c_void_p` 或声明 `argtypes`（64 位句柄按 `int` 传给 ctypes 会抛
   `OverflowError`）；`ctypes` 的数组（如 `c_byte * 16`）不是 `bytes`，格式化前先 `bytes(...)`。
4. **权限**：需要管理员的功能要在清单/入口声明，缺权限时给出明确提示而不是崩溃。
5. **多语言**：新增界面文案必须走 `Config/locales/*.json`，键名遵循既有前缀
   （`msg_*` / `b_*` / `theme_*` / `web_*`）；至少同步 `zh-Hans` / `zh-Hant` / `en`。
6. **文档同步**：行为变化同时更新 `docs/` 下对应文档；过程与证据写进 `devlog-*`。
7. **提交信息**：`type(scope): 中文描述`（`type` 用 `feat/fix/docs/build/chore` 等）。

## 6. 真机调试方法（本项目最容易踩的部分）

Windows 的智能卡子系统对**会话类型**和**调用者身份**很敏感，本地复现不了的坑基本都出在这里：

| 事项 | 限制 | 正确做法 |
|---|---|---|
| 建卡 / 删卡（`tpmvscmgr`） | 远程会话、SSH 会话、服务会话都会被拒（`0x800704d3` / `0x80070005`） | 在本机控制台执行；脚本化时用计划任务并勾选「只在用户登录时运行」（`schtasks /it`）落到交互会话 |
| 枚举读卡器（`SCardListReaders` / PC/SC） | 非交互会话返回 `ERROR_ACCESS_DENIED` | 同上，在交互会话里跑探针，把结果写到文件再读 |
| 读取设备属性（`{2065F23D-…}` / `{2BEED4A8-…}`） | `Enum\…\Properties` 受 ACL 保护，`reg query`/`reg export` 读不到 | 走 PnP 属性接口：`SetupDiGetDevicePropertyKeys` / `SetupDiGetDevicePropertyW`（`CM_Get_DevNode_PropertyKeys` 在 `cfgmgr32` 里没有导出，别用） |
| DPAPI（卡片 `keymaps` 等） | 数据由服务账户（SYSTEM）写入，管理员直接解密会失败（`err=-2146893813`） | 借一次 SYSTEM 令牌再调 `CryptProtectData` / `CryptUnprotectData`；借到后做一次往返探针确认可用 |
| 判断"是否同一颗 TPM" | — | 比对 EK 指纹（备份清单里记录了源机的型号/厂商/EK 指纹） |
| 判断设备节点是否真被创建 | `reg import` 返回成功**不代表**设备存在 | 用 `CM_Locate_DevNodeW` 查 PnP 设备树，或 `pnputil /enum-devices` |

**调试脚本的卫生要求**：临时脚本不得把口令、密钥写进仓库或长期留在磁盘上；用完即删
（历史上用过编译 `askpass` 的临时 SSH 助手脚本，均已按此约定清理）。留在测试机上的计划任务要
**禁用或删除**，避免被定时触发。

## 7. 工程清理记录

### 7.1 已移除的历史遗留（本轮）

按「零引用 + 有替代」的标准逐项核实后移除；括号内为核实依据。

| 移除项 | 依据 | 替代 |
|---|---|---|
| `MoreConfig.exe`（7.1 MB） | 全仓库无 `startfile`/`Popen` 启动点；主程序走 `from SubApp.MoreConfig import MoreConfig` | 源码 `SubApp/MoreConfig.py`（`__main__` 仍可单独运行） |
| `MoreConfig.spec` | 仅为上面那个 exe 的 PyInstaller 配方 | 需要时可用源码重建 |
| `tpmvscmgr.exe`（仓库副本） | `Module/TPMSmartCard.py` 只用 `%SystemRoot%\System32\tpmvscmgr.exe`，无回退 | 系统自带（Windows 8+） |
| `install.aip`（550 KB） | Advanced Installer 工程，无任何 CI/脚本编译；`install.iss` 是唯一在用安装脚本 | `install.iss`（Inno Setup） |
| `install.rtf` | 全仓库 0 引用（Advanced Installer 许可文件残留） | — |
| `Module/CustomDateEntry.py` | 无任何 `import`；文件自述"当前主程序使用 ttkbootstrap.DateEntry" | ttkbootstrap `DateEntry` |
| `Config/install.bat` | 无代码/脚本调用；choco 逻辑已内联在 `SubApp/MoreConfig.py` | 内联实现 |
| `Images/20240901-185515.png` | 未被 README 或文档引用 | README 用另一张截图 |
| `Import/TPMImport.pdb` | C# 工具调试符号，运行期不需要 | — |
| `SubApp/__pycache__/*.pyc`（3 个） | 误提交的字节码缓存（`.gitignore` 已覆盖 `__pycache__`） | 运行/打包时自动重建 |

同步修改：`BuildPackage.py`（`include_files`）、`BuildNuitka.py`（`RESOURCE_FILES` 与产物布局注释）。

### 7.2 明确保留（有引用或属发行必需）

`SSHCardAgent.exe`（运行期启动 SSH 代理）、`OpenSC/*.exe` 与 `opensc.dll`（读卡后端）、
`OpenSC/*.msi`（安装包可选组件 + 程序内按需安装）、`Setups/`（安装包编译与安装前置，缺失会导致
ISCC 编译失败）、`Import/TPMImport.exe` 及其 DLL/JSON（证书导入，运行期调用）、`install.iss`、
`ChineseSimplified.isl`、`Config/tsb.reg`、`LICENSE`、`Images/20241025-115000.png`。

### 7.3 待确认（需要功能决策，未擅自处理）

| 项 | 现状 | 建议 |
|---|---|---|
| `Fix-MsiPolicy.ps1` / `.bat` | 仅互相引用，无构建/CI/应用引用；用于 OpenSC MSI 安装失败（1625 / `0x80070659`）的手工排障 | 体积小、有排障价值，**建议保留**；若确定不再需要可删 |
| `Module/CertutilDeal.py` | 仅被 `Module/SmartCardAPI.py` 的 `else` 分支引用，而 `use_opensc` 全仓库无 `False` 调用 → 事实上的死分支 | 若确认不再保留 certutil 读卡后端，可连同该分支一起删；否则保留 |
| `SSHCardAgent.exe`（4.1 MB） | 随包分发；另有 `choco install wincrypt-sshagent` 的在线安装路径 | 若可接受"在线安装"，可改为按需安装以减小安装包；离线场景建议保留 |
| `build/`（约 159 MB） | 本地构建产物（`.gitignore` 已忽略）；`install.iss` 默认从 `build\exe.win-amd64-3.13` 取文件（按架构还有 `exe.win32-3.10` / `exe.win-arm64-3.13`） | 出安装包前不要删，其余时间可清理 |
| `.idea/`、`dist/`、`Caches/` | 本地/运行时产物，均已被 `.gitignore` 覆盖 | 无需处理 |
