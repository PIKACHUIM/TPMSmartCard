<div align="center">

# TPM 仮想スマートカードマネージャー

_Windows 上で TPM 仮想スマートカードを作成・管理する GUI ツール_

<img src="../Images/20261016-184916.png" width="760" alt="TPM 仮想スマートカードマネージャー">



TPM ベースの仮想スマートカードは物理カードに近い強度を提供します。秘密鍵は TPM に保護され、平文でエクスポートされることはありません

ローカルでの鍵と CSR の生成、クラウドからの安全な証明書配布に対応し、YubiKey や ePass などの物理カードの PIV 用途を代替できます


[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](../LICENSE)
[![Build](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml/badge.svg)](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml)
[![Release](https://img.shields.io/github/v/release/PIKACHUIM/TPMSmartCard?include_prereleases&label=release)](https://github.com/PIKACHUIM/TPMSmartCard/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%208%2B-0078D6.svg)](#-システム要件)

🌐 [オンラインドキュメント](https://pikachuim.github.io/TPMSmartCard/)  · 🧭 [アーキテクチャ](../docs/architecture.md) · 💾 [バックアップ/復元の設計](../docs/design-backup-restore.md) · 🛠️ [トラブルシューティング](../docs/troubleshooting.md) · 🔐 [セキュリティモデル](../docs/security.md)

[English](README_en.md) | [简体中文](../README.md) | [繁體中文](README_zh-Hant.md) | 日本語 | [한국어](README_ko.md)<br>[Deutsch](README_de.md) | [Français](README_fr.md) | [Italiano](README_it.md) | [Português](README_pt.md) | [Русский](README_ru.md) | [Español](README_es.md)
</div>

---

## ✨ 機能

### カードと資格情報

* **仮想スマートカード**：カードの作成・削除、PIN / PUK / 管理者キーの変更・リセット
* **証明書とキー**：X.509 証明書とカード上のキーオブジェクトのインポート・削除・表示、証明書チェーンとキー用途の確認
* **生成と配布**：ローカルで鍵 + CSR を生成して署名、またはクラウドから安全に配布（X25519 鍵交換 + AES 暗号化）

### バックアップと復元

* **カード全体のバックアップ**：カードを `.tsb` にまとめる（カードデータ + デバイスレジストリ + TPM キーインデックス + デバイスプロパティ + DPAPI 平文）
* **同一 TPM への復元**：復元できるのは**同じ TPM** 上だけです（そのマシンで OS を再インストールした場合は可、**別のマシン / 別の TPM は不可**、**カードを削除した後も復元不可**）
* DPAPI データはバックアップ時に復号し、復元時にローカルのマスターキーで再暗号化します（[バックアップ/復元の設計](../docs/design-backup-restore.md)）
* **復元診断**：復元後にデバイスノード / リーダー / DPAPI の 3 層を判定し、実行可能な結論とログを出力

### 用途とツール

* **SSH2 ログイン**：WinCryptSSHAgent と組み合わせ、カード上の秘密鍵でリモートサーバーにログイン
* **環境ツール**：OpenSC と SSH エージェントのインストール / 起動、TPM 状態の確認、証明書と公開鍵のエクスポート
* **多言語 UI**：11 言語（简体中文 / 繁體中文 / English / 日本語 / 한국어 / Deutsch / Français / Italiano / Português / Русский / Español）

---

## 🚀 はじめに

1. [Releases](https://github.com/PIKACHUIM/TPMSmartCard/releases) から `TPMSmartCard-*-setup.exe`（またはポータブル zip）をダウンロードしてインストールします。
2. **管理者として実行**します（カードデバイスの登録、システムフォルダーの読み書きに管理者権限が必要です）。
3. 「カード管理」でカードを作成 → 証明書をインポートまたは生成 →（任意）「システム設定」で SSH エージェントをインストールして起動します。
4. バックアップ：カードを選択 → バックアップで `.tsb` を取得。復元：`.tsb` を選択 → 復元。

> [!IMPORTANT]
> **仮想スマートカードの作成 / 削除はリモートデスクトップ（ターミナルサービス）セッションでは行えません**。Windows は `0x800704d3` で拒否します。
>
> ローカルコンソールで操作するか、`mstsc /admin` でコンソールセッションに接続してください。

> [!TIP]
> カード読み取りに必要な [OpenSC](https://github.com/OpenSC/OpenSC/releases) ツールは**アプリに同梱**されています（プログラムフォルダーの `OpenSC`）。
> 別途インストールは不要です。インストーラーのシステム全体向け OpenSC コンポーネントは任意で、他のソフトウェア（PKCS#11 クライアント、物理カードのミニドライバーなど）専用です。

---

## 🧩 システム要件

| 項目 | 要件 |
|---|---|
| システム | Windows 8 x86 / x64 以降（**管理者権限が必要**） |
| ハードウェア | TPM 1.2 / 2.0 以降 |
| システム コンポーネント | `tpmvscmgr`、`certutil`（Windows 同梱） |
| 同梱コンポーネント | OpenSC ツール、WinCryptSSHAgent、`Import`（.NET 証明書インポートツール） |

---

## 🏗️ 技術構成

| 項目 | 内容 |
|---|---|
| 言語 / ランタイム | Python **3.11** |
| UI | Tkinter + ttkbootstrap（UI はすべてコードで構築、レイアウトは `Config/*.json` で駆動） |
| カード操作 | `tpmvscmgr`（作成 / 削除 / PIN 変更）+ OpenSC（カードと証明書の読み取り）+ 独自 PnP / SetupAPI 層 |
| バックアップと復元 | 独自 `.tsb`（zip）パッケージング。`Module/DPAPI.py` が DPAPI の暗号化 / 復号とトークン借用を担当 |
| パッケージング | 2 系統：**cx_Freeze**（正式ビルド、Inno Setup でインストーラー）と **Nuitka**（standalone フォルダー） |
| ローカライズ | `Config/locales/*.json`、11 言語 |

---

## 🛠️ 開発とビルド

```bash
# 1. Python 3.11 環境を用意（同梱スクリプトで venv を再作成するのを推奨）
powershell -File Builds\NewVenv-PY313.ps1

# 2. 依存関係をインストール
pip install -r requirements.txt

# 3. ソースから直接実行（管理者権限が必要）
python SmartCardAPP.py

# 4. ビルド
python BuildPackage.py build      # cx_Freeze：3 つの exe + 同梱リソース
python BuildNuitka.py             # Nuitka：build/nuitka/TPMSmartCard/
```

* 依存関係の自己チェック：`python Builds/check_imports.py`
* 開発の詳細（実行方法、パッケージング、署名、CI、実機デバッグ）：[開発ガイド](../docs/dev-guide.md)
* コード構成とモジュールの役割：[アーキテクチャ](../docs/architecture.md)

---

## 💾 バックアップと復元

使用可能な TPM 仮想スマートカードは**5 つの部分**で構成され、`.tsb` はそのすべてを格納します：

| 構成要素 | 内容 | 欠けた場合 |
|---|---|---|
| カードデータフォルダー | `Tpm\<store GUID>\`（カードのファイルシステムと鍵 / PIN マップ） | カードに内容がない |
| デバイスレジストリ | `ROOT\SMARTCARDREADER\<インスタンス>` など | デバイスノードを作成できない |
| TPM キーインデックス | `*.PCPKEY`（3 つの候補フォルダー） | ドライバーがカードの鍵を見つけられない |
| デバイスプロパティ | カード名、カード GUID、store バインディング（ACL 保護のためレジストリ エクスポートでは取得不可） | リーダーが PC/SC に公開されない |
| DPAPI 平文 | `keymaps` / `pinmaps` / `pinpolicy` / `blobs\*` の平文（復元時に復元先で再暗号化） | 証明書と秘密鍵が表示されない |

> [!WARNING]
> 上表の最後の項目を含むため、**`.tsb` はカードの鍵素材と同等**です：オフラインで厳重に保管し、バージョン管理・クラウドストレージ・チャットツールに置かないでください。
>
> 復元時にはツールが復元先の DPAPI で再暗号化して書き戻します。カード名、PIN、PUK、管理者キーも併せて保管してください。

その他：

* **前提条件**：**同じ TPM** が必要です（そのマシンでの OS 再インストールは可、別のマシンや別の TPM は不可）
* カードを削除すると TPM 内の永続キーも消えるため、**バックアップがあっても復元できません**。
* 復元後、カードがリーダー一覧に現れるまで**デバイス（ドライバー）の再起動または OS の再起動が必要**な場合があります。

---

## ❓ よくある質問

> **Q：リモートデスクトップでカード作成に失敗し、`0x800704d3` が返るのはなぜですか？**
>
> A：Windows はターミナルサービス セッションでの仮想スマートカードの作成 / 削除を禁止しています。ローカルコンソールで操作するか、`mstsc /admin` で接続してください。
>
> **Q：別のマシンに復元できますか？**
>
> A：**できません**。バックアップは**同じ TPM** にのみ有効です（そのマシンで OS を再インストールした場合は可、別のマシンや別の TPM は不可）。また**削除されたカードは**
>
> **復元できません**（削除時に TPM 内の永続キーも消えるため）。復元後にカードが現れない場合は、デバイスまたは OS を再起動してから確認してください。
>
> **Q：復元後にカードが現れない場合は？**
>
> A：**まず再起動**してください：復元したカードは**デバイス（ドライバー）またはシステムの再起動**後にリーダー一覧へ現れることがあります。それでも現れない場合は、
>
> 復元ログの 3 層判定（デバイスノード / リーダー / DPAPI）を確認してください。多くは「旧バージョンで作成したバックアップ」またはカード識別プロパティの欠落が原因です。
>
> **Q：復元後にリーダーが出ない / 証明書が表示されない場合は？**
>
> A：まず復元ログの 3 層判定（デバイスノード / リーダー / DPAPI）を確認してください。多くは「旧バージョンで作成したバックアップ」またはカード識別プロパティの欠落が原因です。
>
> [トラブルシューティング](../docs/troubleshooting.md) に沿って切り分けるか、ログを Issue に添付してください。
>
> **Q：ネットワーク接続は必要ですか？**
>
> A：「クラウドからの証明書配布」以外はすべてオフラインで利用できます。
>
> **Q：証明書チェーンで `CERT_E_CHAINING` が報告されます。**
>
> A：発行元の中間 CA がこのマシンにインストールされていません。「信頼されたルート / 中間証明書」にインポートしてください。

---

## 🤝 サポート

* 🐛 **不具合・機能要望**：[Issues](https://github.com/PIKACHUIM/TPMSmartCard/issues) へ（`%APPDATA%\TPMSmartCard\logs\` のログを添付してください）
* 💬 **使い方の質問**：Issues での議論も歓迎します

---

## 📄 ライセンス

本プロジェクトは **GPL-3.0** ライセンスで公開されています。詳細は [LICENSE](../LICENSE) を参照してください。

## 🙏 引用プロジェクト

1. [OpenSC/OpenSC](https://github.com/OpenSC/OpenSC) —— オープンソースのスマートカード ツールとミドルウェア
2. [Microsoft Docs: Virtual Smart Cards](https://github.com/MicrosoftDocs/windows-itpro-docs/tree/public/windows/security/identity-protection/virtual-smart-cards)
3. WinCryptSSHAgent —— スマートカードの秘密鍵で SSH 認証を行うエージェント





