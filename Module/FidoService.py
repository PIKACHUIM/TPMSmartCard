# -*- coding: utf-8 -*-
"""FIDO2 服务：把「虚拟 USB 设备 / 命名管道 / 凭据库 / 卡片 PIN」串起来。

对外只有 :class:`FidoService`（单例）：

* :meth:`start` / :meth:`stop` —— 启停设备端进程与管道服务；
* :meth:`status` —— 安装/运行状态（界面用）；
* :meth:`install_driver` —— 安装 USB/IP 虚拟总线驱动；
* :meth:`list_credentials` / :meth:`delete_credential` —— 凭据管理；
* :meth:`rewrap_after_pin_change` / :meth:`rewrap_after_unblock` ——
  改 PIN / PUK 解锁后，把凭据重新封装到新 PIN 下。

认证流程（与 Fido/fido-go.exe 的约定）：

1. 浏览器发起 WebAuthn → fido-go 转一条 CTAP2 请求过来；
2. 没有有效会话时返回 ``rv = 0x36``（PIN_REQUIRED）+ 可用卡片列表；
3. fido-go 弹出「选卡 + 输 PIN」对话框，然后调 ``0x0304`` 登录；
4. 登录时先用 OpenSC 让**卡片**校验 PIN（错误次数由 TPM 卡计数），
   再用同一个 PIN 派生 masterKey 解开凭据库，会话缓存到超时；
5. fido-go 重启虚拟设备，浏览器自动重试，这次就能注册/签名了。
"""

import base64
import json
import os
import subprocess
import threading
import time

from Module import FidoClientPin
from Module import FidoCtap
from Module import FidoIpc
from Module import FidoRuntime
from Module import FidoStore
from Module import Paths


def _log_path():
    return os.path.join(FidoRuntime.log_dir(), "fido-service.log")


