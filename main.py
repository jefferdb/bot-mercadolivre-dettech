import json
import os
import time
import requests
from datetime import datetime, timedelta
from flask import Flask

CLIENT_ID = "SUA_CLIENT_ID"
CLIENT_SECRET = "SUA_CLIENT_SECRET"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
TOKENS_FILE = "tokens.json"

app = Flask(__name__)

def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, "r") as f:
            data = json.load(f)
            return data
    return {}

def save_tokens(data):
    with open(TOKENS_FILE, "w") as f:
        json.dump(data, f)

def refresh_access_token(refresh_token):
    print("🔁 Renovando access token...")
    response = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token
    })

    if response.status_code == 200:
        tokens = response.json()
        expires_in = tokens.get("expires_in", 21600)
        tokens["token_expires_at"] = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
        save_tokens(tokens)
        print("✅ Access token renovado com sucesso!")
        return tokens["access_token"]
    else:
        print("❌ Falha ao renovar token:", response.text)
        return None

def get_valid_access_token():
    tokens = load_tokens()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_at_str = tokens.get("token_expires_at")

    if access_token and refresh_token and expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.utcnow() < expires_at:
            return access_token
        else:
            return refresh_access_token(refresh_token)
    return None

def monitorar_perguntas():
    while True:
        access_token = get_valid_access_token()
        if not access_token:
            print("❌ Sem access token válido.")
            break

        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get("https://api.mercadolibre.com/messages/questions/search?tag=unanswered", headers=headers)

        if response.status_code == 200:
            print("📩 Perguntas buscadas com sucesso.")
        else:
            print("⚠️ Erro ao buscar perguntas:", response.text)

        time.sleep(60)

@app.route("/")
def home():
    return "✅ Bot está rodando!"

if __name__ == "__main__":
    print("🚀 Iniciando bot...")
    monitorar_perguntas()
