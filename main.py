import os
import sqlite3
import json
import requests
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, jsonify, redirect, url_for

app = Flask(__name__)

ML_CLIENT_ID = os.getenv('ML_CLIENT_ID')
ML_CLIENT_SECRET = os.getenv('ML_CLIENT_SECRET')
ML_ACCESS_TOKEN = os.getenv('ML_ACCESS_TOKEN')
ML_USER_ID = os.getenv('ML_USER_ID')

def init_db():
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row  # CORRECAO CRUCIAL

    conn.execute('''CREATE TABLE IF NOT EXISTS rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keywords TEXT NOT NULL,
        response TEXT NOT NULL,
        is_active BOOLEAN DEFAULT 1
    )''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id TEXT UNIQUE,
        question_text TEXT,
        response_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        answered BOOLEAN DEFAULT 0
    )''')

    conn.execute('''CREATE TABLE IF NOT EXISTS absence_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        start_time TEXT,
        end_time TEXT,
        days_of_week TEXT,
        message TEXT,
        is_active BOOLEAN DEFAULT 1
    )''')

    default_rules = [
        ("preço, valor, quanto custa", "O preço está na descrição do produto."),
        ("entrega, prazo, demora", "O prazo de entrega aparece na página do produto."),
        ("frete, envio, correios", "O frete é calculado automaticamente pelo CEP."),
        ("disponível, estoque, tem", "Sim, temos em estoque!"),
        ("garantia, defeito, problema", "Todos os produtos têm garantia."),
        ("pagamento, cartão, pix", "Aceitamos todas as formas de pagamento."),
        ("tamanho, medida, dimensão", "As medidas estão na descrição."),
        ("cor, cores, colorido", "As cores disponíveis estão nas opções do anúncio."),
        ("usado, novo, estado", "Todos os nossos produtos são novos e originais."),
        ("desconto, promoção, oferta", "Este já é nosso melhor preço!")
    ]
    for keywords, response in default_rules:
        conn.execute("INSERT INTO rules (keywords, response) VALUES (?, ?)", (keywords, response))

    conn.commit()
    return conn

db_conn = init_db()

def get_db():
    return db_conn

@app.route('/api/rules', methods=['GET', 'POST', 'PUT', 'DELETE'])
def api_manage_rules():
    conn = get_db()
    if request.method == 'GET':
        rules = conn.execute("SELECT * FROM rules").fetchall()
        return jsonify([dict(row) for row in rules])

    elif request.method == 'POST':
        data = request.json
        conn.execute("INSERT INTO rules (keywords, response, is_active) VALUES (?, ?, ?)",
                     (data['keywords'], data['response'], int(data.get('is_active', 1))))
        conn.commit()
        return jsonify({"status": "created"}), 201

    elif request.method == 'PUT':
        data = request.json
        conn.execute("UPDATE rules SET keywords = ?, response = ?, is_active = ? WHERE id = ?",
                     (data['keywords'], data['response'], int(data.get('is_active', 1)), data['id']))
        conn.commit()
        return jsonify({"status": "updated"})

    elif request.method == 'DELETE':
        rule_id = request.args.get('id')
        conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        conn.commit()
        return jsonify({"status": "deleted"})

@app.route('/regras')
def regras():
    conn = get_db()
    rules = conn.execute("SELECT * FROM rules ORDER BY id").fetchall()
    return render_template_string('''
    <h1>Regras de Resposta</h1>
    <ul>
        {% for rule in rules %}
            <li><strong>{{ rule['keywords'] }}</strong>: {{ rule['response'] }} (ativo: {{ rule['is_active'] }})</li>
        {% endfor %}
    </ul>
    ''', rules=rules)

@app.route('/')
def home():
    return '<h1>Bot Mercado Livre OK</h1><a href="/regras">Ver Regras</a>'

if __name__ == '__main__':
    app.run(debug=True)
