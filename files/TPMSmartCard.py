import os
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

    def dropCards(self, in_uid):
        os.system("tpmvscmgr.exe destroy /instance ROOT\\SMARTCARDREADER\\%04d" % int(in_uid))

    def importCer(self,
                  in_path,
                  in_pins):
        os.system('certutil -csp "Microsoft Base Smart Card Crypto Provider" -importpfx')

    def deleteCer(self):
        pass

    def systemCer(self):
        pass

    def changePIN(self):
        pass

    def resetPIN(self):
        pass
