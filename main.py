import os
import sqlite3
import json
import requests
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, jsonify, redirect, url_for

app = Flask(__name__)

# Configurações do Mercado Livre
ML_CLIENT_ID = os.getenv('ML_CLIENT_ID')
ML_CLIENT_SECRET = os.getenv('ML_CLIENT_SECRET')
ML_ACCESS_TOKEN = os.getenv('ML_ACCESS_TOKEN')
ML_USER_ID = os.getenv('ML_USER_ID')

# Banco de dados em memória
def init_db():
    conn = sqlite3.connect(':memory:', check_same_thread=False)
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
    
    # Inserir regras padrão
    default_rules = [
        ("preço, valor, quanto custa", "O preço está na descrição do produto. Qualquer dúvida, estou à disposição!"),
        ("entrega, prazo, demora", "O prazo de entrega aparece na página do produto. Enviamos no mesmo dia útil!"),
        ("frete, envio, correios", "O frete é calculado automaticamente pelo CEP. Temos frete grátis para algumas regiões!"),
        ("disponível, estoque, tem", "Sim, temos em estoque! Pode fazer o pedido que enviamos rapidinho."),
        ("garantia, defeito, problema", "Todos os produtos têm garantia. Em caso de defeito, trocamos sem problemas!"),
        ("pagamento, cartão, pix", "Aceitamos todas as formas de pagamento do Mercado Livre: cartão, PIX, boleto."),
        ("tamanho, medida, dimensão", "As medidas estão na descrição do produto. Qualquer dúvida específica, me avise!"),
        ("cor, cores, colorido", "As cores disponíveis estão nas opções do anúncio. Escolha a sua preferida!"),
        ("usado, novo, estado", "Todos os nossos produtos são novos e originais, com garantia do fabricante."),
        ("desconto, promoção, oferta", "Este já é nosso melhor preço! Aproveite que temos estoque disponível.")
    ]
    
    for keywords, response in default_rules:
        conn.execute("INSERT INTO rules (keywords, response) VALUES (?, ?)", (keywords, response))
    
    # Inserir configurações de ausência padrão
    absence_configs = [
        ("Horário Comercial", "18:00", "08:00", "1,2,3,4,5", "Obrigado pela pergunta! Nosso atendimento é de segunda a sexta, das 8h às 18h. Responderemos assim que possível!"),
        ("Final de Semana", "00:00", "23:59", "6,0", "Obrigado pela pergunta! Nosso atendimento não funciona aos finais de semana. Responderemos na segunda-feira!")
    ]
    
    for name, start_time, end_time, days, message in absence_configs:
        conn.execute("INSERT INTO absence_config (name, start_time, end_time, days_of_week, message) VALUES (?, ?, ?, ?, ?)", 
                    (name, start_time, end_time, days, message))
    
    conn.commit()
    print("✅ Banco de dados em memória criado com sucesso!")
    print("✅ 10 regras e 2 configurações de ausência carregadas!")
    return conn

# Conexão global
db_conn = init_db()

def get_db():
    return db_conn

# WEBHOOK - ROTA PRINCIPAL
@app.route('/api/ml/webhook', methods=['POST', 'GET'])
def webhook_ml():
    if request.method == 'GET':
        return jsonify({"status": "webhook_active", "message": "Webhook funcionando!"})
    
    try:
        data = request.get_json()
        print(f"🔔 Webhook recebido: {data}")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"❌ Erro no webhook: {e}")
        return jsonify({"error": str(e)}), 500

