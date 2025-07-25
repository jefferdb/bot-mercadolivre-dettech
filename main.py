import os
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests
import sqlite3

# Configuração da aplicação
app = Flask(__name__)
CORS(app)

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
ML_ACCESS_TOKEN = 'APP_USR-5510376630479325-072518-55567b6ae0602cf4fe790826d4cdda45-180617463'
ML_CLIENT_ID = '5510376630479325'
ML_CLIENT_SECRET = 'jlR4As2x8uFY3RTpysLpuPhzC9yM9d35'
ML_USER_ID = '180617463'

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
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    response_type = db.Column(db.String(20), nullable=False)  # 'auto', 'absence', 'manual'
    keywords_matched = db.Column(db.String(200))
    response_time = db.Column(db.Float)  # tempo em segundos para responder
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
                        token_expires_at=datetime.utcnow() + timedelta(hours=6)
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
                
    except Exception as e:
        print(f"❌ Erro ao inicializar banco: {e}")

# Função para verificar se está em horário de ausência
def is_absence_time():
    now = datetime.now()
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
                            question.answered_at = datetime.utcnow()
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
                                question.answered_at = datetime.utcnow()
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
    
    # Estatísticas de hoje
    today = datetime.now().date()
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
    token_status = "Válido" if user.token_expires_at and user.token_expires_at > datetime.utcnow() else "Expirado"
    
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
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Bot do Mercado Livre</h1>
                <p>Sistema Automatizado de Respostas - Banco Persistente Ativo</p>
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
            </div>
            
            <div class="status">
                <div class="status-card connected">
                    <h3>✅ Status da Conexão</h3>
                    <p><strong>Status:</strong> Conectado</p>
                    <p><strong>Token:</strong> {token_status}</p>
                    <p><strong>Monitoramento:</strong> Ativo</p>
                    <p><strong>Banco:</strong> Persistente ({DATABASE_PATH})</p>
                </div>
                <div class="status-card connected">
                    <h3>📊 Configurações e Histórico</h3>
                    <p><strong>Regras Ativas:</strong> {stats['active_rules']}</p>
                    <p><strong>Configurações de Ausência:</strong> {stats['absence_configs']}</p>
                    <p><strong>Respostas Automáticas:</strong> {stats['auto_responses']}</p>
                    <p><strong>Respostas de Ausência:</strong> {stats['absence_responses']}</p>
                    <p><strong>Última Verificação:</strong> {datetime.now().strftime('%H:%M:%S')}</p>
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



