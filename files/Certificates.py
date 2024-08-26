class CertSubjects:
    def __init__(self, in_text=""):
        self.OwnerCountryCode = ""
        self.OwnerCommonNames = ""
        self.OwnerDescription = ""
        self.OwnerMailAddress = ""
        self.OrganizationUnit = ""
        self.OrganizationName = ""
        if len(in_text) > 0:
            self.parseText(in_text)

    def parseText(self, in_text):
        in_text = in_text.split(",")


class CertDataInfo:
    def __init__(self,
                 cr_uuid,  # 证书序列号
                 cr_from,  # 证书颁发者
                 cr_user,  # 证书使用者
                 cr_open,  # 证书生效于
                 cr_stop,  # 证书失效于
                 cr_hash,  # 证书的SHA1
                 is_a_ca,  # 是否CA证书
                 ):
        self.cr_uuid = cr_uuid
        self.cr_owns = cr_from
        self.cr_user = cr_user
        self.cr_open = cr_open
        self.cr_open = cr_open
        self.cr_stop = cr_stop
        self.cr_hash = cr_hash
        self.is_a_ca = is_a_ca
        self.cr_lens = 0  # 密钥长度

SUB = CertSubjects
CER = CertDataInfo
