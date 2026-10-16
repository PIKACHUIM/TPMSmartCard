<div align="center">

# TPM 가상 스마트카드 관리자

_Windows에서 TPM 가상 스마트카드를 만들고 관리하는 GUI 도구_

<img src="../Images/20261016-184916.png" width="760" alt="TPM 가상 스마트카드 관리자">



TPM 기반 가상 스마트카드는 물리 카드에 가까운 강도를 제공합니다. 개인 키는 TPM으로 보호되며 평문으로 내보내지지 않습니다

로컬에서 키와 CSR을 생성하거나 클라우드에서 인증서를 안전하게 배포할 수 있어, YubiKey·ePass 같은 물리 카드의 PIV 용도를 대체할 수 있습니다


[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](../LICENSE)
[![Build](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml/badge.svg)](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml)
[![Release](https://img.shields.io/github/v/release/PIKACHUIM/TPMSmartCard?include_prereleases&label=release)](https://github.com/PIKACHUIM/TPMSmartCard/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%208%2B-0078D6.svg)](#-시스템-요구-사항)

📘 [문서 색인](../docs/README.md) · 🧭 [아키텍처](../docs/architecture.md) · 💾 [백업/복원 설계](../docs/design-backup-restore.md) · 🛠️ [문제 해결](../docs/troubleshooting.md) · 🔐 [보안 모델](../docs/security.md)

[English](README_en.md) | [简体中文](../README.md) | [繁體中文](README_zh-Hant.md) | [日本語](README_ja.md) | 한국어<br>[Deutsch](README_de.md) | [Français](README_fr.md) | [Italiano](README_it.md) | [Português](README_pt.md) | [Русский](README_ru.md) | [Español](README_es.md)
</div>

---

## ✨ 기능

### 카드와 자격 증명

* **가상 스마트카드**: 카드 생성·삭제, PIN / PUK / 관리 키 변경·재설정
* **인증서와 키**: X.509 인증서와 카드상 키 객체 가져오기·삭제·보기, 인증서 체인과 키 용도 확인
* **생성과 배포**: 로컬에서 키 + CSR을 생성해 서명하거나, 클라우드에서 안전하게 배포(X25519 키 합의 + AES 암호화, 수령 코드는 대역 외 전달)

### 백업과 복원

* **카드 전체 백업**: 카드를 `.tsb` 하나로 패키징(카드 데이터 + 장치 레지스트리 + TPM 키 인덱스 + 장치 속성 + DPAPI 평문)
* **동일 TPM 복원**: 백업은 **같은 TPM**에서만 복원할 수 있습니다(해당 PC에서 OS를 재설치한 경우 가능, **다른 PC / 다른 TPM은 불가**, **카드를 삭제한 뒤에도 복원 불가**). DPAPI 데이터는 백업 시 복호화하고 복원 시 로컬 마스터 키로 다시 암호화합니다([백업/복원 설계](../docs/design-backup-restore.md))
* **복원 진단**: 복원 후 장치 노드 / 리더 / DPAPI 3계층 상태를 판정하고 실행 가능한 결론과 로그를 제공합니다

### 활용과 도구

* **SSH2 로그인**: WinCryptSSHAgent와 함께 카드상 개인 키로 원격 서버에 로그인
* **환경 도구**: OpenSC와 SSH 에이전트 설치·시작, TPM 상태 확인, 인증서와 공개 키 내보내기
* **다국어 UI**: 11개 언어(简体中文 / 繁體中文 / English / 日本語 / 한국어 / Deutsch / Français / Italiano / Português / Русский / Español)

---

## 🚀 빠른 시작

1. [Releases](https://github.com/PIKACHUIM/TPMSmartCard/releases)에서 `TPMSmartCard-*-setup.exe`(또는 포터블 zip)를 내려받아 설치합니다.
2. **관리자 권한으로 실행**합니다(카드 장치 등록, 시스템 폴더 읽기/쓰기에 관리자 권한이 필요합니다).
3. 「카드 관리」에서 카드 생성 → 인증서 가져오기 또는 생성 → (선택) 「시스템 설정」에서 SSH 에이전트 설치 및 시작.
4. 백업: 카드 선택 → 백업으로 `.tsb` 생성. 복원: `.tsb` 선택 → 복원.

> [!IMPORTANT]
> **가상 스마트카드 생성 / 삭제는 원격 데스크톱(터미널 서비스) 세션에서 할 수 없습니다**. Windows가 `0x800704d3`으로 거부합니다.
> 로컬 콘솔에서 작업하거나 `mstsc /admin`으로 콘솔 세션에 연결하세요.

> [!TIP]
> 카드 읽기에 필요한 [OpenSC](https://github.com/OpenSC/OpenSC/releases) 도구는 **앱에 포함되어 있습니다**(프로그램 폴더의 `OpenSC`).
> 별도 설치가 필요하지 않습니다. 설치 관리자의 시스템 전역 OpenSC 구성 요소는 선택 사항이며 다른 소프트웨어(PKCS#11 클라이언트, 물리 카드 미니드라이버 등) 전용입니다.

---

## 🧩 시스템 요구 사항

| 항목 | 요구 사항 |
|---|---|
| 운영 체제 | Windows 8 x86 / x64 이상(**관리자 권한 필요**) |
| 하드웨어 | TPM 1.2 / 2.0 이상 |
| 시스템 구성 요소 | `tpmvscmgr`, `certutil`(Windows 기본 포함) |
| 동봉 구성 요소 | OpenSC 도구, WinCryptSSHAgent, `Import`(.NET 인증서 가져오기 도구) |

---

## 🏗️ 기술 구성

| 항목 | 내용 |
|---|---|
| 언어 / 런타임 | Python **3.11** |
| UI | Tkinter + ttkbootstrap(UI는 전부 코드로 구성, 레이아웃은 `Config/*.json`으로 구동) |
| 카드 조작 | `tpmvscmgr`(생성 / 삭제 / PIN 변경) + OpenSC(카드와 인증서 읽기) + 자체 PnP / SetupAPI 계층(장치 노드와 속성) |
| 백업과 복원 | 자체 `.tsb`(zip) 패키징. `Module/DPAPI.py`가 DPAPI 암복호화와 토큰 가장(借用)을 담당 |
| 패키징 | 두 가지 파이프라인: **cx_Freeze**(정식 빌드, Inno Setup으로 설치 관리자)와 **Nuitka**(standalone 폴더) |
| 다국어 | `Config/locales/*.json`, 11개 언어 |

---

## 🛠️ 개발과 빌드

```bash
# 1. Python 3.11 환경 준비(저장소에 포함된 스크립트로 venv 재생성 권장)
powershell -File Builds\NewVenv-PY313.ps1

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 소스에서 바로 실행(관리자 권한 필요)
python SmartCardAPP.py

# 4. 빌드
python BuildPackage.py build      # cx_Freeze: 실행 파일 3개 + 동봉 리소스
python BuildNuitka.py             # Nuitka: build/nuitka/TPMSmartCard/
```

* 의존성 자체 점검: `python Builds/check_imports.py`
* 개발 상세(실행 방법, 패키징, 서명, CI, 실기 디버깅): [개발 가이드](../docs/dev-guide.md)
* 코드 구조와 모듈 역할: [아키텍처](../docs/architecture.md)

---

## 💾 백업과 복원

사용 가능한 TPM 가상 스마트카드는 **다섯 부분**으로 구성되며, `.tsb`는 이 모두를 담습니다:

| 구성 요소 | 내용 | 누락 시 결과 |
|---|---|---|
| 카드 데이터 폴더 | `Tpm\<store GUID>\`(카드 파일 시스템과 키 / PIN 매핑) | 카드에 내용이 없음 |
| 장치 레지스트리 | `ROOT\SMARTCARDREADER\<인스턴스>` 등 | 장치 노드를 만들 수 없음 |
| TPM 키 인덱스 | `*.PCPKEY`(후보 폴더 3개) | 드라이버가 카드 키를 찾지 못함 |
| 장치 속성 | 카드 이름, 카드 GUID, store 바인딩(ACL 보호, 레지스트리 내보내기로는 읽을 수 없음) | 리더가 PC/SC에 게시되지 않음 |
| DPAPI 평문 | `keymaps` / `pinmaps` / `pinpolicy` / `blobs\*`의 평문(복원 시 대상 PC에서 다시 암호화) | 인증서와 개인 키가 표시되지 않음 |

> [!WARNING]
> 위 표의 마지막 항목을 포함하므로 **`.tsb`는 카드 키 자료와 동일합니다**: 오프라인으로 안전하게 보관하고 버전 관리, 클라우드 드라이브, 채팅 도구에 넣지 마세요.
> 복원 시 도구가 대상 PC의 DPAPI로 다시 암호화해 기록합니다. 카드 이름, PIN, PUK, 관리 키도 함께 보관하세요.

그 밖의 안내:

* **전제 조건**: **같은 TPM**이어야 하며(해당 PC에서 OS 재설치 시 가능, 다른 PC나 다른 TPM은 불가), **카드가 삭제되지 않은 상태**여야 합니다
  — 카드를 삭제하면 TPM 내 영구 키도 지워지므로 백업이 있어도 복원할 수 없습니다;
* 복원 후 카드가 리더 목록에 나타나려면 **장치(드라이버) 재시작 또는 시스템 재부팅이 필요할 수 있습니다**;
* 구버전으로 만든 `.tsb`에는 장치 속성과 DPAPI 평문이 없어 복원 시 카드 식별 정보가 빠지고 리더가 나타나지 않습니다. 최신 버전으로 다시 백업하세요.

---

## ❓ 자주 묻는 질문

**Q: 원격 데스크톱에서 카드 생성이 실패하고 `0x800704d3`이 반환되는 이유는?**
A: Windows는 터미널 서비스 세션에서 가상 스마트카드 생성 / 삭제를 금지합니다. 로컬 콘솔에서 작업하거나 `mstsc /admin`으로 연결하세요.

**Q: 다른 PC에서 복원할 수 있나요?**
A: **불가능합니다.** 백업은 **같은 TPM**에만 적용됩니다(해당 PC에서 OS 재설치 시 가능, 다른 PC나 다른 TPM은 불가). 또한 **삭제된 카드는**
**복원할 수 없습니다**(삭제 시 TPM 내 영구 키도 지워집니다). 복원 후 카드가 나타나지 않으면 장치 또는 시스템을 재시작한 뒤 확인하세요.

**Q: 복원 후 카드가 나타나지 않으면 어떻게 하나요?**
A: **먼저 재시작하세요**: 복원한 카드는 **장치(드라이버) 또는 시스템을 다시 시작**해야 리더 목록에 나타날 수 있습니다. 그래도 나타나지 않으면
복원 로그의 3계층 판정(장치 노드 / 리더 / DPAPI)을 확인하세요. 대개 「구버전으로 만든 백업」 또는 카드 식별 속성 누락이 원인입니다([문제 해결 안내](../docs/troubleshooting.md)).

**Q: 복원 후 리더가 나타나지 않거나 인증서가 보이지 않습니다.**
A: 먼저 복원 로그의 3계층 판정(장치 노드 / 리더 / DPAPI)을 확인하세요. 대개 「구버전으로 만든 백업」 또는 카드 식별 속성 누락이 원인입니다.
[문제 해결 안내](../docs/troubleshooting.md)를 따라 확인하거나 로그를 이슈에 첨부해 주세요.

**Q: 네트워크 연결이 필요한가요?**
A: 「클라우드 인증서 배포」 외에는 모두 오프라인으로 사용할 수 있습니다.

**Q: 인증서 체인에서 `CERT_E_CHAINING`이 보고됩니다.**
A: 발급한 중간 CA가 이 PC에 설치되어 있지 않습니다. 「신뢰할 수 있는 루트 / 중간 인증서」로 가져오세요.

---

## 🤝 지원

* 🐛 **버그 / 기능 요청**: [Issues](https://github.com/PIKACHUIM/TPMSmartCard/issues)에 등록해 주세요(`%APPDATA%\TPMSmartCard\logs\`의 로그를 첨부하면 좋습니다)
* 💬 **사용 문의**: Issues에서도 환영합니다

---

## 📄 라이선스

이 프로젝트는 **GPL-3.0** 라이선스로 공개되어 있습니다. 자세한 내용은 [LICENSE](../LICENSE)를 참고하세요.

## 🙏 참고

1. [OpenSC/OpenSC](https://github.com/OpenSC/OpenSC) — 오픈 소스 스마트카드 도구와 미들웨어
2. [Microsoft Docs: Virtual Smart Cards](https://github.com/MicrosoftDocs/windows-itpro-docs/tree/public/windows/security/identity-protection/virtual-smart-cards)
3. WinCryptSSHAgent — 스마트카드 개인 키로 SSH 인증을 수행하는 에이전트





