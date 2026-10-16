<div align="center">
# Administrador de Tarjetas Inteligentes Virtuales TPM

_Una herramienta gráfica para crear y administrar tarjetas inteligentes virtuales TPM en Windows_

<img src="../Images/QQ20261016-184916.png" width="760" alt="Administrador de Tarjetas Inteligentes Virtuales TPM">



Las tarjetas inteligentes virtuales basadas en TPM ofrecen una seguridad cercana a las tarjetas físicas: la clave privada está protegida por el TPM y nunca se exporta en claro

Permite generar claves y CSR localmente o distribuir certificados de forma segura desde la nube, sustituyendo las necesidades PIV de tarjetas físicas como YubiKey o ePass


[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](../LICENSE)
[![Build](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml/badge.svg)](https://github.com/PIKACHUIM/TPMSmartCard/actions/workflows/build-client-release.yml)
[![Release](https://img.shields.io/github/v/release/PIKACHUIM/TPMSmartCard?include_prereleases&label=release)](https://github.com/PIKACHUIM/TPMSmartCard/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%208%2B-0078D6.svg)](#-requisitos)

📘 [Índice de documentación](../docs/README.md) · 🧭 [Arquitectura](../docs/architecture.md) · 💾 [Diseño de copia y restauración](../docs/design-backup-restore.md) · 🛠️ [Solución de problemas](../docs/troubleshooting.md) · 🔐 [Modelo de seguridad](../docs/security.md)

[English](README_en.md) | [简体中文](../README.md) | [繁體中文](README_zh-Hant.md) | [日本語](README_ja.md) | [한국어](README_ko.md)<br>[Deutsch](README_de.md) | [Français](README_fr.md) | [Italiano](README_it.md) | [Português](README_pt.md) | [Русский](README_ru.md) | Español
</div>
---

## ✨ Funciones

### Tarjetas y credenciales

* **Tarjetas inteligentes virtuales**: crear y eliminar tarjetas; cambiar o restablecer PIN, PUK y clave de administración
* **Certificados y claves**: importar, eliminar y consultar certificados X.509 y objetos de clave en la tarjeta; ver la cadena de certificación y los usos de la clave
* **Generación y distribución**: generar clave + CSR localmente y firmarlo, o recibir certificados de forma segura desde la nube (acuerdo de claves X25519 + AES, código de recogida fuera de banda)

### Copia de seguridad y restauración

* **Copia completa de la tarjeta**: empaqueta una tarjeta en un `.tsb` (datos de la tarjeta + registro del dispositivo + índice de claves TPM + propiedades del dispositivo + texto en claro DPAPI)
* **Restauración en el mismo TPM**: una copia solo se puede restaurar en el **mismo TPM** (reinstalar Windows en ese equipo: sí; **otro equipo / otro TPM: no**, y **una tarjeta eliminada no se puede restaurar**); los datos DPAPI se descifran al copiar y se vuelven a cifrar con la clave maestra local al restaurar (ver [diseño de copia y restauración](../docs/design-backup-restore.md))
* **Diagnóstico de restauración**: tras restaurar, la herramienta evalúa las tres capas (nodo de dispositivo / lector PC-SC / DPAPI) y ofrece una conclusión accionable con registros

### Escenarios y herramientas

* **Inicio de sesión SSH2**: junto con WinCryptSSHAgent, usa la clave privada de la tarjeta para conectarte a servidores remotos
* **Herramientas de entorno**: instalar / iniciar OpenSC y el agente SSH, consultar el estado del TPM, exportar certificados y claves públicas
* **Interfaz multiidioma**: 11 idiomas (简体中文 / 繁體中文 / English / 日本語 / 한국어 / Deutsch / Français / Italiano / Português / Русский / Español)

---

## 🚀 Inicio rápido

1. Descarga `TPMSmartCard-*-setup.exe` (o el zip portátil) desde [Releases](https://github.com/PIKACHUIM/TPMSmartCard/releases) e instálalo;
2. **Ejecútalo como administrador** (registrar dispositivos de tarjeta y leer/escribir carpetas del sistema requiere permisos de administrador);
3. En «Gestión de tarjetas» crea una tarjeta → importa o genera un certificado → (opcional) en «Configuración del sistema» instala e inicia el agente SSH;
4. Copia: selecciona una tarjeta → Copia para obtener un `.tsb`; Restaurar: selecciona un `.tsb` → Restaurar.

> [!IMPORTANT]
> **Crear / eliminar tarjetas inteligentes virtuales no se puede hacer dentro de una sesión de Escritorio remoto (Servicios de Terminal Server)**; Windows lo rechaza con `0x800704d3`.
> Usa la consola local o conéctate con `mstsc /admin`.

> [!TIP]
> Las herramientas [OpenSC](https://github.com/OpenSC/OpenSC/releases) necesarias para leer tarjetas **vienen incluidas con la aplicación** (la carpeta `OpenSC` junto al programa),
> por lo que no hace falta instalarlas aparte; el componente OpenSC para todo el sistema del instalador es opcional y solo beneficia a otro software (clientes PKCS#11, minidrivers de tarjetas físicas, etc.).

---

## 🧩 Requisitos

| Elemento | Requisito |
|---|---|
| Sistema | Windows 8 x86 / x64 o superior (**se requieren permisos de administrador**) |
| Hardware | TPM 1.2 / 2.0 o superior |
| Componentes del sistema | `tpmvscmgr`, `certutil` (incluidos en Windows) |
| Componentes incluidos | Herramientas OpenSC, WinCryptSSHAgent, `Import` (herramienta .NET para importar certificados) |

---

## 🏗️ Arquitectura

| Aspecto | Valor |
|---|---|
| Lenguaje / runtime | Python **3.11** |
| Interfaz | Tkinter + ttkbootstrap (interfaz construida íntegramente por código; los diseños se definen en `Config/*.json`) |
| Operaciones sobre la tarjeta | `tpmvscmgr` (crear / eliminar / cambiar PIN) + OpenSC (lectura de tarjeta y certificados) + capa propia PnP / SetupAPI (nodos y propiedades del dispositivo) |
| Copia y restauración | empaquetado propio `.tsb` (zip); `Module/DPAPI.py` gestiona el cifrado/descifrado DPAPI y la suplantación de token |
| Empaquetado | dos canalizaciones: **cx_Freeze** (compilaciones de versión, instalador con Inno Setup) y **Nuitka** (carpeta standalone) |
| Idiomas | `Config/locales/*.json`, 11 idiomas |

---

## 🛠️ Desarrollo y compilación

```bash
# 1. Preparar un entorno de Python 3.11 (se incluye un script de ayuda)
powershell -File Builds\NewVenv-PY313.ps1

# 2. Instalar las dependencias
pip install -r requirements.txt

# 3. Ejecutar directamente desde el código fuente (se requieren permisos de administrador)
python SmartCardAPP.py

# 4. Compilar
python BuildPackage.py build      # cx_Freeze: tres ejecutables + recursos incluidos
python BuildNuitka.py             # Nuitka: build/nuitka/TPMSmartCard/
```

* Comprobación de dependencias: `python Builds/check_imports.py`
* Guía completa de desarrollo (ejecución, empaquetado, firma, CI, depuración en equipo real): [guía de desarrollo](../docs/dev-guide.md)
* Estructura del código y responsabilidades de los módulos: [arquitectura](../docs/architecture.md)

---

## 💾 Copia de seguridad y restauración

Una tarjeta inteligente virtual TPM utilizable consta de **cinco partes**, y el `.tsb` las incluye todas:

| Parte | Contenido | Si falta |
|---|---|---|
| Carpeta de datos de la tarjeta | `Tpm\<store GUID>\` (sistema de archivos de la tarjeta y mapas de claves / PIN) | La tarjeta no tiene contenido |
| Registro del dispositivo | `ROOT\SMARTCARDREADER\<instancia>` y claves relacionadas | No se puede crear el nodo del dispositivo |
| Índice de claves TPM | `*.PCPKEY` (3 carpetas candidatas) | El controlador no encuentra las claves de la tarjeta |
| Propiedades del dispositivo | nombre de la tarjeta, GUID de la tarjeta, enlace del store (protegidas por ACL; la exportación del registro no las lee) | El lector no se publica en PC/SC |
| Texto en claro DPAPI | texto en claro de `keymaps` / `pinmaps` / `pinpolicy` / `blobs\*` (se vuelve a cifrar en el equipo de destino) | Los certificados y la clave privada no aparecen |

> [!WARNING]
> Como se incluye el último elemento, un `.tsb` **equivale al material de claves de la tarjeta**: guárdalo sin conexión y no lo pongas en control de versiones, nubes ni herramientas de chat.
> Al restaurar, la herramienta lo vuelve a cifrar con el DPAPI del equipo de destino antes de escribirlo; guarda también el nombre de la tarjeta, el PIN, el PUK y la clave de administración.

Otras notas:

* **Requisitos**: se necesita el **mismo TPM** (reinstalar en ese equipo: sí; otro equipo u otro TPM: no) y la **tarjeta no debe haber sido eliminada**
  — eliminar una tarjeta borra también su clave persistente en el TPM: después, ni una copia permite restaurarla;
* Tras restaurar, **puede ser necesario reiniciar el dispositivo (controlador) o el sistema** para que la tarjeta aparezca en la lista de lectores;
* Los `.tsb` creados por versiones anteriores no incluyen propiedades del dispositivo ni texto en claro DPAPI: al restaurar falta la identidad de la tarjeta y el lector no aparece — crea una copia nueva con la versión actual.

---

## ❓ Preguntas frecuentes

**P: ¿Por qué falla la creación de una tarjeta en Escritorio remoto con `0x800704d3`?**
R: Windows prohíbe crear / eliminar tarjetas inteligentes virtuales en una sesión de Servicios de Terminal Server. Usa la consola local o conéctate con `mstsc /admin`.

**P: ¿Se puede restaurar una copia en otro equipo?**
R: **No.** Una copia solo sirve para el **mismo TPM**: funciona tras reinstalar Windows en ese equipo, pero no en otro equipo ni con otro TPM; además, una **tarjeta eliminada**
**no se puede restaurar** (al eliminarla se borra su clave persistente en el TPM). Si la tarjeta no aparece tras restaurar, reinicia primero el dispositivo o el sistema.

**P: Tras restaurar la tarjeta no aparece. ¿Qué hago?**
R: **Reinicia primero**: la tarjeta puede aparecer en la lista de lectores solo tras **reiniciar el dispositivo (controlador) o el sistema**. Si sigue sin aparecer,
consulta el veredicto de tres capas del registro (nodo de dispositivo / lector / DPAPI): suele deberse a una copia de una versión anterior o a la falta de las propiedades de identidad ([solución de problemas](../docs/troubleshooting.md)).

**P: Tras restaurar no aparece el lector o no se ven los certificados, ¿qué hago?**
R: Consulta el veredicto de tres capas del registro de restauración (nodo de dispositivo / lector / DPAPI). Las causas más habituales son una copia hecha con una versión anterior o la falta de las propiedades de identidad de la tarjeta;
sigue la [guía de solución de problemas](../docs/troubleshooting.md) paso a paso o adjunta el registro a una incidencia.

**P: ¿Necesita conexión de red?**
R: Todo funciona sin conexión excepto la «distribución de certificados desde la nube».

**P: La cadena de certificación indica `CERT_E_CHAINING`.**
R: La CA intermedia emisora no está instalada en este equipo; impórtala en el almacén de entidades de certificación raíz/intermedias de confianza.

---

## 🤝 Soporte

* 🐛 **Errores o solicitudes de funciones**: abre una [incidencia](https://github.com/PIKACHUIM/TPMSmartCard/issues) (adjunta los registros de `%APPDATA%\TPMSmartCard\logs\`)
* 💬 **Dudas de uso**: también son bienvenidas en las incidencias

---

## 📄 Licencia

Este proyecto se publica bajo la licencia **GPL-3.0**. Consulta [LICENSE](../LICENSE).

## 🙏 Referencias

1. [OpenSC/OpenSC](https://github.com/OpenSC/OpenSC) — herramientas y middleware de código abierto para tarjetas inteligentes
2. [Microsoft Docs: Virtual Smart Cards](https://github.com/MicrosoftDocs/windows-itpro-docs/tree/public/windows/security/identity-protection/virtual-smart-cards)
3. WinCryptSSHAgent — agente SSH basado en la clave privada de una tarjeta inteligente





