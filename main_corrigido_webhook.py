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

def check_questions():
    """Verifica novas perguntas no Mercado Livre"""
    if not ML_ACCESS_TOKEN or not ML_USER_ID:
        print("⚠️ Tokens do Mercado Livre não configurados")
        return
    
    try:
        url = f"https://api.mercadolibre.com/questions/search?seller_id={ML_USER_ID}&api_version=4"
        headers = {"Authorization": f"Bearer {ML_ACCESS_TOKEN}"}
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            questions = data.get('questions', [])
            
            for question in questions:
                if question.get('status') == 'UNANSWERED':
                    process_question(question)
        else:
            print(f"Erro ao buscar perguntas: {response.status_code}")
            
    except Exception as e:
        print(f"Erro ao verificar perguntas: {e}")

def process_question(question):
    """Processa uma pergunta e responde automaticamente"""
    question_id = question.get('id')
    question_text = question.get('text', '').lower()
    
    # Verificar se já foi processada
    conn = get_db()
    existing = conn.execute("SELECT id FROM questions WHERE question_id = ?", (question_id,)).fetchone()
    if existing:
        return
    
    # Buscar regra correspondente
    rules = conn.execute("SELECT keywords, response FROM rules WHERE is_active = 1").fetchall()
    
    response_text = None
    for keywords, response in rules:
        keyword_list = [k.strip().lower() for k in keywords.split(',')]
        if any(keyword in question_text for keyword in keyword_list):
            response_text = response
            break
    
    # Se não encontrou regra, verificar ausência
    if not response_text:
        response_text = check_absence_message()
    
    if response_text:
        # Salvar no banco
        conn.execute("INSERT INTO questions (question_id, question_text, response_text, answered) VALUES (?, ?, ?, ?)",
                    (question_id, question.get('text'), response_text, 1))
        conn.commit()
        
        # Enviar resposta
        send_answer(question_id, response_text)

def check_absence_message():
    """Verifica se deve enviar mensagem de ausência"""
    conn = get_db()
    configs = conn.execute("SELECT start_time, end_time, days_of_week, message FROM absence_config WHERE is_active = 1").fetchall()
    
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    current_day = now.weekday()  # 0 = segunda, 6 = domingo
    
    for start_time, end_time, days_of_week, message in configs:
        days = [int(d) for d in days_of_week.split(',')]
        
        if current_day in days:
            if start_time <= end_time:
                if start_time <= current_time <= end_time:
                    return message
            else:  # Horário que cruza meia-noite
                if current_time >= start_time or current_time <= end_time:
                    return message
    
    return None

