import subprocess
import traceback

from Module.Certificates import CertDataInfo
from Module.SmartCardAPI import SmartCardAPI
from Module.SmartCardObj import SmartCardDev, SmartCardCer


class CertutilDeal:
    def __init__(self):
        self.cards = {}
        self.certs = {}

    @staticmethod
    # 解析当前智能卡的信息(Certutil) ===============================================
    def readCard(in_line):
        try:
            # 预处理 ===============================================================
            in_line = in_line[1:] if in_line[0].startswith("===") else in_line
            in_line = [i.split(":")[1:] if i.find(":") >= 0 else i for i in in_line]
            in_line = [":".join(i) if type(i) is list else i + " " for i in in_line]
            in_line = [i[1:] if i[0] == " " else i for i in in_line]  # 删除前面空格
            if len(in_line) < 10:
                return None
            sc_data = SmartCardDev(
                in_line[0], in_line[1], in_line[2],
                CertDataInfo(
                    "0", in_line[3], in_line[4], in_line[7],
                    in_line[5], in_line[6], in_line[9],
                    in_line[8].replace(" ", "")))
            return sc_data
        except Exception as e:
            print("Deal card error:", e)
            traceback.print_exc()

    @staticmethod
    # 解析当前注册证书信息(Certutil) ===========================================
    def readCert(in_line):
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
    def readList(self):
        command = "certutil -scinfo -silent"
        process = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True, text=True)
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
