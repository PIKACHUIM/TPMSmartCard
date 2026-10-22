import os
import subprocess
import time

from Module import Paths
from Module import PtyCompat
from Module import WinPlatform

# 不弹出控制台窗口（powershell 子进程用）
NO_WINDOW = 0x08000000
# TPM 状态缓存：Get-Tpm 一次要一两秒，启动检查与设置页共用，避免重复等待
TPM_CACHE_TTL = 30.0
_TPM_CACHE = {"stamp": 0.0, "value": None}


class TPMSmartCard:
    def __init__(self):
        pass

    @staticmethod
    # 系统虚拟智能卡管理程序路径 ================================================
    #   必须用系统目录里的官方版本：项目目录下若存在同名副本，
    #   cmd.exe 会优先命中当前目录的那一份（未签名、错误信息被吞、行为不一致）。
    #   注意：32 位进程在 64 位系统上会被 WOW64 重定向到 SysWOW64（那里**没有**
    #   tpmvscmgr.exe），system32_dir() 会改用 Sysnative 兜住（见 Module/WinPlatform）。
    def tpmVscMgr():
        return os.path.join(WinPlatform.system32_dir(), "tpmvscmgr.exe")

    @staticmethod
    # 当前进程是否以管理员身份运行 ==============================================
    #   建卡/删卡都需要管理员权限，未提权时 tpmvscmgr 会抛出误导性的
    #   "(0x80070002) 系统找不到指定的文件"，所以调用前先判断。
    def isElevated():
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception as err:
            print("Check Admin Error:", err)
            return False

    @staticmethod
    # 当前会话是否为远程（终端服务/远程桌面）会话 ================================
    #   Windows 的虚拟智能卡管理会拒绝在终端服务会话中建卡/删卡，报错为
    #   「不能在终端服务会话中使用TPM虚拟智能卡管理。(0x800704d3)」。
    #   该判定由系统在服务端按调用方所在会话完成（tpmvscmgr.exe 本身不导入
    #   任何 WTS/会话相关接口），换 exe、提权、加静默参数都绕不过去，
    #   只能改用 mstsc /admin 附着到物理控制台会话，或直接在本机控制台操作。
    #   这里提前拦截，避免卡在交互式 tpmvscmgr 上干等 5 分钟超时。
    def isRemoteSession():
        try:
            import ctypes
            # SM_REMOTESESSION = 0x1000：远程会话返回非 0，控制台会话返回 0
            return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))
        except Exception as err:
            print("Check Remote Session Error:", err)
            return False

    @staticmethod
    # 制作一张新的虚拟智能卡 =======================================================
    def makeCards(in_pin,  # 卡密码，必要
                  in_puk="",  # 可选PUK码
                  in_adk="",  # Admin Key
                  in_tag="PikaSmartCard"):
        # 前置检查 =================================================================
        mgr_path = TPMSmartCard.tpmVscMgr()
        if not os.path.exists(mgr_path):
            return "Error: %s not found." % mgr_path
        if not TPMSmartCard.isElevated():
            return "Error: Administrator privileges are required to create a TPM virtual smart card."
        if TPMSmartCard.isRemoteSession():
            # 终端服务（远程桌面）会话下建卡必失败，直接返回可读原因
            return ("Error: TPM virtual smart card management cannot be used in a "
                    "Terminal Services session. (0x800704d3)\n"
                    "Please connect to the console session with 'mstsc /admin', "
                    "or run this tool on the local console.")
        # 根据参数设置命令 =========================================================
        # 注意：tpmvscmgr 的 /AdminKey /PUK /PIN 只接受 PROMPT|DEFAULT|RANDOM，
        # 没有「把密码写在命令行上」的写法，自定义密码只能靠回答控制台提示录入
        # （32 位进程读控制台，管道的 stdin 喂不进去，见 Module/PtyCompat）。
        command = [mgr_path, "create", "/name", in_tag,
                   "/AdminKey", "PROMPT" if len(in_adk) == 48 else "RANDOM"]
        if len(in_puk) == 8:
            command += ["/PUK", "PROMPT"]
        command += ["/PIN", "PROMPT", "/generate"]
        print("创建卡片命令:", " ".join(command))
        # 创建卡片 =================================================================
        proc = PtyCompat.spawn(command)
        # 等进程起来（控制台的输入缓冲区会先存下按键，早写也不会丢）
        time.sleep(1)
        # 写入各项密码 =========================
        # 每个 PROMPT 参数各问两次（输入 + 确认）；多写的字会被当成命令执行，
        # 刷出一堆 "'xxx' 不是内部或外部命令"，把真正的报错盖掉。
        if len(in_adk) == 48:
            for _ in range(0, 2):
                proc.write(str(in_adk) + "\r")
        if len(in_puk) == 8:
            for _ in range(0, 2):
                proc.write(str(in_puk) + "\r")
        for _ in range(0, 2):
            proc.write(str(in_pin) + "\r")
        # 判断注册状态 =========================
        # 加超时保护：tpmvscmgr 若卡在交互提示，避免主程序永久挂起
        count = 0
        while proc.isalive() and count < 300:
            time.sleep(1)
            count += 1
            print("Creating Smart Card...")
        result = ""
        if proc.isalive():
            print("Creating Smart Card: timeout, force exit")
            try:
                proc.close(force=True)
            except Exception as err:
                print("Close Card Process Error:", err)
        else:
            try:
                result = proc.read()
            except Exception as err:
                print("Read Card Process Error:", err)
        result = "" if result is None else str(result)
        print(result)
        return result

    @staticmethod
    # 查询 TPM 状态 ==============================================================
    #   返回 (状态码, 字段字典, 展示文本)
    #   状态码：0 已激活可用、1 未激活、-1 状态未知（如未以管理员权限运行）
    #
    #   Get-Tpm 要起一次 PowerShell（一两秒起步），主程序启动检查与「系统设置」
    #   都会问它；带缓存后第二次起就是内存读，设置页不再卡在这儿。
    def tpmStatus(use_cache=True):
        if use_cache:
            cached = _TPM_CACHE["value"]
            if cached is not None and time.time() - _TPM_CACHE["stamp"] < TPM_CACHE_TTL:
                return cached
        value = TPMSmartCard.queryTpmStatus()
        if value[0] != -1:
            # 查不出结果（多半是权限不足）时不缓存，下次再试
            _TPM_CACHE["stamp"] = time.time()
            _TPM_CACHE["value"] = value
        return value

    @staticmethod
    def queryTpmStatus():
        """真正去问一次系统（不读缓存）。"""
        # -NoProfile / -NonInteractive：跳过用户配置脚本，启动快很多；
        # 不用 shell=True：省掉一次 cmd.exe 中转，也避免控制台窗口闪一下。
        command = ["powershell", "-NoProfile", "-NonInteractive",
                   "-Command", "Get-Tpm"]
        try:
            process = subprocess.run(command, text=True, capture_output=True,
                                     timeout=60, creationflags=NO_WINDOW)
        except Exception as err:
            print("Get-TPM Error:", err)
            return -1, {}, "Get-TPM Error: %s" % err
        raw_text = process.stdout if process.stdout else ""
        raw_text = raw_text.replace(" ", "")
        raw_text = ''.join(x for x in raw_text if x.isprintable() or x == "\n")
        fields = dict()
        results = []
        for item in raw_text.split("\n"):
            # 只处理形如 "Key: Value" 的行，避免命令报错等无冒号文本导致索引越界
            if ":" not in item:
                continue
            name, _, value = item.partition(":")
            if not name:
                continue
            fields[name] = value
            results.append("%-25s\t: %s" % (name + "\t" * int(16 / len(name)), value))
        results = "\n".join(results).replace("TpmOwned\t\t", "TpmOwned\t")
        if not results.strip():
            # 未解析到任何键值对（如未以管理员权限运行），使用原始输出/错误信息作为提示
            results = raw_text.strip() or (process.stderr.strip() if process.stderr else "") \
                      or "None TPM Info"
        status = -1
        for name in ("TpmActivated", "TpmReady"):
            if name in fields:
                status = 0 if fields[name].strip().lower().startswith("true") else 1
                break
        return status, fields, results

    @staticmethod
    def dropCards(in_name):
        # 前置检查 =================================================================
        mgr_path = TPMSmartCard.tpmVscMgr()
        if not os.path.exists(mgr_path):
            return "Error: %s not found." % mgr_path
        if not TPMSmartCard.isElevated():
            return "Error: Administrator privileges are required to delete a TPM virtual smart card."
        if TPMSmartCard.isRemoteSession():
            # 删卡与建卡受同一条会话限制（0x800704d3）
            return ("Error: TPM virtual smart card management cannot be used in a "
                    "Terminal Services session. (0x800704d3)\n"
                    "Please connect to the console session with 'mstsc /admin', "
                    "or run this tool on the local console.")
        # /quiet 跳过确认提示：不需要任何控制台交互，直接 subprocess 拿输出即可
        result, _ok = TPMSmartCard.runCommand(
            [mgr_path, "destroy", "/quiet", "/instance", str(in_name)])
        print(result)
        return result

    # certutil 的「证书已经在存储中」提示码：只是跳过重复添加，命令本身仍是成功的
    CERT_EXISTS_CODE = "0x80092005"

    @staticmethod
    def decodeOutput(in_raw):
        """解码系统命令的输出。

        certutil / certreq 等按本机 ANSI 代码页输出（简体中文为 GBK），
        一旦系统开启了「Beta: 使用 UTF-8 提供全球语言支持」，用 locale 解码就会
        变成乱码，导致日志与成败判定都不可读。
        """
        if in_raw is None:
            return ""
        if isinstance(in_raw, str):
            return in_raw
        for encoding in ("mbcs", "gbk", "utf-8"):
            try:
                return in_raw.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
        return in_raw.decode("utf-8", "replace")

    @staticmethod
    def runCommand(in_command):
        """执行系统命令，返回 ``(输出文本, 是否成功)``。

        成败一律以退出码为准（语言无关），不要靠输出里的关键字判断：
        certutil 导入已存在的证书时会打印 CRYPT_E_EXISTS，但退出码仍是 0。
        """
        print(in_command)
        process = subprocess.run(in_command, capture_output=True)
        result = TPMSmartCard.decodeOutput(process.stdout)
        if not result.strip():
            # 少数失败场景信息只出现在 stderr
            result = TPMSmartCard.decodeOutput(process.stderr)
        print(result)
        return result, process.returncode == 0

    @staticmethod
    def initCerts(in_path,
                  in_pass="",
                  in_csp=None):
        """导入 PFX（证书 + 私钥）到智能卡并写入证书存储。

        返回 ``(输出文本, 是否成功)``。注意 ``CERT_EXISTS_CODE``：证书此前已导入时
        certutil 会提示「对象或属性已经存在」，这不是失败（退出码为 0，私钥与证书
        本就已就位），调用方需按退出码区分。
        """
        if in_csp is None:
            in_csp = "Microsoft Base Smart Card Crypto Provider"
        # 用参数列表调用：密码/路径含引号、& 等字符时不会被 shell 解析破坏
        return TPMSmartCard.runCommand(
            ["certutil", "-csp", in_csp, "-p", in_pass, "-importpfx", in_path])

    @staticmethod
    def baseCerts(in_data,
                  in_pass=""):
        # 随包分发在 Import\ 下（install.iss 装到 {app}\Import），按程序根目录定位
        command = [Paths.resource("Import", "TPMImport.exe"), "-user", "-b", in_data, in_pass]
        print(command)
        process = subprocess.run(command, text=True, capture_output=True)
        result = process.stdout
        print(result)
        return result

    @staticmethod
    def CSPFetch():
        command = ('certutil -csplist')
        print(command)
        process = subprocess.run(command, shell=True, text=True, capture_output=True)
        outputs = process.stdout
        results = []
        tmp_str = None
        for line in outputs.split('\n'):
            if len(line) <= 0:
                if tmp_str is not None:
                    results.append(tmp_str)
                    tmp_str = None
                continue
            if tmp_str is None:
                line = line.split(": ")
                # 无冒号的行（本地化/异常输出）直接跳过，避免索引越界
                if len(line) < 2:
                    continue
                line = line[1]
                tmp_str = line
        print(results)
        return results

    @staticmethod
    def dropCerts(in_name):
        command = ["certutil", "-delkey",
                   "-csp", "Microsoft Base Smart Card Crypto Provider", "%s" % in_name]
        process = subprocess.run(command, text=True, capture_output=True)
        result = process.stdout
        print(result)
        # command = ('certutil -delkey '
        #            '-csp "Microsoft Base Smart Card Crypto Provider" "%s"' % in_name)
        # process = subprocess.run(command, shell=True, text=True, capture_output=True)
        # "Get-ChildItem -Path Cert:\ -Recurse | Where-Object {$_.SerialNumber -eq '%s' } | Remove-Item" % ""
        return result

    @staticmethod
    def changePIN(old, new, uid, type="--change-pin", with_state=False):
        # pkcs15-tool 支持用命令行传 PIN（--pin / --puk / --new-pin），
        # 不必再用伪控制台回答提示（32 位构建没有 pywinpty，这条路也更稳）
        command = [Paths.resource("OpenSC", "pkcs15-tool.exe"),
                   "--reader", str(uid), type]
        if type == "--unblock-pin":
            command += ["--puk", str(old)]
        else:
            command += ["--pin", str(old)]
        command += ["--new-pin", str(new)]
        result, ok = TPMSmartCard.runCommand(command)
        print(result)
        text = result.strip() or "OK"
        # 调用方需要知道是否成功（改完要把 FIDO2 凭据重新封装到新 PIN 下），
        # 保持默认返回值不变，避免影响既有调用。
        return (text, ok) if with_state else text

    @staticmethod
    def createCSR(in_file, in_path):
        command = ["certreq", "-new", "-f", in_file, in_path]
        print(command)
        process = subprocess.run(command, text=True, capture_output=True)
        result = process.stdout
        print(result)
        return result

    @staticmethod
    def loadCerts(in_path):
        """导入 CA 签发的证书文件（.p7b/.cer），返回 ``(输出文本, 是否成功)``。"""
        # command = ('certutil -csp "Microsoft Base Smart Card Crypto Provider" '
        #            ' -importcert "%s"' % in_path)
        return TPMSmartCard.runCommand(["CertReq", "-Accept", "-machine", in_path])
