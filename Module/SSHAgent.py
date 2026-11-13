# -*- coding: utf-8 -*-
"""内置 SSH 代理：用卡片上的私钥参与 SSH 登录，并把公钥登记到 ``~/.ssh``。

为什么不再外挂 SSHCardAgent.exe
--------------------------------
以前本程序把 WinCryptSSHAgent 编出的 ``SSHCardAgent.exe`` 随包分发，靠它另起一个
进程监听 Windows 命名管道 ``\\\\.\\pipe\\openssh-ssh-agent``。外挂进程带来三个麻烦：

* 托盘里多一个图标，设置里还要单独管它的开机自启；
* 退出本程序时它不会跟着退出，于是「关程序就把公钥摘掉」根本做不到；
* 它读的是 Windows 证书存储，和本程序选的证书对不上号。

这里按 WinCryptSSHAgent 的做法在**本进程内**实现同一套东西（协议、公钥编码、签名
都自己来），不再需要那个 exe：

* **证书来源**：``CertOpenStore`` 打开当前用户的「个人(My)」存储，逐个
  ``CertEnumCertificatesInStore``，用 ``CERT_KEY_PROV_INFO_PROP_ID`` 判断证书有没有
  私钥、私钥挂在哪个提供程序（只认 ``Microsoft Base Smart Card Crypto Provider`` /
  ``Microsoft Smart Card Key Storage Provider``）。这就是 WinCryptSSHAgent 的
  ``LoadUserCerts``；
* **签名**：``CryptAcquireCertificatePrivateKey`` 带
  ``CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG`` 拿到 CNG 句柄，RSA 走
  ``NCryptSignHash(BCRYPT_PAD_PKCS1)``，ECDSA 走不填 padding 的
  ``NCryptSignHash`` 再转成 SSH 的 ``mpint r/s``。私钥始终留在卡片里，PIN 由 Windows
  自己的智能卡对话框提示，我们不做 PIN 输入框，也不接触 PIN；
* **协议**：命名管道上跑 ssh-agent 的二进制协议（``REQUEST_IDENTITIES`` /
  ``SIGN_REQUEST``），**只读**——``ADD_IDENTITY`` 这类会往 agent 里塞私钥的消息一律
  回 FAILURE。

客户端怎么自动用上这把钥匙
--------------------------
管道名用的是 OpenSSH 的标准名，所以**系统自带的 OpenSSH 客户端（ssh.exe / ssh-add.exe）
在 SSH_AUTH_SOCK 为空时自动就连上了**，git（走系统 ssh 时）、VS Code Remote、JetBrains
系列、PowerShell 里的 ssh 都不用配任何环境变量。

两个坑必须处理：

* 本程序通常以管理员身份运行，Windows 会给管道打上「高完整性」标签，普通权限的
  git/ssh 连上来就是 ``Permission denied``。所以创建管道时要带一份安全描述符：DACL 只
  放本用户/管理员/系统，再把强制完整性标签显式降为 Low（:data:`PIPE_LABEL`）；
* Git for Windows 自带的 ``usr/bin/ssh.exe`` 是 MSYS 版，只认 Unix socket，连不上命名
  管道（``SSH_AUTH_SOCK`` 指向管道会直接报错甚至卡住），所以 :func:`set_git_linked`
  把 ``git config --global core.sshCommand`` 指向系统 OpenSSH，并记住原值以便还原。

公钥登记（authorized_keys）
---------------------------
登记时在行尾写一个固定前缀的注释（``tpmsmartcard:``），反注册只删带这个前缀的行，
不动用户自己的条目。**可以同时登记多张证书**：记忆列表存在 ``settings.json`` 的
``ssh_agent_certs`` 里（每项含指纹、显示名与证书 PEM），启动时逐张重新登记、退出时
一起摘掉；单张停用只删那张自己的行（按公钥 blob 认），别人的行原样保留。

注意：``authorized_keys`` 是「本机作为 SSH **服务端**」时才用的；让 git 等客户端
用上卡上的私钥靠的是上面那条代理通路 + 把**公钥上传到远端**（GitHub/GitLab 账号里、
服务器的 authorized_keys 里），这两件事互不替代。

注意：Windows 上的 OpenSSH **服务端** 对管理员账户读的是
``%ProgramData%\\ssh\\administrators_authorized_keys``，不是 ``~/.ssh/authorized_keys``；
本模块只维护后者（普通用户与本机 SSH 客户端/工具链用的就是它）。
"""

import base64
import ctypes
import hashlib
import os
import shutil
import struct
import subprocess
import threading
import time
from ctypes import wintypes

# 命名管道名：Windows OpenSSH（ssh.exe / ssh-add.exe）以及 Git for Windows、JetBrains、
# VS Code 默认都连这个，和随包 exe 用的是同一个名字，因此可以直接替换。
PIPE_NAME = r"\\.\pipe\openssh-ssh-agent"

# authorized_keys 里「这一行是本程序写的」标记（注释字段前缀）
MARKER = "tpmsmartcard:"

# settings.json 里的键（与语言/主题/代理自启同一个文件，见 Module.I18n）
SETTING_ENABLED = "ssh_agent_builtin"       # 启用内置 SSH 代理（总开关）
SETTING_REGISTER = "ssh_agent_register"     # 启动时自动登记、退出时反登记
SETTING_CERT = "ssh_agent_cert"             # 记住的证书指纹（SHA-1，大写十六进制）
SETTING_CERT_NAME = "ssh_agent_cert_name"   # 记住的证书显示名（只用于界面）
# 记住的证书本身（PEM 文本）：证书是公开数据，存下来才能保证「开机自启时」不依赖
# 读卡是否成功、证书是否还在 Windows 存储里，照样能重新登记公钥。
SETTING_CERT_PEM = "ssh_agent_cert_pem"
# 已「启用 SSH」的证书列表：[{"thumb", "name", "pem"}]。可以同时登记多张，
# 上面三个单值键保留为列表第一项（兼容旧设置与旧版本）。
SETTING_CERT_LIST = "ssh_agent_certs"
SETTING_GIT_SSH = "ssh_agent_git_ssh"       # 已把 Git 切到哪个 ssh（空 = 没切）
SETTING_GIT_PREV = "ssh_agent_git_prev"     # 切换前的 core.sshCommand 原值（关掉时还原）

# 签名后清掉进程内的 PIN 缓存（与 WinCryptSSHAgent 的默认行为一致）：
# 每次签名都要重新输入 PIN，代价是每次认证弹一次对话框，收益是 PIN 不被长期缓存。
CLEAR_PIN_CACHE = True

# 单条 agent 消息的最大长度：SSH 握手阶段的公钥/签名数据都在几十 KB 量级，
# 256KB 足够，同时避免异常客户端把内存吃光。
MESSAGE_MAX = 256 * 1024
# 命名管道的收发缓冲区（每个连接各 64KB，别按 MESSAGE_MAX 开，那是内核池内存）
PIPE_BUFFER = 64 * 1024

