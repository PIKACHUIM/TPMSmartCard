import OpenSSL.crypto


class CertDataInfo:
    """
        {
            'C': 'XX',
            'O': '******************',
            'OU': '******************',
            'CN': '******************',
            'name': '******************',
            'description': '******************',
            'businessCategory': '******************',
            'jurisdictionC': 'XX'
        }
        """

    def __init__(self,
                 _certs_=None
                 ):
        self.CRLsDPoint = None
        self.AuthAccess = None
        self.SubsHashID = None
        self.MainHashID = None
        self.SubsOwners = None
        self.SubsUsages = None
        self.MainUsages = None
        self.CertPolicy = None
        self.TextExtend = None
        self.SerialNums = None
        self.CertExtend = None
        self.Algorithms = None
        self.CommonName = None
        self.IssuedDate = None
        self.ExpireDate = None

        self.pub_key_al = None
        self.pub_origin = None
        self.pub_length = None

        self.IssuerInfo = None
        self.OwnersInfo = None

        self.is_expired = None
        self.is_ca_cert = None
        self._certs_ = _certs_
        if _certs_ is not None:
            self.parseCert()

    @staticmethod
    def KeysUsages(in_data):
        # 定义密钥用途的映射
        key_usage = in_data
        usages = {
            'digitalSignature': 0x80,
            'contentCommitment': 0x40,
            'keyEncipherment': 0x20,
            'dataEncipherment': 0x10,
            'keyAgreement': 0x08,
            'keyCertSign': 0x04,
            'cRLSign': 0x02,
            'encipherOnly': 0x01,
            'decipherOnly': 0x80,  # 注意：这里的值与digitalSignature相同，需要根据实际情况调整
        }
        enabled_usages = [name for name, bit in usages.items() if key_usage & bit]
        return enabled_usages

    def certExtend(self, in_name):
        if in_name in self.CertExtend:
            return self.CertExtend[in_name]
        return b""

    def textExtend(self, in_name):
        for ext_line in self.TextExtend:
            ext_line = str(ext_line)
            if ext_line.find(in_name) == 0:
                return ext_line[len(in_name) + 1:]
        return "Unknown"

    def parseCert(self):
        algorithms_maps = {
            "6": "RSA"
        }
        self.CommonName = self._certs_['common_name'] if 'common_name' in self._certs_ else "Unknown"
        self.SerialNums = str(self._certs_['serial_number'])[2:] if 'serial_number' in self._certs_ else "Unknown"
        self.Algorithms = self._certs_['signature_algorithm'] if 'signature_algorithm' in self._certs_ else "Unknown"
        self.IssuedDate = self._certs_['start_time'] if 'start_time' in self._certs_ else "Unknown"
        self.ExpireDate = self._certs_['end_time'] if 'end_time' in self._certs_ else "Unknown"

        self.pub_length = str(self._certs_['pubkey_len']) if 'pubkey_len' in self._certs_ else "Unknown"
        self.pub_origin = str(self._certs_['pubkey']) if 'pubkey' in self._certs_ else "Unknown"
        self.pub_key_al = str(self._certs_['pubkey_type']) if 'pubkey_type' in self._certs_ else "Unknown"
        self.pub_key_al = algorithms_maps[self.pub_key_al] if self.pub_key_al in algorithms_maps else self.pub_key_al
        self.IssuerInfo = self._certs_['issuer_info'] if 'issuer_info' in self._certs_ else "Unknown"
        self.OwnersInfo = self._certs_['subject_info'] if 'subject_info' in self._certs_ else "Unknown"

        self.CertExtend = self._certs_['extension_data'] if 'extension_data' in self._certs_ else []
        self.TextExtend = self._certs_['extension_text'] if 'extension_text' in self._certs_ else []

        self.is_expired = self._certs_['has_expired'] if 'has_expired' in self._certs_ else "Unknown"
        self.is_ca_cert = str(self.certExtend('basicConstraints')).split(":")[-1]

        self.CertPolicy = self.certExtend('certificatePolicies')
        self.MainUsages = self.certExtend('keyUsage')
        self.MainHashID = self.certExtend('authorityKeyIdentifier')
        self.SubsUsages = self.certExtend('extendedKeyUsage')
        self.SubsOwners = self.certExtend('subjectAltName')
        self.SubsHashID = self.certExtend('subjectKeyIdentifier')
        self.AuthAccess = self.certExtend('authorityInfoAccess')
        self.CRLsDPoint = self.certExtend('crlDistributionPoints')


CER = CertDataInfo
