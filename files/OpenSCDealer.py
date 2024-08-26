import subprocess

from files.SmartCardObj import SmartCardDev


class OpenSCDealer:
    def __init__(self):
        self.cards = {}
        self.certs = {}

    @staticmethod
    def openText(in_comm, in_tool="pkcs15-tool"):
        command = ".\\tools\\opensc\\%s.exe %s" % (in_tool, in_comm)
        process = subprocess.run(command, shell=True, text=True, capture_output=True)
        return (process.stderr + process.stdout).replace("\t", "").split("\n")

    def readCert(self, results):
        print(results)

    def readCard(self, results, card_name):
        results = [i.split(": ") for i in results[1:10] if len(i)]
        results = {i[0].replace(" ", ""): i[1] for i in results}
        if card_name not in self.cards:
            self.cards[card_name] = SmartCardDev(
                card_name, results['Flags'], results['Length'],
                None, results['ID'],
            )
            print(results)

    def readList(self):
        # 获取所有的卡片 ==========================================
        card_all = OpenSCDealer.openText(  # 获取系统上智能卡列表
            "--list-readers", "opensc-tool")[2:]
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

        #
        # print(results)
        # for command in [, "--list-keys"]:
        #     results = OpenSCDealer.openText(command)
        #         if results[nums].find("Private RSA Key") >= 0:
        #             self.openCert(results[nums:nums + 11])
