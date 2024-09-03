import OpenSSL.crypto
from dateutil import parser
from Module.Certificates import CER


class SmartCardDev:
    def __init__(self,
                 card_id: str,  # 智能卡编号
                 sc_name: str,  # 智能卡名称
                 sc_sha1: str,  # 智能卡SHA1
                 sc_sha2: str,  # 智能卡SHA2
                 sc_cert: (CER, None),  # 卡
                 sc_uuid: str = "00",  # UID
                 sc_type: str = None,  # KEY
                 ):
        self.sc_name = sc_name  # 智能卡名称/智能卡名称
        self.sc_sha1 = sc_sha1  # 智能卡SHA1/智能卡Flag
        self.sc_sha2 = sc_sha2  # 智能卡SHA2/智能卡Lens
        self.sc_cert = sc_cert  # 智能卡证书(Certutil用)
        self.sc_uuid = sc_uuid  # 智能卡UUID(OpenSC专属)
        self.card_id = card_id
        self.sc_type = sc_type  # 支持的算法(OpenSC专属)
        self.sc_path = "ROOT\\SMARTCARDREADER\\%04d" % int(self.card_id)


class SmartCardCer:
    def __init__(self,
                 sc_name: str,
                 sc_devs: str,
                 sc_exec: str,
                 sc_keys: str,
                 sc_cert: (CER, dict, str),
                 ):
        self.sc_name = sc_name  # 智能卡证书名称(Certutil+OpenSC二者通用)
        self.sc_devs = sc_devs  # 智能卡证书设备(Certutil)/容器ID(OpenSC)
        self.sc_exec = sc_exec  # 智能卡证书执行(Certutil)/Length(OpenSC)
        self.sc_keys = sc_keys  # 智能卡密钥哈希(Certutil)/用途ID(OpenSC)
        self.sc_cert = sc_cert  # 智能卡证书文件(Certutil)/智能卡描述信息
        self.sc_text = ""
        if type(self.sc_cert) is str:
            self.sc_text = sc_cert
            self.parseCert()

    def parseCert(self):
        cert_content: OpenSSL.crypto.X509 = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, self.sc_cert)
        cert_issuers = cert_content.get_issuer()
        cert_subject = cert_content.get_subject()
        cert_info_ls = {
            "version": cert_content.get_version() + 1,
            "serial_number": hex(cert_content.get_serial_number()),
            "signature_algorithm": cert_content.get_signature_algorithm().decode("UTF-8"),
            "common_name": cert_subject.commonName,
            "start_time": parser.parse(cert_content.get_notBefore().decode("UTF-8")).strftime('%Y-%m-%d %H:%M'),
            "end_time": parser.parse(cert_content.get_notAfter().decode("UTF-8")).strftime('%Y-%m-%d %H:%M'),
            "has_expired": cert_content.has_expired(),
            "pubkey": OpenSSL.crypto.dump_publickey(OpenSSL.crypto.FILETYPE_PEM, cert_content.get_pubkey()),
            "pubkey_len": cert_content.get_pubkey().bits(),
            "pubkey_type": cert_content.get_pubkey().type(),
            "extension_count": cert_content.get_extension_count(),
            "issuer_info": {i[0].decode(): i[1].decode() for i in cert_issuers.get_components()},
            "subject_info": {i[0].decode(): i[1].decode() for i in cert_subject.get_components()},
            "extension_data": {
                cert_content.get_extension(i).get_short_name().decode(): cert_content.get_extension(i) \
                for i in range(cert_content.get_extension_count())
            },
            "extension_text": [
                cert_content.get_extension(i) for i in range(cert_content.get_extension_count())
            ],
            "cert_sha1": cert_content.digest("sha1").decode("utf-8"),
        }
        # print(cert_info_ls)
        self.sc_cert = CER(cert_info_ls)