@app.route('/edit-rules')
def edit_rules_page():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    rules = AutoResponse.query.filter_by(user_id=user.id).all()
    
    html = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Editar Regras - Bot ML</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }
            .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }
            .back-btn { display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }
            .form-card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin-bottom: 20px; }
            .form-group { margin-bottom: 15px; }
            .form-group label { display: block; margin-bottom: 5px; font-weight: bold; }
            .form-group input, .form-group textarea { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }
            .form-group textarea { height: 80px; resize: vertical; }
            .btn { background: #3483fa; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }
            .btn:hover { background: #2968c8; }
            .btn-danger { background: #dc3545; }
            .btn-danger:hover { background: #c82333; }
            .btn-success { background: #28a745; }
            .btn-success:hover { background: #218838; }
            .rule-item { border: 1px solid #ddd; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
            .rule-header { display: flex; justify-content: between; align-items: center; margin-bottom: 10px; }
            .status-toggle { margin-left: auto; }
            .alert { padding: 15px; margin-bottom: 20px; border-radius: 5px; }
            .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
            .alert-error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            
            <div class="header">
                <h1>✏️ Editar Regras de Resposta</h1>
                <p>Gerencie suas respostas automáticas</p>
            </div>
            
            <div id="alert-container"></div>
            
            <!-- Formulário para nova regra -->
            <div class="form-card">
                <h3>➕ Adicionar Nova Regra</h3>
                <form id="new-rule-form">
                    <div class="form-group">
                        <label for="keywords">Palavras-chave (separadas por vírgula):</label>
                        <input type="text" id="keywords" name="keywords" required placeholder="preço, valor, quanto custa">
                    </div>
                    <div class="form-group">
                        <label for="response">Resposta automática:</label>
                        <textarea id="response" name="response" required placeholder="Digite a resposta que será enviada automaticamente..."></textarea>
                    </div>
                    <button type="submit" class="btn">Adicionar Regra</button>
                </form>
            </div>
            
            <!-- Lista de regras existentes -->
            <div class="form-card">
                <h3>📋 Regras Existentes</h3>
                <div id="rules-list">
    """
    
    for rule in rules:
        status_checked = "checked" if rule.is_active else ""
        html += f"""
                    <div class="rule-item" data-rule-id="{rule.id}">
                        <div class="rule-header">
                            <h4>Regra #{rule.id}</h4>
                            <label class="status-toggle">
                                <input type="checkbox" {status_checked} onchange="toggleRule({rule.id})"> Ativa
                            </label>
                        </div>
                        <div class="form-group">
                            <label>Palavras-chave:</label>
                            <input type="text" value="{rule.keywords}" onchange="updateRule({rule.id}, 'keywords', this.value)">
                        </div>
                        <div class="form-group">
                            <label>Resposta:</label>
                            <textarea onchange="updateRule({rule.id}, 'response', this.value)">{rule.response_text}</textarea>
                        </div>
                        <button class="btn btn-danger" onclick="deleteRule({rule.id})">🗑️ Excluir</button>
                    </div>
        """
    
    html += """
                </div>
            </div>
        </div>
        
        <script>
            function showAlert(message, type = 'success') {
                const container = document.getElementById('alert-container');
                const alert = document.createElement('div');
                alert.className = `alert alert-${type}`;
                alert.textContent = message;
                container.appendChild(alert);
                setTimeout(() => alert.remove(), 3000);
            }
            
            // Adicionar nova regra
            document.getElementById('new-rule-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                
                try {
                    const response = await fetch('/api/rules', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            keywords: formData.get('keywords'),
                            response: formData.get('response')
                        })
                    });
                    
                    if (response.ok) {
                        showAlert('Regra adicionada com sucesso!');
                        setTimeout(() => location.reload(), 1000);
                    } else {
                        showAlert('Erro ao adicionar regra', 'error');
                    }
                } catch (error) {
                    showAlert('Erro de conexão', 'error');
                }
            });
            
            // Atualizar regra
            async function updateRule(ruleId, field, value) {
                try {
                    const response = await fetch(`/api/rules/${ruleId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ [field]: value })
                    });
                    
                    if (response.ok) {
                        showAlert('Regra atualizada!');
                    } else {
                        showAlert('Erro ao atualizar regra', 'error');
                    }
                } catch (error) {
                    showAlert('Erro de conexão', 'error');
                }
            }
            
            // Alternar status da regra
            async function toggleRule(ruleId) {
                const checkbox = document.querySelector(`[data-rule-id="${ruleId}"] input[type="checkbox"]`);
                
                try {
                    const response = await fetch(`/api/rules/${ruleId}/toggle`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ active: checkbox.checked })
                    });
                    
                    if (response.ok) {
                        showAlert(`Regra ${checkbox.checked ? 'ativada' : 'desativada'}!`);
                    } else {
                        showAlert('Erro ao alterar status', 'error');
                        checkbox.checked = !checkbox.checked;
                    }
                } catch (error) {
                    showAlert('Erro de conexão', 'error');
                    checkbox.checked = !checkbox.checked;
                }
            }
            
            // Excluir regra
            async function deleteRule(ruleId) {
                if (!confirm('Tem certeza que deseja excluir esta regra?')) return;
                
                try {
                    const response = await fetch(`/api/rules/${ruleId}`, {
                        method: 'DELETE'
                    });
                    
                    if (response.ok) {
                        showAlert('Regra excluída!');
                        document.querySelector(`[data-rule-id="${ruleId}"]`).remove();
                    } else {
                        showAlert('Erro ao excluir regra', 'error');
                    }
                } catch (error) {
                    showAlert('Erro de conexão', 'error');
                }
            }
        </script>
    </body>
    </html>
    """
    return html

@app.route('/edit-absence')
def edit_absence_page():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    configs = AbsenceConfig.query.filter_by(user_id=user.id).all()
    
    html = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Editar Configurações de Ausência - Bot ML</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }
            .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }
            .back-btn { display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }
            .form-card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin-bottom: 20px; }
            .form-group { margin-bottom: 15px; }
            .form-group label { display: block; margin-bottom: 5px; font-weight: bold; }
            .form-group input, .form-group textarea, .form-group select { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }
            .form-group textarea { height: 80px; resize: vertical; }
            .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
            .checkbox-group { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
            .checkbox-item { display: flex; align-items: center; }
            .checkbox-item input { width: auto; margin-right: 8px; }
            .btn { background: #3483fa; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }
            .btn:hover { background: #2968c8; }
            .btn-danger { background: #dc3545; }
            .btn-danger:hover { background: #c82333; }
            .config-item { border: 1px solid #ddd; padding: 15px; margin-bottom: 10px; border-radius: 5px; }
            .config-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
            .status-toggle { margin-left: auto; }
            .alert { padding: 15px; margin-bottom: 20px; border-radius: 5px; }
            .alert-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
            .alert-error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            
            <div class="header">
                <h1>🌙 Editar Configurações de Ausência</h1>
                <p>Gerencie mensagens automáticas por horário</p>
            </div>
            
            <div id="alert-container"></div>
            
            <!-- Formulário para nova configuração -->
            <div class="form-card">
                <h3>➕ Adicionar Nova Configuração</h3>
                <form id="new-config-form">
                    <div class="form-group">
                        <label for="name">Nome da configuração:</label>
                        <input type="text" id="name" name="name" required placeholder="Ex: Horário de Almoço">
                    </div>
                    <div class="form-group">
                        <label for="message">Mensagem de ausência:</label>
                        <textarea id="message" name="message" required placeholder="Digite a mensagem que será enviada durante este período..."></textarea>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="start_time">Horário de início:</label>
                            <input type="time" id="start_time" name="start_time" required>
                        </div>
                        <div class="form-group">
                            <label for="end_time">Horário de fim:</label>
                            <input type="time" id="end_time" name="end_time" required>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Dias da semana:</label>
                        <div class="checkbox-group">
                            <div class="checkbox-item">
                                <input type="checkbox" id="day0" name="days" value="0">
                                <label for="day0">Segunda</label>
                            </div>
                            <div class="checkbox-item">
                                <input type="checkbox" id="day1" name="days" value="1">
                                <label for="day1">Terça</label>
                            </div>
                            <div class="checkbox-item">
                                <input type="checkbox" id="day2" name="days" value="2">
                                <label for="day2">Quarta</label>
                            </div>
                            <div class="checkbox-item">
                                <input type="checkbox" id="day3" name="days" value="3">
                                <label for="day3">Quinta</label>
                            </div>
                            <div class="checkbox-item">
                                <input type="checkbox" id="day4" name="days" value="4">
                                <label for="day4">Sexta</label>
                            </div>
                            <div class="checkbox-item">
                                <input type="checkbox" id="day5" name="days" value="5">
                                <label for="day5">Sábado</label>
                            </div>
                            <div class="checkbox-item">
                                <input type="checkbox" id="day6" name="days" value="6">
                                <label for="day6">Domingo</label>
                            </div>
                        </div>
                    </div>
                    <button type="submit" class="btn">Adicionar Configuração</button>
                </form>
            </div>
            
            <!-- Lista de configurações existentes -->
            <div class="form-card">
                <h3>⚙️ Configurações Existentes</h3>
                <div id="configs-list">
    """
    
    days_map = {
        "0": "Segunda", "1": "Terça", "2": "Quarta", 
        "3": "Quinta", "4": "Sexta", "5": "Sábado", "6": "Domingo"
    }
    
    for config in configs:
        status_checked = "checked" if config.is_active else ""
        days = [days_map.get(d, d) for d in config.days_of_week.split(',')]
        
        html += f"""
                    <div class="config-item" data-config-id="{config.id}">
                        <div class="config-header">
                            <h4>{config.name}</h4>
                            <label class="status-toggle">
                                <input type="checkbox" {status_checked} onchange="toggleConfig({config.id})"> Ativa
                            </label>
                        </div>
                        <div class="form-group">
                            <label>Nome:</label>
                            <input type="text" value="{config.name}" onchange="updateConfig({config.id}, 'name', this.value)">
                        </div>
                        <div class="form-group">
                            <label>Mensagem:</label>
                            <textarea onchange="updateConfig({config.id}, 'message', this.value)">{config.message}</textarea>
                        </div>
                        <div class="form-row">
                            <div class="form-group">
                                <label>Início:</label>
                                <input type="time" value="{config.start_time}" onchange="updateConfig({config.id}, 'start_time', this.value)">
                            </div>
                            <div class="form-group">
                                <label>Fim:</label>
                                <input type="time" value="{config.end_time}" onchange="updateConfig({config.id}, 'end_time', this.value)">
                            </div>
                        </div>
                        <div class="form-group">
                            <label>Dias: {', '.join(days)}</label>
                            <input type="text" value="{config.days_of_week}" onchange="updateConfig({config.id}, 'days_of_week', this.value)" placeholder="0,1,2,3,4">
                        </div>
                        <button class="btn btn-danger" onclick="deleteConfig({config.id})">🗑️ Excluir</button>
                    </div>
        """
    
    html += """
                </div>
            </div>
        </div>
        
        <script>
            function showAlert(message, type = 'success') {
                const container = document.getElementById('alert-container');
                const alert = document.createElement('div');
                alert.className = `alert alert-${type}`;
                alert.textContent = message;
                container.appendChild(alert);
                setTimeout(() => alert.remove(), 3000);
            }
            
            // Adicionar nova configuração
            document.getElementById('new-config-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                
                // Coletar dias selecionados
                const selectedDays = Array.from(document.querySelectorAll('input[name="days"]:checked'))
                    .map(cb => cb.value);
                
                try {
                    const response = await fetch('/api/absence', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name: formData.get('name'),
                            message: formData.get('message'),
                            start_time: formData.get('start_time'),
                            end_time: formData.get('end_time'),
                            days_of_week: selectedDays.join(',')
                        })
                    });
                    
                    if (response.ok) {
                        showAlert('Configuração adicionada com sucesso!');
                        setTimeout(() => location.reload(), 1000);
                    } else {
                        showAlert('Erro ao adicionar configuração', 'error');
                    }
                } catch (error) {
                    showAlert('Erro de conexão', 'error');
                }
            });
            
            // Atualizar configuração
            async function updateConfig(configId, field, value) {
                try {
                    const response = await fetch(`/api/absence/${configId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ [field]: value })
                    });
                    
                    if (response.ok) {
                        showAlert('Configuração atualizada!');
                    } else {
                        showAlert('Erro ao atualizar configuração', 'error');
                    }
                } catch (error) {
                    showAlert('Erro de conexão', 'error');
                }
            }
            
            // Alternar status da configuração
            async function toggleConfig(configId) {
                const checkbox = document.querySelector(`[data-config-id="${configId}"] input[type="checkbox"]`);
                
                try {
                    const response = await fetch(`/api/absence/${configId}/toggle`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ active: checkbox.checked })
                    });
                    
                    if (response.ok) {
                        showAlert(`Configuração ${checkbox.checked ? 'ativada' : 'desativada'}!`);
                    } else {
                        showAlert('Erro ao alterar status', 'error');
                        checkbox.checked = !checkbox.checked;
                    }
                } catch (error) {
                    showAlert('Erro de conexão', 'error');
                    checkbox.checked = !checkbox.checked;
                }
            }
            
            // Excluir configuração
            async function deleteConfig(configId) {
                if (!confirm('Tem certeza que deseja excluir esta configuração?')) return;
                
                try {
                    const response = await fetch(`/api/absence/${configId}`, {
                        method: 'DELETE'
                    });
                    
                    if (response.ok) {
                        showAlert('Configuração excluída!');
                        document.querySelector(`[data-config-id="${configId}"]`).remove();
                    } else {
                        showAlert('Erro ao excluir configuração', 'error');
                    }
                } catch (error) {
                    showAlert('Erro de conexão', 'error');
                }
            }
        </script>
    </body>
    </html>
    """
    return html



@app.route('/history')
def history_page():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    # Buscar histórico com joins
    history_data = db.session.query(
        ResponseHistory,
        Question
    ).join(Question, ResponseHistory.question_id == Question.id)\
     .filter(ResponseHistory.user_id == user.id)\
     .order_by(ResponseHistory.created_at.desc())\
     .limit(100).all()
    
    # Estatísticas do histórico
    total_responses = ResponseHistory.query.filter_by(user_id=user.id).count()
    auto_count = ResponseHistory.query.filter_by(user_id=user.id, response_type='auto').count()
    absence_count = ResponseHistory.query.filter_by(user_id=user.id, response_type='absence').count()
    
    avg_time = db.session.query(db.func.avg(ResponseHistory.response_time)).filter_by(user_id=user.id).scalar()
    avg_time = round(avg_time, 2) if avg_time else 0
    
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Histórico de Respostas - Bot ML</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
            .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }}
            .back-btn {{ display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }}
            .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
            .stat-card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); text-align: center; }}
            .stat-number {{ font-size: 2em; font-weight: bold; color: #3483fa; margin-bottom: 5px; }}
            .stat-label {{ color: #666; }}
            .history-card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin-bottom: 15px; }}
            .history-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
            .response-type {{ padding: 4px 12px; border-radius: 20px; font-size: 0.8em; font-weight: bold; }}
            .type-auto {{ background: #d4edda; color: #155724; }}
            .type-absence {{ background: #fff3cd; color: #856404; }}
            .type-manual {{ background: #d1ecf1; color: #0c5460; }}
            .history-content {{ margin-bottom: 10px; }}
            .history-meta {{ font-size: 0.9em; color: #666; }}
            .filter-bar {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin-bottom: 20px; }}
            .filter-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; align-items: end; }}
            .form-group {{ margin-bottom: 0; }}
            .form-group label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
            .form-group select, .form-group input {{ width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 5px; }}
            .btn {{ background: #3483fa; color: white; padding: 8px 16px; border: none; border-radius: 5px; cursor: pointer; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            
            <div class="header">
                <h1>📈 Histórico de Respostas</h1>
                <p>Análise detalhada das respostas automáticas</p>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-number">{total_responses}</div>
                    <div class="stat-label">Total de Respostas</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{auto_count}</div>
                    <div class="stat-label">Respostas Automáticas</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{absence_count}</div>
                    <div class="stat-label">Respostas de Ausência</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{avg_time}s</div>
                    <div class="stat-label">Tempo Médio</div>
                </div>
            </div>
            
            <div class="filter-bar">
                <div class="filter-row">
                    <div class="form-group">
                        <label>Tipo de Resposta:</label>
                        <select id="filter-type">
                            <option value="">Todos</option>
                            <option value="auto">Automática</option>
                            <option value="absence">Ausência</option>
                            <option value="manual">Manual</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Data:</label>
                        <input type="date" id="filter-date">
                    </div>
                    <div class="form-group">
                        <button class="btn" onclick="applyFilters()">Filtrar</button>
                    </div>
                </div>
            </div>
            
            <div id="history-list">
    """
    
    for history, question in history_data:
        type_class = f"type-{history.response_type}"
        type_label = {
            'auto': 'Automática',
            'absence': 'Ausência', 
            'manual': 'Manual'
        }.get(history.response_type, 'Desconhecido')
        
        keywords_info = f" (Palavras: {history.keywords_matched})" if history.keywords_matched else ""
        
        html += f"""
                <div class="history-card">
                    <div class="history-header">
                        <h4>Pergunta #{question.ml_question_id}</h4>
                        <span class="response-type {type_class}">{type_label}</span>
                    </div>
                    <div class="history-content">
                        <p><strong>Pergunta:</strong> {question.question_text}</p>
                        <p><strong>Resposta:</strong> {question.response_text}</p>
                    </div>
                    <div class="history-meta">
                        <span>⏱️ Tempo de resposta: {round(history.response_time, 2)}s</span>
                        {keywords_info}
                        <span style="float: right;">📅 {history.created_at.strftime('%d/%m/%Y %H:%M')}</span>
                    </div>
                </div>
        """
    
    html += """
            </div>
        </div>
        
        <script>
            function applyFilters() {
                const type = document.getElementById('filter-type').value;
                const date = document.getElementById('filter-date').value;
                
                const cards = document.querySelectorAll('.history-card');
                
                cards.forEach(card => {
                    let show = true;
                    
                    if (type) {
                        const cardType = card.querySelector('.response-type').className;
                        if (!cardType.includes(`type-${type}`)) {
                            show = false;
                        }
                    }
                    
                    if (date && show) {
                        const cardDate = card.querySelector('.history-meta span:last-child').textContent;
                        const cardDateFormatted = cardDate.replace('📅 ', '').split(' ')[0];
                        const [day, month, year] = cardDateFormatted.split('/');
                        const cardDateObj = `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
                        
                        if (cardDateObj !== date) {
                            show = false;
                        }
                    }
                    
                    card.style.display = show ? 'block' : 'none';
                });
            }
        </script>
    </body>
    </html>
    """
    return html

