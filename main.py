import os
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests
import sqlite3
import pytz

# Configuração da aplicação
app = Flask(__name__)
CORS(app)

# Configuração do fuso horário
TIMEZONE = pytz.timezone('America/Sao_Paulo')

def get_local_time():
    """Retorna o horário atual no fuso horário local"""
    return datetime.now(TIMEZONE)

def get_local_time_utc():
    """Retorna o horário atual em UTC para salvar no banco"""
    return datetime.utcnow()

def format_local_time(utc_datetime):
    """Converte UTC para horário local para exibição"""
    if utc_datetime is None:
        return None
    utc_dt = pytz.utc.localize(utc_datetime)
    local_dt = utc_dt.astimezone(TIMEZONE)
    return local_dt

# Configuração do banco SQLite persistente
DATA_DIR = os.getenv('DATA_DIR', '/opt/render/project/src/data')
if not os.path.exists(DATA_DIR):
    DATA_DIR = './data'
    os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_PATH = os.path.join(DATA_DIR, 'bot_ml.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configurações do Mercado Livre - TOKENS ATUALIZADOS
ML_CLIENT_ID = os.getenv('ML_CLIENT_ID', '5510376630479325')
ML_CLIENT_SECRET = os.getenv('ML_CLIENT_SECRET', 'jlR4As2x8uFY3RTpysLpuPhzC9yM9d35')
ML_ACCESS_TOKEN = os.getenv('ML_ACCESS_TOKEN', 'APP_USR-5510376630479325-072423-41cbc33fddb983f73eaf5aa1b1b7f699-180617463')
ML_USER_ID = os.getenv('ML_USER_ID', '180617463')

# Modelos do banco de dados
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    ml_user_id = db.Column(db.String(50), unique=True, nullable=False)
    access_token = db.Column(db.String(200), nullable=False)
    refresh_token = db.Column(db.String(200))
    token_expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=get_local_time_utc)
    updated_at = db.Column(db.DateTime, default=get_local_time_utc, onupdate=get_local_time_utc)

class AutoResponse(db.Model):
    __tablename__ = 'auto_responses'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    keywords = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_local_time_utc)
    updated_at = db.Column(db.DateTime, default=get_local_time_utc, onupdate=get_local_time_utc)

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
    created_at = db.Column(db.DateTime, default=get_local_time_utc)
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
    created_at = db.Column(db.DateTime, default=get_local_time_utc)

class ResponseHistory(db.Model):
    __tablename__ = 'response_history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    response_type = db.Column(db.String(20), nullable=False)  # 'auto', 'absence', 'manual'
    keywords_matched = db.Column(db.String(200))
    response_time = db.Column(db.Float)  # tempo em segundos para responder
    created_at = db.Column(db.DateTime, default=get_local_time_utc)

# Variável global para controlar inicialização
_initialized = False
_db_lock = threading.Lock()

