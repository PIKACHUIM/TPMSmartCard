import re
import subprocess
import traceback

from Module import Paths
from Module.SmartCardObj import SmartCardDev
from Module.SmartCardObj import SmartCardCer


class OpenSCDealer:
    # opensc-tool --serial 成功时输出「十六进制字节 + ASCII 预览」，例如
    #   93 38 FB 1C ... 54 .8.....C.sm}..&T
    # 失败时第一行是报错文本（如 Reader "2" not found (2 reader(s) detected)），
    # 所以只认开头连续的十六进制字节，绝不把报错当序列号。
    SERIAL_RE = re.compile(r"^\s*((?:[0-9A-Fa-f]{2}\s+)+)")

    def __init__(self):
        self.cards = {}
        self.certs = {}

    @staticmethod
    def openText(in_comm, in_tool="pkcs15-tool"):
        # 用绝对路径：FIDO2 后端在后台线程里也会调用这里，工作目录不一定还是
        # 程序根目录（例如从计划任务/其它目录启动时）。
        command = '"%s" %s' % (Paths.resource("OpenSC", "%s.exe" % in_tool), in_comm)
        process = subprocess.run(command, shell=True, text=True, capture_output=True)
        results = (process.stderr + process.stdout).replace("\t", "").split("\n")
        # print(results)
        return results

    @staticmethod
    # 把 "键 : 值" 行解析为字典，无冒号的行一律跳过（避免解析外部输出时越界）
    def readFields(in_lines, in_start=1, in_end=10):
        fields = dict()
        for line in in_lines[in_start:in_end]:
            if len(line) <= 0 or ": " not in line:
                continue
            name, _, value = line.partition(": ")
            fields[name.replace(" ", "")] = value
        return fields

    def readCert(self, results, details, in_card=None):
        if len(results) <= 0 or "[" not in results[0]:
            return None
        cr_name = results[0].split("[")[1].replace("]", "")
        key_parts = results[0].split(" ")
        if len(key_parts) <= 1:
            return None
        results = OpenSCDealer.readFields(results, 1, 11)
        if 'ModLength' not in results:
            return None
        try:
            self.certs[cr_name] = SmartCardCer(
                cr_name, results.get('MD:guid', "Unknown"),
                key_parts[1] + " " + results['ModLength'],
                results.get('Usage', "Unknown"),
                None if details.find("not found") >= 0 else details,
                in_card
            )
        except Exception as err:
            print("Read Cert Error:", err)
            traceback.print_exc()
        # print(results)

    def readCard(self, results, card_name, reader_idx=None):
        """解析一张卡的详情并登记到 self.cards。

        ``reader_idx`` 是这张卡在读卡器列表中的位置（``--reader N`` 用的 N），
        由 :meth:`readList` 传入。它**不等于**卡片编号（卡 0002 可能排在 1 号位），
        所以不能从读卡器名末尾的数字去猜——卡片增删之后那样猜会报
        ``reader "2" not found``。
        """
        results = OpenSCDealer.readFields(results, 1, 10)
        if card_name in self.cards:
            return
        if card_name.find('Microsoft Virtual Smart Card') < 0:
            return
        if 'Flags' not in results or 'Length' not in results:
            return
        card_id = card_name.split(" ")[-1]
        if not card_id.isdigit():
            return
        if reader_idx is None:
            reader_idx = OpenSCDealer.readerIndex(card_name)
        self.cards[card_name] = SmartCardDev(
            "%04d" % int(card_id),
            card_name,
            results['Flags'],
            results['Length'],
            None,
            # results['ID'],
            OpenSCDealer.readSerial(reader_idx),
            None,
            reader_idx,
        )
        # print(results)

    @staticmethod
    def readSerial(reader_idx):
        """读卡序列号：只取输出开头的十六进制字节，取不到返回空串。

        旧实现直接取第一行去掉空格，一旦 ``--reader`` 编号不对，就会把
        ``Reader "2" not found`` 这类报错原样显示在「卡片编号」里。
        """
        if reader_idx is None:
            return ""
        try:
            outputs = OpenSCDealer.openText("--reader %d --serial" % reader_idx, "OpenSC-tool")
        except Exception as err:
            print("Read Serial Error:", err)
            return ""
        for line in outputs:
            matched = OpenSCDealer.SERIAL_RE.match(str(line))
            if matched:
                return matched.group(1).replace(" ", "")[:32].lower()
        return ""

    @staticmethod
    def readerIndex(card_name):
        """按读卡器名取它在 pcsc 列表中的编号（``--reader N`` 的 N）；找不到返回 None。"""
        try:
            for line in OpenSCDealer.openText("--list-readers", "OpenSC-tool"):
                parts = str(line).split()
                # 形如：0    Yes    Microsoft Virtual Smart Card 2
                if len(parts) < 3 or not parts[0].isdigit():
                    continue
                if " ".join(parts[2:]) == card_name:
                    return int(parts[0])
        except Exception as err:
            print("Read Reader Index Error:", err)
        return None

    def readFile(self, in_data):
        pass

    def readList(self):
        self.cards = {}
        self.certs = {}
        try:
            # 获取所有的卡片 ==========================================
            card_all = OpenSCDealer.openText(  # 获取系统上智能卡列表
                "--list-readers", "OpenSC-tool")[2:]
            # 预处理卡片信息 ==========================================
            card_all = [i.split("   ") for i in card_all if len(i) > 0]
            card_all = [[j for j in i if len(j) > 0] for i in card_all]
            card_all = {i[0]: i[2][1:] for i in card_all if len(i) > 2}
            # 遍历所有的卡片 ==========================================
            for card_uuid in card_all:
                if not str(card_uuid).strip().isdigit():
                    continue
                try:
                    results = OpenSCDealer.openText("--list-pins %s" % (
                            "--reader %d" % int(card_uuid)))
                    for nums in range(0, len(results)):
                        if results[nums].find("PIN [UserPIN]") >= 0:
                            # card_uuid 就是读卡器在列表中的编号，必须传下去：
                            # 卡片编号与 pcsc 编号并不相等（删过卡后会错位）
                            self.readCard(results[nums + 1:nums + 10],
                                          card_all[card_uuid], int(card_uuid))
                    results = OpenSCDealer.openText("--list-keys %s" % (
                            "--reader %d" % int(card_uuid)))
                    count = -1
                    for nums in range(0, len(results)):
                        if results[nums].find("Private") >= 0:
                            count += 1
                            details = OpenSCDealer.openText(
                                "--read-certificate %d %s" % (
                                    int(count), "--reader %d" % int(card_uuid)))
                            # 记下证书所属读卡器名（与 self.cards 的键一致），供界面按卡过滤
                            self.readCert(results[nums:nums + 11], "\n".join(details),
                                          card_all[card_uuid])
                except Exception as err:
                    print("Read Card Error:", err)
                    traceback.print_exc()
                    continue
        except Exception as err:
            print("Read List Error:", err)
            traceback.print_exc()
        return self.cards
