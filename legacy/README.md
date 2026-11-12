# legacy —— v1（Python）归档

本目录是 **v1.7.0** 的完整实现，作为 Go 版本（v2）的功能对照与回退路径。
对应的 Git 标签是 [`v1.7.0`](https://github.com/PIKACHUIM/TPMSmartCard/releases/tag/v1.7.0)。

## 目录内容

| 路径 | 说明 |
|---|---|
| `SmartCardAPP.py` | Tkinter 主程序（需管理员权限） |
| `SmartCardWEB.py` | Flask 证书下发服务（监听 `0.0.0.0:1080`） |
| `Module/` | 核心库：TPM 虚拟卡、OpenSC、DPAPI、备份、SSH、FIDO |
| `SubApp/` | 证书导入、系统设置等子程序 |
| `Config/` | 布局 JSON、11 语言包、主题、图标、随包字体 |
| `templates/` `static/` | Web 上传页 |
| `Builds/` `install.iss` `BuildPackage.py` `BuildNuitka.py` | 打包与签名脚本（cx_Freeze / Nuitka / Inno Setup） |
| `OpenSC/` `Import/` | 随包分发的 Windows 工具 |
| `SSHCardAgent.exe` | 历史外挂 SSH 代理（v1.7 已内建，仅留档） |

## 运行 v1

```powershell
# 1. 重建虚拟环境（x86 线用 -PythonVersion 3.10）
powershell -File Builds\NewVenv-PY313.ps1

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行（管理员）
python SmartCardAPP.py

# 4. 打包
python BuildPackage.py build      # cx_Freeze + Inno Setup
python BuildNuitka.py             # Nuitka standalone
```

> 脚本里的相对路径以 `legacy/` 为工作目录；`Module/Paths.py` 通过「含 `Config` 子目录的目录」
> 判定程序根目录，因此在 `legacy/` 下运行即可正确解析资源。

## 与 v2 的对应关系

| v1 | v2 |
|---|---|
| `Module/Cryptography.py` | `core/internal/crypto`（逐字节兼容） |
| `Module/TPMSmartCard.py` | `core/internal/platform/win32` |
| `Module/SmartCardAPI.py` | `core/internal/platform/p11` |
| `Module/TPMBackup.py` | `core/internal/backup` |
| `Module/SSHAgent.py` | `core/internal/sshagent`（协议层） |
| `Fido/src/fido-go` | 保持原位的独立 Go 模块，由 CI 构建 |
| `Config/locales/*.json` | `web/src/locales/*.json` |

## 注意

- v1 只支持 Windows；`tpmvscmgr` 建卡/删卡禁止在远程桌面会话中执行（`0x800704d3`）。
- `.tsb` 备份绑定同一颗 TPM，删卡后不可还原。
- 本目录不再接收功能更新，只做安全修复（如有）。