# Função para criar tabelas e dados iniciais
def initialize_database():
    global _initialized
    if _initialized:
        return
    
    try:
        with _db_lock:
            with app.app_context():
                db.create_all()
                
                # Criar usuário padrão
                user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
                if not user:
                    user = User(
                        ml_user_id=ML_USER_ID,
                        access_token=ML_ACCESS_TOKEN,
                        token_expires_at=get_local_time_utc() + timedelta(hours=6)
                    )
                    db.session.add(user)
                    db.session.commit()
                
                # Criar regras padrão se não existirem
                if AutoResponse.query.count() == 0:
                    default_rules = [
                        {
                            "keywords": "preço, valor, quanto custa",
                            "response": "O preço está na descrição do produto. Qualquer dúvida, estamos à disposição!"
                        },
                        {
                            "keywords": "entrega, prazo, demora",
                            "response": "O prazo de entrega aparece na página do produto. Enviamos pelos Correios com código de rastreamento."
                        },
                        {
                            "keywords": "frete, envio, correios",
                            "response": "O frete é calculado automaticamente pelo Mercado Livre baseado no seu CEP. Enviamos pelos Correios."
                        },
                        {
                            "keywords": "disponível, estoque, tem",
                            "response": "Sim, temos em estoque! Pode fazer o pedido que enviamos no mesmo dia útil."
                        },
                        {
                            "keywords": "garantia, defeito, problema",
                            "response": "Todos os produtos têm garantia. Em caso de defeito, trocamos ou devolvemos o dinheiro."
                        },
                        {
                            "keywords": "pagamento, cartão, pix",
                            "response": "Aceitamos todas as formas de pagamento do Mercado Livre: cartão, PIX, boleto."
                        },
                        {
                            "keywords": "tamanho, medida, dimensão",
                            "response": "As medidas estão na descrição do produto. Qualquer dúvida específica, me avise!"
                        },
                        {
                            "keywords": "cor, cores, colorido",
                            "response": "As cores disponíveis estão nas opções do anúncio. Se não aparecer, é porque está em falta."
                        },
                        {
                            "keywords": "usado, novo, estado",
                            "response": "Todos os nossos produtos são novos, lacrados e com nota fiscal."
                        },
                        {
                            "keywords": "desconto, promoção, oferta",
                            "response": "Este já é nosso melhor preço! Aproveite que temos frete grátis para sua região."
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
                    print(f"✅ {len(default_rules)} regras padrão criadas!")
                
                # Criar configurações de ausência padrão
                if AbsenceConfig.query.count() == 0:
                    absence_configs = [
                        {
                            "name": "Horário Comercial",
                            "message": "Obrigado pela pergunta! Nosso horário de atendimento é das 8h às 18h, de segunda a sexta. Responderemos assim que possível!",
                            "start_time": "18:00",
                            "end_time": "08:00",
                            "days_of_week": "0,1,2,3,4"  # Segunda a sexta
                        },
                        {
                            "name": "Final de Semana",
                            "message": "Obrigado pela pergunta! Não atendemos aos finais de semana, mas responderemos na segunda-feira. Bom final de semana!",
                            "start_time": "00:00",
                            "end_time": "23:59",
                            "days_of_week": "5,6"  # Sábado e domingo
                        }
                    ]
                    
                    for config in absence_configs:
                        absence = AbsenceConfig(
                            user_id=user.id,
                            name=config["name"],
                            message=config["message"],
                            start_time=config["start_time"],
                            end_time=config["end_time"],
                            days_of_week=config["days_of_week"],
                            is_active=True
                        )
                        db.session.add(absence)
                    
                    db.session.commit()
                    print(f"✅ {len(absence_configs)} configurações de ausência criadas!")
                
                _initialized = True
                print(f"✅ Banco de dados inicializado com sucesso em: {DATABASE_PATH}")
                print(f"🕐 Fuso horário configurado: {TIMEZONE}")
                
    except Exception as e:
        print(f"❌ Erro ao inicializar banco: {e}")

# Função para verificar se está em horário de ausência
def is_absence_time():
    now = get_local_time()
    current_time = now.strftime("%H:%M")
    current_weekday = str(now.weekday())  # 0=segunda, 6=domingo
    
    absence_configs = AbsenceConfig.query.filter_by(is_active=True).all()
    
    for config in absence_configs:
        if current_weekday in config.days_of_week.split(','):
            start_time = config.start_time
            end_time = config.end_time
            
            # Se start_time > end_time, significa que cruza meia-noite
            if start_time > end_time:
                if current_time >= start_time or current_time <= end_time:
                    return config.message
            else:
                if start_time <= current_time <= end_time:
                    return config.message
    
    return None

# Função para encontrar resposta automática
def find_auto_response(question_text):
    question_lower = question_text.lower()
    
    auto_responses = AutoResponse.query.filter_by(is_active=True).all()
    
    for response in auto_responses:
        keywords = [k.strip().lower() for k in response.keywords.split(',')]
        
        for keyword in keywords:
            if keyword in question_lower:
                return response.response_text, response.keywords
    
    return None, None

# Função para responder pergunta no ML
def answer_question_ml(question_id, answer_text):
    url = f"https://api.mercadolibre.com/answers"
    
    headers = {
        "Authorization": f"Bearer {ML_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = {
        "question_id": question_id,
        "text": answer_text
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            return True
        else:
            print(f"❌ Erro ao responder pergunta {question_id}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Erro na requisição: {e}")
        return False

# Função para buscar perguntas não respondidas
def fetch_unanswered_questions():
    url = f"https://api.mercadolibre.com/my/received_questions/search"
    
    headers = {
        "Authorization": f"Bearer {ML_ACCESS_TOKEN}"
    }
    
    params = {
        "status": "UNANSWERED",
        "limit": 50
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json().get("questions", [])
        else:
            print(f"❌ Erro ao buscar perguntas: {response.status_code}")
            return []
    except Exception as e:
        print(f"❌ Erro na requisição: {e}")
        return []

# Função para processar perguntas automaticamente
def process_questions():
    try:
        with _db_lock:
            with app.app_context():
                questions = fetch_unanswered_questions()
                
                if not questions:
                    return
                
                user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
                if not user:
                    return
                
                for q in questions:
                    question_id = str(q.get("id"))
                    question_text = q.get("text", "")
                    item_id = q.get("item_id", "")
                    
                    # Verificar se já processamos esta pergunta
                    existing = Question.query.filter_by(ml_question_id=question_id).first()
                    if existing:
                        continue
                    
                    start_time = time.time()
                    
                    # Salvar pergunta no banco
                    question = Question(
                        ml_question_id=question_id,
                        user_id=user.id,
                        item_id=item_id,
                        question_text=question_text,
                        is_answered=False
                    )
                    db.session.add(question)
                    db.session.flush()  # Para obter o ID
                    
                    response_type = None
                    keywords_matched = None
                    
                    # Verificar se está em horário de ausência
                    absence_message = is_absence_time()
                    if absence_message:
                        if answer_question_ml(question_id, absence_message):
                            question.response_text = absence_message
                            question.is_answered = True
                            question.answered_automatically = True
                            question.answered_at = get_local_time_utc()
                            response_type = "absence"
                            print(f"✅ Pergunta {question_id} respondida com mensagem de ausência")
                    else:
                        # Buscar resposta automática
                        auto_response, matched_keywords = find_auto_response(question_text)
                        if auto_response:
                            if answer_question_ml(question_id, auto_response):
                                question.response_text = auto_response
                                question.is_answered = True
                                question.answered_automatically = True
                                question.answered_at = get_local_time_utc()
                                response_type = "auto"
                                keywords_matched = matched_keywords
                                print(f"✅ Pergunta {question_id} respondida automaticamente")
                    
                    # Salvar histórico de resposta
                    if response_type:
                        response_time = time.time() - start_time
                        history = ResponseHistory(
                            user_id=user.id,
                            question_id=question.id,
                            response_type=response_type,
                            keywords_matched=keywords_matched,
                            response_time=response_time
                        )
                        db.session.add(history)
                    
                    db.session.commit()
    except Exception as e:
        print(f"❌ Erro ao processar perguntas: {e}")

# Função de monitoramento contínuo
def monitor_questions():
    while True:
        try:
            process_questions()
            time.sleep(60)  # Verificar a cada 60 segundos
        except Exception as e:
            print(f"❌ Erro no monitoramento: {e}")
            time.sleep(60)

# Função para obter estatísticas em tempo real
def get_real_time_stats():
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return {}
    
    # Estatísticas básicas
    total_questions = Question.query.filter_by(user_id=user.id).count()
    answered_auto = Question.query.filter_by(user_id=user.id, answered_automatically=True).count()
    pending_questions = Question.query.filter_by(user_id=user.id, is_answered=False).count()
    
    # Estatísticas de hoje (usando horário local)
    today = get_local_time().date()
    today_questions = Question.query.filter_by(user_id=user.id).filter(
        db.func.date(Question.created_at) == today
    ).count()
    
    today_answered = Question.query.filter_by(user_id=user.id, answered_automatically=True).filter(
        db.func.date(Question.answered_at) == today
    ).count()
    
    # Estatísticas por tipo de resposta
    auto_responses = ResponseHistory.query.filter_by(user_id=user.id, response_type='auto').count()
    absence_responses = ResponseHistory.query.filter_by(user_id=user.id, response_type='absence').count()
    
    # Taxa de sucesso
    success_rate = round((answered_auto / total_questions * 100) if total_questions > 0 else 0, 1)
    
    # Contadores de configurações
    active_rules = AutoResponse.query.filter_by(user_id=user.id, is_active=True).count()
    absence_configs = AbsenceConfig.query.filter_by(user_id=user.id, is_active=True).count()
    
    # Tempo médio de resposta
    avg_response_time = db.session.query(db.func.avg(ResponseHistory.response_time)).filter_by(user_id=user.id).scalar()
    avg_response_time = round(avg_response_time, 2) if avg_response_time else 0
    
    return {
        'total_questions': total_questions,
        'answered_auto': answered_auto,
        'pending_questions': pending_questions,
        'today_questions': today_questions,
        'today_answered': today_answered,
        'auto_responses': auto_responses,
        'absence_responses': absence_responses,
        'success_rate': success_rate,
        'active_rules': active_rules,
        'absence_configs': absence_configs,
        'avg_response_time': avg_response_time
    }

# Rotas da aplicação
@app.route('/')
def dashboard():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    # Obter estatísticas em tempo real
    stats = get_real_time_stats()
    
    # Status do token
    token_status = "Válido" if user.token_expires_at and user.token_expires_at > get_local_time_utc() else "Expirado"
    
    # Horário local atual
    current_local_time = get_local_time().strftime('%H:%M:%S')
    
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Bot Mercado Livre - Dashboard</title>
        <meta http-equiv="refresh" content="30">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
            .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; }}
            .header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
            .header p {{ font-size: 1.2em; opacity: 0.9; }}
            .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
            .stat-card {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); text-align: center; }}
            .stat-number {{ font-size: 2.5em; font-weight: bold; color: #3483fa; margin-bottom: 8px; }}
            .stat-label {{ font-size: 1em; color: #666; }}
            .today-stats {{ background: linear-gradient(135deg, #00a650, #00d862); color: white; }}
            .today-stats .stat-number {{ color: white; }}
            .today-stats .stat-label {{ color: rgba(255,255,255,0.9); }}
            .status {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 25px; margin-bottom: 30px; }}
            .status-card {{ padding: 25px; background: white; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
            .status-card.connected {{ border-left: 6px solid #00a650; }}
            .status-card.warning {{ border-left: 6px solid #ff9500; }}
            .status-card h3 {{ margin-bottom: 15px; font-size: 1.3em; }}
            .navigation {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; }}
            .nav-card {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); text-align: center; }}
            .nav-card a {{ text-decoration: none; color: #3483fa; font-weight: bold; font-size: 1.1em; }}
            .nav-card:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.12); }}
            .performance {{ background: linear-gradient(135deg, #ff6900, #fcb900); color: white; }}
            .performance .stat-number {{ color: white; }}
            .performance .stat-label {{ color: rgba(255,255,255,0.9); }}
            .timezone-info {{ background: linear-gradient(135deg, #6f42c1, #8e44ad); color: white; }}
            .timezone-info .stat-number {{ color: white; font-size: 1.8em; }}
            .timezone-info .stat-label {{ color: rgba(255,255,255,0.9); }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Bot do Mercado Livre</h1>
                <p>Sistema Automatizado de Respostas - Fuso Horário: America/Sao_Paulo</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{stats['total_questions']}</div>
                    <div class="stat-label">Total de Perguntas</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['answered_auto']}</div>
                    <div class="stat-label">Respondidas Automaticamente</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['pending_questions']}</div>
                    <div class="stat-label">Aguardando Resposta</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats['success_rate']}%</div>
                    <div class="stat-label">Taxa de Sucesso</div>
                </div>
                <div class="stat-card today-stats">
                    <div class="stat-number">{stats['today_questions']}</div>
                    <div class="stat-label">Perguntas Hoje</div>
                </div>
                <div class="stat-card today-stats">
                    <div class="stat-number">{stats['today_answered']}</div>
                    <div class="stat-label">Respondidas Hoje</div>
                </div>
                <div class="stat-card performance">
                    <div class="stat-number">{stats['avg_response_time']}s</div>
                    <div class="stat-label">Tempo Médio de Resposta</div>
                </div>
                <div class="stat-card timezone-info">
                    <div class="stat-number">{current_local_time}</div>
                    <div class="stat-label">Horário Local (SP)</div>
                </div>
            </div>
            
            <div class="status">
                <div class="status-card connected">
                    <h3>✅ Status da Conexão</h3>
                    <p><strong>Status:</strong> Conectado</p>
                    <p><strong>Token:</strong> {token_status}</p>
                    <p><strong>Monitoramento:</strong> Ativo</p>
                    <p><strong>Banco:</strong> Persistente ({DATABASE_PATH})</p>
                    <p><strong>Fuso Horário:</strong> America/Sao_Paulo</p>
                </div>
                <div class="status-card connected">
                    <h3>📊 Configurações e Histórico</h3>
                    <p><strong>Regras Ativas:</strong> {stats['active_rules']}</p>
                    <p><strong>Configurações de Ausência:</strong> {stats['absence_configs']}</p>
                    <p><strong>Respostas Automáticas:</strong> {stats['auto_responses']}</p>
                    <p><strong>Respostas de Ausência:</strong> {stats['absence_responses']}</p>
                    <p><strong>Última Verificação:</strong> {current_local_time}</p>
                </div>
            </div>
            
            <div class="navigation">
                <div class="nav-card">
                    <h3>📋 Regras de Resposta</h3>
                    <p>Gerenciar respostas automáticas</p>
                    <a href="/rules">Acessar →</a>
                </div>
                <div class="nav-card">
                    <h3>✏️ Editar Regras</h3>
                    <p>Interface de edição</p>
                    <a href="/edit-rules">Editar →</a>
                </div>
                <div class="nav-card">
                    <h3>❓ Perguntas Recebidas</h3>
                    <p>Histórico de perguntas</p>
                    <a href="/questions">Acessar →</a>
                </div>
                <div class="nav-card">
                    <h3>📈 Histórico de Respostas</h3>
                    <p>Análise detalhada</p>
                    <a href="/history">Acessar →</a>
                </div>
                <div class="nav-card">
                    <h3>🌙 Configurações de Ausência</h3>
                    <p>Mensagens automáticas</p>
                    <a href="/absence">Acessar →</a>
                </div>
                <div class="nav-card">
                    <h3>✏️ Editar Ausência</h3>
                    <p>Interface de edição</p>
                    <a href="/edit-absence">Editar →</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html

