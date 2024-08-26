from files.Certificates import CER, SUB


class SmartCardDev:
    def __init__(self,
                 sc_name: str,  # 智能卡名称
                 sc_sha1: str,  # 智能卡SHA1
                 sc_sha2: str,  # 智能卡SHA2
                 sc_cert: (CER, None),  # 卡
                 sc_uuid: str = None,  # UID
                 ):
        self.sc_name = sc_name  # 智能卡名称/智能卡名称
        self.sc_sha1 = sc_sha1  # 智能卡SHA1/智能卡Flag
        self.sc_sha2 = sc_sha2  # 智能卡SHA2/智能卡Lens
        self.sc_cert = sc_cert  # 智能卡证书(Certutil用)
        self.sc_uuid = sc_uuid  # 智能卡UUID(OpenSC专属)


class SmartCardCer:
    def __init__(self,
                 sc_name: str,
                 sc_devs: str,
                 sc_exec: str,
                 sc_keys: str,
                 sc_cert: (CER, dict),
                 ):
        self.sc_name = sc_name  # 智能卡证书名称(Certutil+OpenSC二者通用)
        self.sc_devs = sc_devs  # 智能卡证书设备(Certutil)/容器ID(OpenSC)
        self.sc_exec = sc_exec  # 智能卡证书执行(Certutil)/Length(OpenSC)
        self.sc_keys = sc_keys  # 智能卡密钥哈希(Certutil)/用途ID(OpenSC)
        self.sc_cert = sc_cert  # 智能卡证书文件(Certutil)/智能卡描述信息
