<div align="center">
# TPM Virtual Smartcard Manager

_A graphical tool for creating and managing TPM Virtual Smart Cards on Windows_

<img src="../Images/QQ20261016-184916.png" width="760" alt="TPM Virtual Smartcard Manager">



TPM-based virtual smart cards offer security close to physical smart cards: the private key is protected by the TPM and is never exported in plaintext

Generate keys and CSRs locally, or deliver certificates securely from the cloud — a replacement for the PIV needs of physical cards such as YubiKey and ePass


[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](../LICENSE)
[![Build](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml/badge.svg)](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml)
[![Release](https://img.shields.io/github/v/release/PIKACHUIM/TPMSmartCard?include_prereleases&label=release)](https://github.com/PIKACHUIM/TPMSmartCard/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%208%2B-0078D6.svg)](#-requirements)

📘 [Documentation index](../docs/README.md) · 🧭 [Architecture](../docs/architecture.md) · 💾 [Backup & restore design](../docs/design-backup-restore.md) · 🛠️ [Troubleshooting](../docs/troubleshooting.md) · 🔐 [Security model](../docs/security.md)

English | [简体中文](../README.md) | [繁體中文](README_zh-Hant.md) | [日本語](README_ja.md) | [한국어](README_ko.md)<br>[Deutsch](README_de.md) | [Français](README_fr.md) | [Italiano](README_it.md) | [Português](README_pt.md) | [Русский](README_ru.md) | [Español](README_es.md)
</div>
---

## ✨ Features

### Cards and credentials

* **Virtual smart cards**: create and delete cards; change or reset PIN, PUK and admin key
* **Certificates and keys**: import, delete and inspect X.509 certificates and on-card key objects; view certificate chains and key usages
* **Generation and delivery**: generate key + CSR locally and get it signed, or receive certificates securely from the cloud (X25519 key agreement + AES, pickup code delivered out of band)

### Backup and restore

* **Full-card backup**: package a card into a `.tsb` (card data + device registry + TPM key index + device properties + DPAPI plaintext)
* **Same-TPM restore**: a backup can only be restored on the **same TPM** (reinstalling Windows on that machine works; **another machine / another TPM does not**, and **a deleted card cannot be restored**); DPAPI data is decrypted when backing up and re-encrypted with the local master key when restoring (see [backup & restore design](../docs/design-backup-restore.md))
* **Restore diagnostics**: after a restore the tool checks the device node / PC-SC reader / DPAPI layers and reports an actionable verdict with logs

### Scenarios and tools

* **SSH2 login**: use the on-card private key with WinCryptSSHAgent to log in to remote servers
* **Environment helpers**: install / start OpenSC and the SSH agent, inspect TPM status, export certificates and public keys
* **Localized UI**: 11 languages (Simplified Chinese / Traditional Chinese / English / 日本語 / 한국어 / Deutsch / Français / Italiano / Português / Русский / Español)

---

## 🚀 Quick start

1. Download `TPMSmartCard-*-setup.exe` (or the portable zip) from [Releases](https://github.com/PIKACHUIM/TPMSmartCard/releases) and install it;
2. **Run as administrator** (registering card devices and reading/writing system folders require administrator rights);
3. Create a card in "Card Management" → import or generate a certificate → (optional) install and start the SSH agent in "System Settings";
4. Backup: select a card → Backup to get a `.tsb`; Restore: select a `.tsb` → Restore.

> [!IMPORTANT]
> **Creating / deleting a virtual smart card cannot be done inside a Remote Desktop (Terminal Services) session**; Windows rejects it with `0x800704d3`.
> Use the local console, or connect with `mstsc /admin`.

> [!TIP]
> The [OpenSC](https://github.com/OpenSC/OpenSC/releases) tools needed for reading cards are **bundled with the app** (the `OpenSC` folder next to the program),
> so no separate installation is required; the system-wide OpenSC component in the installer is optional and only benefits other software (PKCS#11 clients, physical-card minidrivers, etc.).

---

## 🧩 Requirements

| Item | Requirement |
|---|---|
| OS | Windows 8 x86 / x64 or later (**administrator rights required**) |
| Hardware | TPM 1.2 / 2.0 or later |
| System components | `tpmvscmgr`, `certutil` (bundled with Windows) |
| Bundled components | OpenSC tools, WinCryptSSHAgent, `Import` (.NET certificate import tool) |

---

## 🏗️ Architecture

| Aspect | Value |
|---|---|
| Language / runtime | Python **3.11** |
| UI | Tkinter + ttkbootstrap (UI built entirely in code; layouts driven by `Config/*.json`) |
| Card operations | `tpmvscmgr` (create / delete / change PIN) + OpenSC (card and certificate reading) + in-house PnP / SetupAPI layer (device nodes and properties) |
| Backup and restore | in-house `.tsb` (zip) packaging; `Module/DPAPI.py` handles DPAPI encryption/decryption and token impersonation |
| Packaging | two pipelines: **cx_Freeze** (release builds, installer via Inno Setup) and **Nuitka** (standalone folder) |
| Localization | `Config/locales/*.json`, 11 languages |

---

## 🛠️ Development and building

```bash
# 1. Prepare a Python 3.11 environment (a helper script is included)
powershell -File Builds\NewVenv-PY313.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run directly from source (administrator rights required)
python SmartCardAPP.py

# 4. Build
python BuildPackage.py build      # cx_Freeze: three executables + bundled resources
python BuildNuitka.py             # Nuitka: build/nuitka/TPMSmartCard/
```

* Dependency self-check: `python Builds/check_imports.py`
* Full development guide (running, packaging, signing, CI, on-device debugging): [development guide](../docs/dev-guide.md)
* Module layout and responsibilities: [architecture](../docs/architecture.md)

---

## 💾 Backup and restore

A usable TPM Virtual Smart Card consists of **five parts**, and a `.tsb` captures all of them:

| Part | Content | If missing |
|---|---|---|
| Card data folder | `Tpm\<store GUID>\` (card filesystem and key / PIN maps) | Card has no content |
| Device registry | `ROOT\SMARTCARDREADER\<instance>` and related keys | Device node cannot be created |
| TPM key index | `*.PCPKEY` (3 candidate folders) | Driver cannot find the card keys |
| Device properties | card name, card GUID, store binding (ACL-protected; registry export cannot read them) | Reader is not published to PC/SC |
| DPAPI plaintext | plaintext of `keymaps` / `pinmaps` / `pinpolicy` / `blobs\*` (re-encrypted on the target machine) | Certificates and private key do not show up |

> [!WARNING]
> Because the last item is included, a `.tsb` is **equivalent to card key material**: keep it safe offline and never put it into version control, cloud drives or chat tools.
> On restore the tool re-encrypts it with the target machine's DPAPI before writing it back; keep the card name, PIN, PUK and admin key safe as well.

Other notes:

* **Preconditions**: the **same TPM** is required (a clean reinstall on that machine works; another machine or another TPM does not), and the **card must not have been deleted**
  — deleting a card removes its persistent TPM key, so even a backup cannot bring it back;
* After a restore you **may need to restart the device (driver) or reboot Windows** before the card appears in the reader list;
* `.tsb` files created by older versions lack the device properties and DPAPI plaintext: restoring them leaves the card identity missing and the reader will not appear — create a fresh backup with the current version.

---

## ❓ FAQ

**Q: Why does creating a card fail inside a Remote Desktop session with `0x800704d3`?**
A: Windows forbids creating / deleting virtual smart cards in a Terminal Services session. Use the local console, or connect with `mstsc /admin`.

**Q: Can a backup be restored on another machine?**
A: **No.** A backup only applies to the **same TPM**: it works after reinstalling Windows on that machine, but not on another machine or another TPM; and a **deleted card**
**cannot be restored** (deleting a card removes its persistent TPM key). If the card does not appear after a restore, restart the device or reboot first.

**Q: After a restore the card does not show up. What should I do?**
A: **Restart first**: the card may need a device (driver) restart or a system reboot before it appears in the reader list. If it still does not appear,
read the three-layer verdict in the restore log (device node / reader / DPAPI): the usual causes are a backup made by an older version or missing card identity properties — follow the [troubleshooting guide](../docs/troubleshooting.md).

**Q: After a restore the reader does not appear, or certificates do not show up. What now?**
A: Read the three-layer verdict in the restore log (device node / reader / DPAPI). The most common causes are a backup made by an older version or missing card identity properties;
follow the [troubleshooting guide](../docs/troubleshooting.md) step by step, or attach the log to an issue.

**Q: Does it need a network connection?**
A: Everything works offline except "cloud certificate delivery".

**Q: The certificate chain reports `CERT_E_CHAINING`?**
A: The issuing intermediate CA is not installed on this machine — import it into the trusted root/intermediate store.

---

## 🤝 Support

* 🐛 **Bugs or feature requests**: open an [issue](https://github.com/PIKACHUIM/TPMSmartCard/issues) (please attach the logs under `%APPDATA%\TPMSmartCard\logs\`)
* 💬 **Usage questions**: also welcome in the issue tracker

---

## 📄 License

This project is released under the **GPL-3.0** license. See [LICENSE](../LICENSE).

## 🙏 References

1. [OpenSC/OpenSC](https://github.com/OpenSC/OpenSC) — open source smart card tools and middleware
2. [Microsoft Docs: Virtual Smart Cards](https://github.com/MicrosoftDocs/windows-itpro-docs/tree/public/windows/security/identity-protection/virtual-smart-cards)
3. WinCryptSSHAgent — an SSH agent backed by smart card private keys



