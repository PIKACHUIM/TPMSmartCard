import subprocess
import traceback

from Module.SmartCardObj import SmartCardDev
from Module.SmartCardObj import SmartCardCer


class OpenSCDealer:
    def __init__(self):
        self.cards = {}
        self.certs = {}

    @staticmethod
    def openText(in_comm, in_tool="pkcs15-tool"):
        command = ".\\OpenSC\\%s.exe %s" % (in_tool, in_comm)
        process = subprocess.run(command, shell=True, text=True, capture_output=True)
        results = (process.stderr + process.stdout).replace("\t", "").split("\n")
        # print(results)
        return results

    @staticmethod
    # 把 "键 : 值" 行解析为字典，无冒号的行一律跳过（避免解析外部输出时越界）
    def readFields(in_lines, in_start=1, in_end=10):
        fields = dict()
        for line in in_lines[in_start:in_end]:
            if len(line) <= 0 or ": " not in line:
                continue
            name, _, value = line.partition(": ")
            fields[name.replace(" ", "")] = value
        return fields

    def readCert(self, results, details, in_card=None):
        if len(results) <= 0 or "[" not in results[0]:
            return None
        cr_name = results[0].split("[")[1].replace("]", "")
        key_parts = results[0].split(" ")
        if len(key_parts) <= 1:
            return None
        results = OpenSCDealer.readFields(results, 1, 11)
        if 'ModLength' not in results:
            return None
        try:
            self.certs[cr_name] = SmartCardCer(
                cr_name, results.get('MD:guid', "Unknown"),
                key_parts[1] + " " + results['ModLength'],
                results.get('Usage', "Unknown"),
                None if details.find("not found") >= 0 else details,
                in_card
            )
        except Exception as err:
            print("Read Cert Error:", err)
            traceback.print_exc()
        # print(results)

    def readCard(self, results, card_name):
        results = OpenSCDealer.readFields(results, 1, 10)
        if card_name in self.cards:
            return
        if card_name.find('Microsoft Virtual Smart Card') < 0:
            return
        if 'Flags' not in results or 'Length' not in results:
            return
        card_id = card_name.split(" ")[-1]
        if not card_id.isdigit():
            return
        card_uuid = int(card_id)
        serials = ""
        try:
            outputs = OpenSCDealer.openText("--reader %d --serial" % card_uuid, "OpenSC-tool")
            serials = outputs[0] if len(outputs) > 0 else ""
        except Exception as err:
            print("Read Serial Error:", err)
        serials = str(serials).replace(" ", "")[:32]
        self.cards[card_name] = SmartCardDev(
            "%04d" % card_uuid,
            card_name,
            results['Flags'],
            results['Length'],
            None,
            # results['ID'],
            serials.lower(),
        )
        # print(results)

    def readFile(self, in_data):
        pass

    def readList(self):
        self.cards = {}
        self.certs = {}
        try:
            # 获取所有的卡片 ==========================================
            card_all = OpenSCDealer.openText(  # 获取系统上智能卡列表
                "--list-readers", "OpenSC-tool")[2:]
            # 预处理卡片信息 ==========================================
            card_all = [i.split("   ") for i in card_all if len(i) > 0]
            card_all = [[j for j in i if len(j) > 0] for i in card_all]
            card_all = {i[0]: i[2][1:] for i in card_all if len(i) > 2}
            # 遍历所有的卡片 ==========================================
            for card_uuid in card_all:
                if not str(card_uuid).strip().isdigit():
                    continue
                try:
                    results = OpenSCDealer.openText("--list-pins %s" % (
                            "--reader %d" % int(card_uuid)))
                    for nums in range(0, len(results)):
                        if results[nums].find("PIN [UserPIN]") >= 0:
                            self.readCard(results[nums + 1:nums + 10],
                                          card_all[card_uuid])
                    results = OpenSCDealer.openText("--list-keys %s" % (
                            "--reader %d" % int(card_uuid)))
                    count = -1
                    for nums in range(0, len(results)):
                        if results[nums].find("Private") >= 0:
                            count += 1
                            details = OpenSCDealer.openText(
                                "--read-certificate %d %s" % (
                                    int(count), "--reader %d" % int(card_uuid)))
                            # 记下证书所属读卡器名（与 self.cards 的键一致），供界面按卡过滤
                            self.readCert(results[nums:nums + 11], "\n".join(details),
                                          card_all[card_uuid])
                except Exception as err:
                    print("Read Card Error:", err)
                    traceback.print_exc()
                    continue
        except Exception as err:
            print("Read List Error:", err)
            traceback.print_exc()
        return self.cards
