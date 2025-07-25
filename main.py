
import os
import requests
import json
import time
from datetime import datetime, timedelta
from flask import Flask, request

app = Flask(__name__)

# Variáveis de ambiente (ou substitua diretamente pelas strings, se preferir)
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", "5510376630479325")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "jlR4As2x8uFY3RTpysLpuPhzC9yM9d35")
ML_REDIRECT_URI = os.getenv("ML_REDIRECT_URI", "https://bot-mercadolivre-dettech-v2.onrender.com/callback")

# Simulação de banco de dados em memória
db = {"access_token": None, "refresh_token": None, "token_expires_at": None}

@app.route('/')
def index():
    return '<a href="/auth">Autenticar com Mercado Livre</a>'

@app.route('/auth')
def auth():
    auth_url = "https://auth.mercadolivre.com.br/authorization?response_type=code&client_id={}&redirect_uri={}".format(ML_CLIENT_ID, ML_REDIRECT_URI)
    return '<a href="{}">Clique aqui para autorizar o aplicativo</a>'.format(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return 'Erro: código de autorização não encontrado.', 400

    token_url = 'https://api.mercadolibre.com/oauth/token'
    payload = {
        'grant_type': 'authorization_code',
        'client_id': ML_CLIENT_ID,
        'client_secret': ML_CLIENT_SECRET,
        'code': code,
        'redirect_uri': ML_REDIRECT_URI
    }

    response = requests.post(token_url, data=payload)
    if response.status_code == 200:
        data = response.json()
        db["access_token"] = data['access_token']
        db["refresh_token"] = data['refresh_token']
        db["token_expires_at"] = datetime.utcnow() + timedelta(seconds=data['expires_in'])
        return "<h2>✅ Autenticado com sucesso!</h2><p><strong>Access Token:</strong><br>{}</p><p><strong>Refresh Token:</strong><br>{}</p><p>Copie esses tokens e adicione no seu script principal para ativar o bot.</p>".format(data['access_token'], data['refresh_token'])
    else:
        return "❌ Erro ao obter tokens: {}".format(response.text), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
