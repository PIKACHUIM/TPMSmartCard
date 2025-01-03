import subprocess
import time
from winpty import PtyProcess


class TPMSmartCard:
    def __init__(self):
        pass

    @staticmethod
    # 制作一张新的虚拟智能卡 =======================================================
    def makeCards(in_pin,  # 卡密码，必要
                  in_puk="",  # 可选PUK码
                  in_adk="",  # Admin Key
                  in_tag="PikaSmartCard"):
        # 根据参数设置命令 =========================================================
        command = 'tpmvscmgr.exe create /name "%s"' % in_tag
        command += " /AdminKey PROMPT" if len(in_adk) == 48 else " /AdminKey RANDOM"
        command += " /PUK PROMPT" if len(in_puk) == 8 else ""
        command += " /PIN PROMPT /generate\r"
        print("创建卡片命令:", command)
        # 创建卡片 =================================================================
        proc = PtyProcess.spawn('cmd.exe')
        proc.write("@echo off && cls\r")
        time.sleep(1)
        proc.write(command)
        time.sleep(1)
        # 写入各项密码 =========================
        if len(in_adk) == 48:
            for _ in range(0, 2):
                proc.write(str(in_adk) + "\r")
        if len(in_puk) == 8:
            for _ in range(0, 2):
                proc.write(str(in_puk) + "\r")
        for _ in range(0, 2):
            for _ in range(0, 2):
                proc.write(str(in_pin) + "\r")
        proc.write("\rexit\r")
        # 判断注册状态 =========================
        while proc.isalive():
            time.sleep(1)
            print("Creating Smart Card...")
        result = proc.read()
        print(result)
        return result

    @staticmethod
    def dropCards(in_name):
        proc = PtyProcess.spawn('cmd.exe')
        proc.write("@echo off && cls\r")
        time.sleep(1)
        proc.read()
        proc.write("tpmvscmgr.exe destroy /instance %s\r\r" % in_name)
        proc.write("\rexit\r")
        time.sleep(1)
        result = proc.read().split("\r\n")
        print(result)
        return "\n".join(result[2:8])

    @staticmethod
    def initCerts(in_path,
                  in_pass="",
                  in_csp=None):
        if in_csp is None:
            in_csp = "Microsoft Base Smart Card Crypto Provider"
        command = ('certutil -csp "%s"  -p "%s" -importpfx "%s"' % (in_csp, in_pass, in_path))
        print(command)
        process = subprocess.run(command, shell=True, text=True, capture_output=True)
        result = process.stdout
        print(result)
        return result

    @staticmethod
    def baseCerts(in_data,
                  in_pass=""):
        command = ('Import/TPMImport.exe -user -b %s "%s"' % (in_data, in_pass))
        print(command)
        process = subprocess.run(command, shell=True, text=True, capture_output=True)
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
                if len(line) < 1:
                    continue
                line = line[1]
                tmp_str = line
        print(results)
        return results

    @staticmethod
    def dropCerts(in_name):
        command = ('certutil -delkey '
                   '-csp "Microsoft Base Smart Card Crypto Provider" "%s"' % in_name)
        process = subprocess.run(command, shell=True, text=True, capture_output=True)
        result = process.stdout
        print(result)
        # command = ('certutil -delkey '
        #            '-csp "Microsoft Base Smart Card Crypto Provider" "%s"' % in_name)
        # process = subprocess.run(command, shell=True, text=True, capture_output=True)
        # "Get-ChildItem -Path Cert:\ -Recurse | Where-Object {$_.SerialNumber -eq '%s' } | Remove-Item" % ""
        return result

    @staticmethod
    def changePIN(old, new, uid, type="--change-pin"):
        command = ".\\OpenSC\\pkcs15-tool.exe --reader %s %s\r" % (uid, type)
        proc = PtyProcess.spawn(command)
        # proc.write("@echo off && cls\r")
        # proc.read()
        # proc.write(command)
        time.sleep(1)
        proc.write(old + "\r")
        proc.write(new + "\r")
        proc.write(new + "\r")
        # proc.write("\rexit\r")
        time.sleep(1)
        result = proc.read()
        result = result.split(": ")[-1]
        if len(result) == 0:
            result = "OK"
        print(result)
        return result

    @staticmethod
    def createCSR(in_file, in_path):
        command = 'certreq -new -f "%s" "%s"' % (in_file, in_path)
        print(command)
        process = subprocess.run(command, shell=True, text=True, capture_output=True)
        result = process.stdout
        print(result)
        return result

    @staticmethod
    def loadCerts(in_path):
        command = ('CertReq -Accept -machine "%s"' % in_path)
        # command = ('certutil -csp "Microsoft Base Smart Card Crypto Provider" '
        #            ' -importcert "%s"' % in_path)
        print(command)
        process = subprocess.run(command, shell=True, text=True, capture_output=True)
        result = process.stdout
        print(result)
        return result
