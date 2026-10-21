# -*- coding: utf-8 -*-
"""一次性脚本：补「设备端程序」状态行文案。"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES = os.path.join(ROOT, "Config", "locales")

TEXTS = {
    "zh-Hans": "设备端程序：",
    "zh-Hant": "裝置端程式：",
    "en": "Device program:",
    "ja": "デバイス側プログラム:",
    "ko": "장치 프로그램:",
    "fr": "Programme du périphérique :",
    "de": "Geräteprogramm:",
    "es": "Programa del dispositivo:",
    "it": "Programma del dispositivo:",
    "pt": "Programa do dispositivo:",
    "ru": "Программа устройства:",
}


def main():
    for code, value in TEXTS.items():
        path = os.path.join(LOCALES, "%s.json" % code)
        with io.open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        added = 0
        if "msg_fido_runtime" not in data:
            data["msg_fido_runtime"] = value
            added = 1
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print("%s: 新增 %d 条，共 %d 条" % (code, added, len(data)))


if __name__ == "__main__":
    main()
