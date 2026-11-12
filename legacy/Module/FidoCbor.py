# -*- coding: utf-8 -*-
"""极简 CBOR 编解码（CTAP2 需要的那一小部分）。

为什么不用现成库：CTAP2 只用到 uint / negint / bytes / text / array / map /
bool / null 七种主类型，手写一个一百多行的实现即可，既避免给 cx_Freeze /
Nuitka 打包引入额外依赖，也能保证编码顺序完全可控（CTAP2 要求 map 键按规范
排序，部分平台对非规范 CBOR 会直接报错）。

主要接口::

    encode(obj) -> bytes
    decode(data) -> object          # 必须恰好消费完 data
    decode_from(data, offset) -> (obj, new_offset)
"""


class CborError(ValueError):
    """CBOR 数据格式错误。"""


# --------------------------------------------------------------------------- #
# 编码
# --------------------------------------------------------------------------- #
def _encode_head(major, value, out):
    if value < 24:
        out.append((major << 5) | value)
    elif value < 0x100:
        out.append((major << 5) | 24)
        out.append(value)
    elif value < 0x10000:
        out.append((major << 5) | 25)
        out += value.to_bytes(2, "big")
    elif value < 0x100000000:
        out.append((major << 5) | 26)
        out += value.to_bytes(4, "big")
    else:
        out.append((major << 5) | 27)
        out += value.to_bytes(8, "big")


def encode(obj):
    """把 Python 对象编码成 CBOR 字节串。"""
    out = bytearray()
    _encode_into(obj, out)
    return bytes(out)


def _encode_into(obj, out):
    if obj is True:
        out.append(0xF5)
        return
    if obj is False:
        out.append(0xF4)
        return
    if obj is None:
        out.append(0xF6)
        return
    if isinstance(obj, int):
        if obj >= 0:
            _encode_head(0, obj, out)
        else:
            _encode_head(1, -obj - 1, out)
        return
    if isinstance(obj, (bytes, bytearray)):
        _encode_head(2, len(obj), out)
        out += bytes(obj)
        return
    if isinstance(obj, str):
        raw = obj.encode("utf-8")
        _encode_head(3, len(raw), out)
        out += raw
        return
    if isinstance(obj, (list, tuple)):
        _encode_head(4, len(obj), out)
        for item in obj:
            _encode_into(item, out)
        return
    if isinstance(obj, dict):
        _encode_head(5, len(obj), out)
        # CTAP2 要求 map 键按「编码后的字节串」长度优先、再按字典序排列
        pairs = [(_encode_key(key), key) for key in obj]
        pairs.sort(key=lambda pair: (len(pair[0]), pair[0]))
        for key_raw, key in pairs:
            out += key_raw
            _encode_into(obj[key], out)
        return
    raise CborError("不支持的类型: %r" % (type(obj),))


def _encode_key(key):
    out = bytearray()
    _encode_into(key, out)
    return bytes(out)


# --------------------------------------------------------------------------- #
# 解码
# --------------------------------------------------------------------------- #
def decode(data):
    """解码一段完整的 CBOR 数据（不允许尾随字节）。"""
    value, offset = decode_from(data, 0)
    if offset != len(data):
        raise CborError("CBOR 数据有多余字节（%d/%d）" % (offset, len(data)))
    return value


def decode_from(data, offset=0):
    """从 ``offset`` 开始解码一个对象，返回 ``(对象, 新的偏移)``。"""
    data = bytes(data)
    if offset >= len(data):
        raise CborError("CBOR 数据不完整")
    initial = data[offset]
    offset += 1
    major = initial >> 5
    info = initial & 0x1F

    if major == 7:
        if info == 20:
            return False, offset
        if info == 21:
            return True, offset
        if info in (22, 23):
            return None, offset
        if info == 25:      # half float
            raw = int.from_bytes(data[offset:offset + 2], "big")
            return _half_to_float(raw), offset + 2
        if info == 26:
            return _bytes_to_float(data[offset:offset + 4]), offset + 4
        if info == 27:
            return _bytes_to_float(data[offset:offset + 8]), offset + 8
        raise CborError("不支持的简单值: %d" % info)

    if info < 24:
        value = info
    elif info == 24:
        value = data[offset]
        offset += 1
    elif info == 25:
        value = int.from_bytes(data[offset:offset + 2], "big")
        offset += 2
    elif info == 26:
        value = int.from_bytes(data[offset:offset + 4], "big")
        offset += 4
    elif info == 27:
        value = int.from_bytes(data[offset:offset + 8], "big")
        offset += 8
    else:
        raise CborError("非法的长度字段: %d" % info)

    if major == 0:
        return value, offset
    if major == 1:
        return -value - 1, offset
    if major == 2:
        return data[offset:offset + value], offset + value
    if major == 3:
        return data[offset:offset + value].decode("utf-8", "replace"), offset + value
    if major == 4:
        items = []
        for _ in range(value):
            item, offset = decode_from(data, offset)
            items.append(item)
        return items, offset
    if major == 5:
        result = {}
        for _ in range(value):
            key, offset = decode_from(data, offset)
            item, offset = decode_from(data, offset)
            result[key] = item
        return result, offset
    if major == 6:
        # 标签：CTAP2 不使用语义标签，读出标签值后继续解内容
        item, offset = decode_from(data, offset)
        return item, offset
    raise CborError("不支持的 CBOR 主类型: %d" % major)


def _bytes_to_float(raw):
    import struct
    if len(raw) == 4:
        return struct.unpack(">f", raw)[0]
    if len(raw) == 8:
        return struct.unpack(">d", raw)[0]
    raise CborError("浮点长度不对: %d" % len(raw))


def _half_to_float(raw):
    import struct
    sign = (raw >> 15) & 0x1
    exponent = (raw >> 10) & 0x1F
    fraction = raw & 0x3FF
    if exponent == 0:
        value = fraction / 1024.0 * (2.0 ** -14)
    elif exponent == 31:
        value = float("inf") if fraction == 0 else float("nan")
    else:
        value = (1 + fraction / 1024.0) * (2.0 ** (exponent - 15))
    return -value if sign else value


if __name__ == "__main__":
    samples = [
        0, 23, 24, 255, 65535, 4294967296, -1, -24, -25,
        b"", b"\x01\x02", "", "hello", [], [1, 2, 3], {}, {"a": 1, 1: b"x"},
        True, False, None, {"a": [True, None, -7]},
    ]
    for sample in samples:
        raw = encode(sample)
        back = decode(raw)
        assert back == sample, (sample, back, raw.hex())
        print("%-24r -> %s" % (sample, raw.hex()))
    print("CBOR 自检通过")
