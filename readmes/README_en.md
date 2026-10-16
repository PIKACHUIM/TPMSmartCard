<img src="../Images/QQ20261016-184916.png" width="760" alt="TPM Virtual Smart Cards Manager">

_A graphical tool for creating and managing TPM Virtual Smart Cards on Windows_

TPM Virtual Smart Cards offer security close to physical smart cards: the private key is protected by
the TPM and is never exported in plaintext. Keys and CSRs can be generated locally, or certificates can
be delivered securely from the cloud. It can partially replace the PIV/SSH usage of physical cards such
as YubiKey or ePass (SSL mutual authentication, BitLocker, EFS, SSH2 login, and more).

[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](../LICENSE)
[![Build](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml/badge.svg)](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml)
[![Release](https://img.shields.io/github/v/release/PIKACHUIM/TPMSmartCard?include_prereleases&label=release)](https://github.com/PIKACHUIM/TPMSmartCard/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%208%2B-0078D6.svg)](#-requirements)

📘 [Documentation index](../docs/README.md) · 🧭 [Architecture](../docs/architecture.md) · 💾 [Backup & restore design](../docs/design-backup-restore.md) · 🛠️ [Troubleshooting](../docs/troubleshooting.md) · 🔐 [Security model](../docs/security.md)

English | [简体中文](../README.md)

---

## ✨ Features

### Cards and credentials

* **Virtual smart cards**: create and delete cards; change or reset PIN, PUK and admin key
* **Certificates and keys**: import, delete and inspect X.509 certificates and on-card key objects
* **Generation and delivery**: generate key + CSR locally, or receive certificates securely from the cloud (X25519 key agreement + AES, with an out-of-band pickup code)

### Backup and restore

* **Full-card backup**: package a card into a `.tsb` (card data + device registry + TPM key index + device properties + DPAPI plaintext)
* **Cross-machine restore**: restore on **another machine** or after a **clean reinstall**; DPAPI data is decrypted on the source machine and re-encrypted with the target machine's key ([design notes](../docs/design-backup-restore.md))
* **Restore diagnostics**: after a restore the tool checks device node, PC/SC reader and DPAPI layers and reports an actionable verdict

### Scenarios and tools

* **SSH2 login**: use the on-card private key with WinCryptSSHAgent
* **Environment helpers**: install/start OpenSC and the SSH agent, inspect TPM status, export certificates
* **Localized UI**: 11 languages (Simplified/Traditional Chinese, English, Japanese, Korean, German, French, Italian, Portuguese, Russian, Spanish)

---

## 🚀 Quick start

1. Download `TPMSmartCard-*-setup.exe` (or the portable zip) from [Releases](https://github.com/PIKACHUIM/TPMSmartCard/releases);
2. **Run as administrator** (registering card devices and writing system paths require elevation);
3. Create a card, then import or generate a certificate; optionally install and start the SSH agent in Settings;
4. Backup: select a card → Backup (produces a `.tsb`). Restore: select a `.tsb` → Restore.

> [!IMPORTANT]
> Creating or deleting a virtual smart card **cannot be done inside a Remote Desktop (Terminal Services) session**;
> Windows rejects it with `0x800704d3`. Use the local console, or connect with `mstsc /admin`.

> [!TIP]
> The [OpenSC](https://github.com/OpenSC/OpenSC/releases) tools needed for reading cards are **bundled with the app**
> (the `OpenSC` folder next to the program) — no separate installation is required. The optional system-wide OpenSC
> component exists only for other software (PKCS#11 clients, physical-card minidrivers).

---

## 💾 About backup and restore (`.tsb`)

A usable TPM Virtual Smart Card consists of **five parts**, and a `.tsb` captures all of them:

| Part | Content | If missing |
|---|---|---|
| Card data folder | `Tpm\<store GUID>\` (card filesystem, key/PIN maps) | Card has no content |
| Device registry | `ROOT\SMARTCARDREADER\<instance>` and related keys | Device node cannot be created |
| TPM key index | `*.PCPKEY` (3 candidate folders) | Driver cannot find the card keys |
| Device properties | card name, card GUID, store binding (ACL-protected; registry export cannot read them) | Reader is not published to PC/SC |
| DPAPI plaintext | plaintext of `keymaps` / `pinmaps` / `pinpolicy` / `blobs\*` (re-encrypted on the target machine) | Certificates and private key do not show up |

> [!WARNING]
> Because of the last item, a `.tsb` is **equivalent to key material**: keep it offline and never put it into
> version control, cloud drives or chat tools. The tool re-encrypts it with the target machine's DPAPI on restore;
> keep the card name, PIN, PUK and admin key safe as well.

Other notes:

* After moving to another machine or reinstalling Windows, the **reader, card and certificates** can be restored.
  Whether the **on-card private key** remains usable depends on the target machine — verify with a signature test
  using the PIN, and re-issue the certificate if needed.
* `.tsb` files created by older versions lack the device properties and DPAPI plaintext, so they cannot be used for
  cross-machine restores; create a fresh backup with the current version.

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
| UI | Tkinter + ttkbootstrap (UI built in code; layouts driven by `Config/*.json`) |
| Card operations | `tpmvscmgr` (create/delete/change PIN) + OpenSC (card and certificate reading) + in-house PnP/SetupAPI layer (device nodes and properties) |
| Backup & restore | in-house `.tsb` (zip) packaging; `Module/DPAPI.py` handles DPAPI encryption and token impersonation |
| Packaging | two pipelines: **cx_Freeze** (release builds, installer via Inno Setup) and **Nuitka** (standalone folder) |
| Localization | `Config/locales/*.json`, 11 languages |

---

## 🛠️ Development and building

```bash
# 1. Prepare a Python 3.11 environment (a helper script is included)
powershell -File Builds\NewVenv-PY311.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run from source (administrator rights required)
python SmartCardAPP.py

# 4. Build
python BuildPackage.py build      # cx_Freeze: three executables + bundled resources
python BuildNuitka.py             # Nuitka: build/nuitka/TPMSmartCard/
```

* Dependency self-check: `python Builds/check_imports.py`
* Full development guide (running, packaging, signing, CI, on-device debugging): [dev guide](../docs/dev-guide.md)
* Module layout and responsibilities: [architecture](../docs/architecture.md)

---

## ❓ FAQ

**Q: Why does creating a card fail inside a Remote Desktop session with `0x800704d3`?**
A: Windows forbids creating/deleting virtual smart cards in a Terminal Services session. Use the local console, or `mstsc /admin`.

**Q: Do I need to install OpenSC separately?**
A: No. The OpenSC tools used for reading cards ship with the app; a system-wide install is optional (only useful for other PKCS#11 clients).

**Q: Can a backup be restored on a different machine?**
A: Yes — that is exactly what `.tsb` is designed for. Data, device node, reader and certificates can be restored.
Whether the on-card private key is usable depends on the target machine's TPM and card state; confirm with a PIN
signature test and re-issue the certificate if necessary.

**Q: After restore the reader is missing, or certificates do not show up. What now?**
A: Read the three-layer verdict in the restore log (device node / reader / DPAPI). The most common causes are an old
backup format or missing card identity properties — follow the [troubleshooting guide](../docs/troubleshooting.md),
or attach the log to an issue.

**Q: Does it need network access?**
A: Everything works offline except the optional cloud certificate delivery.

**Q: `CERT_E_CHAINING` is reported for the certificate chain?**
A: The issuing intermediate CA is not installed on this machine. Import it into the intermediate/root store.

---

## 🤝 Support

* 🐛 **Bugs and feature requests**: open an [issue](https://github.com/PIKACHUIM/TPMSmartCard/issues) (please attach the logs under `%APPDATA%\TPMSmartCard\logs\`)
* 💬 **Usage questions**: also welcome in the issue tracker

---

## 📄 License

Licensed under **GPL-3.0**. See [LICENSE](../LICENSE).

## 🙏 References

1. [OpenSC/OpenSC](https://github.com/OpenSC/OpenSC) — open source smart card tools and middleware
2. [Microsoft Docs: Virtual Smart Cards](https://github.com/MicrosoftDocs/windows-itpro-docs/tree/public/windows/security/identity-protection/virtual-smart-cards)
3. WinCryptSSHAgent — SSH agent backed by smart card private keys
