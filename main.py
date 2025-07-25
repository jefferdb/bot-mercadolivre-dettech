import sqlite3
import json
import requests
import threading
import time
import os
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)
DATABASE = ':memory:'
TOKENS_FILE = 'tokens.json'

# ---- CLIENTE MERCADO LIVRE ----
ML_CLIENT_ID = "5510376630479325"
ML_CLIENT_SECRET = "jlR4As2x8uFY3RTpysLpuPhzC9yM9d35"
ML_USER_ID = "180617463"

# ---- HTML (simplificado e funcional) ----
PAINEL_HTML = '''
<!DOCTYPE html>
<html lang="pt-br"><head><meta charset="UTF-8">
<title>Bot Mercado Livre</title>
<style>
body { font-family: Arial, sans-serif; margin: 40px; background: #f3f3f3; }
h1 { color: #2968c8; }
.card { background: white; padding: 20px; margin-bottom: 20px; border-radius: 10px; box-shadow: 0 0 5px rgba(0,0,0,0.1); }
</style></head><body>
<h1>🤖 Bot Mercado Livre</h1>
<div class="card">
    <h2>Status do Bot</h2>
    <p><strong>Token:</strong> {{ 'Válido ✅' if token_ok else 'Expirado ❌' }}</p>
    <p><strong>Última verificação:</strong> {{ ultima_verificacao }}</p>
</div>
<div class="card">
    <h2><a href="/regras">📋 Ver Regras</a></h2>
    <h2><a href="/ausencia">⏰ Configurações de Ausência</a></h2>
</div>
</body></html>
'''

REGRAS_HTML = '''
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Regras</title>
<style>
body { font-family: sans-serif; padding: 30px; background: #fafafa; }
h1 { color: #2968c8; }
.rule { background: white; margin-bottom: 10px; padding: 10px; border-left: 5px solid #2968c8; }
</style></head><body>
<h1>📋 Regras de Resposta</h1>
{% for r in regras %}
<div class="rule">
    <strong>#{{ r.id }}</strong><br>
    <em>Palavras-chave:</em> {{ r.keywords }}<br>
    <em>Resposta:</em> {{ r.response }}<br>
    <em>Ativa:</em> {{ 'Sim' if r.is_active else 'Não' }}
</div>
{% endfor %}
</body></html>
'''

AUSENCIA_HTML = '''
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Ausência</title>
<style>
body { font-family: sans-serif; padding: 30px; background: #fafafa; }
h1 { color: #e67e22; }
.conf { background: white; margin-bottom: 10px; padding: 10px; border-left: 5px solid #e67e22; }
</style></head><body>
<h1>⏰ Horários de Ausência</h1>
{% for a in ausencia %}
<div class="conf">
    <strong>{{ a.name }}</strong><br>
    <em>Início:</em> {{ a.start_time }} - <em>Fim:</em> {{ a.end_time }}<br>
    <em>Dias:</em> {{ a.days_of_week }}<br>
    <em>Mensagem:</em> {{ a.message }}<br>
    <em>Ativa:</em> {{ 'Sim' if a.is_active else 'Não' }}
</div>
{% endfor %}
</body></html>
'''

# ---- BANCO DE DADOS EM MEMÓRIA ----
def init_db():
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS rules (id INTEGER PRIMARY KEY, keywords TEXT, response TEXT, is_active INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS absence_config (id INTEGER PRIMARY KEY, name TEXT, start_time TEXT, end_time TEXT, days_of_week TEXT, message TEXT, is_active INTEGER)")
    regras = [
        ("preço,valor", "Está no anúncio!"), ("frete,envio", "Calcule com seu CEP!"),
        ("garantia", "Temos garantia de 3 meses!"), ("estoque,tem", "Sim, disponível!"),
    ]
    for k, r in regras:
        conn.execute("INSERT INTO rules (keywords, response, is_active) VALUES (?, ?, 1)", (k, r))
    conn.execute("INSERT INTO absence_config (name, start_time, end_time, days_of_week, message, is_active) VALUES (?, ?, ?, ?, ?, 1)",
                 ("Fora do expediente", "19:00", "09:00", "segunda,terça,quarta,quinta,sexta", "Estamos fora do horário comercial, responderemos em breve."))
    conn.commit()
    return conn

db = init_db()

# ---- TOKEN MANAGEMENT ----
def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, 'r') as f:
            data = json.load(f)
            data['expires_at'] = datetime.fromisoformat(data['expires_at'])
            return data
    return None

def save_tokens(data):
    data['expires_at'] = data['expires_at'].isoformat()
    with open(TOKENS_FILE, 'w') as f:
        json.dump(data, f)

def refresh_token(refresh_token):
    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": ML_CLIENT_ID,
        "client_secret": ML_CLIENT_SECRET,
        "refresh_token": refresh_token
    }
    response = requests.post(url, data=payload)
    if response.ok:
        new_data = response.json()
        tokens = {
            "access_token": new_data["access_token"],
            "refresh_token": new_data["refresh_token"],
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=new_data["expires_in"])
        }
        save_tokens(tokens)
        return tokens
    else:
        print("❌ Falha ao renovar token:", response.text)
        return None

def get_valid_token():
    tokens = load_tokens()
    if tokens and datetime.now(timezone.utc) < tokens["expires_at"]:
        return tokens["access_token"]
    elif tokens:
        return refresh_token(tokens["refresh_token"])["access_token"]
    return None

# ---- MONITORAMENTO ----
ultima_verificacao = "Nunca"

def buscar_perguntas():
    global ultima_verificacao
    token = get_valid_token()
    if not token:
        print("❌ Token inválido")
        return
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://api.mercadolibre.com/users/{ML_USER_ID}/questions/search?status=UNANSWERED"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            perguntas = response.json().get("questions", [])
            print(f"🔍 {len(perguntas)} perguntas encontradas.")
            for p in perguntas:
                texto = p['text'].lower()
                regras = db.execute("SELECT * FROM rules WHERE is_active = 1").fetchall()
                resposta = next((r['response'] for r in regras if any(k in texto for k in r['keywords'].split(','))), None)
                if resposta:
                    post_url = f"https://api.mercadolibre.com/questions/{p['id']}/answers"
                    r = requests.post(post_url, headers=headers, json={"text": resposta})
                    print(f"💬 Respondido: {resposta}")
                else:
                    print(f"❓ Sem regra: {texto}")
        else:
            print("⚠️ Erro:", response.text)
    except Exception as e:
        print("Erro:", e)
    ultima_verificacao = datetime.now().strftime("%H:%M:%S")

def iniciar_bot():
    def loop():
        while True:
            buscar_perguntas()
            time.sleep(60)
    t = threading.Thread(target=loop)
    t.daemon = True
    t.start()

# ---- ROTAS ----
@app.route('/')
def home():
    token_ok = bool(get_valid_token())
    return render_template_string(PAINEL_HTML, token_ok=token_ok, ultima_verificacao=ultima_verificacao)

@app.route('/regras')
def ver_regras():
    regras = db.execute("SELECT * FROM rules").fetchall()
    return render_template_string(REGRAS_HTML, regras=regras)

@app.route('/ausencia')
def ver_ausencia():
    ausencia = db.execute("SELECT * FROM absence_config").fetchall()
    return render_template_string(AUSENCIA_HTML, ausencia=ausencia)

if __name__ == '__main__':
    print("🚀 Iniciando bot...")
    iniciar_bot()
    app.run(host="0.0.0.0", port=5000)
