import json
import locale


class AppConfigure:
    def __init__(self):
        self.conf = {}
        self.lang = "zh" if locale.getlocale()[0].find('Chinese') >= 0 else "en"

    def read(self):
        for conf_name in ["tables", "frames", "button", "labels", "global", "cncode"]:
            with open("Config/%s.json" % conf_name, "r", encoding="utf8") as conf_file:
                self.conf[conf_name] = json.loads(conf_file.read())

    def i18n(self, in_name):
        if "global" not in self.conf:
            return in_name
        temp_data = self.conf["global"]
        if self.lang not in temp_data:
            return in_name
        temp_data = temp_data[self.lang]
        if in_name not in temp_data:
            return in_name
        if type(temp_data[in_name]) is list:
            return "".join(temp_data[in_name])
        return temp_data[in_name]