# 管道的安全描述符（%s 是当前用户 SID）：只有本用户/管理员/系统能连，别人签不了名。
PIPE_SDDL = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;OW)(A;;GA;;;%s)"
# 强制完整性标签「低」。本程序建卡要提权，管道默认会是高完整性对象，普通权限的
# ssh/git 连上来直接 Permission denied——必须显式把标签降到 Low 才放行。
PIPE_LABEL = "S:(ML;;NW;;;LW)"

# Win32 ======================================================================
CERT_STORE_PROV_SYSTEM_W = 10
CERT_SYSTEM_STORE_CURRENT_USER = 0x00010000
CERT_STORE_READONLY_FLAG = 0x00008000
CERT_KEY_PROV_INFO_PROP_ID = 2
CERT_NCRYPT_KEY_SPEC = 0xFFFFFFFF
CRYPT_ACQUIRE_CACHE_FLAG = 0x00000001
CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG = 0x00040000
BCRYPT_PAD_PKCS1 = 0x00000002

# 智能卡私钥的提供程序：微软的 Base Smart Card CSP 与 Smart Card KSP（前者是后者的
# CSP 外壳，两个都要认）；另外带 "smart card" 字样的第三方 KSP（SafeNet、Yubico PIV
# 等）也一并纳入，否则这些卡上的证书会在这个代理里「消失」。
SMARTCARD_PROVIDERS = ("microsoft base smart card crypto provider",
                       "microsoft smart card key storage provider")
SMARTCARD_HINTS = ("smart card", "smartcard", "smart-card", "card key storage")


def is_card_provider(in_name):
    """私钥提供程序是不是智能卡（TPM 虚拟卡走的是上面两种微软提供程序）。"""
    name = str(in_name or "").strip().lower()
    if not name:
        return False
    if name in SMARTCARD_PROVIDERS:
        return True
    return any(hint in name for hint in SMARTCARD_HINTS)


# ssh-agent 协议的消息号（draft-miller-ssh-agent）
SSH_AGENT_FAILURE = 5
SSH_AGENT_SUCCESS = 6
SSH_AGENTC_REQUEST_IDENTITIES = 11
SSH_AGENT_IDENTITIES_ANSWER = 12
SSH_AGENTC_SIGN_REQUEST = 13
SSH_AGENT_SIGN_RESPONSE = 14

# SSH_AGENTC_SIGN_REQUEST 的 flags
RSA_SHA2_256 = 2
RSA_SHA2_512 = 4

# 曲线 -> (SSH 算法名, 坐标字节数, 摘要)
EC_CURVES = {
    "secp256r1": ("ecdsa-sha2-nistp256", 32, "sha256"),
    "secp384r1": ("ecdsa-sha2-nistp384", 48, "sha384"),
    "secp521r1": ("ecdsa-sha2-nistp521", 66, "sha512"),
}


class SshError(Exception):
    """本模块统一抛出的错误（文案可直接展示给用户）。"""


# SSH 线格式 =================================================================
def ssh_u32(in_value):
    return struct.pack(">I", int(in_value))


def ssh_string(in_data):
    """SSH 的 string：4 字节长度 + 内容。"""
    if isinstance(in_data, str):
        in_data = in_data.encode("utf-8")
    return ssh_u32(len(in_data)) + bytes(in_data)


def ssh_mpint(in_value):
    """SSH 的 mpint：大端补码正整数（最高位为 1 时要补一个 0x00 前导字节）。"""
    in_value = int(in_value)
    if in_value == 0:
        return ssh_string(b"")
    body = in_value.to_bytes((in_value.bit_length() + 7) // 8, "big")
    if body[0] & 0x80:
        body = b"\x00" + body
    return ssh_string(body)


def read_string(in_data, in_offset=0):
    """从 buffer 里读一个 SSH string，返回 ``(内容, 下一个偏移)``。"""
    if in_offset + 4 > len(in_data):
        raise SshError("报文长度不足")
    size = struct.unpack(">I", in_data[in_offset:in_offset + 4])[0]
    start = in_offset + 4
    end = start + size
    if end > len(in_data):
        raise SshError("报文长度越界")
    return in_data[start:end], end


# 设置读写 ===================================================================
def read_settings():
    from Module.I18n import read_user_settings
    return read_user_settings()


def save_settings(in_patch):
    from Module.I18n import read_user_settings, write_user_settings
    settings = read_user_settings()
    settings.update(in_patch)
    return write_user_settings(settings)


def builtin_enabled():
    """内置 SSH 代理总开关（默认关：不主动抢 OpenSSH 的管道）。"""
    return bool(read_settings().get(SETTING_ENABLED))


def set_builtin_enabled(in_value):
    return save_settings({SETTING_ENABLED: bool(in_value)})


def register_enabled():
    """是否「启动时自动登记、退出时反登记」。"""
    return bool(read_settings().get(SETTING_REGISTER))


def set_register_enabled(in_value):
    return save_settings({SETTING_REGISTER: bool(in_value)})


def remembered_certs():
    """已「启用 SSH」的证书列表：``[{"thumb", "name", "pem"}]``，可以有多张。"""
    settings = read_settings()
    items = settings.get(SETTING_CERT_LIST)
    result = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            thumb = str(item.get("thumb") or "").upper()
            if not thumb or any(x["thumb"] == thumb for x in result):
                continue
            result.append({"thumb": thumb,
                           "name": str(item.get("name") or ""),
                           "pem": str(item.get("pem") or "")})
    if result:
        return result
    # 旧版只记了一张：把它当成只有一项的列表（下次保存时自动迁移成列表）
    old = {"thumb": str(settings.get(SETTING_CERT) or "").upper(),
           "name": str(settings.get(SETTING_CERT_NAME) or ""),
           "pem": str(settings.get(SETTING_CERT_PEM) or "")}
    return [old] if old["thumb"] else []


def save_remembered(in_items):
    """整体保存记忆列表；单值键同步成第一项，旧逻辑读到的仍是有效证书。"""
    items = []
    for item in in_items or []:
        thumb = str(item.get("thumb") or "").upper()
        if not thumb or any(x["thumb"] == thumb for x in items):
            continue
        items.append({"thumb": thumb,
                      "name": str(item.get("name") or ""),
                      "pem": str(item.get("pem") or "")})
    first = items[0] if items else {"thumb": "", "name": "", "pem": ""}
    return save_settings({SETTING_CERT_LIST: items,
                          SETTING_CERT: first["thumb"],
                          SETTING_CERT_NAME: first["name"],
                          SETTING_CERT_PEM: first["pem"]})


def add_remembered(in_cert, in_name=""):
    """把一张证书加进记忆列表（已经存在的先摘掉再加，保持顺序靠后）。"""
    thumb = cert_thumbprint(in_cert)
    items = [item for item in remembered_certs() if item["thumb"] != thumb]
    items.append({"thumb": thumb, "name": str(in_name or ""), "pem": cert_pem(in_cert)})
    save_remembered(items)
    return items


def remove_remembered(in_thumbs):
    """从记忆列表里去掉若干指纹（不碰 authorized_keys）。"""
    drop = {str(item).upper() for item in in_thumbs or []}
    return save_remembered([item for item in remembered_certs()
                            if item["thumb"] not in drop])


def selected_cert():
    """兼容旧接口：记忆列表里的第一张（没登记过时 thumb/name 都是空串）。"""
    items = remembered_certs()
    if not items:
        return {"thumb": "", "name": ""}
    return {"thumb": items[0]["thumb"], "name": items[0]["name"]}


def set_selected_cert(in_thumb, in_name="", in_pem=""):
    """兼容旧接口：等价于「只记这一张」。"""
    return save_remembered([{"thumb": in_thumb, "name": in_name, "pem": in_pem}])


def selected_cert_pem():
    """兼容旧接口：记忆列表里第一张的 PEM（没有就是空串）。"""
    items = remembered_certs()
    return items[0]["pem"] if items else ""


# 客户端接入：让 ssh / git 等程序自动用上卡上的密钥 ==========================
#
# Windows 自带的 OpenSSH 客户端在 SSH_AUTH_SOCK 未设置时会**自动**连
# \\.\pipe\openssh-ssh-agent ——也就是本代理，不需要任何环境变量。
# 麻烦的是 Git for Windows 自带的 ssh（MSYS 版）：它只认 Unix socket，
# 连不上命名管道（实测 SSH_AUTH_SOCK 指向管道会直接报错/卡住），
# 所以要么把 Git 切到系统 OpenSSH，要么就一直用不了代理。
def system_ssh():
    """系统自带 OpenSSH 客户端 ssh.exe 的路径（没有就返回空串）。"""
    path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                        "System32", "OpenSSH", "ssh.exe")
    return path if os.path.isfile(path) else ""


