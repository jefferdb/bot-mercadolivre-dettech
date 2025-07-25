from flask import Flask, render_template, request, redirect, jsonify
import json
from datetime import datetime

app = Flask(__name__)

def load_tokens():
    try:
        with open("tokens.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"access_token": "", "expires_in": ""}

def save_tokens(data):
    with open("tokens.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

horario_ausente = {"inicio": "", "fim": ""}

@app.route("/", methods=["GET", "POST"])
def index():
    tokens = load_tokens()
    ultima_verificacao = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return render_template("painel.html", tokens=tokens, ultima=ultima_verificacao, horario=horario_ausente)

@app.route("/salvar-horario", methods=["POST"])
def salvar_horario():
    inicio = request.form.get("inicio")
    fim = request.form.get("fim")
    horario_ausente["inicio"] = inicio
    horario_ausente["fim"] = fim
    return redirect("/")

@app.route("/atualizar-token", methods=["POST"])
def atualizar_token():
    tokens = load_tokens()
    tokens["access_token"] = "novo_token_" + datetime.now().strftime("%H%M%S")
    tokens["expires_in"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    save_tokens(tokens)
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)
