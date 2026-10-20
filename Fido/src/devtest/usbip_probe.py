# -*- coding: utf-8 -*-
"""USB/IP 设备端自检脚本（开发/排障用，不随安装包分发）。

用法::

    python usbip_probe.py            # 默认连 127.0.0.1:3240
    python usbip_probe.py 127.0.0.1 3240

依次验证：OP_REQ_DEVLIST / OP_REQ_IMPORT / 控制传输（设备描述符、配置描述符、
HID 报告描述符），用于确认 Fido/fido-go.exe 的虚拟 USB 设备是否正常。
"""
import socket
import struct
import sys

OP_REQ_DEVLIST = 0x8005
OP_REQ_IMPORT = 0x8003
CMD_SUBMIT = 0x00000001
RET_SUBMIT = 0x00000003


def enum_devices(host, port):
    sock = socket.create_connection((host, port), timeout=5)
    sock.sendall(struct.pack(">HHI", 0x1111, OP_REQ_DEVLIST, 0))
    head = recv_exact(sock, 12)
    version, code, status = struct.unpack(">HHI", head[:8])
    count = struct.unpack(">I", head[8:12])[0]
    devices = []
    for _ in range(count):
        raw = recv_exact(sock, 315)
        busid = raw[256:288].split(b"\x00")[0].decode("ascii", "replace")
        busnum, devnum, speed, vid, pid = struct.unpack(">IIIII", raw[288:308])
        devices.append({"busid": busid, "busnum": busnum, "devnum": devnum,
                        "speed": speed, "vid": vid, "pid": pid,
                        "iface_class": raw[312]})
    sock.close()
    return version, code, status, devices


def import_device(host, port, busid):
    sock = socket.create_connection((host, port), timeout=5)
    sock.sendall(struct.pack(">HHI", 0x1111, OP_REQ_IMPORT, 0))
    sock.sendall(busid.encode("ascii").ljust(32, b"\x00"))
    head = recv_exact(sock, 8)
    version, code, status = struct.unpack(">HHI", head)
    if status == 0:
        recv_exact(sock, 312)
    return sock, status


def recv_exact(sock, length):
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise RuntimeError("连接被关闭（已收到 %d/%d 字节）" % (len(data), length))
        data += chunk
    return data


def control_in(sock, setup, seq):
    """发送一次控制读传输（ep0，方向 IN），返回实际数据。"""
    header = struct.pack(">IIIIIIIIII", CMD_SUBMIT, seq, 1, 1, 0, 0,
                         setup[6] | (setup[7] << 8), 0, 0, 0)
    sock.sendall(header + bytes(setup))
    reply = struct.unpack(">IIIIIIIIII8s", recv_exact(sock, 48))
    command, _, _, _, _, status, actual = reply[0], reply[1], reply[2], reply[3], reply[4], reply[5], reply[6]
    if command != RET_SUBMIT:
        raise RuntimeError("意外的响应命令 0x%08X" % command)
    data = recv_exact(sock, actual) if actual else b""
    return status, data


def main(argv):
    host = argv[1] if len(argv) > 1 else "127.0.0.1"
    port = int(argv[2]) if len(argv) > 2 else 3240

    version, code, status, devices = enum_devices(host, port)
    print("DEVLIST: version=0x%04X code=0x%04X status=%d devices=%d"
          % (version, code, status, len(devices)))
    for item in devices:
        print("  busid=%s busnum=%d devnum=%d vid=%04X pid=%04X 接口类=0x%02X"
              % (item["busid"], item["busnum"], item["devnum"], item["vid"],
                 item["pid"], item["iface_class"]))
    if not devices:
        print("没有导出任何设备")
        return 1

    sock, status = import_device(host, port, devices[0]["busid"])
    print("IMPORT: status=%d" % status)
    if status != 0:
        return 1

    try:
        _, descriptor = control_in(sock, [0x80, 0x06, 0x00, 0x01, 0x00, 0x00, 18, 0], 1)
        print("设备描述符: %s" % descriptor.hex())
        if len(descriptor) >= 18:
            print("  bLength=%d bDescriptorType=0x%02X USB版本=%d.%02d 类=0x%02X 端点0包长=%d"
                  % (descriptor[0], descriptor[1], descriptor[2], descriptor[3],
                     descriptor[4], descriptor[7]))
        _, config = control_in(sock, [0x80, 0x06, 0x00, 0x02, 0x00, 0x00, 0x22, 0], 2)
        print("配置描述符: %s" % config.hex())
        _, report = control_in(sock, [0x81, 0x06, 0x00, 0x22, 0x00, 0x00, 0x22, 0], 3)
        print("HID 报告描述符(%d 字节): %s" % (len(report), report.hex()))
        if report:
            print("  Usage Page = 0x%02X%02X（FIDO 需要 0xF1D0）" % (report[2], report[1]))
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