@app.route('/rules')
def rules_page():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    rules = AutoResponse.query.filter_by(user_id=user.id).all()
    
    rules_html = ""
    for rule in rules:
        status = "✅ Ativa" if rule.is_active else "❌ Inativa"
        rules_html += f"""
        <div class="rule-card">
            <div class="rule-header">
                <h3>Regra #{rule.id}</h3>
                <span class="status {'active' if rule.is_active else 'inactive'}">{status}</span>
            </div>
            <div class="rule-content">
                <p><strong>Palavras-chave:</strong> {rule.keywords}</p>
                <p><strong>Resposta:</strong> {rule.response_text}</p>
                <p><strong>Criada em:</strong> {rule.created_at.strftime('%d/%m/%Y %H:%M')}</p>
            </div>
        </div>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Regras de Resposta - Bot ML</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
            .container {{ max-width: 1000px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }}
            .rule-card {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin-bottom: 20px; }}
            .rule-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
            .status.active {{ color: #00a650; font-weight: bold; }}
            .status.inactive {{ color: #ff3333; font-weight: bold; }}
            .rule-content p {{ margin-bottom: 10px; }}
            .back-btn {{ display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }}
            .edit-btn {{ display: inline-block; background: #28a745; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-left: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            <a href="/edit-rules" class="edit-btn">✏️ Editar Regras</a>
            
            <div class="header">
                <h1>📋 Regras de Resposta Automática</h1>
                <p>Total: {len(rules)} regras configuradas</p>
            </div>
            
            {rules_html}
        </div>
    </body>
    </html>
    """
    return html

