import os
import subprocess
import time
import traceback

from files.Certificates import CertDataInfo
from files.SmartCardObj import SmartCardDev
from files.SmartCardObj import SmartCardCer
from winpty import PtyProcess


class SmartCardAPI:
    def __init__(self):
        self.cards = {}
        self.certs = {}

    def saveLogs(self):
        pass

    @staticmethod
    # 解析当前智能卡的信息 ==========================================================
    def dealCard(in_line):
        try:
            in_line = in_line[1:] if in_line[0].startswith("===") else in_line
            in_line = [i.split(":")[1:] if i.find(":") >= 0 else i for i in in_line]
            in_line = [":".join(i) if type(i) is list else i + " " for i in in_line]
            in_line = [i[1:] if i[0] == " " else i for i in in_line]  # 删除前面空格
            if len(in_line) < 10:
                return None
            sc_data = SmartCardDev(
                in_line[0], in_line[1], in_line[2],
                CertDataInfo(
                    in_line[3], in_line[4], in_line[7],
                    in_line[5], in_line[6], in_line[9],
                    in_line[8].replace(" ", "")))
            return sc_data
        except Exception as e:
            print("Deal card error:", e)
            traceback.print_exc()

    @staticmethod
    # 解析当前注册证书信息 ==========================================================
    def dealCert(in_line):
        in_line = [i for i in in_line if i]
        in_line = in_line[1:] if in_line[0].startswith("===") else in_line
        in_line = [i.split(":")[1:] if i.find(":") >= 0 else i for i in in_line]
        in_line = [":".join(i) if type(i) is list else i + " " for i in in_line]
        in_line = [i[1:] if i[0] == " " else i for i in in_line]  # 删除前面空格
        if in_line[4] == in_line[0]:
            in_line = in_line[0:4] + in_line[5:]
        sc_data = SmartCardCer(
            in_line[0], in_line[1],  # 基本信息
            in_line[2].split("= ")[1], in_line[3].split("= ")[1],
            CertDataInfo(
                in_line[4], in_line[5], in_line[8],
                in_line[6], in_line[7], in_line[9],
                in_line[7].replace(" ", "")))
        return sc_data

    # 获取所有智能卡和证书 ==========================================================
    def showList(self):
        command = "certutil -scinfo -silent"
        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   shell=True, text=True)
        results = ""
        if process.stdout.readable():
            results, _ = process.communicate()
            results = results.split("\n")
        for num in range(0, len(results)):
            txt_line = results[num]
            # 智能卡设备信息 ========================================================
            if txt_line == "=======================================================":
                try:
                    temp_card = SmartCardAPI.dealCard(results[num + 1:num + 11])
                    if temp_card is None:
                        continue
                except (ValueError, Exception) as err:
                    print("Read Card Error:", err)
                    traceback.print_exc()
                    continue
                if temp_card.sc_name not in self.cards:
                    if temp_card.sc_name.find("Microsoft Virtual Smart Card") >= 0:
                        self.cards[temp_card.sc_name] = temp_card
            # 智能卡证书信息 =======================================================
            if txt_line == "--------------===========================--------------":
                if len(results[num + 1]) == 0 or results[num + 1].find("Util") >= 0:
                    continue
                try:
                    temp_cert = SmartCardAPI.dealCert(results[num + 2:num + 14])
                except (ValueError, Exception) as err:
                    print("Read Card Error:", err)
                    traceback.print_exc()
                    continue
                if temp_cert.sc_cert.cr_uuid not in self.certs:
                    if temp_cert.sc_name.find("Microsoft Virtual Smart Card") >= 0:
                        self.certs[temp_cert.sc_cert.cr_uuid] = temp_cert
        return results

    def openList(self):
        command = ".\\tools\\opensc\\pkcs15-tool.exe -D"
        process = subprocess.run(command, shell=True, text=True, capture_output=True)
        results = process.stdout.replace("\t", "").split("\n")
        print(results)

    # 制作一张新的虚拟智能卡 ==========================================================
    def makeCard(self,
                 in_pin,  # 卡密码，必要
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
        self.showList()
        return result

    def dropCard(self, in_uid):
        os.system("tpmvscmgr.exe destroy /instance ROOT\SMARTCARDREADER\%04d" % int(in_uid))

    def importCR(self,
                 in_path,
                 in_pins):
        os.system('certutil -csp "Microsoft Base Smart Card Crypto Provider" -importpfx')

    def deleteCR(self):
        pass

    def systemCR(self):
        pass


if __name__ == "__main__":
    api = SmartCardAPI()
    # api.showList()
    api.openList()
    # api.makeCard(
    #     in_pin="12345678",
    #     in_adk="010203040506070801020304050607080102030405060708"
    # )