def _client_env(in_pipe=""):
    """子进程的环境：``in_pipe`` 非空时显式指定管道（自检/测试用）。

    平时**不设** SSH_AUTH_SOCK —— 指向命名管道会让 MSYS 版 ssh 直接卡住，
    而系统 OpenSSH 在变量为空时本来就连默认管道。
    """
    env = dict(os.environ)
    env.pop("SSH_AUTH_SOCK", None)
    if in_pipe:
        env["SSH_AUTH_SOCK"] = in_pipe
    return env


def _run_quiet(in_cmd, in_timeout=10, in_pipe=""):
    """跑一个控制台程序并取回输出（不弹黑框）。"""
    try:
        result = subprocess.run(in_cmd, capture_output=True, text=True,
                                timeout=in_timeout, creationflags=0x08000000,
                                env=_client_env(in_pipe))
        return (result.stdout + result.stderr).strip()
    except Exception as err:
        return "执行失败：%s" % err


def _git_exe():
    return shutil.which("git") or ""


def _git(*in_args):
    """执行 git 命令，返回 ``(返回码, stdout)``。"""
    git = _git_exe()
    if not git:
        return 127, "找不到 git"
    try:
        result = subprocess.run([git] + list(in_args), capture_output=True, text=True,
                                timeout=10, creationflags=0x08000000)
        return result.returncode, (result.stdout + result.stderr).strip()
    except Exception as err:
        return 1, str(err)


def git_ssh_now():
    """``(git 会用的 ssh, 来源)``：core.sshCommand > GIT_SSH_COMMAND/GIT_SSH > PATH。"""
    code, out = _git("config", "--global", "--get", "core.sshCommand")
    if code == 0 and out:
        return out.strip('"'), "core.sshCommand"
    for name in ("GIT_SSH_COMMAND", "GIT_SSH"):
        value = os.environ.get(name)
        if value:
            return value.strip('"'), name
    return shutil.which("ssh") or "", "PATH"


def git_linked():
    """Git 现在用的 ssh 是不是系统 OpenSSH（= 能不能用上本代理）。"""
    ssh = system_ssh()
    if not ssh:
        return False
    return os.path.normcase(git_ssh_now()[0]) == os.path.normcase(ssh)


def git_ours():
    """``core.sshCommand`` 是不是本程序改的（关开关时才知道要不要还原）。"""
    return os.path.normcase(str(read_settings().get(SETTING_GIT_SSH) or "")) == \
        os.path.normcase(system_ssh()) and bool(system_ssh())


def set_git_linked(in_enable):
    """把 Git 切到系统 OpenSSH / 还原成原来的设置。

    改的是 ``git config --global core.sshCommand``：只影响当前用户，且原值会记进
    设置里，关掉开关时原样还回去。
    """
    ssh = system_ssh()
    if in_enable:
        if not ssh:
            return False, "找不到系统自带的 OpenSSH：%s" % ssh
        code, out = _git("config", "--global", "--get", "core.sshCommand")
        prev = out.strip() if code == 0 else ""
        if prev and os.path.normcase(prev.strip('"')) != os.path.normcase(ssh):
            save_settings({SETTING_GIT_PREV: prev})
        code, out = _git("config", "--global", "core.sshCommand",
                         '"%s"' % ssh.replace("\\", "/"))
        if code != 0:
            return False, out or "git config 执行失败"
        save_settings({SETTING_GIT_SSH: ssh})
        return True, "Git 已切换到系统 OpenSSH（%s）" % ssh
    prev = str(read_settings().get(SETTING_GIT_PREV) or "")
    if prev:
        _git("config", "--global", "core.sshCommand", prev)
    else:
        _git("config", "--global", "--unset", "core.sshCommand")
    save_settings({SETTING_GIT_SSH: "", SETTING_GIT_PREV: ""})
    return True, "已还原 Git 原来的 ssh 设置"


def ssh_add_list(in_ssh_path="", in_pipe=""):
    """用「某个 ssh 客户端同目录下的 ssh-add」列出代理里的密钥。

    返回 ``(能否连上代理, 输出文本)``：连上但没密钥也算能连上
    （ssh-add 这时返回码是 1，输出 "The agent has no identities."）。
    """
    folder = os.path.dirname(in_ssh_path) if in_ssh_path else ""
    candidate = os.path.join(folder, "ssh-add.exe") if folder else ""
    if not candidate or not os.path.isfile(candidate):
        candidate = os.path.join(os.path.dirname(system_ssh()), "ssh-add.exe")
    if not os.path.isfile(candidate):
        return False, "找不到 ssh-add.exe"
    text = _run_quiet([candidate, "-l"], 8, in_pipe)
    broken = ("connect" in text.lower() or "failed" in text.lower()
              or "拒绝" in text or "失败" in text or "无法" in text)
    return (not broken), text


# 公钥编码 ===================================================================
def _load_cert(in_cert):
    """把 PEM / DER 统一成 ``cryptography`` 的证书对象（只在用到时才导入）。

    PEM 也可能是 ``bytes``（OpenSC 的输出被 decode 过就是 str，但证书存储里拿到的是
    DER），所以先看内容里有没有 PEM 头，再看类型。
    """
    from cryptography import x509
    if isinstance(in_cert, (bytes, bytearray)):
        raw = bytes(in_cert)
        if b"BEGIN CERTIFICATE" in raw:
            return x509.load_pem_x509_certificate(raw)
        return x509.load_der_x509_certificate(raw)
    text = str(in_cert or "")
    if "BEGIN CERTIFICATE" in text:
        return x509.load_pem_x509_certificate(text.encode("utf-8"))
    raise SshError("证书内容无法识别")