@app.route('/questions')
def questions_page():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    questions = Question.query.filter_by(user_id=user.id).order_by(Question.created_at.desc()).limit(50).all()
    
    questions_html = ""
    for q in questions:
        status = "✅ Respondida" if q.is_answered else "⏳ Pendente"
        auto_status = " (Automática)" if q.answered_automatically else ""
        
        questions_html += f"""
        <div class="question-card">
            <div class="question-header">
                <h3>Pergunta #{q.ml_question_id}</h3>
                <span class="status">{status}{auto_status}</span>
            </div>
            <div class="question-content">
                <p><strong>Pergunta:</strong> {q.question_text}</p>
                {f'<p><strong>Resposta:</strong> {q.response_text}</p>' if q.response_text else ''}
                <p><strong>Data:</strong> {q.created_at.strftime('%d/%m/%Y %H:%M')}</p>
                {f'<p><strong>Respondida em:</strong> {q.answered_at.strftime("%d/%m/%Y %H:%M")}</p>' if q.answered_at else ''}
            </div>
        </div>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Perguntas Recebidas - Bot ML</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
            .container {{ max-width: 1000px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }}
            .question-card {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin-bottom: 20px; }}
            .question-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
            .status {{ font-weight: bold; color: #00a650; }}
            .question-content p {{ margin-bottom: 10px; }}
            .back-btn {{ display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            
            <div class="header">
                <h1>❓ Perguntas Recebidas</h1>
                <p>Últimas {len(questions)} perguntas</p>
            </div>
            
            {questions_html if questions_html else '<div class="question-card"><p>Nenhuma pergunta recebida ainda.</p></div>'}
        </div>
    </body>
    </html>
    """
    return html

