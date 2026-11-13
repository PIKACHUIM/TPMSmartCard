import subprocess
import traceback

from Module.SmartCardObj import SmartCardDev, SmartCardCer


class CertutilDeal:
    """`certutil -scinfo -silent` 的解析实现（旧版路径，默认不启用）。

    SmartCardAPI 默认使用 OpenSC 解析（use_opensc=True）。本实现依赖 certutil
    输出的字段行，其内容随系统语言/版本变化，因此这里一律按“取不到就跳过”的方式
    处理，任何解析异常都不会向上抛出，只是拿不到卡片/证书数据。
    """

    def __init__(self):
        self.cards = {}
        self.certs = {}

    @staticmethod
    # 只保留 "键: 值" 中的值部分，无冒号的行丢弃首个字符（去掉行首空格）
    def splitValues(in_lines):
        values = []
        for line in in_lines:
            if len(line) <= 0:
                continue
            if line.find(":") >= 0:
                value = ":".join(line.split(":")[1:])
                if len(value) > 0 and value[0] == " ":
                    value = value[1:]
            else:
                value = line[1:] if len(line) > 1 else ""
            values.append(value)
        return values

    @staticmethod
    # 解析当前智能卡的信息(Certutil) ===============================================
    def readCard(in_line):
        try:
            values = CertutilDeal.splitValues(in_line)
            if len(values) < 5:
                return None
            # 首字段必须是卡序号（sc_path 会被用于 tpmvscmgr destroy，不能是任意文本）
            if not values[0].strip().isdigit():
                return None
            # 字段顺序沿用旧实现：编号 / 名称 / Flag / Lens / UUID
            sc_data = SmartCardDev(
                values[0], values[1], values[2],
                values[3],
                # 证书在此路径下无法获取，交由 OpenSC 路径或证书列表提供
                None,
                values[4].replace(" ", ""))
            return sc_data
        except Exception as err:
            print("Deal card error:", err)
            traceback.print_exc()

    @staticmethod
    # 解析当前注册证书信息(Certutil) ===========================================
    def readCert(in_line):
        try:
            values = CertutilDeal.splitValues(in_line)
            if len(values) < 4:
                return None
            if "= " not in values[2] or "= " not in values[3]:
                return None
            # sc_exec / sc_keys 来自 "名称 = 值" 形式的字段行
            sc_data = SmartCardCer(
                values[0], values[1],
                values[2].split("= ")[1], values[3].split("= ")[1],
                # certutil 不输出 PEM，证书内容置空（界面按“无证书”处理）
                None)
            return sc_data
        except Exception as err:
            print("Deal cert error:", err)
            traceback.print_exc()

    # 获取所有智能卡和证书 ==========================================================
    def readList(self):
        command = "certutil -scinfo -silent"
        process = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True, text=True)
        results = ""
        if process.stdout.readable():
            results, _ = process.communicate()
            results = results if results else ""
            results = results.split("\n")
        for num in range(0, len(results)):
            txt_line = results[num]
            # 智能卡设备信息 ========================================================
            if txt_line == "=======================================================":
                try:
                    temp_card = CertutilDeal.readCard(results[num + 1:num + 11])
                    if temp_card is None:
                        continue
                except Exception as err:
                    print("Read Card Error:", err)
                    traceback.print_exc()
                    continue
                if temp_card.sc_name not in self.cards:
                    if temp_card.sc_name.find("Microsoft Virtual Smart Card") >= 0:
                        self.cards[temp_card.sc_name] = temp_card
            # 智能卡证书信息 =======================================================
            if txt_line == "--------------===========================--------------":
                if num + 1 >= len(results):
                    continue
                if len(results[num + 1]) == 0 or results[num + 1].find("Util") >= 0:
                    continue
                try:
                    temp_cert = CertutilDeal.readCert(results[num + 2:num + 14])
                except Exception as err:
                    print("Read Cert Error:", err)
                    traceback.print_exc()
                    continue
                if temp_cert is None:
                    continue
                if temp_cert.sc_name not in self.certs:
                    if temp_cert.sc_name.find("Microsoft Virtual Smart Card") >= 0:
                        self.certs[temp_cert.sc_name] = temp_cert
        return results
