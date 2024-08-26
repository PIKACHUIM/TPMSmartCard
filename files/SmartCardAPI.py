import os
import time
from winpty import PtyProcess


class SmartCardAPI:
    def __init__(self, use_opensc=True):
        self.cards = {}
        self.certs = {}
        if use_opensc:
            from files.OpenSCDealer import OpenSCDealer as Deal
        else:
            from files.CertutilDeal import CertutilDeal as Deal
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