@app.route('/absence')
def absence_page():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    configs = AbsenceConfig.query.filter_by(user_id=user.id).all()
    
    configs_html = ""
    for config in configs:
        status = "✅ Ativa" if config.is_active else "❌ Inativa"
        days_map = {
            "0": "Segunda", "1": "Terça", "2": "Quarta", 
            "3": "Quinta", "4": "Sexta", "5": "Sábado", "6": "Domingo"
        }
        days = [days_map.get(d, d) for d in config.days_of_week.split(',')]
        
        configs_html += f"""
        <div class="config-card">
            <div class="config-header">
                <h3>{config.name}</h3>
                <span class="status {'active' if config.is_active else 'inactive'}">{status}</span>
            </div>
            <div class="config-content">
                <p><strong>Mensagem:</strong> {config.message}</p>
                <p><strong>Horário:</strong> {config.start_time} às {config.end_time}</p>
                <p><strong>Dias:</strong> {', '.join(days)}</p>
                <p><strong>Criada em:</strong> {config.created_at.strftime('%d/%m/%Y %H:%M')}</p>
            </div>
        </div>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Configurações de Ausência - Bot ML</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
            .container {{ max-width: 1000px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }}
            .config-card {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin-bottom: 20px; }}
            .config-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
            .status.active {{ color: #00a650; font-weight: bold; }}
            .status.inactive {{ color: #ff3333; font-weight: bold; }}
            .config-content p {{ margin-bottom: 10px; }}
            .back-btn {{ display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }}
            .edit-btn {{ display: inline-block; background: #28a745; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-left: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            <a href="/edit-absence" class="edit-btn">✏️ Editar Configurações</a>
            
            <div class="header">
                <h1>🌙 Configurações de Ausência</h1>
                <p>Total: {len(configs)} configurações</p>
            </div>
            
            {configs_html}
        </div>
    </body>
    </html>
    """
    return html