def cert_der(in_cert):
    """取证书的 DER 编码（PEM 会先转换）。"""
    from cryptography.hazmat.primitives.serialization import Encoding
    return _load_cert(in_cert).public_bytes(Encoding.DER)


def cert_pem(in_cert):
    """证书的 PEM 文本（DER 也会转成 PEM；记进设置时用这个形式，便于肉眼核对）。"""
    from cryptography.hazmat.primitives.serialization import Encoding
    return _load_cert(in_cert).public_bytes(Encoding.PEM).decode("ascii")


def cert_thumbprint(in_cert):
    """证书指纹：SHA-1 大写十六进制，与 Windows 证书管理器里显示的一致。"""
    return hashlib.sha1(cert_der(in_cert)).hexdigest().upper()


def cert_common_name(in_cert):
    from cryptography.x509.oid import NameOID
    try:
        names = _load_cert(in_cert).subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    except Exception:
        return ""
    return str(names[0].value) if names else ""


def key_info(in_cert):
    """把证书公钥转成 SSH 需要的信息。

    返回 ``{"type", "kind", "blob", "half", "size", "hash"}``：

    * ``type``：SSH 算法名（``ssh-rsa`` / ``ecdsa-sha2-nistp256`` …）；
    * ``kind``：``rsa`` 或 ``ecdsa``，决定签名时怎么调 CNG；
    * ``blob``：agent 协议里的公钥 blob（也就是 ``ssh-add -L`` 打印的那一段）；
    * ``half``：ECDSA 单个坐标的字节数，``size``：RSA 模数的字节数。
    """
    from cryptography.hazmat.primitives.asymmetric import ec, rsa

    pub = _load_cert(in_cert).public_key()
    if isinstance(pub, rsa.RSAPublicKey):
        numbers = pub.public_numbers()
        blob = ssh_string("ssh-rsa") + ssh_mpint(numbers.e) + ssh_mpint(numbers.n)
        size = (numbers.n.bit_length() + 7) // 8
        return {"type": "ssh-rsa", "kind": "rsa", "blob": blob,
                "size": size, "half": 0, "hash": "sha1"}
    if isinstance(pub, ec.EllipticCurvePublicKey):
        curve = EC_CURVES.get(str(pub.curve.name))
        if curve is None:
            raise SshError("不支持的椭圆曲线：%s" % pub.curve.name)
        alg_name, half, _digest = curve
        numbers = pub.public_numbers()
        point = (b"\x04"
                 + numbers.x.to_bytes(half, "big")
                 + numbers.y.to_bytes(half, "big"))
        blob = (ssh_string(alg_name) + ssh_string(alg_name.split("-")[-1])
                + ssh_string(point))
        return {"type": alg_name, "kind": "ecdsa", "blob": blob,
                "size": half * 2, "half": half, "hash": curve[2]}
    raise SshError("不支持的密钥类型：%s" % type(pub).__name__)


def public_key_line(in_cert, in_comment):
    """authorized_keys 里的一行：``<算法> <base64 公钥> <注释>``。"""
    info = key_info(in_cert)
    text = base64.b64encode(info["blob"]).decode("ascii")
    comment = str(in_comment or "").replace("\r", " ").replace("\n", " ").strip()
    return ("%s %s %s" % (info["type"], text, comment)).strip()


# Windows 加密 API ===========================================================
class _CERT_CONTEXT(ctypes.Structure):
    _fields_ = [("dwCertEncodingType", wintypes.DWORD),
                ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
                ("cbCertEncoded", wintypes.DWORD),
                ("pCertInfo", ctypes.c_void_p),
                ("hCertStore", ctypes.c_void_p)]


class _CRYPT_KEY_PROV_INFO(ctypes.Structure):
    _fields_ = [("pwszContainerName", wintypes.LPWSTR),
                ("pwszProvName", wintypes.LPWSTR),
                ("dwProvType", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("cProvParam", wintypes.DWORD),
                ("rgProvParam", ctypes.c_void_p)]


class _PKCS1_PADDING_INFO(ctypes.Structure):
    _fields_ = [("pszAlgId", wintypes.LPCWSTR)]


_API = {}
_API_ERROR = ""


def _api():
    """懒加载 crypt32 / ncrypt 并绑定函数原型（只做一次）。"""
    global _API_ERROR
    if _API:
        return _API
    if _API_ERROR:
        raise SshError(_API_ERROR)
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        ncrypt = ctypes.WinDLL("ncrypt", use_last_error=True)

        crypt32.CertOpenStore.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.c_size_t, wintypes.DWORD,
                                         ctypes.c_wchar_p]
        crypt32.CertOpenStore.restype = ctypes.c_void_p
        crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        crypt32.CertEnumCertificatesInStore.restype = ctypes.c_void_p
        crypt32.CertFreeCertificateContext.argtypes = [ctypes.c_void_p]
        crypt32.CertFreeCertificateContext.restype = wintypes.BOOL
        crypt32.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        crypt32.CertCloseStore.restype = wintypes.BOOL
        crypt32.CertGetCertificateContextProperty.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD)]
        crypt32.CertGetCertificateContextProperty.restype = wintypes.BOOL
        crypt32.CryptAcquireCertificatePrivateKey.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.BOOL)]
        crypt32.CryptAcquireCertificatePrivateKey.restype = wintypes.BOOL

        ncrypt.NCryptSignHash.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD),
                                          wintypes.DWORD]
        ncrypt.NCryptSignHash.restype = ctypes.c_long
        ncrypt.NCryptFreeObject.argtypes = [ctypes.c_void_p]
        ncrypt.NCryptFreeObject.restype = ctypes.c_long
        ncrypt.NCryptSetProperty.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                             ctypes.c_void_p, wintypes.DWORD,
                                             wintypes.DWORD]
        ncrypt.NCryptSetProperty.restype = ctypes.c_long
    except Exception as err:
        _API_ERROR = "Windows 加密接口不可用：%s" % err
        raise SshError(_API_ERROR)
    _API.update({"crypt32": crypt32, "ncrypt": ncrypt})
    return _API


def error_text(in_code):
    """把 NCrypt / CryptoAPI 的返回码翻成一句人话（认不出来的给十六进制）。"""
    code = int(in_code) & 0xFFFFFFFF
    known = {
        0x8010006B: "用户取消了 PIN 输入",
        0x8010006C: "PIN 输入被取消",
        0x80100069: "智能卡已移除",
        0x8010006A: "PIN 已被锁定",
        0x8010000C: "没有可用的智能卡读卡器",
        0x80090010: "密钥对象已存在",
        0x8009000B: "密钥状态无效（PIN 未验证或已锁定）",
        0x80090027: "密钥句柄无效",
    }
    if code in known:
        return known[code]
    if code == 0x80092004:
        return "没有找到对象"
    return "错误码 0x%08X" % code


