# legacy —— 原 Python 实现（归档说明）

本目录用于归档 **v1.x 的 Python 实现**，作为 Go 版本的功能对照与回退路径。

## 当前状态

P0/P1 阶段 Python 代码仍保留在仓库根目录（`SmartCardAPP.py`、`SmartCardWEB.py`、
`Module/`、`SubApp/`、`Config/`、`templates/`、`static/`、`Builds/`、`install.iss`），
原因有两条：

1. `.github/workflows/build-client-*.yml` 仍以根目录为构建上下文，立即移动会让现网发布流水线中断；
2. Go 版本达到功能对等（P1 验收）之前，Python 版本是唯一的可用产物。

## 归档计划（P2 执行）

当 P1 验收清单逐项通过后，按下列顺序整体迁移，并在一次提交中完成：

```bash
git mv SmartCardAPP.py SmartCardWEB.py Module SubApp Config templates static \
       Builds install.iss BuildNuitka.py BuildPackage.py \
       requirements.txt requirements-nuitka.txt ChineseSimplified.isl \
       legacy/
```

迁移后需要同步修改：

| 位置 | 改动 |
|---|---|
| `.github/workflows/build-client-*.yml` | 构建上下文改为 `legacy/`，或直接停用（由新 Go 流水线取代） |
| `docs/dev-guide.md` | 命令前缀加 `legacy/` |
| `README.md` | 标注「v1（Python，维护模式）/ v2（Go，主线）」 |

## 对照用途

`core/` 的 Go 实现以 Python 模块为行为基准，禁止「顺手优化」改变外部行为：

| Python | Go 对应 |
|---|---|
| `Module/Cryptography.py` | `core/internal/crypto`（协议逐字节兼容） |
| `Module/TPMSmartCard.py` | `core/internal/platform/win32` |
| `Module/SmartCardAPI.py` | `core/internal/platform/p11` |
| `Module/TPMBackup.py` | `core/internal/backup` |
| `Module/SSHAgent.py` | `core/internal/sshagent` |
| `Fido/src/fido-go` | `core/internal/fido`（直接搬迁） |
| `Config/locales/*.json` | `web/src/locales/*.json`（键名不变） |