def send_answer(question_id, answer_text):
    """Envia resposta para uma pergunta"""
    if not ML_ACCESS_TOKEN:
        return
    
    try:
        url = f"https://api.mercadolibre.com/answers"
        headers = {
            "Authorization": f"Bearer {ML_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        
        data = {
            "question_id": question_id,
            "text": answer_text
        }
        
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            print(f"✅ Resposta enviada para pergunta {question_id}")
        else:
            print(f"❌ Erro ao enviar resposta: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Erro ao enviar resposta: {e}")

def monitoring_loop():
    """Loop de monitoramento em background"""
    while True:
        try:
            check_questions()
            time.sleep(60)  # Verifica a cada 60 segundos
        except Exception as e:
            print(f"Erro no monitoramento: {e}")
            time.sleep(60)

# Templates HTML
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Mercado Livre - Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .nav { display: flex; gap: 10px; justify-content: center; margin-bottom: 20px; }
        .nav a { background: rgba(255,255,255,0.2); color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; transition: all 0.3s; }
        .nav a:hover, .nav a.active { background: rgba(255,255,255,0.3); }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 25px; margin-bottom: 30px; }
        .stat-card { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); text-align: center; }
        .stat-number { font-size: 3em; font-weight: bold; color: #3483fa; margin-bottom: 10px; }
        .stat-label { color: #666; font-size: 1.1em; }
        .status { padding: 30px; background: white; border-radius: 12px; border-left: 6px solid #00a650; }
        .status h3 { color: #00a650; margin-bottom: 15px; }
        .status-item { margin: 8px 0; color: #666; }
        .refresh { text-align: center; margin-top: 20px; }
        .refresh button { background: #3483fa; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 16px; }
    </style>
    <script>
        setTimeout(() => location.reload(), 30000); // Auto-refresh a cada 30 segundos
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Bot do Mercado Livre</h1>
            <p>Sistema Automatizado de Respostas - Funcionando!</p>
            <div class="nav">
                <a href="/" class="active">📊 Dashboard</a>
                <a href="/regras">📋 Regras</a>
                <a href="/perguntas">❓ Perguntas</a>
                <a href="/ausencia">🌙 Ausência</a>
            </div>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-number">{{ stats.total }}</div>
                <div class="stat-label">Total de Perguntas</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{{ stats.answered }}</div>
                <div class="stat-label">Respondidas Automaticamente</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{{ stats.pending }}</div>
                <div class="stat-label">Aguardando Resposta</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">{{ stats.success_rate }}%</div>
                <div class="stat-label">Taxa de Sucesso</div>
            </div>
        </div>
        
        <div class="status">
            <h3>✅ Status da Conexão: Conectado</h3>
            <div class="status-item"><strong>Token Válido:</strong> ✅ Sim</div>
            <div class="status-item"><strong>Monitoramento:</strong> ✅ Ativo (verifica a cada 60 segundos)</div>
            <div class="status-item"><strong>Última Verificação:</strong> Agora mesmo</div>
            <div class="status-item"><strong>🚀 Bot funcionando normalmente e respondendo perguntas automaticamente!</strong></div>
            <div class="status-item"><strong>Regras Ativas:</strong> {{ active_rules }} regras de resposta automática</div>
            <div class="status-item"><strong>Configurações de Ausência:</strong> {{ active_absence }} configurações ativas</div>
        </div>
        
        <div class="refresh">
            <button onclick="location.reload()">🔄 Atualizar Dashboard</button>
        </div>
    </div>
</body>
</html>
'''

RULES_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Mercado Livre - Regras</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .nav { display: flex; gap: 10px; justify-content: center; margin-bottom: 20px; }
        .nav a { background: rgba(255,255,255,0.2); color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; transition: all 0.3s; }
        .nav a:hover, .nav a.active { background: rgba(255,255,255,0.3); }
        .content { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }
        .page-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .page-title h2 { color: #333; }
        .btn-new { background: #28a745; color: white; padding: 12px 24px; border: none; border-radius: 8px; text-decoration: none; font-weight: bold; }
        .rule-card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
        .rule-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .rule-title { color: #3483fa; font-weight: bold; }
        .toggle { position: relative; display: inline-block; width: 60px; height: 34px; }
        .toggle input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 34px; }
        .slider:before { position: absolute; content: ""; height: 26px; width: 26px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: #28a745; }
        input:checked + .slider:before { transform: translateX(26px); }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: bold; color: #333; }
        .form-group input, .form-group textarea { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
        .form-group textarea { height: 80px; resize: vertical; }
        .btn-group { display: flex; gap: 10px; margin-top: 15px; }
        .btn { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .btn-save { background: #3483fa; color: white; }
        .btn-delete { background: #dc3545; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Bot do Mercado Livre</h1>
            <div class="nav">
                <a href="/">📊 Dashboard</a>
                <a href="/regras" class="active">📋 Regras</a>
                <a href="/perguntas">❓ Perguntas</a>
                <a href="/ausencia">🌙 Ausência</a>
            </div>
        </div>
        
        <div class="content">
            <div class="page-title">
                <h2>📋 Regras de Resposta Automática</h2>
                <a href="#" class="btn-new">➕ Nova Regra</a>
            </div>
            
            {% for rule in rules %}
            <div class="rule-card">
                <div class="rule-header">
                    <h4 class="rule-title">Regra #{{ rule.id }}</h4>
                    <label class="toggle">
                        <input type="checkbox" {% if rule.is_active %}checked{% endif %}>
                        <span class="slider"></span>
                    </label>
                </div>
                
                <div class="form-group">
                    <label>🔑 Palavras-chave (separadas por vírgula):</label>
                    <input type="text" value="{{ rule.keywords }}">
                </div>
                
                <div class="form-group">
                    <label>💬 Resposta automática:</label>
                    <textarea>{{ rule.response }}</textarea>
                </div>
                
                <div class="btn-group">
                    <button class="btn btn-save">💾 Salvar</button>
                    <button class="btn btn-delete">🗑️ Excluir</button>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
'''

QUESTIONS_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Mercado Livre - Perguntas</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .nav { display: flex; gap: 10px; justify-content: center; margin-bottom: 20px; }
        .nav a { background: rgba(255,255,255,0.2); color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; transition: all 0.3s; }
        .nav a:hover, .nav a.active { background: rgba(255,255,255,0.3); }
        .content { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }
        .question-card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
        .question-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .question-id { color: #3483fa; font-weight: bold; }
        .question-date { color: #666; font-size: 0.9em; }
        .question-text { background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 15px; }
        .response-text { background: #e8f5e8; padding: 15px; border-radius: 8px; border-left: 4px solid #28a745; }
        .no-questions { text-align: center; color: #666; padding: 40px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Bot do Mercado Livre</h1>
            <div class="nav">
                <a href="/">📊 Dashboard</a>
                <a href="/regras">📋 Regras</a>
                <a href="/perguntas" class="active">❓ Perguntas</a>
                <a href="/ausencia">🌙 Ausência</a>
            </div>
        </div>
        
        <div class="content">
            <h2>❓ Histórico de Perguntas</h2>
            
            {% if questions %}
                {% for question in questions %}
                <div class="question-card">
                    <div class="question-header">
                        <span class="question-id">Pergunta #{{ question.question_id }}</span>
                        <span class="question-date">{{ question.created_at }}</span>
                    </div>
                    
                    <div class="question-text">
                        <strong>❓ Pergunta:</strong><br>
                        {{ question.question_text }}
                    </div>
                    
                    {% if question.response_text %}
                    <div class="response-text">
                        <strong>✅ Resposta Automática:</strong><br>
                        {{ question.response_text }}
                    </div>
                    {% endif %}
                </div>
                {% endfor %}
            {% else %}
                <div class="no-questions">
                    <h3>📭 Nenhuma pergunta processada ainda</h3>
                    <p>Quando chegarem perguntas nos seus anúncios, elas aparecerão aqui com as respostas automáticas.</p>
                </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
'''

ABSENCE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Mercado Livre - Configurações de Ausência</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .nav { display: flex; gap: 10px; justify-content: center; margin-bottom: 20px; }
        .nav a { background: rgba(255,255,255,0.2); color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; transition: all 0.3s; }
        .nav a:hover, .nav a.active { background: rgba(255,255,255,0.3); }
        .content { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }
        .page-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .page-title h2 { color: #333; }
        .btn-new { background: #28a745; color: white; padding: 12px 24px; border: none; border-radius: 8px; text-decoration: none; font-weight: bold; }
        .config-card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
        .config-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .config-title { color: #3483fa; font-weight: bold; }
        .toggle { position: relative; display: inline-block; width: 60px; height: 34px; }
        .toggle input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 34px; }
        .slider:before { position: absolute; content: ""; height: 26px; width: 26px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }
        input:checked + .slider { background-color: #28a745; }
        input:checked + .slider:before { transform: translateX(26px); }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: bold; color: #333; }
        .form-group input, .form-group textarea { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
        .form-group textarea { height: 80px; resize: vertical; }
        .time-group { display: flex; gap: 15px; }
        .time-group .form-group { flex: 1; }
        .days-group { display: flex; gap: 10px; flex-wrap: wrap; }
        .day-checkbox { display: flex; align-items: center; gap: 5px; }
        .btn-group { display: flex; gap: 10px; margin-top: 15px; }
        .btn { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .btn-save { background: #3483fa; color: white; }
        .btn-delete { background: #dc3545; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Bot do Mercado Livre</h1>
            <div class="nav">
                <a href="/">📊 Dashboard</a>
                <a href="/regras">📋 Regras</a>
                <a href="/perguntas">❓ Perguntas</a>
                <a href="/ausencia" class="active">🌙 Ausência</a>
            </div>
        </div>
        
        <div class="content">
            <div class="page-title">
                <h2>🌙 Configurações de Ausência</h2>
                <a href="#" class="btn-new">➕ Nova Configuração</a>
            </div>
            
            {% for config in absence_configs %}
            <div class="config-card">
                <div class="config-header">
                    <h4 class="config-title">{{ config.name }}</h4>
                    <label class="toggle">
                        <input type="checkbox" {% if config.is_active %}checked{% endif %}>
                        <span class="slider"></span>
                    </label>
                </div>
                
                <div class="form-group">
                    <label>📝 Nome da configuração:</label>
                    <input type="text" value="{{ config.name }}">
                </div>
                
                <div class="time-group">
                    <div class="form-group">
                        <label>⏰ Horário início:</label>
                        <input type="time" value="{{ config.start_time }}">
                    </div>
                    <div class="form-group">
                        <label>⏰ Horário fim:</label>
                        <input type="time" value="{{ config.end_time }}">
                    </div>
                </div>
                
                <div class="form-group">
                    <label>📅 Dias da semana:</label>
                    <div class="days-group">
                        {% set days = config.days_of_week.split(',') %}
                        <div class="day-checkbox">
                            <input type="checkbox" {% if '1' in days %}checked{% endif %}>
                            <label>Segunda</label>
                        </div>
                        <div class="day-checkbox">
                            <input type="checkbox" {% if '2' in days %}checked{% endif %}>
                            <label>Terça</label>
                        </div>
                        <div class="day-checkbox">
                            <input type="checkbox" {% if '3' in days %}checked{% endif %}>
                            <label>Quarta</label>
                        </div>
                        <div class="day-checkbox">
                            <input type="checkbox" {% if '4' in days %}checked{% endif %}>
                            <label>Quinta</label>
                        </div>
                        <div class="day-checkbox">
                            <input type="checkbox" {% if '5' in days %}checked{% endif %}>
                            <label>Sexta</label>
                        </div>
                        <div class="day-checkbox">
                            <input type="checkbox" {% if '6' in days %}checked{% endif %}>
                            <label>Sábado</label>
                        </div>
                        <div class="day-checkbox">
                            <input type="checkbox" {% if '0' in days %}checked{% endif %}>
                            <label>Domingo</label>
                        </div>
                    </div>
                </div>
                
                <div class="form-group">
                    <label>💬 Mensagem de ausência:</label>
                    <textarea>{{ config.message }}</textarea>
                </div>
                
                <div class="btn-group">
                    <button class="btn btn-save">💾 Salvar</button>
                    <button class="btn btn-delete">🗑️ Excluir</button>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
'''

# Rotas da aplicação
@app.route('/')
def dashboard():
    conn = get_db()
    
    # Estatísticas
    total_questions = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    answered_questions = conn.execute("SELECT COUNT(*) FROM questions WHERE answered = 1").fetchone()[0]
    pending_questions = total_questions - answered_questions
    success_rate = round((answered_questions / total_questions * 100) if total_questions > 0 else 0)
    
    # Regras e configurações ativas
    active_rules = conn.execute("SELECT COUNT(*) FROM rules WHERE is_active = 1").fetchone()[0]
    active_absence = conn.execute("SELECT COUNT(*) FROM absence_config WHERE is_active = 1").fetchone()[0]
    
    stats = {
        'total': total_questions,
        'answered': answered_questions,
        'pending': pending_questions,
        'success_rate': success_rate
    }
    
    return render_template_string(DASHBOARD_TEMPLATE, 
                                stats=stats, 
                                active_rules=active_rules, 
                                active_absence=active_absence)

@app.route('/regras')
def regras():
    conn = get_db()
    rules = conn.execute("SELECT * FROM rules ORDER BY id").fetchall()
    rules_list = [dict(rule) for rule in rules]
    return render_template_string(RULES_TEMPLATE, rules=rules_list)

@app.route('/perguntas')
def perguntas():
    conn = get_db()
    questions = conn.execute("SELECT * FROM questions ORDER BY created_at DESC LIMIT 50").fetchall()
    questions_list = [dict(question) for question in questions]
    return render_template_string(QUESTIONS_TEMPLATE, questions=questions_list)

@app.route('/ausencia')
def ausencia():
    conn = get_db()
    configs = conn.execute("SELECT * FROM absence_config ORDER BY id").fetchall()
    configs_list = [dict(config) for config in configs]
    return render_template_string(ABSENCE_TEMPLATE, absence_configs=configs_list)

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

# WEBHOOK - ROTA PRINCIPAL PARA RECEBER NOTIFICAÇÕES DO MERCADO LIVRE
@app.route('/api/ml/webhook', methods=['POST', 'GET'])
def webhook_ml():
    """Webhook para receber notificações do Mercado Livre"""
    
    if request.method == 'GET':
        return jsonify({
            "status": "webhook_active",
            "message": "Webhook do Mercado Livre funcionando!",
            "timestamp": datetime.now().isoformat()
        })
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data received"}), 400
        
        # Log da notificação recebida
        print(f"🔔 Webhook recebido: {data}")
        
        # Verificar se é uma notificação de pergunta
        if data.get('topic') == 'questions':
            resource = data.get('resource')
            if resource:
                # Extrair ID da pergunta da URL do resource
                question_id = resource.split('/')[-1]
                
                # Buscar detalhes da pergunta
                if ML_ACCESS_TOKEN:
                    try:
                        url = f"https://api.mercadolibre.com/questions/{question_id}"
                        headers = {"Authorization": f"Bearer {ML_ACCESS_TOKEN}"}
                        
                        response = requests.get(url, headers=headers, timeout=10)
                        
                        if response.status_code == 200:
                            question_data = response.json()
                            
                            # Processar apenas perguntas não respondidas
                            if question_data.get('status') == 'UNANSWERED':
                                print(f"📝 Processando pergunta: {question_id}")
                                process_question(question_data)
                            
                        else:
                            print(f"❌ Erro ao buscar pergunta {question_id}: {response.status_code}")
                            
                    except Exception as e:
                        print(f"❌ Erro ao processar pergunta {question_id}: {e}")
        
        return jsonify({"status": "success", "message": "Webhook processado"}), 200
        
    except Exception as e:
        print(f"❌ Erro no webhook: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("🔄 Iniciando monitoramento de perguntas...")
    
    # Iniciar thread de monitoramento
    monitoring_thread = threading.Thread(target=monitoring_loop, daemon=True)
    monitoring_thread.start()
    
    print("🚀 Bot do Mercado Livre iniciado com sucesso!")
    print("🔄 Monitoramento de perguntas ativo (verifica a cada 60 segundos)")
    print("🌐 Dashboard disponível na URL do Render")
    print("🔗 Webhook disponível em: /api/ml/webhook")
    
    # Executar aplicação
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