# APIs para CRUD de regras
@app.route('/api/rules', methods=['GET', 'POST'])
def api_rules():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    
    if request.method == 'GET':
        rules = AutoResponse.query.filter_by(user_id=user.id).all()
        return jsonify([{
            "id": rule.id,
            "keywords": rule.keywords,
            "response": rule.response_text,
            "active": rule.is_active,
            "created_at": rule.created_at.isoformat()
        } for rule in rules])
    
    elif request.method == 'POST':
        data = request.get_json()
        
        rule = AutoResponse(
            user_id=user.id,
            keywords=data.get('keywords'),
            response_text=data.get('response'),
            is_active=True
        )
        
        db.session.add(rule)
        db.session.commit()
        
        return jsonify({"message": "Regra criada com sucesso", "id": rule.id}), 201

@app.route('/api/rules/<int:rule_id>', methods=['PUT', 'DELETE'])
def api_rule_detail(rule_id):
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    
    rule = AutoResponse.query.filter_by(id=rule_id, user_id=user.id).first()
    if not rule:
        return jsonify({"error": "Regra não encontrada"}), 404
    
    if request.method == 'PUT':
        data = request.get_json()
        
        if 'keywords' in data:
            rule.keywords = data['keywords']
        if 'response' in data:
            rule.response_text = data['response']
        
        rule.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({"message": "Regra atualizada com sucesso"})
    
    elif request.method == 'DELETE':
        db.session.delete(rule)
        db.session.commit()
        
        return jsonify({"message": "Regra excluída com sucesso"})

