import sqlite3
import json
import requests
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string, redirect

app = Flask(__name__)

ML_CLIENT_ID = "5510376630479325"
ML_CLIENT_SECRET = "jlR4As2x8uFY3RTpysLpuPhzC9yM9d35"
REDIRECT_URI = "https://bot-mercadolivre-dettech-v2.onrender.com/callback"

access_token_global = None

@app.route("/")
def home():
    return '''
    <h1>Bot Mercado Livre</h1>
    <p><a href="/auth">🔐 Conectar com Mercado Livre</a></p>
    '''

@app.route("/auth")
def auth():
    return redirect(
        f"https://auth.mercadolivre.com.br/authorization?response_type=code&client_id={ML_CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    )

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "❌ Código de autorização não recebido."

    payload = {
        "grant_type": "authorization_code",
        "client_id": ML_CLIENT_ID,
        "client_secret": ML_CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post("https://api.mercadolibre.com/oauth/token", data=payload, headers=headers)

    if response.status_code == 200:
        tokens = response.json()
        global access_token_global
        access_token_global = tokens["access_token"]
        return f'''
        <h2>✅ Autenticado com sucesso!</h2>
        <p><strong>Access Token:</strong></p>
        <pre>{tokens["access_token"]}</pre>
        <p><strong>Refresh Token:</strong></p>
        <pre>{tokens["refresh_token"]}</pre>
        <p>Copie esses tokens e adicione no seu script principal para ativar o bot.</p>
        '''
    else:
        return f"❌ Erro ao obter tokens: {response.text}"

if __name__ == "__main__":
    app.run(debug=True)