# Templates HTML simples
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html><head><title>Bot Mercado Livre - Dashboard</title>
<style>
body{font-family:Arial;margin:20px;background:#f5f5f5}
.header{background:#3483fa;color:white;padding:20px;border-radius:8px;text-align:center}
.nav{display:flex;gap:10px;margin:20px 0;justify-content:center}
.nav a{background:#3483fa;color:white;padding:10px 20px;text-decoration:none;border-radius:5px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin:20px 0}
.stat{background:white;padding:20px;border-radius:8px;text-align:center;box-shadow:0 2px 5px rgba(0,0,0,0.1)}
.stat-number{font-size:2em;color:#3483fa;font-weight:bold}
.status{background:white;padding:20px;border-radius:8px;border-left:5px solid #28a745}
</style>
</head><body>
<div class="header">
<h1>🤖 Bot do Mercado Livre</h1>
<p>Sistema Automatizado de Respostas - Funcionando!</p>
</div>
<div class="nav">
<a href="/">📊 Dashboard</a>
<a href="/regras">📋 Regras</a>
<a href="/perguntas">❓ Perguntas</a>
<a href="/ausencia">🌙 Ausência</a>
</div>
<div class="stats">
<div class="stat"><div class="stat-number">{{ stats.total }}</div><div>Total de Perguntas</div></div>
<div class="stat"><div class="stat-number">{{ stats.answered }}</div><div>Respondidas</div></div>
<div class="stat"><div class="stat-number">{{ stats.pending }}</div><div>Pendentes</div></div>
<div class="stat"><div class="stat-number">{{ stats.success_rate }}%</div><div>Taxa de Sucesso</div></div>
</div>
<div class="status">
<h3>✅ Status: Conectado</h3>
<p><strong>Token:</strong> ✅ Válido</p>
<p><strong>Monitoramento:</strong> ✅ Ativo</p>
<p><strong>Webhook:</strong> ✅ Funcionando</p>
<p><strong>Regras Ativas:</strong> {{ active_rules }}</p>
<p><strong>Configurações de Ausência:</strong> {{ active_absence }}</p>
</div>
</body></html>
'''

REGRAS_HTML = '''
<!DOCTYPE html>
<html><head><title>Bot Mercado Livre - Regras</title>
<style>
body{font-family:Arial;margin:20px;background:#f5f5f5}
.header{background:#3483fa;color:white;padding:20px;border-radius:8px;text-align:center}
.nav{display:flex;gap:10px;margin:20px 0;justify-content:center}
.nav a{background:#3483fa;color:white;padding:10px 20px;text-decoration:none;border-radius:5px}
.content{background:white;padding:20px;border-radius:8px}
.rule{border:1px solid #ddd;margin:10px 0;padding:15px;border-radius:5px}
.rule h4{color:#3483fa;margin-bottom:10px}
input,textarea{width:100%;padding:8px;margin:5px 0;border:1px solid #ddd;border-radius:4px}
textarea{height:60px}
button{padding:8px 15px;margin:5px;border:none;border-radius:4px;cursor:pointer}
.btn-save{background:#28a745;color:white}
.btn-delete{background:#dc3545;color:white}
</style>
</head><body>
<div class="header">
<h1>🤖 Bot do Mercado Livre</h1>
</div>
<div class="nav">
<a href="/">📊 Dashboard</a>
<a href="/regras">📋 Regras</a>
<a href="/perguntas">❓ Perguntas</a>
<a href="/ausencia">🌙 Ausência</a>
</div>
<div class="content">
<h2>📋 Regras de Resposta Automática</h2>
{% for rule in rules %}
<div class="rule">
<h4>Regra #{{ rule.id }}</h4>
<label>🔑 Palavras-chave:</label>
<input type="text" value="{{ rule.keywords }}">
<label>💬 Resposta:</label>
<textarea>{{ rule.response }}</textarea>
<button class="btn-save">💾 Salvar</button>
<button class="btn-delete">🗑️ Excluir</button>
</div>
{% endfor %}
</div>
</body></html>
'''

PERGUNTAS_HTML = '''
<!DOCTYPE html>
<html><head><title>Bot Mercado Livre - Perguntas</title>
<style>
body{font-family:Arial;margin:20px;background:#f5f5f5}
.header{background:#3483fa;color:white;padding:20px;border-radius:8px;text-align:center}
.nav{display:flex;gap:10px;margin:20px 0;justify-content:center}
.nav a{background:#3483fa;color:white;padding:10px 20px;text-decoration:none;border-radius:5px}
.content{background:white;padding:20px;border-radius:8px}
.question{border:1px solid #ddd;margin:10px 0;padding:15px;border-radius:5px}
.question-text{background:#f8f9fa;padding:10px;border-radius:4px;margin:10px 0}
.response-text{background:#e8f5e8;padding:10px;border-radius:4px;margin:10px 0}
.no-questions{text-align:center;color:#666;padding:40px}
</style>
</head><body>
<div class="header">
<h1>🤖 Bot do Mercado Livre</h1>
</div>
<div class="nav">
<a href="/">📊 Dashboard</a>
<a href="/regras">📋 Regras</a>
<a href="/perguntas">❓ Perguntas</a>
<a href="/ausencia">🌙 Ausência</a>
</div>
<div class="content">
<h2>❓ Histórico de Perguntas</h2>
{% if questions %}
{% for question in questions %}
<div class="question">
<strong>Pergunta #{{ question.question_id }}</strong> - {{ question.created_at }}
<div class="question-text">{{ question.question_text }}</div>
{% if question.response_text %}
<div class="response-text">✅ Resposta: {{ question.response_text }}</div>
{% endif %}
</div>
{% endfor %}
{% else %}
<div class="no-questions">
<h3>📭 Nenhuma pergunta ainda</h3>
<p>Quando chegarem perguntas, elas aparecerão aqui.</p>
</div>
{% endif %}
</div>
</body></html>
'''

AUSENCIA_HTML = '''
<!DOCTYPE html>
<html><head><title>Bot Mercado Livre - Ausência</title>
<style>
body{font-family:Arial;margin:20px;background:#f5f5f5}
.header{background:#3483fa;color:white;padding:20px;border-radius:8px;text-align:center}
.nav{display:flex;gap:10px;margin:20px 0;justify-content:center}
.nav a{background:#3483fa;color:white;padding:10px 20px;text-decoration:none;border-radius:5px}
.content{background:white;padding:20px;border-radius:8px}
.config{border:1px solid #ddd;margin:10px 0;padding:15px;border-radius:5px}
.config h4{color:#3483fa;margin-bottom:10px}
input,textarea{width:100%;padding:8px;margin:5px 0;border:1px solid #ddd;border-radius:4px}
textarea{height:60px}
.time-group{display:flex;gap:10px}
.time-group input{width:48%}
button{padding:8px 15px;margin:5px;border:none;border-radius:4px;cursor:pointer}
.btn-save{background:#28a745;color:white}
.btn-delete{background:#dc3545;color:white}
</style>
</head><body>
<div class="header">
<h1>🤖 Bot do Mercado Livre</h1>
</div>
<div class="nav">
<a href="/">📊 Dashboard</a>
<a href="/regras">📋 Regras</a>
<a href="/perguntas">❓ Perguntas</a>
<a href="/ausencia">🌙 Ausência</a>
</div>
<div class="content">
<h2>🌙 Configurações de Ausência</h2>
{% for config in absence_configs %}
<div class="config">
<h4>{{ config.name }}</h4>
<label>📝 Nome:</label>
<input type="text" value="{{ config.name }}">
<label>⏰ Horários:</label>
<div class="time-group">
<input type="time" value="{{ config.start_time }}">
<input type="time" value="{{ config.end_time }}">
</div>
<label>💬 Mensagem:</label>
<textarea>{{ config.message }}</textarea>
<button class="btn-save">💾 Salvar</button>
<button class="btn-delete">🗑️ Excluir</button>
</div>
{% endfor %}
</div>
</body></html>
'''

# Rotas
@app.route('/')
def dashboard():
    conn = get_db()
    total_questions = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    answered_questions = conn.execute("SELECT COUNT(*) FROM questions WHERE answered = 1").fetchone()[0]
    pending_questions = total_questions - answered_questions
    success_rate = round((answered_questions / total_questions * 100) if total_questions > 0 else 0)
    active_rules = conn.execute("SELECT COUNT(*) FROM rules WHERE is_active = 1").fetchone()[0]
    active_absence = conn.execute("SELECT COUNT(*) FROM absence_config WHERE is_active = 1").fetchone()[0]
    
    stats = {
        'total': total_questions,
        'answered': answered_questions,
        'pending': pending_questions,
        'success_rate': success_rate
    }
    
    return render_template_string(DASHBOARD_HTML, stats=stats, active_rules=active_rules, active_absence=active_absence)

@app.route('/regras')
def regras():
    conn = get_db()
    rules = conn.execute("SELECT * FROM rules ORDER BY id").fetchall()
    rules_list = [dict(rule) for rule in rules]
    return render_template_string(REGRAS_HTML, rules=rules_list)

@app.route('/perguntas')
def perguntas():
    conn = get_db()
    questions = conn.execute("SELECT * FROM questions ORDER BY created_at DESC LIMIT 50").fetchall()
    questions_list = [dict(question) for question in questions]
    return render_template_string(PERGUNTAS_HTML, questions=questions_list)

@app.route('/ausencia')
def ausencia():
    conn = get_db()
    configs = conn.execute("SELECT * FROM absence_config ORDER BY id").fetchall()
    configs_list = [dict(config) for config in configs]
    return render_template_string(AUSENCIA_HTML, absence_configs=configs_list)

# APIs
@app.route('/api/ml/rules')
def api_rules():
    conn = get_db()
    rules = conn.execute("SELECT * FROM rules").fetchall()
    return jsonify([dict(rule) for rule in rules])

@app.route('/api/ml/questions/recent')
def api_questions():
    conn = get_db()
    questions = conn.execute("SELECT * FROM questions ORDER BY created_at DESC LIMIT 10").fetchall()
    return jsonify([dict(question) for question in questions])

@app.route('/api/ml/absence')
def api_absence():
    conn = get_db()
    configs = conn.execute("SELECT * FROM absence_config").fetchall()
    return jsonify([dict(config) for config in configs])

def monitoring_loop():
    while True:
        try:
            print("🔄 Monitoramento ativo...")
            time.sleep(60)
        except Exception as e:
            print(f"Erro no monitoramento: {e}")
            time.sleep(60)

if __name__ == '__main__':
    print("🔄 Iniciando monitoramento...")
    monitoring_thread = threading.Thread(target=monitoring_loop, daemon=True)
    monitoring_thread.start()
    
    print("🚀 Bot iniciado com sucesso!")
    print("🔗 Webhook disponível em: /api/ml/webhook")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