@app.route('/api/rules/<int:rule_id>/toggle', methods=['POST'])
def api_toggle_rule(rule_id):
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    
    rule = AutoResponse.query.filter_by(id=rule_id, user_id=user.id).first()
    if not rule:
        return jsonify({"error": "Regra não encontrada"}), 404
    
    data = request.get_json()
    rule.is_active = data.get('active', False)
    rule.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({"message": "Status da regra atualizado"})

# APIs para CRUD de configurações de ausência
@app.route('/api/absence', methods=['GET', 'POST'])
def api_absence():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    
    if request.method == 'GET':
        configs = AbsenceConfig.query.filter_by(user_id=user.id).all()
        return jsonify([{
            "id": config.id,
            "name": config.name,
            "message": config.message,
            "start_time": config.start_time,
            "end_time": config.end_time,
            "days": config.days_of_week,
            "active": config.is_active,
            "created_at": config.created_at.isoformat()
        } for config in configs])
    
    elif request.method == 'POST':
        data = request.get_json()
        
        config = AbsenceConfig(
            user_id=user.id,
            name=data.get('name'),
            message=data.get('message'),
            start_time=data.get('start_time'),
            end_time=data.get('end_time'),
            days_of_week=data.get('days_of_week'),
            is_active=True
        )
        
        db.session.add(config)
        db.session.commit()
        
        return jsonify({"message": "Configuração criada com sucesso", "id": config.id}), 201