def _key_prov_info(in_cert_ptr):
    """取证书的 ``CRYPT_KEY_PROV_INFO``：没有私钥时返回 None。"""
    crypt32 = _api()["crypt32"]
    size = wintypes.DWORD(0)
    if not crypt32.CertGetCertificateContextProperty(
            in_cert_ptr, CERT_KEY_PROV_INFO_PROP_ID, None, ctypes.byref(size)):
        return None
    if size.value <= 0:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if not crypt32.CertGetCertificateContextProperty(
            in_cert_ptr, CERT_KEY_PROV_INFO_PROP_ID, buffer, ctypes.byref(size)):
        return None
    info = ctypes.cast(buffer, ctypes.POINTER(_CRYPT_KEY_PROV_INFO)).contents
    return {"provider": str(info.pwszProvName or ""),
            "container": str(info.pwszContainerName or "")}


def _with_store(in_worker):
    """打开当前用户「个人」存储执行 ``in_worker(store)``，结束后关掉存储。

    枚举出来的证书上下文由 ``CertEnumCertificatesInStore`` 自己接管（下一次迭代会
    释放上一个），循环结束后要把最后一个还回去。
    """
    crypt32 = _api()["crypt32"]
    store = crypt32.CertOpenStore(
        ctypes.c_void_p(CERT_STORE_PROV_SYSTEM_W), 0, 0,
        CERT_SYSTEM_STORE_CURRENT_USER | CERT_STORE_READONLY_FLAG,
        ctypes.c_wchar_p("MY"))
    if not store:
        raise SshError("打不开证书存储：%s" % error_text(ctypes.get_last_error()))
    try:
        return in_worker(crypt32, store)
    finally:
        crypt32.CertCloseStore(store, 0)


def store_certificates(in_smartcard_only=True):
    """枚举「个人(My)」存储里的证书。

    返回 ``[{"der", "thumb", "name", "provider"}]``；``in_smartcard_only`` 为真时
    只返回私钥挂在智能卡提供程序上的证书（软件密钥不通过本代理暴露）。
    """
    def worker(crypt32, store):
        result = []
        cert_ptr = None
        try:
            while True:
                ctypes.set_last_error(0)
                cert_ptr = crypt32.CertEnumCertificatesInStore(store, cert_ptr)
                if not cert_ptr:
                    break
                ctx = ctypes.cast(cert_ptr, ctypes.POINTER(_CERT_CONTEXT)).contents
                der = ctypes.string_at(ctx.pbCertEncoded, ctx.cbCertEncoded)
                prov = _key_prov_info(cert_ptr)
                if prov is None:
                    continue
                provider = prov["provider"]
                if in_smartcard_only and not is_card_provider(provider):
                    continue
                try:
                    name = cert_common_name(der)
                except Exception:
                    continue
                result.append({"der": der,
                               "thumb": hashlib.sha1(der).hexdigest().upper(),
                               "name": name,
                               "provider": provider})
        finally:
            if cert_ptr:
                crypt32.CertFreeCertificateContext(cert_ptr)
        return result

    return _with_store(worker)


def find_store_cert(in_thumb):
    """按指纹在证书存储里找一张证书（返回 ``store_certificates`` 的元素）。"""
    thumb = str(in_thumb or "").upper()
    if not thumb:
        return None
    for item in store_certificates():
        if item["thumb"] == thumb:
            return item
    return None


_SIGN_LOCK = threading.Lock()


def _acquire_key(in_cert_ptr):
    """取证书私钥的 CNG 句柄；返回 ``(句柄, 是否需要调用方释放)``。"""
    crypt32 = _api()["crypt32"]
    handle = ctypes.c_void_p()
    spec = wintypes.DWORD()
    free_it = wintypes.BOOL()
    ok = crypt32.CryptAcquireCertificatePrivateKey(
        in_cert_ptr,
        CRYPT_ACQUIRE_CACHE_FLAG | CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG,
        None, ctypes.byref(handle), ctypes.byref(spec), ctypes.byref(free_it))
    if not ok:
        raise SshError("取不到证书私钥：%s" % error_text(ctypes.get_last_error()))
    if spec.value != CERT_NCRYPT_KEY_SPEC:
        # 老式 CSP 句柄要用 CryptReleaseContext 释放，本代理不走那条路：
        # 只把失败原因说清楚（智能卡与 TPM 虚拟卡都是 CNG，正常不会走到这里）
        raise SshError("该私钥不是 CNG 密钥（老式 CSP），本代理无法使用")
    return handle, bool(free_it.value)


def _release_key(in_handle, in_free_it):
    if not in_handle or not in_handle.value:
        return None
    try:
        if in_free_it:
            _api()["ncrypt"].NCryptFreeObject(in_handle)
    except Exception as err:
        print("SSH: 释放密钥句柄失败:", err)
    return None


def _clear_pin(in_handle):
    """清掉 KSP 进程内的 PIN 缓存，让下次签名重新提示 PIN（尽力而为）。"""
    try:
        ncrypt = _api()["ncrypt"]
        empty = ctypes.create_unicode_buffer("")
        ncrypt.NCryptSetProperty(in_handle, "SmartCardPin",
                                 ctypes.cast(empty, ctypes.c_void_p),
                                 ctypes.sizeof(empty), 0)
    except Exception as err:
        print("SSH: 清 PIN 缓存失败:", err)
    return None


def sign_hash(in_handle, in_info, in_digest, in_alg_id=""):
    """用 CNG 句柄对摘要签名，返回裸签名字节。

    * RSA：``BCRYPT_PAD_PKCS1`` + ``pszAlgId``（SHA1/SHA256/SHA512），输出即 PKCS#1 v1.5；
    * ECDSA：不给 padding，输出是定长的 ``r || s`` 拼接。
    """
    ncrypt = _api()["ncrypt"]
    if in_info["kind"] == "rsa":
        padding = _PKCS1_PADDING_INFO(ctypes.c_wchar_p(in_alg_id or "SHA256"))
        pad_ptr = ctypes.cast(ctypes.byref(padding), ctypes.c_void_p)
        flags = BCRYPT_PAD_PKCS1
        size = in_info["size"]
    else:
        pad_ptr = None
        flags = 0
        size = in_info["half"] * 2
    digest_buf = ctypes.create_string_buffer(bytes(in_digest), len(in_digest))
    sig_buf = ctypes.create_string_buffer(size)
    done = wintypes.DWORD(0)
    code = ncrypt.NCryptSignHash(in_handle, pad_ptr,
                                 ctypes.cast(digest_buf, ctypes.c_void_p),
                                 len(in_digest),
                                 ctypes.cast(sig_buf, ctypes.c_void_p),
                                 size, ctypes.byref(done), flags)
    if code != 0:
        raise SshError("签名失败：%s" % error_text(code))
    return sig_buf.raw[:done.value]


