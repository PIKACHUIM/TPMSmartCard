import subprocess

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
        print(results)
        return results

    def readCert(self, results, details):
        cr_name = results[0].split("[")[1].replace("]", "")
        key_alg = results[0].split(" ")[1]
        results = [i.split(": ") for i in results[1:11] if len(i)]
        results = {i[0].replace(" ", ""): i[1] for i in results}
        if 'ModLength' not in results:
            return None
        self.certs[cr_name] = SmartCardCer(
            cr_name, results['MD:guid'],
            key_alg + " " + results['ModLength'] if 'ModLength' in results else "No Key",
            results['Usage'],
            None if details.find("not found") >= 0 else details
        )
        print(results)

    def readCard(self, results, card_name):
        results = [i.split(": ") for i in results[1:10] if len(i)]
        results = {i[0].replace(" ", ""): i[1] for i in results}
        if card_name not in self.cards:
            if card_name.find('Microsoft Virtual Smart Card') >= 0:
                card_uuid = int(card_name.split(" ")[-1])
                serials = OpenSCDealer.openText(" %s --serial" % (
                        "--reader %d" % int(card_uuid)), "OpenSC-tool")[0]
                serials = serials.replace(" ", "")[:32]
                self.cards[card_name] = SmartCardDev(
                    "%04d" % card_uuid,
                    card_name,
                    results['Flags'],
                    results['Length'],
                    None,
                    # results['ID'],
                    serials.lower(),
                )
            print(results)

    def readFile(self, in_data):
        pass

    def readList(self):
        self.cards = {}
        self.certs = {}
        # 获取所有的卡片 ==========================================
        card_all = OpenSCDealer.openText(  # 获取系统上智能卡列表
            "--list-readers", "OpenSC-tool")[2:]
        # 预处理卡片信息 ==========================================
        card_all = [i.split("   ") for i in card_all if len(i) > 0]
        card_all = [[j for j in i if len(j) > 0] for i in card_all]
        card_all = {i[0]: i[2][1:] for i in card_all if len(i) > 2}
        # 遍历所有的卡片 ==========================================
        for card_uuid in card_all:
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
                    count+=1
                    details = OpenSCDealer.openText(
                        "--read-certificate %d %s" % (int(count), "--reader %d" % int(card_uuid)))
                    self.readCert(results[nums:nums + 11], "\n".join(details))
