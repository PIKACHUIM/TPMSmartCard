import base64
import os
import pickle
import threading
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from flask import Flask, request, render_template, current_app
from flask_classful import FlaskView, route

from Module.Cryptography import Crypto

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
            if os.path.exists(SmartCardWeb.save_path):
                with open(SmartCardWeb.save_path, "rb") as save_file:
                    current_app.config['lock'].acquire()
                    current_app.config['cert'] = pickle.loads(save_file.read())
                    current_app.config['lock'].release()
                    # self.cert = pickle.loads(save_file.read())

    def saveData(self, cert):
        with app.app_context():
            with open(SmartCardWeb.save_path, "wb") as save_file:
                save_file.write(pickle.dumps(cert))

    @route('/get/cert')
    def getCerts(self):
        with app.app_context():
            pubkey = request.form.get('pubkey')
            current_app.config['lock'].acquire()
            if pubkey in current_app.config['cert']:
                current_app.config['lock'].release()
                return {
                    "flag": True,
                    "data": current_app.config['cert'][pubkey]
                }
            else:
                current_app.config['lock'].release()
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
            print(encrypted_keys)
            current_app.config['lock'].acquire()
            current_app.config['cert'][client_pub_pem] = {
                "vaults": base64.b64encode(
                    Crypto.aes_encrypt(encrypted_keys, inputs_strings)
                ).decode(),
                "pubkey": base64.b64encode(server_pub_pem).decode(),
                "pfxkey": client_pfx_key,
            }
            self.saveData(current_app.config['cert'])
            current_app.config['lock'].release()
            return {
                "flag": True,
                "data": "OK"
            }

    @route('/web/cert', methods=['GET'])
    def webCerts(self):
        return render_template('CertUpload.html')


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