def build_signature(in_info, in_raw, in_alg_name):
    """把裸签名包成 SSH 的签名 blob：``string 算法`` + ``string 签名值``。"""
    if in_info["kind"] == "rsa":
        return ssh_string(in_alg_name) + ssh_string(in_raw)
    half = in_info["half"]
    if len(in_raw) != half * 2:
        raise SshError("ECDSA 签名长度异常：%d" % len(in_raw))
    r_value = int.from_bytes(in_raw[:half], "big")
    s_value = int.from_bytes(in_raw[half:], "big")
    return ssh_string(in_alg_name) + ssh_string(ssh_mpint(r_value) + ssh_mpint(s_value))


def sign_with_cert(in_cert_ptr, in_info, in_data, in_flags):
    """对 ``in_data`` 签名，返回 ``(算法名, SSH 签名 blob)``。

    ``in_flags`` 来自 SIGN_REQUEST：OpenSSH 用 ``RSA_SHA2_256/512`` 这两位告诉 agent
    该用哪一档 RSA 签名（不带 flag 就是老的 ``ssh-rsa``/SHA-1）；ECDSA 的算法由曲线
    唯一决定，忽略这两个 flag。
    """
    if in_info["kind"] == "rsa":
        if in_flags & RSA_SHA2_512:
            alg_name, hash_name, alg_id = "rsa-sha2-512", "sha512", "SHA512"
        elif in_flags & RSA_SHA2_256:
            alg_name, hash_name, alg_id = "rsa-sha2-256", "sha256", "SHA256"
        else:
            alg_name, hash_name, alg_id = "ssh-rsa", "sha1", "SHA1"
    else:
        alg_name = in_info["type"]
        hash_name = in_info["hash"]
        alg_id = ""
    digest = hashlib.new(hash_name, bytes(in_data)).digest()
    handle, free_it = _acquire_key(in_cert_ptr)
    try:
        raw = sign_hash(handle, in_info, digest, alg_id)
        if CLEAR_PIN_CACHE:
            _clear_pin(handle)
    finally:
        _release_key(handle, free_it)
    return alg_name, build_signature(in_info, raw, alg_name)


def sign_request(in_key_blob, in_data, in_flags, in_smartcard_only=True):
    """按公钥 blob 找到证书并签名（找不到就抛 :class:`SshError`）。

    ``in_smartcard_only=False`` 只给自测/诊断用：把软件密钥也纳入匹配范围，
    便于在没有智能卡的环境里验证签名链路。
    """
    wanted = bytes(in_key_blob)
    with _SIGN_LOCK:                       # 卡片同一时刻只处理一个 PIN/签名会话
        for item in store_certificates(in_smartcard_only=in_smartcard_only):
            try:
                info = key_info(item["der"])
            except Exception:
                continue
            if info["blob"] != wanted:
                continue
            return _sign_with_ctx(item["der"], info, in_data, in_flags)
    raise SshError("代理里没有匹配的私钥（证书可能不在 Windows 个人证书存储里）")


def _sign_with_ctx(in_der, in_info, in_data, in_flags):
    """在「个人」存储里定位到这张证书的上下文再签名。

    证书上下文在枚举结束、存储关闭后就失效，所以这里必须重新打开存储并在其生命周期
    内完成签名（与 WinCryptSSHAgent 每次 ``List()`` 重新枚举是同一个道理）。
    """
    thumb = hashlib.sha1(in_der).hexdigest().upper()

    def worker(crypt32, store):
        cert_ptr = None
        try:
            index = 0
            while True:
                cert_ptr = crypt32.CertEnumCertificatesInStore(store, cert_ptr)
                if not cert_ptr:
                    break
                index += 1
                ctx = ctypes.cast(cert_ptr, ctypes.POINTER(_CERT_CONTEXT)).contents
                der = ctypes.string_at(ctx.pbCertEncoded, ctx.cbCertEncoded)
                if hashlib.sha1(der).hexdigest().upper() != thumb:
                    continue
                # 注意：这里不能 break 再签名——枚举器会在下一次迭代释放上下文，
                # 所以当前上下文正好有效，直接用它签完再结束整个枚举。
                return sign_with_cert(cert_ptr, in_info, in_data, in_flags)
        finally:
            if cert_ptr:
                crypt32.CertFreeCertificateContext(cert_ptr)
        raise SshError("证书已不在个人证书存储中（扫描了 %d 张）" % index)

    return _with_store(worker)


# agent 协议 =================================================================
def identities():
    """``REQUEST_IDENTITIES`` 的应答内容：``[(公钥 blob, 注释)]``。"""
    result = []
    for item in store_certificates():
        try:
            info = key_info(item["der"])
        except Exception:
            continue
        comment = item["name"] or "TPMSmartCard"
        result.append((info["blob"], "%s %s" % (comment, item["thumb"][:8])))
    return result


def handle_message(in_payload):
    """处理一条 agent 请求，返回应答报文（不含长度前缀）。"""
    if not in_payload:
        return bytes([SSH_AGENT_FAILURE])
    msg_type = in_payload[0]
    if msg_type == SSH_AGENTC_REQUEST_IDENTITIES:
        keys = identities()
        body = ssh_u32(len(keys))
        for blob, comment in keys:
            body += ssh_string(blob) + ssh_string(comment)
        return bytes([SSH_AGENT_IDENTITIES_ANSWER]) + body
    if msg_type == SSH_AGENTC_SIGN_REQUEST:
        try:
            key_blob, offset = read_string(in_payload, 1)
            data, offset = read_string(in_payload, offset)
            flags = struct.unpack(">I", in_payload[offset:offset + 4])[0] \
                if offset + 4 <= len(in_payload) else 0
        except SshError as err:
            print("SSH: 签名请求解析失败:", err)
            return bytes([SSH_AGENT_FAILURE])
        try:
            _alg, signature = sign_request(key_blob, data, flags)
        except SshError as err:
            print("SSH: 签名失败:", err)
            return bytes([SSH_AGENT_FAILURE])
        except Exception as err:
            print("SSH: 签名异常:", err)
            return bytes([SSH_AGENT_FAILURE])
        return bytes([SSH_AGENT_SIGN_RESPONSE]) + ssh_string(signature)
    # 其余消息（ADD_IDENTITY / REMOVE_IDENTITY / LOCK / EXTENSION …）一律不支持：
    # 本代理只读，私钥永远不出卡片。
    return bytes([SSH_AGENT_FAILURE])


def current_user_sid():
    """当前进程用户的 SID 字符串（用于管道安全描述符）。"""
    try:
        import win32api
        import win32con
        import win32security
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(),
                                               win32con.TOKEN_QUERY)
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return win32security.ConvertSidToStringSid(sid)
    except Exception as err:
        print("SSH: 取当前用户 SID 失败:", err)
        return ""


def pipe_attrs():
    """返回 ``[(SECURITY_ATTRIBUTES 或 None, 说明)]``，从最严格逐级降级。

    首选「仅本用户 + 低完整性标签」；没有 SE_SECURITY_NAME 之类的权限时退回
    「仅本用户」；再不行才交给系统默认描述符（此时若程序是管理员身份，普通权限的
    客户端会被拒绝，所以这种情况要记日志）。
    """
    candidates = []
    sid = current_user_sid()
    if sid:
        for label, tag in ((PIPE_LABEL, "本用户 + 低完整性"),
                           ("", "本用户")):
            try:
                import win32security
                desc = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                    (PIPE_SDDL % sid) + label, 1)
                attrs = win32security.SECURITY_ATTRIBUTES()
                attrs.SECURITY_DESCRIPTOR = desc
                attrs.bInheritHandle = False
                candidates.append((attrs, tag))
            except Exception as err:
                print("SSH: 生成管道安全描述符失败:", err)
    candidates.append((None, "系统默认"))
    return candidates


