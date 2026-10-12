class SmartCardAPI:
    def __init__(self, use_opensc=True):
        self.cards = {}
        self.certs = {}
        if use_opensc:
            from Module.OpenSCDealer import OpenSCDealer as Deal
        else:
            # 旧版 certutil 解析路径：字段随系统语言/版本变化，可能取不到卡片信息
            print("WARN: 使用 CertutilDeal（旧解析路径），仅作兜底")
            from Module.CertutilDeal import CertutilDeal as Deal
        self.deals = Deal()

    def saveLogs(self):
        pass

    def readInfo(self):
        self.deals.readList()
        self.cards = self.deals.cards
        self.certs = self.deals.certs


if __name__ == "__main__":
    api = SmartCardAPI()
    api.readInfo()
    # api.makeCard(
    #     in_pin="12345678",
    #     in_adk="010203040506070801020304050607080102030405060708"
    # )
