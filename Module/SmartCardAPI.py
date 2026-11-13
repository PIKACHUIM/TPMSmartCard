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

    def readerIndex(self, card_name):
        """按读卡器名取它在 pcsc 列表中的编号（``--reader N`` 的 N）；不支持时返回 None。"""
        helper = getattr(self.deals, "readerIndex", None)
        if helper is None:
            return None
        return helper(card_name)

    def readerIndexFor(self, card_name):
        """取读卡器编号：先用当前列表重新解析，失败才回退到扫描时记下的值。

        同一台机器上同时有多张虚拟卡时，**pcsc 编号会随卡片增删而变化**
        （例如删掉一张卡后，编号 2 的卡可能排到 1 号位），
        因此所有 ``--reader N`` 都必须是实际编号，不能拿卡片编号去猜。
        """
        idx = self.readerIndex(card_name)
        if idx is not None:
            return idx
        card = self.cards.get(card_name)
        if card is None:
            return None
        return getattr(card, "sc_reader_idx", None)


if __name__ == "__main__":
    api = SmartCardAPI()
    api.readInfo()
    # api.makeCard(
    #     in_pin="12345678",
    #     in_adk="010203040506070801020304050607080102030405060708"
    # )
