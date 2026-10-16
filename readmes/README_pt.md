<div align="center">
# Gerenciador de Cartões Inteligentes Virtuais TPM

_Uma ferramenta gráfica para criar e gerenciar cartões inteligentes virtuais TPM no Windows_

<img src="../Images/QQ20261016-184916.png" width="760" alt="Gerenciador de Cartões Inteligentes Virtuais TPM">



Cartões inteligentes virtuais baseados em TPM oferecem segurança próxima à dos cartões físicos: a chave privada é protegida pelo TPM e nunca é exportada em texto claro

Permite gerar chaves e CSR localmente ou distribuir certificados com segurança pela nuvem, substituindo as necessidades PIV de cartões físicos como YubiKey e ePass


[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](../LICENSE)
[![Build](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml/badge.svg)](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml)
[![Release](https://img.shields.io/github/v/release/PIKACHUIM/TPMSmartCard?include_prereleases&label=release)](https://github.com/PIKACHUIM/TPMSmartCard/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%208%2B-0078D6.svg)](#-requisitos)

📘 [Índice da documentação](../docs/README.md) · 🧭 [Arquitetura](../docs/architecture.md) · 💾 [Design de backup e restauração](../docs/design-backup-restore.md) · 🛠️ [Solução de problemas](../docs/troubleshooting.md) · 🔐 [Modelo de segurança](../docs/security.md)

[English](README_en.md) | [简体中文](../README.md) | [繁體中文](README_zh-Hant.md) | [日本語](README_ja.md) | [한국어](README_ko.md)<br>[Deutsch](README_de.md) | [Français](README_fr.md) | [Italiano](README_it.md) | Português | [Русский](README_ru.md) | [Español](README_es.md)
</div>
---

## ✨ Recursos

### Cartões e credenciais

* **Cartões inteligentes virtuais**: criar e excluir cartões; alterar ou redefinir PIN, PUK e chave de administração
* **Certificados e chaves**: importar, excluir e consultar certificados X.509 e objetos de chave no cartão; ver a cadeia de certificação e os usos da chave
* **Geração e distribuição**: gerar chave + CSR localmente e assinar, ou receber certificados com segurança pela nuvem (acordo de chaves X25519 + AES, código de retirada fora de banda)

### Backup e restauração

* **Backup completo do cartão**: empacota um cartão em um `.tsb` (dados do cartão + registro do dispositivo + índice de chaves TPM + propriedades do dispositivo + texto claro DPAPI)
* **Restauração no mesmo TPM**: um backup só pode ser restaurado no **mesmo TPM** (reinstalar o Windows nessa máquina: sim; **outra máquina / outro TPM: não**, e **um cartão excluído não pode ser restaurado**); os dados DPAPI são descriptografados no backup e recriptografados com a chave mestra local na restauração (veja o [design de backup e restauração](../docs/design-backup-restore.md))
* **Diagnóstico da restauração**: após restaurar, a ferramenta avalia as três camadas (nó do dispositivo / leitor PC-SC / DPAPI) e apresenta uma conclusão acionável com logs

### Cenários e ferramentas

* **Login SSH2**: com o WinCryptSSHAgent, use a chave privada do cartão para acessar servidores remotos
* **Ferramentas de ambiente**: instalar / iniciar o OpenSC e o agente SSH, consultar o estado do TPM, exportar certificados e chaves públicas
* **Interface multilíngue**: 11 idiomas (简体中文 / 繁體中文 / English / 日本語 / 한국어 / Deutsch / Français / Italiano / Português / Русский / Español)

---

## 🚀 Início rápido

1. Baixe o `TPMSmartCard-*-setup.exe` (ou o zip portátil) em [Releases](https://github.com/PIKACHUIM/TPMSmartCard/releases) e instale;
2. **Execute como administrador** (registrar dispositivos de cartão e ler/gravar pastas do sistema exigem privilégios de administrador);
3. Em «Gerenciamento de cartões» crie um cartão → importe ou gere um certificado → (opcional) em «Configurações do sistema» instale e inicie o agente SSH;
4. Backup: selecione um cartão → Backup para obter um `.tsb`; Restaurar: selecione um `.tsb` → Restaurar.

> [!IMPORTANT]
> **Criar / excluir cartões inteligentes virtuais não pode ser feito em uma sessão de Área de Trabalho Remota (Serviços de Terminal)**; o Windows recusa com `0x800704d3`.
> Use o console local ou conecte-se com `mstsc /admin`.

> [!TIP]
> As ferramentas [OpenSC](https://github.com/OpenSC/OpenSC/releases) necessárias para ler cartões **acompanham o aplicativo** (a pasta `OpenSC` ao lado do programa),
> portanto não é preciso instalá-las separadamente; o componente OpenSC para todo o sistema presente no instalador é opcional e beneficia apenas outros softwares (clientes PKCS#11, minidrivers de cartões físicos etc.).

---

## 🧩 Requisitos

| Item | Requisito |
|---|---|
| Sistema | Windows 8 x86 / x64 ou superior (**privilégios de administrador necessários**) |
| Hardware | TPM 1.2 / 2.0 ou superior |
| Componentes do sistema | `tpmvscmgr`, `certutil` (incluídos no Windows) |
| Componentes incluídos | Ferramentas OpenSC, WinCryptSSHAgent, `Import` (ferramenta .NET de importação de certificados) |

---

## 🏗️ Arquitetura

| Aspecto | Valor |
|---|---|
| Linguagem / runtime | Python **3.11** |
| Interface | Tkinter + ttkbootstrap (interface construída inteiramente em código; layouts definidos em `Config/*.json`) |
| Operações no cartão | `tpmvscmgr` (criar / excluir / alterar PIN) + OpenSC (leitura de cartão e certificados) + camada própria PnP / SetupAPI (nós e propriedades do dispositivo) |
| Backup e restauração | empacotamento próprio `.tsb` (zip); `Module/DPAPI.py` cuida da criptografia/descriptografia DPAPI e da representação de token |
| Empacotamento | dois pipelines: **cx_Freeze** (builds de release, instalador via Inno Setup) e **Nuitka** (pasta standalone) |
| Idiomas | `Config/locales/*.json`, 11 idiomas |

---

## 🛠️ Desenvolvimento e compilação

```bash
# 1. Preparar um ambiente Python 3.11 (há um script de apoio incluído)
powershell -File Builds\NewVenv-PY311.ps1

# 2. Instalar as dependências
pip install -r requirements.txt

# 3. Executar direto do código-fonte (privilégios de administrador necessários)
python SmartCardAPP.py

# 4. Compilar
python BuildPackage.py build      # cx_Freeze: três executáveis + recursos incluídos
python BuildNuitka.py             # Nuitka: build/nuitka/TPMSmartCard/
```

* Verificação das dependências: `python Builds/check_imports.py`
* Guia completo de desenvolvimento (execução, empacotamento, assinatura, CI, depuração em máquina real): [guia de desenvolvimento](../docs/dev-guide.md)
* Estrutura do código e responsabilidades dos módulos: [arquitetura](../docs/architecture.md)

---

## 💾 Backup e restauração

Um cartão inteligente virtual TPM utilizável é composto por **cinco partes**, e o `.tsb` inclui todas elas:

| Parte | Conteúdo | Se faltar |
|---|---|---|
| Pasta de dados do cartão | `Tpm\<store GUID>\` (sistema de arquivos do cartão e mapas de chaves / PIN) | O cartão não tem conteúdo |
| Registro do dispositivo | `ROOT\SMARTCARDREADER\<instância>` e chaves relacionadas | O nó do dispositivo não pode ser criado |
| Índice de chaves TPM | `*.PCPKEY` (3 pastas candidatas) | O driver não encontra as chaves do cartão |
| Propriedades do dispositivo | nome do cartão, GUID do cartão, vínculo do store (protegidas por ACL; a exportação do registro não as lê) | O leitor não é publicado no PC/SC |
| Texto claro DPAPI | texto claro de `keymaps` / `pinmaps` / `pinpolicy` / `blobs\*` (recriptografado na máquina de destino) | Certificados e chave privada não aparecem |

> [!WARNING]
> Como o último item está incluído, um `.tsb` **equivale ao material de chaves do cartão**: guarde-o offline e não o coloque em controle de versão, nuvem ou ferramentas de chat.
> Na restauração, a ferramenta recriptografa com o DPAPI da máquina de destino antes de gravar; guarde também o nome do cartão, o PIN, o PUK e a chave de administração.

Outras observações:

* **Pré-requisitos**: é necessário o **mesmo TPM** (reinstalação nessa máquina: sim; outra máquina ou outro TPM: não) e o **cartão não pode ter sido excluído**
  — excluir um cartão também remove sua chave persistente no TPM: depois disso nem um backup permite restaurar;
* Após a restauração, **pode ser necessário reiniciar o dispositivo (driver) ou o sistema** para o cartão aparecer na lista de leitores;
* `.tsb` criados por versões antigas não contêm propriedades do dispositivo nem texto claro DPAPI: a restauração deixa a identidade do cartão faltando e o leitor não aparece — faça um novo backup com a versão atual.

---

## ❓ Perguntas frequentes

**P: Por que a criação de um cartão falha na Área de Trabalho Remota com `0x800704d3`?**
R: O Windows proíbe criar / excluir cartões inteligentes virtuais em uma sessão de Serviços de Terminal. Use o console local ou `mstsc /admin`.

**P: Um backup pode ser restaurado em outra máquina?**
R: **Não.** Um backup vale apenas para o **mesmo TPM**: funciona após reinstalar o Windows nessa máquina, mas não em outra máquina ou com outro TPM; além disso, um **cartão excluído**
**não pode ser restaurado** (a exclusão remove sua chave persistente no TPM). Se o cartão não aparecer após a restauração, reinicie primeiro o dispositivo ou o sistema.

**P: Após restaurar, o leitor não aparece ou os certificados não são exibidos. E agora?**
R: Veja o veredito de três camadas no log de restauração (nó do dispositivo / leitor / DPAPI). As causas mais comuns são um backup feito por versão antiga ou a ausência das propriedades de identidade do cartão;
siga o [guia de solução de problemas](../docs/troubleshooting.md) ou anexe o log a uma issue.

**P: Precisa de conexão de rede?**
R: Tudo funciona offline, exceto a «distribuição de certificados pela nuvem».

**P: A cadeia de certificação reporta `CERT_E_CHAINING`.**
R: A CA intermediária emissora não está instalada nesta máquina; importe-a para o repositório de autoridades raiz/intermediárias confiáveis.

---

## 🤝 Suporte

* 🐛 **Bugs ou sugestões de recursos**: abra uma [issue](https://github.com/PIKACHUIM/TPMSmartCard/issues) (anexe os logs em `%APPDATA%\TPMSmartCard\logs\`)
* 💬 **Dúvidas de uso**: também são bem-vindas nas issues

---

## 📄 Licença

Este projeto é distribuído sob a licença **GPL-3.0**. Consulte [LICENSE](../LICENSE).

## 🙏 Referências

1. [OpenSC/OpenSC](https://github.com/OpenSC/OpenSC) — ferramentas e middleware de código aberto para cartões inteligentes
2. [Microsoft Docs: Virtual Smart Cards](https://github.com/MicrosoftDocs/windows-itpro-docs/tree/public/windows/security/identity-protection/virtual-smart-cards)
3. WinCryptSSHAgent — agente SSH baseado na chave privada de um cartão inteligente




