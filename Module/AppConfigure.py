import json

from Module.I18n import get_i18n


class AppConfigure:
    """子界面（CertImport 等）的配置与文案入口。

    界面文案统一由 Module.I18n 提供（语言包位于 Config/locales），
    本类只负责读取界面布局配置，语言状态与主程序共享同一份。
    """

    def __init__(self):
        self.conf = {}
        self.i18n_data = get_i18n()
        self.lang = self.i18n_data.language

    def read(self):
        for conf_name in ["tables", "frames", "button", "labels", "cncode"]:
            with open("Config/%s.json" % conf_name, "r", encoding="utf8") as conf_file:
                self.conf[conf_name] = json.loads(conf_file.read())

    @property
    def wide(self):
        """当前语言是否需要更宽的行控件（拉丁/西里尔字母比汉字占位更宽）。"""
        return self.i18n_data.is_wide()

    def i18n(self, in_name, *args):
        if args:
            return self.i18n_data.tp(in_name, *args)
        return self.i18n_data.t(in_name)

    def load_status(self):
        pass
