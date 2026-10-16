<div align="center">

# Gestore di Smart Card Virtuali TPM

_Uno strumento grafico per creare e gestire smart card virtuali TPM su Windows_

<img src="../Images/20261016-184916.png" width="760" alt="Gestore di Smart Card Virtuali TPM">



Le smart card virtuali basate su TPM offrono una sicurezza vicina a quella delle smart card fisiche: la chiave privata è protetta dal TPM e non viene mai esportata in chiaro

Consente di generare chiavi e CSR in locale o di distribuire i certificati in modo sicuro dal cloud, sostituendo le esigenze PIV di card fisiche come YubiKey ed ePass


[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](../LICENSE)
[![Build](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml/badge.svg)](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml)
[![Release](https://img.shields.io/github/v/release/PIKACHUIM/TPMSmartCard?include_prereleases&label=release)](https://github.com/PIKACHUIM/TPMSmartCard/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%208%2B-0078D6.svg)](#-requisiti)

📘 [Indice della documentazione](../docs/README.md) · 🧭 [Architettura](../docs/architecture.md) · 💾 [Progettazione backup/ripristino](../docs/design-backup-restore.md) · 🛠️ [Risoluzione dei problemi](../docs/troubleshooting.md) · 🔐 [Modello di sicurezza](../docs/security.md)

[English](README_en.md) | [简体中文](../README.md) | [繁體中文](README_zh-Hant.md) | [日本語](README_ja.md) | [한국어](README_ko.md)<br>[Deutsch](README_de.md) | [Français](README_fr.md) | Italiano | [Português](README_pt.md) | [Русский](README_ru.md) | [Español](README_es.md)
</div>

---

## ✨ Funzionalità

### Smart card e credenziali

* **Smart card virtuali**: creazione ed eliminazione delle card; modifica o reimpostazione di PIN, PUK e chiave di amministrazione
* **Certificati e chiavi**: importazione, eliminazione e visualizzazione di certificati X.509 e oggetti chiave sulla card; catena di certificazione e utilizzi della chiave
* **Generazione e distribuzione**: generazione locale di chiave + CSR e firma, oppure distribuzione sicura dal cloud (accordo di chiavi X25519 + AES, codice di ritiro fuori banda)

### Backup e ripristino

* **Backup completo della card**: pacchettizza una card in un `.tsb` (dati della card + registro di sistema del dispositivo + indice chiavi TPM + proprietà del dispositivo + testo in chiaro DPAPI)
* **Ripristino sullo stesso TPM**: un backup può essere ripristinato solo sullo **stesso TPM** (reinstallazione di Windows su questa macchina: sì; **altra macchina / altro TPM: no**, e **una scheda eliminata non può essere ripristinata**); i dati DPAPI vengono decifrati al momento del backup e ri-cifrati con la chiave principale locale al ripristino (vedi [progettazione backup/ripristino](../docs/design-backup-restore.md))
* **Diagnostica del ripristino**: dopo il ripristino lo strumento verifica i tre livelli nodo dispositivo / lettore PC-SC / DPAPI e fornisce una conclusione operativa con i log

### Scenari e strumenti

* **Login SSH2**: con WinCryptSSHAgent è possibile accedere ai server remoti con la chiave privata sulla card
* **Strumenti d'ambiente**: installazione / avvio di OpenSC e dell'agente SSH, stato del TPM, esportazione di certificati e chiavi pubbliche
* **Interfaccia multilingue**: 11 lingue (简体中文 / 繁體中文 / English / 日本語 / 한국어 / Deutsch / Français / Italiano / Português / Русский / Español)

---

## 🚀 Avvio rapido

1. Scarica `TPMSmartCard-*-setup.exe` (o lo zip portatile) da [Releases](https://github.com/PIKACHUIM/TPMSmartCard/releases) e installalo;
2. **Esegui come amministratore** (la registrazione dei dispositivi della card e la lettura/scrittura delle cartelle di sistema richiedono i privilegi di amministratore);
3. In «Gestione card» crea una card → importa o genera un certificato → (facoltativo) in «Impostazioni di sistema» installa e avvia l'agente SSH;
4. Backup: seleziona una card → Backup per ottenere un `.tsb`; Ripristino: seleziona un `.tsb` → Ripristina.

> [!IMPORTANT]
> **La creazione / eliminazione di smart card virtuali non è possibile in una sessione Desktop remoto (Servizi terminal)**; Windows la rifiuta con `0x800704d3`.
> Usa la console locale oppure collegati con `mstsc /admin`.

> [!TIP]
> Gli strumenti [OpenSC](https://github.com/OpenSC/OpenSC/releases) necessari per leggere le card sono **inclusi nell'applicazione** (la cartella `OpenSC` accanto al programma),
> quindi non serve installarli separatamente; il componente OpenSC a livello di sistema nel programma di installazione è facoltativo e serve solo ad altri software (client PKCS#11, minidriver per card fisiche, ecc.).

---

## 🧩 Requisiti

| Voce | Requisito |
|---|---|
| Sistema | Windows 8 x86 / x64 o successivo (**privilegi di amministratore richiesti**) |
| Hardware | TPM 1.2 / 2.0 o successivo |
| Componenti di sistema | `tpmvscmgr`, `certutil` (inclusi in Windows) |
| Componenti inclusi | Strumenti OpenSC, WinCryptSSHAgent, `Import` (strumento .NET per l'importazione dei certificati) |

---

## 🏗️ Architettura

| Aspetto | Valore |
|---|---|
| Linguaggio / runtime | Python **3.11** |
| Interfaccia | Tkinter + ttkbootstrap (interfaccia costruita interamente via codice; layout guidati da `Config/*.json`) |
| Operazioni sulla card | `tpmvscmgr` (creazione / eliminazione / cambio PIN) + OpenSC (lettura card e certificati) + livello PnP / SetupAPI proprietario (nodi e proprietà del dispositivo) |
| Backup e ripristino | pacchettizzazione `.tsb` (zip) proprietaria; `Module/DPAPI.py` gestisce cifratura/decifratura DPAPI e l'impersonificazione del token |
| Packaging | due pipeline: **cx_Freeze** (build di rilascio, installer tramite Inno Setup) e **Nuitka** (cartella standalone) |
| Localizzazione | `Config/locales/*.json`, 11 lingue |

---

## 🛠️ Sviluppo e build

```bash
# 1. Preparare un ambiente Python 3.11 (è incluso uno script di supporto)
powershell -File Builds\NewVenv-PY313.ps1

# 2. Installare le dipendenze
pip install -r requirements.txt

# 3. Eseguire direttamente dai sorgenti (privilegi di amministratore richiesti)
python SmartCardAPP.py

# 4. Compilare
python BuildPackage.py build      # cx_Freeze: tre eseguibili + risorse incluse
python BuildNuitka.py             # Nuitka: build/nuitka/TPMSmartCard/
```

* Autodiagnosi delle dipendenze: `python Builds/check_imports.py`
* Guida completa allo sviluppo (esecuzione, packaging, firma, CI, debug su macchina reale): [guida allo sviluppo](../docs/dev-guide.md)
* Struttura del codice e responsabilità dei moduli: [architettura](../docs/architecture.md)

---

## 💾 Backup e ripristino

Una smart card virtuale TPM utilizzabile è composta da **cinque parti** e il `.tsb` le raccoglie tutte:

| Parte | Contenuto | Se manca |
|---|---|---|
| Cartella dati della card | `Tpm\<store GUID>\` (filesystem della card e mappe chiavi / PIN) | La card non ha contenuto |
| Registro del dispositivo | `ROOT\SMARTCARDREADER\<istanza>` e chiavi correlate | Il nodo del dispositivo non può essere creato |
| Indice chiavi TPM | `*.PCPKEY` (3 cartelle candidate) | Il driver non trova le chiavi della card |
| Proprietà del dispositivo | nome della card, GUID della card, binding dello store (protette da ACL; l'esportazione del registro non le legge) | Il lettore non viene pubblicato su PC/SC |
| Testo in chiaro DPAPI | testo in chiaro di `keymaps` / `pinmaps` / `pinpolicy` / `blobs\*` (ri-cifrato sulla macchina di destinazione) | Certificati e chiave privata non compaiono |

> [!WARNING]
> Poiché è inclusa l'ultima voce, un `.tsb` **equivale al materiale di chiave della card**: conservalo offline e non inserirlo in sistemi di controllo versione, cloud drive o strumenti di chat.
> Al ripristino lo strumento lo ri-cifra con il DPAPI della macchina di destinazione prima di riscriverlo; conserva anche nome della card, PIN, PUK e chiave di amministrazione.

Altre note:

* **Prerequisiti**: serve lo **stesso TPM** (reinstallazione su questa macchina: sì; altra macchina o altro TPM: no) e la **scheda non deve essere stata eliminata**
  — eliminando una scheda si rimuove anche la sua chiave persistente nel TPM: dopo, nemmeno un backup può ripristinarla;
* Dopo il ripristino **può essere necessario riavviare il dispositivo (driver) o il sistema** perché la scheda compaia nell'elenco dei lettori;
* I `.tsb` creati da versioni precedenti non contengono proprietà del dispositivo né testo in chiaro DPAPI: il ripristino lascia l'identità della scheda mancante e il lettore non compare — crea un nuovo backup con la versione corrente.

---

## ❓ Domande frequenti

**D: Perché la creazione di una card in Desktop remoto fallisce con `0x800704d3`?**
R: Windows vieta la creazione / eliminazione di smart card virtuali in una sessione Servizi terminal. Usa la console locale o `mstsc /admin`.

**D: Un backup può essere ripristinato su un'altra macchina?**
R: **No.** Un backup vale solo per lo **stesso TPM**: funziona dopo una reinstallazione su questa macchina, ma non su un'altra macchina o con un altro TPM; inoltre una **scheda eliminata**
**non può essere ripristinata** (l'eliminazione rimuove la sua chiave persistente nel TPM). Se la scheda non compare dopo il ripristino, riavvia prima il dispositivo o il sistema.

**D: Dopo il ripristino la scheda non compare. Cosa fare?**
R: **Riavvia prima**: la scheda può comparire nell'elenco dei lettori solo dopo un **riavvio del dispositivo (driver) o del sistema**. Se ancora non compare,
leggi la valutazione sui tre livelli nel log (nodo dispositivo / lettore / DPAPI): di solito è una copia creata da una versione precedente o la mancanza delle proprietà di identità ([guida](../docs/troubleshooting.md)).

**D: Dopo il ripristino il lettore non compare o i certificati non si vedono. Cosa fare?**
R: Leggi la valutazione sui tre livelli nel log di ripristino (nodo dispositivo / lettore / DPAPI). Le cause più comuni sono un backup creato da una versione precedente o proprietà di identità della card mancanti;
segui la [guida alla risoluzione dei problemi](../docs/troubleshooting.md) oppure allega il log a una issue.

**D: Serve una connessione di rete?**
R: Tutto funziona offline tranne la «distribuzione dei certificati dal cloud».

**D: La catena di certificazione riporta `CERT_E_CHAINING`?**
R: La CA intermedia emittente non è installata su questa macchina: importala nell'archivio delle autorità di certificazione attendibili / intermedie.

---

## 🤝 Supporto

* 🐛 **Bug o richieste di funzionalità**: apri una [issue](https://github.com/PIKACHUIM/TPMSmartCard/issues) (allega i log in `%APPDATA%\TPMSmartCard\logs\`)
* 💬 **Domande d'uso**: benvenute anche nelle issue

---

## 📄 Licenza

Questo progetto è distribuito con licenza **GPL-3.0**. Vedi [LICENSE](../LICENSE).

## 🙏 Riferimenti

1. [OpenSC/OpenSC](https://github.com/OpenSC/OpenSC) — strumenti e middleware open source per smart card
2. [Microsoft Docs: Virtual Smart Cards](https://github.com/MicrosoftDocs/windows-itpro-docs/tree/public/windows/security/identity-protection/virtual-smart-cards)
3. WinCryptSSHAgent — agente SSH basato sulla chiave privata di una smart card