class AgentServer:
    """命名管道上的 ssh-agent 服务端（每个连接一个线程，按请求串行签名）。"""

    def __init__(self):
        self.error = ""
        self.security_desc = ""
        self._stop = threading.Event()
        self._thread = None
        self._ready = threading.Event()
        self._handles = set()
        self._lock = threading.Lock()

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        """启动监听，返回 ``(是否成功, 说明)``。"""
        if self.running:
            return True, "内置 SSH 代理已在运行"
        self.error = ""
        self.security_desc = ""
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._listen, name="ssh-agent-pipe",
                                        daemon=True)
        self._thread.start()
        # 等监听线程把第一个实例建好（建不起来就把原因带回去，例如管道被系统服务占着）
        self._ready.wait(3)
        if self.error:
            return False, self.error
        return True, "内置 SSH 代理已启动（%s）" % PIPE_NAME

    def stop(self):
        """停止监听并断开所有客户端连接。"""
        self._stop.set()
        # 监听线程可能阻塞在 ConnectNamedPipe 上：自己连一次就能把它叫醒
        try:
            import win32file
            for _attempt in range(4):
                try:
                    handle = win32file.CreateFile(
                        PIPE_NAME, win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                        0, None, win32file.OPEN_EXISTING, 0, None)
                    win32file.CloseHandle(handle)
                    break
                except Exception:
                    time.sleep(0.05)
        except Exception as err:
            print("SSH: 唤醒监听线程失败:", err)
        with self._lock:
            handles = list(self._handles)
        try:
            import win32file
            for handle in handles:
                try:
                    win32file.CloseHandle(handle)
                except Exception:
                    pass
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(2)
        self._thread = None
        return None

    # -- 内部实现 ---------------------------------------------------------- #
    def _listen(self):
        try:
            import pywintypes
            import win32file
            import win32pipe
        except Exception as err:
            self.error = "缺少 pywin32，无法启动内置 SSH 代理：%s" % err
            self._ready.set()
            return None

        attrs_list = pipe_attrs()
        state = {"index": 0}          # 当前用第几档安全属性（降级后不再回头）

        def new_instance(need_first):
            """建一个管道实例；失败时返回 None（原因写进 self.error）。"""
            flags = win32pipe.PIPE_ACCESS_DUPLEX
            if need_first:
                # 第一个实例带 FIRST_PIPE_INSTANCE：如果系统自带的 ssh-agent 服务
                # （或别的代理）已经占着这个管道，我们会直接失败，而不是和它抢连接
                flags |= win32pipe.FILE_FLAG_FIRST_PIPE_INSTANCE
            while state["index"] < len(attrs_list):
                attrs, tag = attrs_list[state["index"]]
                try:
                    handle = win32pipe.CreateNamedPipe(
                        PIPE_NAME, flags,
                        win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE
                        | win32pipe.PIPE_WAIT | win32pipe.PIPE_REJECT_REMOTE_CLIENTS,
                        win32pipe.PIPE_UNLIMITED_INSTANCES,
                        PIPE_BUFFER, PIPE_BUFFER, 0, attrs)
                except pywintypes.error as err:
                    if err.winerror == 5:
                        # 名字被占（系统 ssh-agent 服务 / 旧 exe），跟安全属性无关
                        self.error = ("管道 %s 已被其它进程占用：请先停用系统自带的 "
                                      "ssh-agent 服务或旧的 SSHCardAgent.exe" % PIPE_NAME)
                        return None
                    if state["index"] + 1 < len(attrs_list):
                        # 多半是没有 SE_SECURITY_NAME（设置完整性标签要用）：
                        # 降一档再试，别因为「想更安全」把功能整个弄没
                        print("SSH: 管道安全属性（%s）被拒绝：%s，改用下一档"
                              % (tag, err))
                        state["index"] += 1
                        continue
                    self.error = "创建命名管道失败：%s" % err
                    return None
                self.security_desc = tag
                return handle
            return None

        handle = new_instance(True)
        self._ready.set()
        if not handle:
            return None
        while not self._stop.is_set():
            try:
                win32pipe.ConnectNamedPipe(handle, None)
            except pywintypes.error as err:
                # 535/ERROR_PIPE_CONNECTED：客户端在 Connect 之前就连上了，属于正常
                if err.winerror not in (535, 0):
                    try:
                        win32file.CloseHandle(handle)
                    except Exception:
                        pass
                    if self._stop.is_set():
                        break
                    handle = new_instance(False)
                    if not handle:
                        break
                    continue
            if self._stop.is_set():
                try:
                    win32file.CloseHandle(handle)
                except Exception:
                    pass
                break
            # 先把这个连接交给服务线程，同时**立刻**预建下一个实例：
            # 中间不留「没有实例在监听」的空档，客户端不会偶发地连不上
            next_handle = new_instance(False)
            with self._lock:
                self._handles.add(handle)
            threading.Thread(target=self._serve, args=(handle,), daemon=True,
                             name="ssh-agent-conn").start()
            if not next_handle:
                print("SSH: 预建管道实例失败:", self.error)
                break
            handle = next_handle
        return None

    def _serve(self, in_handle):
        import pywintypes
        import win32file
        try:
            while not self._stop.is_set():
                head = self._read_exact(in_handle, 4)
                if not head:
                    break
                length = struct.unpack(">I", head)[0]
                if length <= 0 or length > MESSAGE_MAX:
                    break
                body = self._read_exact(in_handle, length)
                if not body:
                    break
                reply = handle_message(body)
                win32file.WriteFile(in_handle, ssh_u32(len(reply)) + reply)
        except pywintypes.error:
            pass
        except Exception as err:
            print("SSH: 连接处理异常:", err)
        finally:
            with self._lock:
                self._handles.discard(in_handle)
            try:
                import win32pipe
                win32pipe.DisconnectNamedPipe(in_handle)
            except Exception:
                pass
            try:
                win32file.CloseHandle(in_handle)
            except Exception:
                pass
        return None

    @staticmethod
    def _read_exact(in_handle, in_size):
        import pywintypes
        import win32file
        buffer = b""
        while len(buffer) < in_size:
            try:
                _hr, chunk = win32file.ReadFile(in_handle, in_size - len(buffer))
            except pywintypes.error as err:
                # 109/232/233 = 客户端正常断开或管道已关闭，不算错误
                if err.winerror not in (109, 232, 233):
                    print("SSH: 读取客户端数据失败:", err)
                return None
            if not chunk:
                return None
            buffer += chunk
        return buffer


_SERVER = AgentServer()


def server():
    """全局唯一的代理服务实例。"""
    return _SERVER


def agent_running():
    return _SERVER.running


