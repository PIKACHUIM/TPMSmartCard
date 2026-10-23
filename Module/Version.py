# -*- coding: utf-8 -*-
"""版本与仓库信息（单一来源）。

* ``VERSION`` 同时用于「关于本工具」显示与「版本更新检查」比对，
  打包时可由环境变量 ``TPMSMART_VERSION`` 覆盖（见 BuildPackage.py）。
* 版本比较只取其中的数字段，因此 ``v1.5`` 与 ``1.5.0`` 视为同一版本。
"""

import os
import re

# 工具版本（与 GitHub Release 的 Tag 对应）
VERSION = os.environ.get("TPMSMART_VERSION") or "1.7.0"

# 项目仓库信息
GITHUB_OWNER = "PIKACHUIM"
GITHUB_REPO = "TPMSmartCard"
GITHUB_URL = "https://github.com/%s/%s" % (GITHUB_OWNER, GITHUB_REPO)
RELEASES_URL = GITHUB_URL + "/releases"
LATEST_RELEASE_URL = RELEASES_URL + "/latest"
RELEASE_API_URL = ("https://api.github.com/repos/%s/%s/releases/latest"
                   % (GITHUB_OWNER, GITHUB_REPO))
USER_AGENT = "TPMSmartCard-Updater"

# 关于信息
PRODUCT = "TPM Virtual Smart Card Manager"
AUTHOR = "Pikachu Ren"
LICENSE = "The MIT License"


def version_tuple(text):
    """把任意版本字符串转成可比较的数字元组（不足四位补 0）。"""
    numbers = [int(item) for item in re.findall(r"\d+", str(text or ""))[:4]]
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers)


def compare_versions(left, right):
    """比较两个版本：返回 1 表示 left 更新，0 表示相同，-1 表示更旧。"""
    left_tuple, right_tuple = version_tuple(left), version_tuple(right)
    return (left_tuple > right_tuple) - (left_tuple < right_tuple)


def normalize_tag(tag):
    """去掉 Tag 前缀（如 ``v1.5`` -> ``1.5``），找不到数字段时原样返回。"""
    text = str(tag or "").strip()
    match = re.search(r"\d+(?:\.\d+)*", text)
    return match.group(0) if match else text
