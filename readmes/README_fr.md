<div align="center">

# Gestionnaire de cartes à puce virtuelles TPM

_Un outil graphique pour créer et gérer des cartes à puce virtuelles TPM sous Windows_

<img src="../Images/QQ20261016-184916.png" width="760" alt="Gestionnaire de cartes à puce virtuelles TPM">



Les cartes à puce virtuelles basées sur le TPM offrent une sécurité proche de celle des cartes physiques : la clé privée est protégée par le TPM et n'est jamais exportée en clair

Générez les clés et les CSR en local, ou recevez les certificats en toute sécurité depuis le cloud — en remplacement des besoins PIV des cartes physiques telles que YubiKey ou ePass


[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](../LICENSE)
[![Build](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml/badge.svg)](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml)
[![Release](https://img.shields.io/github/v/release/PIKACHUIM/TPMSmartCard?include_prereleases&label=release)](https://github.com/PIKACHUIM/TPMSmartCard/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%208%2B-0078D6.svg)](#-configuration-requise)

📘 [Index de la documentation](../docs/README.md) · 🧭 [Architecture](../docs/architecture.md) · 💾 [Conception sauvegarde/restauration](../docs/design-backup-restore.md) · 🛠️ [Dépannage](../docs/troubleshooting.md) · 🔐 [Modèle de sécurité](../docs/security.md)

[English](README_en.md) | [简体中文](../README.md) | [繁體中文](README_zh-Hant.md) | [日本語](README_ja.md) | [한국어](README_ko.md)<br>[Deutsch](README_de.md) | Français | [Italiano](README_it.md) | [Português](README_pt.md) | [Русский](README_ru.md) | [Español](README_es.md)
</div>
---

## ✨ Fonctionnalités

### Cartes et informations d'identification

* **Cartes à puce virtuelles** : créer et supprimer des cartes ; modifier ou réinitialiser le PIN, le PUK et la clé d'administration
* **Certificats et clés** : importer, supprimer et consulter les certificats X.509 et les objets de clé présents sur la carte ; chaîne de certification et usages de la clé
* **Génération et distribution** : générer la clé + le CSR en local puis les faire signer, ou recevoir les certificats en toute sécurité depuis le cloud (accord de clés X25519 + AES, code de retrait transmis hors bande)

### Sauvegarde et restauration

* **Sauvegarde complète de la carte** : empaquette une carte dans un `.tsb` (données de la carte + registre de l'appareil + index des clés TPM + propriétés de l'appareil + texte en clair DPAPI)
* **Restauration sur le même TPM** : une sauvegarde ne peut être restaurée que sur le **même TPM** (réinstallation de Windows sur cette machine : oui ; **autre machine / autre TPM : non**, et **une carte supprimée ne peut pas être restaurée**) ; les données DPAPI sont déchiffrées lors de la sauvegarde puis rechiffrées avec la clé principale locale lors de la restauration (voir [conception sauvegarde/restauration](../docs/design-backup-restore.md))
* **Diagnostic de restauration** : après restauration, l'outil évalue les trois couches nœud d'appareil / lecteur PC-SC / DPAPI et fournit une conclusion exploitable avec les journaux

### Scénarios et outils

* **Connexion SSH2** : avec WinCryptSSHAgent, utilisez la clé privée de la carte pour vous connecter aux serveurs distants
* **Outils d'environnement** : installer / démarrer OpenSC et l'agent SSH, consulter l'état du TPM, exporter certificats et clés publiques
* **Interface multilingue** : 11 langues (简体中文 / 繁體中文 / English / 日本語 / 한국어 / Deutsch / Français / Italiano / Português / Русский / Español)

---

## 🚀 Démarrage rapide

1. Téléchargez `TPMSmartCard-*-setup.exe` (ou l'archive zip portable) depuis [Releases](https://github.com/PIKACHUIM/TPMSmartCard/releases) et installez-le ;
2. **Exécutez en tant qu'administrateur** (l'enregistrement des appareils de carte et l'accès aux dossiers système exigent des droits d'administrateur) ;
3. Dans « Gestion des cartes », créez une carte → importez ou générez un certificat → (facultatif) dans « Paramètres système », installez et démarrez l'agent SSH ;
4. Sauvegarde : sélectionnez une carte → Sauvegarder pour obtenir un `.tsb` ; Restauration : sélectionnez un `.tsb` → Restaurer.

> [!IMPORTANT]
> **La création / suppression de cartes à puce virtuelles est impossible dans une session Bureau à distance (Services Terminal Server)** ; Windows la refuse avec `0x800704d3`.
> Utilisez la console locale ou connectez-vous avec `mstsc /admin`.

> [!TIP]
> Les outils [OpenSC](https://github.com/OpenSC/OpenSC/releases) nécessaires à la lecture des cartes sont **fournis avec l'application** (dossier `OpenSC` à côté du programme),
> aucune installation séparée n'est requise ; le composant OpenSC à l'échelle du système proposé par l'installateur est facultatif et ne sert qu'à d'autres logiciels (clients PKCS#11, minidrivers de cartes physiques, etc.).

---

## 🧩 Configuration requise

| Élément | Exigence |
|---|---|
| Système | Windows 8 x86 / x64 ou version ultérieure (**droits d'administrateur requis**) |
| Matériel | TPM 1.2 / 2.0 ou version ultérieure |
| Composants système | `tpmvscmgr`, `certutil` (fournis avec Windows) |
| Composants inclus | Outils OpenSC, WinCryptSSHAgent, `Import` (outil .NET d'import de certificats) |

---

## 🏗️ Architecture

| Aspect | Valeur |
|---|---|
| Langage / exécution | Python **3.11** |
| Interface | Tkinter + ttkbootstrap (interface entièrement construite en code ; dispositions pilotées par `Config/*.json`) |
| Opérations sur la carte | `tpmvscmgr` (création / suppression / changement de PIN) + OpenSC (lecture de la carte et des certificats) + couche PnP / SetupAPI maison (nœuds et propriétés d'appareil) |
| Sauvegarde et restauration | format `.tsb` (zip) maison ; `Module/DPAPI.py` gère le chiffrement/déchiffrement DPAPI et l'emprunt de jeton |
| Empaquetage | deux chaînes : **cx_Freeze** (versions de production, installateur via Inno Setup) et **Nuitka** (dossier autonome) |
| Localisation | `Config/locales/*.json`, 11 langues |

---

## 🛠️ Développement et compilation

```bash
# 1. Préparer un environnement Python 3.11 (un script d'aide est fourni)
powershell -File Builds\NewVenv-PY311.ps1

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Exécuter directement depuis les sources (droits d'administrateur requis)
python SmartCardAPP.py

# 4. Compiler
python BuildPackage.py build      # cx_Freeze : trois exécutables + ressources incluses
python BuildNuitka.py             # Nuitka : build/nuitka/TPMSmartCard/
```

* Auto-vérification des dépendances : `python Builds/check_imports.py`
* Guide de développement complet (exécution, empaquetage, signature, CI, débogage sur machine réelle) : [guide de développement](../docs/dev-guide.md)
* Structure du code et responsabilités des modules : [architecture](../docs/architecture.md)

---

## 💾 Sauvegarde et restauration

Une carte à puce virtuelle TPM utilisable se compose de **cinq parties**, et le `.tsb` les contient toutes :

| Partie | Contenu | En cas d'absence |
|---|---|---|
| Dossier de données de la carte | `Tpm\<store GUID>\` (système de fichiers de la carte et tables clés / PIN) | La carte n'a aucun contenu |
| Registre de l'appareil | `ROOT\SMARTCARDREADER\<instance>` et clés associées | Le nœud d'appareil ne peut pas être créé |
| Index des clés TPM | `*.PCPKEY` (3 dossiers candidats) | Le pilote ne trouve pas les clés de la carte |
| Propriétés de l'appareil | nom de la carte, GUID de la carte, liaison du store (protégées par ACL ; l'export du registre ne les lit pas) | Le lecteur n'est pas publié sur PC/SC |
| Texte en clair DPAPI | texte en clair de `keymaps` / `pinmaps` / `pinpolicy` / `blobs\*` (rechiffré sur la machine cible) | Certificats et clé privée ne s'affichent pas |

> [!WARNING]
> Comme le dernier élément est inclus, un `.tsb` **équivaut au matériel de clé de la carte** : conservez-le hors ligne et ne le placez jamais dans un système de gestion de versions, un espace cloud ou un outil de messagerie.
> Lors de la restauration, l'outil le rechiffre avec le DPAPI de la machine cible avant de l'écrire ; conservez également le nom de la carte, le PIN, le PUK et la clé d'administration.

Autres remarques :

* **Prérequis** : le **même TPM** est nécessaire (réinstallation sur cette machine : oui ; autre machine ou autre TPM : non) et la **carte ne doit pas avoir été supprimée**
  — supprimer une carte efface aussi sa clé persistante dans le TPM : même avec une sauvegarde, la restauration est alors impossible ;
* Après une restauration, **un redémarrage de l'appareil (pilote) ou du système peut être nécessaire** pour que la carte apparaisse dans la liste des lecteurs ;
* Les `.tsb` créés par des versions antérieures n'ont ni propriétés d'appareil ni texte en clair DPAPI : la restauration laisse l'identité de la carte manquante et le lecteur n'apparaît pas — créez une nouvelle sauvegarde avec la version actuelle.

---

## ❓ Questions fréquentes

**Q : Pourquoi la création d'une carte échoue-t-elle en Bureau à distance avec `0x800704d3` ?**
R : Windows interdit la création / suppression de cartes à puce virtuelles dans une session Services Terminal Server. Utilisez la console locale ou `mstsc /admin`.

**Q : Une sauvegarde peut-elle être restaurée sur une autre machine ?**
R : **Non.** Une sauvegarde ne s'applique qu'au **même TPM** : elle fonctionne après une réinstallation sur cette machine, mais pas sur une autre machine ni avec un autre TPM ; et une **carte supprimée**
**ne peut pas être restaurée** (sa suppression efface sa clé persistante dans le TPM). Si la carte n'apparaît pas après restauration, redémarrez d'abord l'appareil ou le système.

**Q : Après restauration, le lecteur n'apparaît pas ou les certificats ne s'affichent pas. Que faire ?**
R : Consultez le verdict en trois couches du journal de restauration (nœud d'appareil / lecteur / DPAPI). Les causes les plus fréquentes sont une sauvegarde créée par une version antérieure ou l'absence des propriétés d'identité de la carte ;
suivez le [guide de dépannage](../docs/troubleshooting.md) étape par étape, ou joignez le journal à un ticket.

**Q : Une connexion réseau est-elle nécessaire ?**
R : Tout fonctionne hors ligne, sauf la « distribution des certificats depuis le cloud ».

**Q : La chaîne de certification signale `CERT_E_CHAINING`.**
R : L'autorité intermédiaire émettrice n'est pas installée sur cette machine ; importez-la dans le magasin des autorités racine/intermédiaires approuvées.

---

## 🤝 Assistance

* 🐛 **Bogues ou demandes de fonctionnalités** : ouvrez un [ticket](https://github.com/PIKACHUIM/TPMSmartCard/issues) (joignez les journaux de `%APPDATA%\TPMSmartCard\logs\`)
* 💬 **Questions d'utilisation** : également bienvenues dans les tickets

---

## 📄 Licence

Ce projet est distribué sous licence **GPL-3.0**. Voir [LICENSE](../LICENSE).

## 🙏 Références

1. [OpenSC/OpenSC](https://github.com/OpenSC/OpenSC) — outils et intergiciel open source pour cartes à puce
2. [Microsoft Docs: Virtual Smart Cards](https://github.com/MicrosoftDocs/windows-itpro-docs/tree/public/windows/security/identity-protection/virtual-smart-cards)
3. WinCryptSSHAgent — agent SSH reposant sur la clé privée d'une carte à puce