@app.route('/api/absence/<int:config_id>', methods=['PUT', 'DELETE'])
def api_absence_detail(config_id):
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    
    config = AbsenceConfig.query.filter_by(id=config_id, user_id=user.id).first()
    if not config:
        return jsonify({"error": "Configuração não encontrada"}), 404
    
    if request.method == 'PUT':
        data = request.get_json()
        
        for field in ['name', 'message', 'start_time', 'end_time', 'days_of_week']:
            if field in data:
                setattr(config, field, data[field])
        
        db.session.commit()
        
        return jsonify({"message": "Configuração atualizada com sucesso"})
    
    elif request.method == 'DELETE':
        db.session.delete(config)
        db.session.commit()
        
        return jsonify({"message": "Configuração excluída com sucesso"})

@app.route('/api/absence/<int:config_id>/toggle', methods=['POST'])
def api_toggle_absence(config_id):
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    
    config = AbsenceConfig.query.filter_by(id=config_id, user_id=user.id).first()
    if not config:
        return jsonify({"error": "Configuração não encontrada"}), 404
    
    data = request.get_json()
    config.is_active = data.get('active', False)
    
    db.session.commit()
    
    return jsonify({"message": "Status da configuração atualizado"})

# APIs para dados em tempo real
@app.route('/api/ml/questions/recent')
def api_recent_questions():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    
    questions = Question.query.filter_by(user_id=user.id).order_by(Question.created_at.desc()).limit(10).all()
    
    return jsonify([{
        "id": q.ml_question_id,
        "question": q.question_text,
        "response": q.response_text,
        "answered": q.is_answered,
        "automatic": q.answered_automatically,
        "date": q.created_at.isoformat()
    } for q in questions])

@app.route('/api/stats')
def api_stats():
    if not _initialized:
        initialize_database()
    
    return jsonify(get_real_time_stats())

# Webhook para receber notificações do Mercado Livre
@app.route('/api/ml/webhook', methods=['GET', 'POST'])
def webhook_ml():
    if request.method == 'GET':
        return jsonify({"message": "webhook funcionando!", "status": "webhook_active"})
    
    try:
        data = request.get_json()
        
        if data and data.get('topic') == 'questions':
            # Processar notificação de pergunta
            print(f"📨 Notificação de pergunta recebida: {data}")
            
            # Processar perguntas imediatamente
            threading.Thread(target=lambda: process_questions(), daemon=True).start()
            
            return jsonify({"status": "ok", "message": "notificação processada"})
        
        return jsonify({"status": "ok", "message": "webhook recebido"})
        
    except Exception as e:
        print(f"❌ Erro no webhook: {e}")
        return jsonify({"error": str(e)}), 500

# Inicializar aplicação
initialize_database()

# Iniciar monitoramento
monitor_thread = threading.Thread(target=monitor_questions, daemon=True)
monitor_thread.start()
print("✅ Monitoramento de perguntas iniciado!")

print("🚀 Bot do Mercado Livre iniciado com sucesso!")
print(f"🗄️ Banco de dados: {DATABASE_PATH}")
print(f"🔑 Token: {ML_ACCESS_TOKEN[:20]}...")
print(f"👤 User ID: {ML_USER_ID}")

if __name__ == '__main__':
    # Executar aplicação
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)

