import os
import time
import threading
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests
import sqlite3

# Configuração da aplicação
app = Flask(__name__)
CORS(app)

# Configuração do banco SQLite persistente
DATABASE_PATH = '/opt/render/project/src/data/bot_ml.db'
if not os.path.exists('/opt/render/project/src/data'):
    DATABASE_PATH = './data/bot_ml.db'
    os.makedirs('./data', exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configurações do Mercado Livre
ML_CLIENT_ID = os.getenv('ML_CLIENT_ID', '5510376630479325')
ML_CLIENT_SECRET = os.getenv('ML_CLIENT_SECRET', 'jlR4As2x8uFY3RTpysLpuPhzC9yM9d35')
ML_ACCESS_TOKEN = os.getenv('ML_ACCESS_TOKEN', 'APP_USR-5510376630479325-072511-3ae2fcd67777738f910e1dc08131b55d-180617463')
ML_USER_ID = os.getenv('ML_USER_ID', '180617463')
ML_REFRESH_TOKEN = os.getenv('ML_REFRESH_TOKEN', '')

# Timezone São Paulo
SAO_PAULO_TZ = timezone(timedelta(hours=-3))

def get_local_time():
    """Retorna horário local de São Paulo"""
    return datetime.now(SAO_PAULO_TZ)

def format_local_time(dt=None):
    """Formata horário local"""
    if dt is None:
        dt = get_local_time()
    return dt.strftime("%H:%M:%S")

# Modelos do banco de dados
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    ml_user_id = db.Column(db.String(50), unique=True, nullable=False)
    access_token = db.Column(db.String(200), nullable=False)
    refresh_token = db.Column(db.String(200))
    token_expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AutoResponse(db.Model):
    __tablename__ = 'auto_responses'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    keywords = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    ml_question_id = db.Column(db.String(50), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    item_id = db.Column(db.String(50), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text)
    is_answered = db.Column(db.Boolean, default=False)
    answered_automatically = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    answered_at = db.Column(db.DateTime)

class AbsenceConfig(db.Model):
    __tablename__ = 'absence_configs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    start_time = db.Column(db.String(5))  # HH:MM
    end_time = db.Column(db.String(5))    # HH:MM
    days_of_week = db.Column(db.String(20))  # 0,1,2,3,4,5,6
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ResponseHistory(db.Model):
    __tablename__ = 'response_history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.String(50), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text, nullable=False)
    response_type = db.Column(db.String(20), nullable=False)  # 'auto', 'absence', 'manual'
    keywords_matched = db.Column(db.String(200))
    response_time = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DebugLog(db.Model):
    __tablename__ = 'debug_logs'
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.Text, nullable=False)
    level = db.Column(db.String(20), default='INFO')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Variável global para controlar inicialização
_initialized = False

def log_debug(message, level='INFO'):
    """Adiciona log de debug ao banco"""
    try:
        with app.app_context():
            log = DebugLog(message=message, level=level)
            db.session.add(log)
            db.session.commit()
            print(f"[{level}] {message}")
    except Exception as e:
        print(f"Erro ao salvar log: {e}")

# Função para criar tabelas e dados iniciais
def initialize_database():
    global _initialized
    if _initialized:
        return
    
    try:
        with app.app_context():
            db.create_all()
            log_debug("Banco de dados criado")
            
            # Criar usuário padrão
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                user = User(
                    ml_user_id=ML_USER_ID,
                    access_token=ML_ACCESS_TOKEN,
                    refresh_token=ML_REFRESH_TOKEN,
                    token_expires_at=datetime.utcnow() + timedelta(hours=6)
                )
                db.session.add(user)
                db.session.commit()
                log_debug(f"Usuário criado: {ML_USER_ID}")
            
            # Criar regras padrão se não existirem
            if AutoResponse.query.count() == 0:
                default_rules = [
                    {
                        "keywords": "preço,valor,quanto custa,custa quanto",
                        "response": "O preço está na descrição do produto. Qualquer dúvida, estamos à disposição!"
                    },
                    {
                        "keywords": "entrega,prazo,demora,quando chega",
                        "response": "O prazo de entrega aparece na página do produto. Enviamos pelos Correios com código de rastreamento."
                    },
                    {
                        "keywords": "frete,envio,correios,sedex",
                        "response": "O frete é calculado automaticamente pelo Mercado Livre baseado no seu CEP. Enviamos pelos Correios."
                    },
                    {
                        "keywords": "disponível,estoque,tem,disponibilidade",
                        "response": "Sim, temos em estoque! Pode fazer o pedido que enviamos no mesmo dia útil."
                    },
                    {
                        "keywords": "garantia,defeito,problema,troca",
                        "response": "Todos os produtos têm garantia. Em caso de defeito, trocamos ou devolvemos o dinheiro."
                    },
                    {
                        "keywords": "pagamento,cartão,pix,boleto",
                        "response": "Aceitamos todas as formas de pagamento do Mercado Livre: cartão, PIX, boleto."
                    },
                    {
                        "keywords": "nota,fiscal,nf,emite",
                        "response": "Olá, seja bem-vindo à DETTECH, todos os produtos são com nota fiscal, qualquer dúvida estamos à disposição."
                    }
                ]
                
                for rule in default_rules:
                    auto_response = AutoResponse(
                        user_id=user.id,
                        keywords=rule["keywords"],
                        response_text=rule["response"],
                        is_active=True
                    )
                    db.session.add(auto_response)
                
                db.session.commit()
                log_debug(f"{len(default_rules)} regras padrão criadas")
            
            # Criar configurações de ausência padrão
            if AbsenceConfig.query.count() == 0:
                absence_config = AbsenceConfig(
                    user_id=user.id,
                    name="Horário Comercial",
                    message="Olá, seja bem-vindo à DETTECH, a sua mensagem foi recebida com sucesso.",
                    start_time="00:00",
                    end_time="23:59",
                    days_of_week="0,1,2,3,4,5,6",  # Todos os dias
                    is_active=True
                )
                db.session.add(absence_config)
                db.session.commit()
                log_debug("Configuração de ausência criada")
            
            _initialized = True
            log_debug("Banco de dados inicializado com sucesso")
            
    except Exception as e:
        log_debug(f"Erro ao inicializar banco: {e}", "ERROR")

# Função para verificar se está em horário de ausência
def is_absence_time():
    try:
        now = get_local_time()
        current_time = now.strftime("%H:%M")
        current_weekday = str(now.weekday())  # 0=segunda, 6=domingo
        
        log_debug(f"Verificando ausência - Hora: {current_time}, Dia: {current_weekday}")
        
        absence_configs = AbsenceConfig.query.filter_by(is_active=True).all()
        
        for config in absence_configs:
            # Verificar se o dia da semana está incluído
            if current_weekday in config.days_of_week.split(','):
                start_time = config.start_time
                end_time = config.end_time
                
                # Se start_time > end_time, significa que cruza meia-noite
                if start_time > end_time:
                    if current_time >= start_time or current_time <= end_time:
                        log_debug(f"Ausência ativa: {config.name}")
                        return config.message
                else:
                    if start_time <= current_time <= end_time:
                        log_debug(f"Ausência ativa: {config.name}")
                        return config.message
        
        log_debug("Nenhuma ausência ativa")
        return None
        
    except Exception as e:
        log_debug(f"Erro ao verificar ausência: {e}", "ERROR")
        return None

# Função para encontrar resposta automática
def find_auto_response(question_text):
    try:
        log_debug(f"Buscando resposta para: {question_text}")
        
        auto_responses = AutoResponse.query.filter_by(is_active=True).all()
        question_lower = question_text.lower()
        
        for response in auto_responses:
            keywords = [k.strip().lower() for k in response.keywords.split(',')]
            
            for keyword in keywords:
                if keyword in question_lower:
                    log_debug(f"Palavra-chave encontrada: {keyword}")
                    return response.response_text, keyword
        
        log_debug("Nenhuma palavra-chave encontrada")
        return None, None
        
    except Exception as e:
        log_debug(f"Erro ao buscar resposta: {e}", "ERROR")
        return None, None

# Função para enviar resposta
def send_answer(question_id, answer_text):
    try:
        url = f"https://api.mercadolibre.com/answers"
        headers = {
            'Authorization': f'Bearer {ML_ACCESS_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'question_id': int(question_id),
            'text': answer_text
        }
        
        log_debug(f"Enviando resposta para pergunta {question_id}")
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 200:
            log_debug("Resposta enviada com sucesso")
            return True
        else:
            log_debug(f"Erro ao enviar resposta: {response.status_code} - {response.text}", "ERROR")
            return False
            
    except Exception as e:
        log_debug(f"Erro ao enviar resposta: {e}", "ERROR")
        return False

# Função para processar perguntas
def process_questions():
    try:
        with app.app_context():
            log_debug("Iniciando processamento de perguntas")
            
            # Buscar perguntas não respondidas
            url = f"https://api.mercadolibre.com/my/received_questions/search?access_token={ML_ACCESS_TOKEN}"
            response = requests.get(url)
            
            if response.status_code != 200:
                log_debug(f"Erro ao buscar perguntas: {response.status_code}", "ERROR")
                return
            
            data = response.json()
            questions = data.get('questions', [])
            
            log_debug(f"Encontradas {len(questions)} perguntas")
            
            for question in questions:
                if question.get('status') == 'UNANSWERED':
                    question_id = question['id']
                    question_text = question['text']
                    item_id = question['item_id']
                    
                    # Verificar se já processamos esta pergunta
                    existing = Question.query.filter_by(ml_question_id=str(question_id)).first()
                    if existing:
                        continue
                    
                    log_debug(f"Nova pergunta: {question_text}")
                    
                    # Salvar pergunta no banco
                    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
                    if user:
                        new_question = Question(
                            ml_question_id=str(question_id),
                            user_id=user.id,
                            item_id=str(item_id),
                            question_text=question_text,
                            is_answered=False
                        )
                        db.session.add(new_question)
                        db.session.commit()
                    
                    # Verificar ausência primeiro
                    absence_message = is_absence_time()
                    if absence_message:
                        if send_answer(question_id, absence_message):
                            # Salvar no histórico
                            if user:
                                history = ResponseHistory(
                                    user_id=user.id,
                                    question_id=str(question_id),
                                    question_text=question_text,
                                    response_text=absence_message,
                                    response_type='absence'
                                )
                                db.session.add(history)
                                
                                # Atualizar pergunta
                                new_question.is_answered = True
                                new_question.answered_automatically = True
                                new_question.response_text = absence_message
                                new_question.answered_at = datetime.utcnow()
                                
                                db.session.commit()
                                log_debug("Resposta de ausência enviada e salva")
                        continue
                    
                    # Buscar resposta automática
                    auto_response, keyword = find_auto_response(question_text)
                    if auto_response:
                        if send_answer(question_id, auto_response):
                            # Salvar no histórico
                            if user:
                                history = ResponseHistory(
                                    user_id=user.id,
                                    question_id=str(question_id),
                                    question_text=question_text,
                                    response_text=auto_response,
                                    response_type='auto',
                                    keywords_matched=keyword
                                )
                                db.session.add(history)
                                
                                # Atualizar pergunta
                                new_question.is_answered = True
                                new_question.answered_automatically = True
                                new_question.response_text = auto_response
                                new_question.answered_at = datetime.utcnow()
                                
                                db.session.commit()
                                log_debug("Resposta automática enviada e salva")
                    
    except Exception as e:
        log_debug(f"Erro no processamento: {e}", "ERROR")

# Função para executar polling
def run_polling():
    while True:
        try:
            process_questions()
            time.sleep(30)  # Aguardar 30 segundos
        except Exception as e:
            log_debug(f"Erro no polling: {e}", "ERROR")
            time.sleep(60)  # Aguardar 1 minuto em caso de erro

# ========== ROTAS WEB ==========

@app.route('/')
def dashboard():
    """Dashboard principal"""
    try:
        with app.app_context():
            # Estatísticas
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if user:
                today = get_local_time().date()
                
                total_questions = Question.query.filter_by(user_id=user.id).count()
                answered_today = Question.query.filter_by(user_id=user.id, is_answered=True).filter(
                    db.func.date(Question.answered_at) == today
                ).count()
                auto_responses_today = ResponseHistory.query.filter_by(user_id=user.id, response_type='auto').filter(
                    db.func.date(ResponseHistory.created_at) == today
                ).count()
                absence_responses_today = ResponseHistory.query.filter_by(user_id=user.id, response_type='absence').filter(
                    db.func.date(ResponseHistory.created_at) == today
                ).count()
                
                # Tempo médio de resposta
                avg_response = db.session.query(db.func.avg(ResponseHistory.response_time)).filter_by(user_id=user.id).scalar()
                avg_response = round(avg_response, 2) if avg_response else 0
                
                stats = {
                    'total_questions': total_questions,
                    'answered_today': answered_today,
                    'auto_responses_today': auto_responses_today,
                    'absence_responses_today': absence_responses_today,
                    'avg_response_time': avg_response
                }
            else:
                stats = {'total_questions': 0, 'answered_today': 0, 'auto_responses_today': 0, 'absence_responses_today': 0, 'avg_response_time': 0}
            
            # Últimos logs de debug
            recent_logs = DebugLog.query.order_by(DebugLog.created_at.desc()).limit(10).all()
            
            current_time = format_local_time()
            
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Bot ML - Dashboard</title>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                    .container {{ max-width: 1200px; margin: 0 auto; }}
                    .header {{ background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }}
                    .stat-card {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .stat-number {{ font-size: 2em; font-weight: bold; color: #2196F3; }}
                    .stat-label {{ color: #666; margin-top: 5px; }}
                    .nav {{ margin-bottom: 20px; }}
                    .nav a {{ display: inline-block; padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }}
                    .nav a:hover {{ background: #1976D2; }}
                    .debug-logs {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .log-item {{ padding: 5px 0; border-bottom: 1px solid #eee; font-family: monospace; font-size: 12px; }}
                    .log-error {{ color: #f44336; }}
                    .log-info {{ color: #2196F3; }}
                </style>
                <script>
                    setInterval(function() {{ window.location.reload(); }}, 30000); // Atualizar a cada 30 segundos
                </script>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🤖 Bot Mercado Livre - DETTECH</h1>
                        <p><strong>Horário Local (SP):</strong> {current_time}</p>
                        <p><strong>Status:</strong> Sistema funcionando</p>
                    </div>
                    
                    <div class="nav">
                        <a href="/edit-rules">✏️ Editar Regras</a>
                        <a href="/edit-absence">🌙 Configurar Ausência</a>
                        <a href="/history">📊 Histórico</a>
                        <a href="/renovar-tokens" style="background: #ff9800;">🔄 Renovar Tokens</a>
                    </div>
                    
                    <div class="stats">
                        <div class="stat-card">
                            <div class="stat-number">{stats['total_questions']}</div>
                            <div class="stat-label">Total de Perguntas</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{stats['answered_today']}</div>
                            <div class="stat-label">Respondidas Hoje</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number" style="color: {'#4CAF50' if stats['auto_responses_today'] > 0 else '#f44336'}">{stats['auto_responses_today']}</div>
                            <div class="stat-label">Respostas Automáticas Hoje</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number" style="color: {'#ff9800' if stats['absence_responses_today'] > 0 else '#666'}">{stats['absence_responses_today']}</div>
                            <div class="stat-label">Respostas Ausência Hoje</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{stats['avg_response_time']}s</div>
                            <div class="stat-label">Tempo Médio de Resposta</div>
                        </div>
                    </div>
                    
                    <div class="debug-logs">
                        <h3>🔍 Logs de Debug (Últimos 10)</h3>
                        {''.join([f'<div class="log-item log-{log.level.lower()}">[{log.created_at.strftime("%H:%M:%S")}] {log.message}</div>' for log in recent_logs])}
                    </div>
                </div>
            </body>
            </html>
            """
            
            return html
            
    except Exception as e:
        return f"Erro: {e}"

@app.route('/edit-rules')
def edit_rules():
    return "Página de edição de regras em desenvolvimento..."

@app.route('/edit-absence')
def edit_absence():
    return "Página de configuração de ausência em desenvolvimento..."

@app.route('/history')
def history():
    return "Página de histórico em desenvolvimento..."

@app.route('/renovar-tokens')
def renovar_tokens():
    return "Página de renovação de tokens em desenvolvimento..."

# Inicializar aplicação
if __name__ == '__main__':
    initialize_database()
    
    # Iniciar polling em thread separada
    polling_thread = threading.Thread(target=run_polling, daemon=True)
    polling_thread.start()
    log_debug("Polling iniciado")
    
    # Executar aplicação
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)



# ========== SISTEMA DE RENOVAÇÃO DE TOKEN ==========

def generate_auth_url():
    """Gera URL de autorização do ML"""
    redirect_uri = "https://bot-mercadolivre-dettech.onrender.com/api/ml/webhook"
    
    url = (
        f"https://auth.mercadolivre.com.br/authorization?"
        f"response_type=code&"
        f"client_id={ML_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        f"scope=offline_access read write"
    )
    
    return url

def process_auth_code(code):
    """Processa código de autorização e gera novos tokens"""
    try:
        redirect_uris = [
            "https://bot-mercadolivre-dettech.onrender.com/api/ml/webhook",
            "https://bot-mercadolivre-dettech.onrender.com/api/ml/auth-callback"
        ]
        
        for redirect_uri in redirect_uris:
            try:
                url = "https://api.mercadolibre.com/oauth/token"
                data = {
                    'grant_type': 'authorization_code',
                    'client_id': ML_CLIENT_ID,
                    'client_secret': ML_CLIENT_SECRET,
                    'code': code,
                    'redirect_uri': redirect_uri
                }
                
                response = requests.post(url, data=data)
                
                if response.status_code == 200:
                    token_data = response.json()
                    
                    # Atualizar variáveis globais
                    global ML_ACCESS_TOKEN, ML_REFRESH_TOKEN, ML_USER_ID
                    ML_ACCESS_TOKEN = token_data['access_token']
                    ML_REFRESH_TOKEN = token_data.get('refresh_token', '')
                    ML_USER_ID = str(token_data['user_id'])
                    
                    # Atualizar no banco
                    with app.app_context():
                        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
                        if not user:
                            user = User(ml_user_id=ML_USER_ID)
                            db.session.add(user)
                        
                        user.access_token = ML_ACCESS_TOKEN
                        user.refresh_token = ML_REFRESH_TOKEN
                        user.token_expires_at = datetime.utcnow() + timedelta(seconds=token_data.get('expires_in', 21600))
                        user.updated_at = datetime.utcnow()
                        
                        db.session.commit()
                    
                    log_debug(f"Tokens atualizados com sucesso! User ID: {ML_USER_ID}")
                    
                    return {
                        'success': True,
                        'message': 'Tokens atualizados com sucesso!',
                        'access_token': ML_ACCESS_TOKEN,
                        'user_id': ML_USER_ID,
                        'expires_in': token_data.get('expires_in', 21600)
                    }
                    
            except Exception as e:
                log_debug(f"Erro com redirect_uri {redirect_uri}: {e}", "ERROR")
                continue
        
        return {
            'success': False,
            'message': 'Erro ao processar código. Verifique se o código está correto.'
        }
        
    except Exception as e:
        log_debug(f"Erro ao processar código: {e}", "ERROR")
        return {
            'success': False,
            'message': f'Erro: {str(e)}'
        }

@app.route('/renovar-tokens')
def renovar_tokens():
    """Interface para renovação de tokens"""
    auth_url = generate_auth_url()
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Renovar Tokens do Bot</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .card {{ background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .btn {{ padding: 10px 20px; background: #2196F3; color: white; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; }}
            .btn:hover {{ background: #1976D2; }}
            .btn-success {{ background: #4CAF50; }}
            .btn-success:hover {{ background: #45a049; }}
            .form-group {{ margin-bottom: 15px; }}
            .form-control {{ width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }}
            .alert {{ padding: 15px; border-radius: 4px; margin-bottom: 20px; }}
            .alert-info {{ background: #d1ecf1; border: 1px solid #bee5eb; color: #0c5460; }}
            .alert-danger {{ background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }}
            .alert-success {{ background: #d4edda; border: 1px solid #c3e6cb; color: #155724; }}
            .step {{ background: #f8f9fa; padding: 15px; border-left: 4px solid #2196F3; margin-bottom: 15px; }}
            .nav {{ margin-bottom: 20px; }}
            .nav a {{ display: inline-block; padding: 10px 20px; background: #6c757d; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>🔄 Renovar Tokens do Bot</h1>
                <div class="nav">
                    <a href="/">🏠 Dashboard</a>
                    <a href="/edit-rules">✏️ Regras</a>
                    <a href="/history">📊 Histórico</a>
                </div>
            </div>
            
            <div class="card">
                <div class="alert alert-info">
                    <h3>📋 Como Renovar os Tokens</h3>
                    <p>Este processo gera novos tokens de acesso que duram 6 horas e refresh tokens para renovação automática.</p>
                </div>
                
                <div class="step">
                    <h4>🔗 Passo 1: Autorizar Aplicação</h4>
                    <p>Clique no botão abaixo para abrir a página de autorização do Mercado Livre:</p>
                    <a href="{auth_url}" target="_blank" class="btn">🌐 Abrir Autorização do ML</a>
                </div>
                
                <div class="step">
                    <h4>🔑 Passo 2: Obter Código</h4>
                    <p>Após autorizar:</p>
                    <ol>
                        <li>✅ Faça login no Mercado Livre</li>
                        <li>✅ Autorize a aplicação</li>
                        <li>✅ Você será redirecionado (pode dar erro, é normal)</li>
                        <li>✅ Copie o código da URL (ex: TG-abc123...)</li>
                    </ol>
                </div>
                
                <div class="step">
                    <h4>🔄 Passo 3: Processar Código</h4>
                    <p>Cole o código de autorização aqui:</p>
                    <div class="form-group">
                        <input type="text" id="authCode" class="form-control" placeholder="TG-68839cdf8b73a2000176ea5f-180617463" />
                    </div>
                    <button class="btn btn-success" onclick="processCode()">🔄 Processar e Atualizar Tokens</button>
                </div>
                
                <div id="result"></div>
            </div>
            
            <div class="card">
                <h3>🔗 URL de Redirect Configurada</h3>
                <p><code>https://bot-mercadolivre-dettech.onrender.com/api/ml/webhook</code></p>
                <p>Esta URL deve estar configurada no painel de desenvolvedores do Mercado Livre.</p>
            </div>
        </div>
        
        <script>
            function processCode() {{
                const code = document.getElementById('authCode').value.trim();
                const resultDiv = document.getElementById('result');
                
                if (!code) {{
                    resultDiv.innerHTML = '<div class="alert alert-danger">Por favor, insira o código de autorização.</div>';
                    return;
                }}
                
                resultDiv.innerHTML = '<div class="alert alert-info">🔄 Processando código...</div>';
                
                fetch('/api/tokens/process-code', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{ code: code }})
                }})
                .then(response => response.json())
                .then(data => {{
                    if (data.success) {{
                        resultDiv.innerHTML = `
                            <div class="alert alert-success">
                                <h4>✅ Tokens Atualizados com Sucesso!</h4>
                                <p><strong>User ID:</strong> ${{data.user_id}}</p>
                                <p><strong>Token:</strong> ${{data.access_token.substring(0, 20)}}...</p>
                                <p><strong>Expira em:</strong> ${{data.expires_in}} segundos</p>
                                <p>O sistema já está usando os novos tokens!</p>
                            </div>
                        `;
                    }} else {{
                        resultDiv.innerHTML = `
                            <div class="alert alert-danger">
                                <h4>❌ Erro ao Processar Código</h4>
                                <p>${{data.message}}</p>
                            </div>
                        `;
                    }}
                }})
                .catch(error => {{
                    resultDiv.innerHTML = `
                        <div class="alert alert-danger">
                            <h4>❌ Erro de Conexão</h4>
                            <p>${{error.message}}</p>
                        </div>
                    `;
                }});
            }}
        </script>
    </body>
    </html>
    """
    
    return html

@app.route('/api/tokens/process-code', methods=['POST'])
def api_process_code():
    """API para processar código de autorização"""
    try:
        data = request.get_json()
        code = data.get('code', '').strip()
        
        if not code:
            return jsonify({'success': False, 'message': 'Código não fornecido'})
        
        result = process_auth_code(code)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Erro: {str(e)}'})

@app.route('/api/ml/webhook', methods=['GET', 'POST'])
def ml_webhook():
    """Webhook para receber códigos de autorização"""
    try:
        if request.method == 'GET':
            code = request.args.get('code')
            if code:
                result = process_auth_code(code)
                if result['success']:
                    return f"""
                    <html>
                    <head><title>Tokens Atualizados</title></head>
                    <body>
                        <h1>✅ Tokens Atualizados com Sucesso!</h1>
                        <p>User ID: {result['user_id']}</p>
                        <p>O sistema já está usando os novos tokens.</p>
                        <p><a href="/">Voltar ao Dashboard</a></p>
                    </body>
                    </html>
                    """
                else:
                    return f"""
                    <html>
                    <head><title>Erro</title></head>
                    <body>
                        <h1>❌ Erro ao Processar Código</h1>
                        <p>{result['message']}</p>
                        <p><a href="/renovar-tokens">Tentar Novamente</a></p>
                    </body>
                    </html>
                    """
            else:
                return "Webhook funcionando - aguardando código de autorização"
        
        # POST - notificações do ML
        return jsonify({'status': 'received'})
        
    except Exception as e:
        log_debug(f"Erro no webhook: {e}", "ERROR")
        return jsonify({'error': str(e)}), 500

