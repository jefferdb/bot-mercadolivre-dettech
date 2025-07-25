import os
import json
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, redirect, url_for

TOKENS_FILE = "tokens.json"

app = Flask(__name__)

# ===================== HTML DO LAYOUT =====================
HTML = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <title>Painel Bot Mercado Livre</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 30px;
            background-color: #f8f8f8;
        }
        h1 {
            color: #333;
        }
        section {
            background-color: #fff;
            padding: 20px;
            margin-top: 20px;
            border-radius: 12px;
            box-shadow: 0 0 10px #ccc;
        }
        input[type="text"], input[type="number"], input[type="time"] {
            padding: 8px;
            margin: 8px 0;
            width: 100%;
            box-sizing: border-box;
        }
        button {
            padding: 10px 20px;
            background-color: #009688;
            color: #fff;
            border: none;
            border-radius: 6px;
            cursor: pointer;
        }
        button:hover {
            background-color: #00796B;
        }
        .token-box {
            font-family: monospace;
            background-color: #f0f0f0;
            padding: 10px;
            border-radius: 6px;
        }
        .log-entry {
            background: #efefef;
            padding: 8px;
            margin: 4px 0;
            border-radius: 6px;
        }
    </style>
</head>
<body>
    <h1>Painel do Bot - Mercado Livre</h1>

    <section>
        <h2>Token Atual</h2>
        {% if token %}
            <div class="token-box">
                <strong>Access Token:</strong><br>{{ token.get('access_token') }}<br><br>
                <strong>Expira em:</strong> {{ token.get('expires_at') }}
            </div>
        {% else %}
            <p style="color: red;">Nenhum token encontrado.</p>
        {% endif %}
    </section>

    <section>
        <h2>Histórico de Atualização</h2>
        <div class="log-entry">Última verificação: {{ last_checked }}</div>
    </section>

    <section>
        <h2>Horário de Ausência</h2>
        <form method="post" action="/salvar-horario">
            <label>Início:</label>
            <input type="time" name="inicio" value="{{ horario.get('inicio', '') }}">
            <label>Fim:</label>
            <input type="time" name="fim" value="{{ horario.get('fim', '') }}">
            <button type="submit">Salvar Horário</button>
        </form>
    </section>

    <section>
        <h2>Forçar Atualização de Token</h2>
        <form method="post" action="/atualizar-token">
            <button type="submit">Atualizar Agora</button>
        </form>
    </section>
</body>
</html>
"""

# ===================== FUNÇÕES =====================

def carregar_tokens():
    if not os.path.exists(TOKENS_FILE):
        return None
    with open(TOKENS_FILE, "r") as f:
        return json.load(f)

def salvar_tokens(token_data):
    with open(TOKENS_FILE, "w") as f:
        json.dump(token_data, f, indent=4)

def token_expirado(token_data):
    if not token_data:
        return True
    try:
        expira_em = datetime.strptime(token_data["expires_at"], "%Y-%m-%d %H:%M:%S")
        return datetime.utcnow() > expira_em
    except:
        return True

def atualizar_token():
    print("🔄 Atualizando token (simulado)...")
    novo_token = {
        "access_token": f"MLA-TOKEN-{int(time.time())}",
        "expires_at": (datetime.utcnow() + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
    }
    salvar_tokens(novo_token)
    print("✅ Token atualizado com sucesso!")

def atualizar_em_background():
    while True:
        token = carregar_tokens()
        if token_expirado(token):
            atualizar_token()
        time.sleep(300)  # Checa a cada 5 minutos

def carregar_horario():
    if os.path.exists("horario.json"):
        with open("horario.json", "r") as f:
            return json.load(f)
    return {}

def salvar_horario(horario):
    with open("horario.json", "w") as f:
        json.dump(horario, f, indent=4)

# ===================== ROTAS =====================

@app.route("/", methods=["GET"])
def painel():
    token = carregar_tokens()
    horario = carregar_horario()
    last_checked = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return render_template_string(HTML, token=token, horario=horario, last_checked=last_checked)

@app.route("/salvar-horario", methods=["POST"])
def salvar_horario_route():
    horario = {
        "inicio": request.form.get("inicio"),
        "fim": request.form.get("fim")
    }
    salvar_horario(horario)
    return redirect(url_for("painel"))

@app.route("/atualizar-token", methods=["POST"])
def forcar_atualizacao():
    atualizar_token()
    return redirect(url_for("painel"))

# ===================== EXECUTAR APP =====================

if __name__ == "__main__":
    threading.Thread(target=atualizar_em_background, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