def start_agent():
    return _SERVER.start()


def stop_agent():
    return _SERVER.stop()


# authorized_keys ============================================================
def ssh_dir():
    return os.path.join(os.path.expanduser("~"), ".ssh")


def authorized_keys_path():
    return os.path.join(ssh_dir(), "authorized_keys")


def is_ours(in_line):
    return MARKER in str(in_line or "")


def read_registered():
    """当前 authorized_keys 里由本程序写入的行。"""
    try:
        with open(authorized_keys_path(), "r", encoding="utf-8",
                  errors="replace", newline="") as handle:
            return [line.strip() for line in handle.read().splitlines()
                    if is_ours(line)]
    except OSError:
        return []


def _read_lines():
    try:
        with open(authorized_keys_path(), "r", encoding="utf-8",
                  errors="replace", newline="") as handle:
            return handle.read().splitlines()
    except OSError:
        return []


def _write_lines(in_lines):
    folder = ssh_dir()
    os.makedirs(folder, exist_ok=True)
    path = authorized_keys_path()
    text = "\n".join(in_lines)
    if text:
        text += "\n"
    # newline="" + 显式 LF：OpenSSH 两种换行都认，统一成 LF 便于跨工具查看
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    try:
        os.chmod(path, 0o600)          # Windows 上没有意义，换到别的平台时是正确姿势
    except OSError:
        pass
    return path


def _key_blob_b64(in_cert):
    """证书公钥在 authorized_keys 行里的 base64 部分（用来定位"这一张"的行）。"""
    return base64.b64encode(key_info(in_cert)["blob"]).decode("ascii")


def is_registered(in_cert, in_lines=None):
    """这张证书的公钥现在是否已经在 ``~/.ssh/authorized_keys`` 里。"""
    try:
        blob = _key_blob_b64(in_cert)
    except Exception:
        return False
    lines = read_registered() if in_lines is None else in_lines
    return any(blob in line for line in lines)


def register(in_cert, in_name=""):
    """把证书公钥登记到 ``~/.ssh/authorized_keys``，返回 ``(是否成功, 说明)``。

    只影响**这张证书自己**的行（按公钥 blob 认），别的证书已登记的行原样保留；
    同时把证书记进记忆列表，供「启动时自动登记」使用。
    """
    try:
        thumb = cert_thumbprint(in_cert)
        blob = _key_blob_b64(in_cert)
        info_type = key_info(in_cert)["type"]
    except Exception as err:
        return False, "证书公钥解析失败：%s" % err
    comment = "%s%s:%s" % (MARKER, (in_name or "ssh").replace(" ", "_"), thumb[:16])
    try:
        line = public_key_line(in_cert, comment)
    except Exception as err:
        return False, "无法生成 SSH 公钥：%s" % err
    # 先摘掉这张证书自己的旧行（可能是不同注释），再追加；别人的行不动
    lines = [item for item in _read_lines() if not (is_ours(item) and blob in item)]
    lines.append(line)
    try:
        path = _write_lines(lines)
    except OSError as err:
        return False, "写入 %s 失败：%s" % (authorized_keys_path(), err)
    add_remembered(in_cert, in_name or "")
    store_cert = find_store_cert(thumb)
    note = "" if store_cert else "\n（注意：该证书不在 Windows「个人」证书存储里，SSH 代理签不了名）"
    return True, "%s\n%s%s" % (path, "%s %s" % (info_type, thumb[:16]), note)


def unregister_one(in_cert):
    """只删这一张证书写进 authorized_keys 的行。"""
    try:
        blob = _key_blob_b64(in_cert)
    except Exception as err:
        return False, "证书公钥解析失败：%s" % err
    lines = _read_lines()
    kept = [item for item in lines if not (is_ours(item) and blob in item)]
    if len(kept) == len(lines):
        return True, "authorized_keys 里没有这张证书的公钥"
    try:
        path = _write_lines(kept)
    except OSError as err:
        return False, "写入 %s 失败：%s" % (authorized_keys_path(), err)
    return True, "已从 %s 移除该证书的公钥" % path


def unregister():
    """删掉本程序写入 authorized_keys 的全部行（退出程序时用）。"""
    lines = _read_lines()
    kept = [item for item in lines if not is_ours(item)]
    if len(kept) == len(lines):
        return True, "authorized_keys 里没有本程序登记的公钥"
    try:
        path = _write_lines(kept)
    except OSError as err:
        return False, "写入 %s 失败：%s" % (authorized_keys_path(), err)
    return True, "已从 %s 移除本程序登记的公钥" % path


def find_cert_der(in_thumb):
    """按指纹找证书 DER：先查 Windows 证书存储，再退到卡片上读。"""
    thumb = str(in_thumb or "").upper()
    if not thumb:
        return None
    try:
        item = find_store_cert(thumb)
        if item:
            return item["der"]
    except Exception as err:
        print("SSH: 查询证书存储失败:", err)
    try:
        from Module.SmartCardAPI import SmartCardAPI
        api = SmartCardAPI()
        api.readInfo()
        for cert_now in api.certs.values():
            text = getattr(cert_now, "sc_text", "") or ""
            if not text:
                continue
            try:
                if cert_thumbprint(text) == thumb:
                    return cert_der(text)
            except Exception:
                continue
    except Exception as err:
        print("SSH: 从卡片读取证书失败:", err)
    return None


def auto_register():
    """按记忆的证书列表逐张重新登记公钥（启动时调用）；没配置过时安静返回。

    优先用设置里存下来的证书 PEM：开机自启时卡片可能还没就绪、证书也可能被从
    Windows 存储里清掉，只有存下来的这份才保证「一定能重新写上」。
    """
    items = remembered_certs()
    if not items:
        return False, "还没有登记过证书"
    done, failed = [], []
    for item in items:
        label = item["name"] or item["thumb"][:12]
        in_cert = item["pem"]
        if not in_cert:
            der = find_cert_der(item["thumb"])
            if not der:
                failed.append("%s（找不到证书）" % label)
                continue
            in_cert = der
        try:
            ok, text = register(in_cert, item["name"])
        except Exception as err:
            ok, text = False, str(err)
        if ok:
            done.append(label)
        else:
            failed.append("%s：%s" % (label, text))
    if not failed:
        return True, "%s：%s" % (authorized_keys_path(), "、".join(done))
    summary = "已登记 %d 张：%s" % (len(done), "、".join(done) or "无")
    summary += "\n失败 %d 张：%s" % (len(failed), "；".join(failed))
    return bool(done), summary


def status():
    """给界面用的状态快照。"""
    items = remembered_certs()
    names = [item["name"] or item["thumb"][:12] for item in items]
    return {"enabled": builtin_enabled(),
            "running": agent_running(),
            "register": register_enabled(),
            "cert": ", ".join(names),
            "certs": names,
            "count": len(names),
            "thumb": items[0]["thumb"] if items else "",
            "registered": bool(read_registered()),
            "error": _SERVER.error,
            "security": _SERVER.security_desc,
            "git": git_linked(),
            "keys": len(identities()) if agent_running() else 0}
