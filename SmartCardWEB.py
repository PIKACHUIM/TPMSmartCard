import base64
import os
import pickle
import threading

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from flask import Flask, make_response, request, render_template, current_app
from flask_classful import FlaskView, route

from Module.Cryptography import Crypto
from Module.I18n import (available_languages, get_i18n, language_from_header,
                         language_label, normalize_language, translator)

app = Flask(__name__)
app.template_folder = os.path.abspath('.') + '/templates'
app.config['cert'] = dict()
app.config['lock'] = threading.Lock()


class SmartCardWeb(FlaskView):
    save_path = "Caches/PullCerts.pkl"
    route_base = '/'

    def __init__(self):
        self.apps = app
        # self.cert = app.config['cert']
        self.loadData()

    def loadData(self):
        with app.app_context():
            if not os.path.exists(SmartCardWeb.save_path):
                return None
            try:
                with open(SmartCardWeb.save_path, "rb") as save_file:
                    raw_data = save_file.read()
            except Exception as err:
                print("Load Cert Cache Error:", err)
                return None
            if len(raw_data) <= 0:
                return None
            # 缓存文件可能被写坏，反序列化失败时退化为空数据而不是启动即崩
            with current_app.config['lock']:
                try:
                    current_app.config['cert'] = pickle.loads(raw_data)
                except Exception as err:
                    print("Parse Cert Cache Error:", err)
                    current_app.config['cert'] = dict()
                return current_app.config['cert']

    def saveData(self, cert):
        with app.app_context():
            try:
                save_dir = os.path.dirname(SmartCardWeb.save_path)
                if len(save_dir) > 0 and not os.path.exists(save_dir):
                    os.makedirs(save_dir, exist_ok=True)
                # 先写临时文件再替换：写入中途失败不会留下损坏的缓存
                temp_path = SmartCardWeb.save_path + ".tmp"
                with open(temp_path, "wb") as save_file:
                    save_file.write(pickle.dumps(cert))
                os.replace(temp_path, SmartCardWeb.save_path)
                return True
            except Exception as err:
                print("Save Cert Cache Error:", err)
                return False

    @route('/get/cert')
    def getCerts(self):
        with app.app_context():
            pubkey = request.form.get('pubkey')
            with current_app.config['lock']:
                data = current_app.config['cert'].get(pubkey)
            if data is not None:
                return {
                    "flag": True,
                    "data": data
                }
            return {
                "flag": False,
                "data": None
            }

    @route('/put/cert', methods=['POST'])
    def putCerts(self):
        with app.app_context():
            client_pub_pem = request.form.get('pubkey')
            client_pfx_key = request.form.get('pfxkey')
            if client_pub_pem is None or \
                    client_pfx_key is None or \
                    'vaults' not in request.files:
                return {
                    "flag": False,
                    "data": {
                        "client_pub_pem": client_pub_pem,
                        "client_pfx_key": client_pfx_key,
                        "inputs_pfx_dat": len(request.files)
                    }
                }
            inputs_pfx_dat = request.files['vaults']
            inputs_strings = inputs_pfx_dat.read()
            # 公钥 Base64/AES 都可能因非法入参抛异常，统一兜底为失败响应
            try:
                server_pri_key = X25519PrivateKey.generate()
                server_pub_key = server_pri_key.public_key()
                client_pub_key = X25519PublicKey.from_public_bytes(
                    base64.b64decode(client_pub_pem)
                )
                encrypted_keys = server_pri_key.exchange(client_pub_key)
                server_pub_pem = server_pub_key.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw
                )
                payload = {
                    "vaults": base64.b64encode(
                        Crypto.aes_encrypt(encrypted_keys, inputs_strings)
                    ).decode(),
                    "pubkey": base64.b64encode(server_pub_pem).decode(),
                    "pfxkey": client_pfx_key,
                }
            except Exception as err:
                print("Put Cert Error:", err)
                return {
                    "flag": False,
                    "data": {
                        "error": str(err)
                    }
                }
            with current_app.config['lock']:
                current_app.config['cert'][client_pub_pem] = payload
                saved = self.saveData(current_app.config['cert'])
            if not saved:
                return {
                    "flag": False,
                    "data": {
                        "error": "cache save failed"
                    }
                }
            return {
                "flag": True,
                "data": "OK"
            }

    @route('/web/cert', methods=['GET'])
    def webCerts(self):
        """上传页：语言优先级为 URL 参数 > Cookie > 浏览器语言 > 程序当前语言。"""
        langs = available_languages()
        code = normalize_language(request.args.get('lang'))
        if code not in langs:
            code = normalize_language(request.cookies.get('lang'))
        if code not in langs:
            code = language_from_header(request.headers.get('Accept-Language'),
                                        get_i18n().language)
        page = make_response(render_template(
            'CertUpload.html',
            t=translator(code).t,
            lang=code,
            languages=[(item, language_label(item)) for item in langs],
        ))
        page.set_cookie('lang', code, max_age=365 * 24 * 3600, samesite='Lax')
        return page


SmartCardWeb.register(app)
if __name__ == '__main__':
    print(os.getcwd())
    if not os.path.exists("Caches"):
        os.mkdir("Caches")
    web = SmartCardWeb()
    os.startfile("http://127.0.0.1:1080/web/cert")
    web.apps.run(debug=True,
                 host="0.0.0.0", port=1080,
                 use_reloader=False)