class FidoService:
    """FIDO2 服务单例。"""

    _instance = None
    _instance_lock = threading.Lock()

    # ---- 单例 ------------------------------------------------------------ #
    @classmethod
    def get(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._lock = threading.RLock()
        self._server = None
        self._session = None          # {"store", "master", "expires", "card"}
        self._started_at = ""
        self._last_error = ""
        self._log_lock = threading.Lock()
        # clientPIN 模式的密钥协商状态（平台每次认证前会重新 getKeyAgreement）
        self._pin = FidoClientPin.PinProtocol()
        self._pin_retries = 8         # 平台侧展示的剩余次数（真实计数在卡片里）

    # ---- 日志 ------------------------------------------------------------ #
    def log(self, text):
        line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), text)
        print("FIDO:", text)
        try:
            with self._log_lock:
                with open(_log_path(), "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError:
            pass

    # ---- 设置 ------------------------------------------------------------ #
    @property
    def settings(self):
        return FidoStore.read_settings()

    def update_settings(self, **kwargs):
        settings = self.settings
        settings.update(kwargs)
        return FidoStore.write_settings(settings)

    @property
    def pin_mode(self):
        """PIN 由谁收集：``clientpin``（平台，默认）/ ``builtin``（本程序弹窗）。"""
        value = str(self.settings.get("pin_mode")
                    or FidoCtap.PIN_MODE_CLIENT).strip().lower()
        if value not in (FidoCtap.PIN_MODE_CLIENT, FidoCtap.PIN_MODE_BUILTIN):
            return FidoCtap.PIN_MODE_CLIENT
        return value

    # ---- 卡片枚举 -------------------------------------------------------- #
    def cards(self, include_disabled=False):
        """当前系统里的 TPM 虚拟卡 + 它们在 FIDO 存储中的身份。

        返回 ``[{"name","uuid","reader","key","guid","enabled","count"}]``，
        ``uuid`` 是读卡器序列号（fido-go 只把它当不透明标识回传）。
        """
        result = []
        try:
            from Module.SmartCardAPI import SmartCardAPI
            api = SmartCardAPI()
            api.readInfo()
        except Exception as err:                       # 卡片服务没起来等
            self.log("枚举卡片失败: %s" % err)
            return result
        for name, card in (api.cards or {}).items():
            serial = getattr(card, "sc_uuid", "") or ""
            instance = getattr(card, "sc_path", "") or ""
            reader = api.readerIndexFor(name)
            guid = ""
            try:
                from Module import TPMBackup
                guid = TPMBackup.card_store_guid(
                    str(instance).split("\\")[-1]) or ""
            except Exception:
                guid = ""
            key = FidoStore.card_key(guid, serial, name)
            store = None
            try:
                store = FidoStore.FidoStore.load(key)
            except FidoStore.StoreError as err:
                self.log("读取凭据库失败(%s): %s" % (name, err))
            enabled = True if store is None else store.enabled
            if not enabled and not include_disabled:
                continue
            result.append({
                "name": name,
                "uuid": serial or name,
                "reader": reader,
                "key": key,
                "guid": guid,
                "serial": serial,
                "enabled": enabled,
                "count": len(store.credentials) if store else 0,
            })
        return result

    def card_identity(self, card_name):
        """按读卡器名取卡片身份（含 reader / guid / key）。"""
        for item in self.cards(include_disabled=True):
            if item["name"] == card_name:
                return item
        return None

    def store_for_card(self, card_name):
        """取（或创建）某张卡的凭据库。"""
        info = self.card_identity(card_name)
        if info is None:
            return None
        return FidoStore.FidoStore.open(info["guid"], info["serial"], info["name"])

    def active_card(self, prefer=None):
        """clientPIN 流程用哪张卡：优先上次用过的，否则取第一张可用卡。"""
        items = self.cards()
        if not items:
            return None
        name = str(prefer or self.settings.get("active_card") or "")
        for item in items:
            if item["name"] == name:
                return item
        return items[0]

    def _bind_session(self, card, store, master):
        self._session = {"store": store, "master": master, "card": card,
                         "expires": time.time() + self._session_timeout()}
        try:
            self.update_settings(active_card=card["name"])
        except Exception:
            pass

    # ---- clientPIN：平台弹 PIN，设备只负责校验 ---------------------------- #
    def _pin_verifier(self, action, payload=None):
        """:func:`Module.FidoCtap.client_pin` 的回调。

        返回 ``{"status": ok/wrong/locked/not_set, "retries": n, "message": str}``。
        """
        if self.pin_mode != FidoCtap.PIN_MODE_CLIENT:
            return {"status": "not_set", "message": "当前不是 clientPIN 模式"}
        card = self.active_card()
        if card is None:
            return {"status": "not_set", "message": "没有可用的 TPM 虚拟卡"}
        try:
            store = FidoStore.FidoStore.open(card["guid"], card["serial"],
                                            card["name"])
        except FidoStore.StoreError as err:
            return {"status": "not_set", "message": str(err)}
        if action == "retries":
            if not store.has_pin_verifier:
                return {"status": "not_set"}
            return {"status": "ok", "retries": max(1, int(self._pin_retries))}
        if action == "set_pin":
            return self._clientpin_set_pin(card, store, str(payload or ""))
        if action == "token":
            return self._clientpin_token(card, store, bytes(payload or b""))
        return {"status": "not_set"}

    def _clientpin_set_pin(self, card, store, pin):
        """平台第一次收 PIN：这是唯一能拿到明文的时刻，交给卡片自己校验。"""
        if not pin:
            return {"status": "wrong", "message": "PIN 不能为空"}
        state, text = self.verify_pin(card["reader"], pin)
        if state == "locked":
            self._pin_retries = 0
            self.log("clientPIN：卡片 PIN 已锁定")
            return {"status": "locked", "message": "PIN 已锁定，请先用 PUK 解锁"}
        if state != "ok":
            self._pin_retries = max(0, self._pin_retries - 1)
            self.log("clientPIN：卡片 PIN 校验未通过（%s）：%s"
                     % (state, (text or "")[:200]))
            if self._pin_retries <= 0:
                return {"status": "locked", "message": (text or "")[:120]}
            return {"status": "wrong", "message": (text or "")[:120]}
        master = store.unlock(pin)
        if master is None:
            self.log("clientPIN：PIN 正确但凭据库解不开（PIN 与库不匹配）")
            return {"status": "wrong", "message": "PIN 与凭据库不匹配"}
        store.set_pin_verifier(pin)      # 之后只能拿到哈希，用它比对
        store.remember_master(master)    # DPAPI 副本：重启后不用 PIN 原文也能解库
        self._bind_session(card, store, master)
        self._pin_retries = 8
        self.log("clientPIN：卡片校验通过，已记录 PIN 校验材料（%s）" % card["name"])
        return {"status": "ok", "retries": 8}

    def _clientpin_token(self, card, store, digest):
        """之后的每次认证：平台只送 ``SHA-256(PIN)[0:16]``，比对记录值。"""
        if not store.has_pin_verifier:
            self.log("clientPIN：本机还没有 PIN 校验材料，需要平台重新设置 PIN")
            return {"status": "not_set"}
        if not store.check_pin_verifier(digest):
            self._pin_retries = max(0, self._pin_retries - 1)
            self.log("clientPIN：PIN 哈希不匹配（本机记录剩余 %d 次）"
                     % self._pin_retries)
            if self._pin_retries <= 0:
                return {"status": "locked", "message": "PIN 连续错误"}
            return {"status": "wrong", "message": "PIN 不正确",
                    "retries": self._pin_retries}
        master = store.recover_master()
        if master is None:
            # 换机/重装丢了 DPAPI 副本：清掉哈希，让平台重新走 setPIN
            store.clear_pin_verifier()
            self.log("clientPIN：缺少本机解锁副本，已要求重新设置 PIN")
            return {"status": "not_set", "message": "凭据库缺少本机解锁副本"}
        session = self.session
        if session is None or session["card"].get("name") != card["name"]:
            self._bind_session(card, store, master)
        else:
            session["store"] = store
            session["master"] = master
            self._touch_session()
        self._pin_retries = 8
        return {"status": "ok", "retries": 8}

    # ---- 卡片 PIN 校验 --------------------------------------------------- #
    @staticmethod
    def _opensc_tool(name):
        return Paths.resource("OpenSC", name)

    def verify_pin(self, reader, pin):
        """让**卡片**校验 PIN：``(状态, 说明)``，状态 ∈ ok / wrong / locked / error。"""
        if reader is None:
            return "error", "找不到卡片在读卡器列表中的编号"
        tool = self._opensc_tool("pkcs15-tool.exe")
        if not os.path.isfile(tool):
            return "error", "缺少 OpenSC 工具: %s" % tool
        base = [tool, "--verify-pin", "--reader", str(int(reader))]
        # 先用 stdin 传 PIN，避免 PIN 出现在命令行（其它用户可以读进程命令行）。
        # 超时给 12 秒：万一这个 OpenSC 构建在非控制台下弹窗等输入，别让浏览器
        # 的 WebAuthn 请求干等太久，超时后走下面的 --pin 参数兜底。
        text = ""
        try:
            proc = subprocess.run(base, input="%s\n" % pin, text=True,
                                  capture_output=True, timeout=12)
            text = "%s%s" % (proc.stdout or "", proc.stderr or "")
            state = self._pin_verdict(proc.returncode, text, pin)
            if state != "retry":
                self.log("PIN 校验（stdin）: %s" % state)
                return state, text.strip()[:400]
        except (OSError, subprocess.SubprocessError) as err:
            self.log("PIN 校验（stdin）失败: %s" % err)
        # 兜底：OpenSC 在非交互管道下可能不读 stdin，改用 --pin 参数
        try:
            proc = subprocess.run(base + ["--pin", str(pin)], text=True,
                                  capture_output=True, timeout=45)
            text = "%s%s" % (proc.stdout or "", proc.stderr or "")
            state = self._pin_verdict(proc.returncode, text, pin)
            self.log("PIN 校验（命令行）: %s" % state)
            return state, text.strip()[:400]
        except (OSError, subprocess.SubprocessError) as err:
            return "error", str(err)

    @staticmethod
    def _pin_verdict(returncode, text, pin):
        """根据 pkcs15-tool 的输出判断 PIN 校验结果。"""
        lowered = (text or "").lower()
        if "locked" in lowered or "blocked" in lowered:
            return "locked"
        if "verification failed" in lowered or "not satisfied" in lowered \
                or "incorrect" in lowered:
            return "wrong"
        if returncode == 0 and "succed" in lowered:
            return "ok"
        if returncode == 0 and "verified" in lowered:
            return "ok"
        if "please enter pin" in lowered or "pin:" in lowered:
            # 没有真正读到 PIN（说明 stdin 未被读取），交给调用方换方式重试
            return "retry"
        if returncode == 0:
            return "ok"
        return "error"

    # ---- 会话 ------------------------------------------------------------ #
    def _session_timeout(self):
        try:
            return max(60, int(self.settings.get("session_timeout") or 900))
        except (TypeError, ValueError):
            return 900

    @property
    def session(self):
        session = self._session
        if session and session["expires"] >= time.time():
            return session
        self._session = None
        return None

    def logout(self):
        with self._lock:
            if self._session:
                self.log("会话已结束: %s" % self._session["card"].get("name"))
            self._session = None

    def login(self, card_uuid, pin):
        """fido-go 的登录回调：校验卡片 PIN + 解锁凭据库。返回 rv 码。"""
        with self._lock:
            items = [item for item in self.cards() if item["uuid"] == card_uuid]
            if not items:
                self.log("登录失败：找不到卡片 %s" % card_uuid)
                return 0xA2                     # 没有这张卡
            card = items[0]
            state, text = self.verify_pin(card["reader"], pin)
            if state == "locked":
                self.log("PIN 已锁定: %s" % card["name"])
                return 0xA1
            if state != "ok":
                self.log("PIN 校验未通过（%s）: %s" % (state, text))
                return 0xA0
            store = FidoStore.FidoStore.open(card["guid"], card["serial"], card["name"])
            master = store.unlock(pin)
            if master is None:
                self.log("PIN 正确但凭据库解不开：凭据是用另一个 PIN 封装的")
                return 0xA0
            store.remember_master(master)
            self._bind_session(card, store, master)
            self.log("PIN 认证成功: %s（凭据 %d 条）" % (card["name"],
                                                        len(store.credentials)))
            return 0

    def _touch_session(self):
        if self._session:
            self._session["expires"] = time.time() + self._session_timeout()

    # ---- IPC 分发 -------------------------------------------------------- #
    def dispatch(self, cmd, payload):
        """管道请求处理：``(cmd, payload) -> dict``。"""
        try:
            body = json.loads(payload.decode("utf-8")) if payload else {}
        except ValueError:
            body = {}
        try:
            if cmd == FidoIpc.CMD_GET_INFO:
                info = FidoCtap.get_info(self.pin_mode)
                return {"rv": 0, "data": {
                    "cbor_info": base64.b64encode(info).decode("ascii")}}
            if cmd == FidoIpc.CMD_CANCEL:
                return {"rv": 0}
            if cmd == FidoIpc.CMD_LOGIN:
                rv = self.login(str(body.get("card_uuid") or ""),
                                str(body.get("pin") or ""))
                return {"rv": rv}
            if cmd in (FidoIpc.CMD_MAKE_CREDENTIAL, FidoIpc.CMD_GET_ASSERTION,
                       FidoIpc.CMD_CLIENT_PIN):
                return self._handle_ctap(cmd, body)
            self.log("未知 IPC 命令 0x%04X" % cmd)
            return {"rv": FidoCtap.CTAP1_ERR_INVALID_COMMAND}
        except Exception as err:                       # 兜底：绝不让管道线程崩掉
            self.log("处理 IPC 命令 0x%04X 异常: %s" % (cmd, err))
            import traceback
            self.log(traceback.format_exc(limit=4))
            return {"rv": FidoCtap.CTAP1_ERR_OTHER}

    def _handle_ctap(self, cmd, body):
        cbor = base64.b64decode(body.get("cbor_req") or "")
        command = {
            FidoIpc.CMD_MAKE_CREDENTIAL: FidoCtap.CMD_MAKE_CREDENTIAL,
            FidoIpc.CMD_GET_ASSERTION: FidoCtap.CMD_GET_ASSERTION,
            FidoIpc.CMD_CLIENT_PIN: FidoCtap.CMD_CLIENT_PIN,
        }.get(cmd, FidoCtap.CMD_GET_ASSERTION)
        mode = self.pin_mode
        client_pin = mode == FidoCtap.PIN_MODE_CLIENT
        session = self.session
        try:
            result = FidoCtap.handle(
                command, cbor,
                session["store"] if session else None,
                session["master"] if session else None,
                self.log,
                pin=self._pin if client_pin else None,
                pin_mode=mode,
                pin_verifier=self._pin_verifier if client_pin else None)
            self._touch_session()
        except FidoCtap.PinRequired:
            # platform_pin=True 告诉 fido-go：不要弹自带对话框，直接把 0x36
            # 交给平台（Windows 会用自己的 PIN 对话框继续 clientPIN 流程）
            return {"rv": FidoCtap.CTAP2_ERR_PIN_REQUIRED,
                    "data": {"platform_pin": client_pin,
                             "cards": [{"card_uuid": item["uuid"],
                                        "card_name": item["name"]}
                                       for item in self.cards()]}}
        except FidoCtap.CtapError as err:
            self.log("CTAP 命令 0x%02X 失败（0x%02X）: %s"
                     % (command, err.code, err))
            if err.code == FidoCtap.CTAP2_ERR_PIN_REQUIRED and client_pin:
                # 同样是「要 PIN」：告诉 fido-go 别弹自带对话框（它只认这个标记）
                return {"rv": err.code, "data": {"platform_pin": True}}
            return {"rv": err.code}
        return {"rv": 0, "data": {"cbor_resp": base64.b64encode(result).decode("ascii")}}

    # ---- 启停 ------------------------------------------------------------ #
    def start(self, auto_install_driver=False):
        """启动 FIDO2 服务；返回 ``(ok, 说明)``。"""
        with self._lock:
            ok, text = FidoRuntime.runtime_ready()
            if not ok:
                self._last_error = text
                return False, text

            if self._server is None:
                self._server = FidoIpc.PipeServer(self.dispatch,
                                                  name=FidoRuntime.PIPE_NAME,
                                                  logger=self.log)
            if not self._server.running:
                if not self._server.start():
                    self._last_error = self._server.error or "管道服务启动失败"
                    return False, self._last_error
            state, state_text, _driver = FidoRuntime.driver_state()
            if state != "ok":
                if auto_install_driver:
                    ok, lines = FidoRuntime.install_driver()
                    self.log("自动安装驱动: %s" % (lines[-1] if lines else ""))
                    if not ok:
                        return False, "\n".join(lines[-4:])
                else:
                    return False, "USB/IP 虚拟总线驱动未就绪：%s" % state_text

            FidoRuntime.clear_old_log()
            ok, text = FidoRuntime.start_service(pin_strings=self.pin_strings())
            if not ok:
                self._last_error = text
                return False, text
            self.update_settings(enabled=True)
            self._started_at = time.strftime("%Y-%m-%d %H:%M:%S")
            self.log("FIDO2 服务已启动: %s" % text)
            return True, text

    def stop(self, keep_enabled=True):
        with self._lock:
            self.logout()
            ok, text = FidoRuntime.stop_service()
            if self._server is not None and self._server.running:
                self._server.stop()
            if keep_enabled:
                # 「停止」只停这一次运行，设置里的总开关保持不变
                pass
            self.log("FIDO2 服务已停止: %s" % text)
            return ok, text

    def restart(self):
        self.stop()
        return self.start()

    @property
    def running(self):
        return (self._server is not None and self._server.running
                and FidoRuntime.service_running())

    def install_driver(self):
        """安装/修复 USB/IP 虚拟总线驱动；返回 ``(ok, 日志行)``。"""
        with self._lock:
            self.log("开始安装虚拟总线驱动（需要管理员权限）")
            ok, lines = FidoRuntime.install_driver()
            self.log("驱动安装结果: %s" % ("成功" if ok else "失败"))
            for line in lines[-6:]:
                self.log("  %s" % line)
            return ok, lines

    def uninstall_driver(self):
        with self._lock:
            ok, lines = FidoRuntime.uninstall_driver()
            self.log("驱动卸载结果: %s" % ("成功" if ok else "失败"))
            return ok, lines

    # ---- 界面文案（PIN 弹窗） -------------------------------------------- #
    def pin_strings(self):
        """把 PIN 弹窗文案按当前界面语言取出来交给 fido-go。"""
        try:
            from Module.I18n import get_i18n
            i18n = get_i18n()
        except Exception:
            i18n = None

        def text(key, default):
            if i18n is None:
                return default
            value = i18n.t(key)
            return default if not value or value == key else value

        return {
            "title": text("msg_fido_pin_title", "TPM 智能卡 - FIDO2 认证"),
            "card": text("msg_fido_pin_card", "选择智能卡(&C):"),
            "pin": text("msg_fido_pin_label", "PIN 码(&P):"),
            "ok": text("msg_fido_pin_ok", "确定"),
            "cancel": text("msg_fido_pin_cancel", "取消"),
            "wrong": text("msg_fido_pin_wrong", "PIN 不正确，请重试"),
        }

    # ---- 状态 ------------------------------------------------------------ #
    def status(self):
        info = FidoRuntime.status()
        settings = self.settings
        stores = FidoStore.FidoStore.list_all()
        info.update({
            "service": bool(self._server is not None and self._server.running),
            "session": bool(self.session),
            "session_card": (self.session["card"]["name"] if self.session else ""),
            "started_at": self._started_at,
            "settings": settings,
            "cards": [store.summary() for store in stores],
            "credential_count": sum(len(store.credentials) for store in stores),
            "error": self._last_error,
        })
        return info

    # ---- 自检 ------------------------------------------------------------ #
    def selfcheck(self):
        """端到端自检：管道往返 + GetInfo 解析 + 设备挂载状态。

        用来区分「后端没起来」和「驱动/设备没挂上」——这两类问题的现象都是
        「浏览器里看不到安全密钥」。
        """
        from Module import FidoCbor
        info = self.status()
        lines = []
        if info["runtime"]:
            lines.append("[OK] 运行文件：%s" % info["runtime_text"])
        else:
            lines.append("[失败] %s" % info["runtime_text"])
        lines.append("%s 虚拟总线驱动：%s" % ("[OK]" if info["driver"] == "ok" else "[失败]",
                                            info["driver_text"]))
        lines.append("%s 设备端进程：%s" % ("[OK]" if info["process"] else "[失败]",
                                           ("PID %d" % info["pid"]) if info["process"]
                                           else "未运行"))
        lines.append("%s 虚拟设备挂载：%s" % ("[OK]" if info["device"] else "[失败]",
                                           "已挂载" if info["device"] else "未挂载"))
        lines.append("%s 命名管道服务：%s" % ("[OK]" if info["service"] else "[失败]",
                                           "运行中" if info["service"] else "未启动"))
        if info["driver"] != "ok":
            # 驱动装不上时最大概率是签名问题，把诊断直接摆出来省一次来回
            report = FidoRuntime.signature_report()
            lines.append("签名诊断：测试签名=%s" % report.get("testsigning"))
            for name, state in (report.get("files") or {}).items():
                lines.append("  %s：%s" % (name, state))
        try:
            response = FidoIpc.call_pipe(FidoIpc.CMD_GET_INFO, {},
                                         FidoRuntime.PIPE_NAME, timeout=3)
            if response.get("rv"):
                lines.append("[失败] GetInfo 返回错误码 %s" % response.get("rv"))
            else:
                raw = base64.b64decode(response["data"]["cbor_info"])
                parsed = FidoCbor.decode(raw)
                algorithms = [item.get("alg") for item in parsed.get(0x0A) or []
                              if isinstance(item, dict)]
                lines.append("[OK] GetInfo：版本=%s，算法=%s，rk=%s，uv=%s"
                             % ("/".join(parsed.get(1) or []), algorithms,
                                (parsed.get(4) or {}).get("rk"),
                                (parsed.get(4) or {}).get("uv")))
        except Exception as err:
            lines.append("[失败] GetInfo 往返失败：%s" % err)
        lines.append("凭据：%d 条（%s）"
                     % (info["credential_count"],
                        "；".join("%s:%d" % (item["name"], item["count"])
                                 for item in info["cards"]) or "无卡片记录"))
        ok = all(not line.startswith("[失败]") for line in lines)
        return ok, lines

    # ---- 凭据管理 -------------------------------------------------------- #
    def list_credentials(self):
        """列出本机所有卡的凭据（不含私钥）。"""
        rows = []
        for store in FidoStore.FidoStore.list_all():
            for entry in store.credentials:
                meta = entry.get("meta") or {}
                rows.append({
                    "card_key": store.key,
                    "card": store.display_name,
                    "uuid": entry.get("uuid", ""),
                    "rp_id": meta.get("rp_id", ""),
                    "rp_name": meta.get("rp_name", ""),
                    "user_name": meta.get("user_name", ""),
                    "user_display_name": meta.get("user_display_name", ""),
                    "credential_id": meta.get("credential_id", ""),
                    "counter": meta.get("counter", 0),
                    "algorithm": meta.get("algorithm", 0),
                    "created_at": entry.get("created_at", ""),
                    "last_used_at": entry.get("last_used_at", ""),
                })
        rows.sort(key=lambda row: (row["card"], row["rp_id"]))
        return rows

    def _store_for_write(self, card_key):
        """取一个和当前会话一致的 store 实例（避免内存副本覆盖磁盘）。

        关键：登录后 ``self._session["store"]`` 是一份**内存副本**，认证成功后
        ``bump_counter`` 会把它写回磁盘。如果删除凭据时另开一个实例只改磁盘，
        下一次认证就会用内存副本把刚删掉的凭据写回去——现象就是「删了以后
        重启程序又出现，而且还能用它认证」。
        """
        session = self.session
        if session is not None and session["store"].key == card_key:
            return session["store"], True
        return FidoStore.FidoStore.load(card_key), False

    def delete_credential(self, card_key, entry_uuid):
        with self._lock:
            store, shared = self._store_for_write(card_key)
            if store is None:
                return False
            ok = store.delete_credential(entry_uuid)
            if ok:
                # 凭据集合变了，当前会话语义上已经不可信：直接失效，下次认证
                # 重新验 PIN（否则同一个 PIN 会话里还能继续用旧状态）
                if shared:
                    self.logout()
                self.log("已删除凭据: %s（%s）" % (entry_uuid, store.display_name))
            return ok

    def clear_credentials(self, card_key):
        with self._lock:
            store, shared = self._store_for_write(card_key)
            if store is None:
                return 0
            count = len(store.credentials)
            if not count:
                return 0
            store.clear_credentials()
            if shared:
                self.logout()
            self.log("已清空卡片凭据: %s（%d 条）" % (store.display_name, count))
            return count

    # ---- PIN 变更后的重新封装 -------------------------------------------- #
    def rewrap_after_pin_change(self, card_name, old_pin, new_pin):
        """改 PIN 之后调用：把已有凭据重新封装到新 PIN 下。"""
        store = self.store_for_card(card_name)
        if store is None:
            return False, "找不到卡片的凭据库"
        if not store.credentials:
            return True, "该卡没有 FIDO2 凭据，无需处理"
        old_master = store.master_key(old_pin)
        new_master = store.master_key(new_pin)
        try:
            count = store.rotate_master(old_master, new_master)
        except FidoStore.StoreError as err:
            return False, ("PIN 已修改，但 FIDO2 凭据重新封装失败：%s\n"
                           "（这些凭据仍用旧 PIN 封装，请保留旧 PIN 或重新注册）" % err)
        self.log("改 PIN 后重新封装 %d 条 FIDO2 凭据（%s）" % (count, card_name))
        return True, "已把 %d 条 FIDO2 凭据重新封装到新 PIN" % count

    def rewrap_after_unblock(self, card_name, new_pin):
        """PUK 解锁（旧 PIN 未知）之后调用：用 guard 取回旧 masterKey 再迁移。"""
        store = self.store_for_card(card_name)
        if store is None:
            return False, "找不到卡片的凭据库"
        if not store.credentials:
            return True, "该卡没有 FIDO2 凭据，无需处理"
        old_master = store.recover_master()
        if old_master is None:
            return False, ("拿不到旧 PIN 派生的密钥（guard 缺失或不在本机），"
                           "已有 FIDO2 凭据将无法使用，请重新注册 passkey")
        new_master = store.master_key(new_pin)
        try:
            count = store.rotate_master(old_master, new_master)
        except FidoStore.StoreError as err:
            return False, "FIDO2 凭据重新封装失败：%s" % err
        self.log("解锁后重新封装 %d 条 FIDO2 凭据（%s）" % (count, card_name))
        return True, "已把 %d 条 FIDO2 凭据重新封装到新 PIN" % count


if __name__ == "__main__":
    service = FidoService.get()
    print(json.dumps(service.status(), ensure_ascii=False, indent=2))
