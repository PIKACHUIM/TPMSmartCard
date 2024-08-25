from Certificates import CER, SUB


class SmartCardDev:
    def __init__(self,
                 sc_name: str,  # 智能卡名称
                 sc_sha1: str,  # 智能卡SHA1
                 sc_sha2: str,  # 智能卡SHA2
                 sc_cert: CER,  # 智能卡证书
                 ):
        self.sc_name = sc_name
        self.sc_sha1 = sc_sha1
        self.sc_sha2 = sc_sha2
        self.sc_cert = sc_cert


class SmartCardCer:
    def __init__(self,
                 sc_name: str,
                 sc_devs: str,
                 sc_exec: str,
                 sc_keys: str,
                 sc_cert: CER,
                 ):
        self.sc_name = sc_name
        self.sc_devs = sc_devs
        self.sc_exec = sc_exec
        self.sc_keys = sc_keys
        self.sc_cert = sc_cert
