import os
import time
import threading
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests
import sqlite3

# Configuração da aplicação
app = Flask(__name__)
CORS(app)

# Configuração do fuso horário (UTC-3 para São Paulo)
SAO_PAULO_TZ = timezone(timedelta(hours=-3))

def get_local_time():
    """Retorna o horário atual no fuso horário de São Paulo"""
    return datetime.now(SAO_PAULO_TZ)

def get_local_time_utc():
    """Retorna o horário atual em UTC para salvar no banco"""
    return datetime.utcnow()

def format_local_time(utc_datetime):
    """Converte UTC para horário local para exibição"""
    if utc_datetime is None:
        return None
    utc_dt = utc_datetime.replace(tzinfo=timezone.utc)
    local_dt = utc_dt.astimezone(SAO_PAULO_TZ)
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

# Variáveis globais para status do token
TOKEN_STATUS = {
    'valid': False,
    'last_check': None,
    'error_message': None,
    'expires_at': None,
    'time_remaining': None
}

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

class TokenLog(db.Model):
    __tablename__ = 'token_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token_status = db.Column(db.String(20), nullable=False)  # 'valid', 'expired', 'error'
    error_message = db.Column(db.Text)
    checked_at = db.Column(db.DateTime, default=get_local_time_utc)

# Variável global para controlar inicialização
_initialized = False
_db_lock = threading.Lock()

# FUNÇÕES DE VERIFICAÇÃO DE TOKEN
def check_token_validity(token=None):
    """
    Verifica se o token está válido fazendo uma requisição de teste
    """
    global TOKEN_STATUS
    
    if token is None:
        token = ML_ACCESS_TOKEN
    
    try:
        # Fazer uma requisição simples para verificar se o token funciona
        url = "https://api.mercadolibre.com/users/me"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        TOKEN_STATUS['last_check'] = get_local_time()
        
        if response.status_code == 200:
            TOKEN_STATUS['valid'] = True
            TOKEN_STATUS['error_message'] = None
            
            # Tentar obter informações sobre expiração
            user_info = response.json()
            print(f"✅ Token válido! Usuário: {user_info.get('nickname', 'N/A')}")
            
            return True, "Token válido"
            
        elif response.status_code == 401:
            TOKEN_STATUS['valid'] = False
            TOKEN_STATUS['error_message'] = "Token expirado ou inválido"
            print("❌ Token expirado ou inválido!")
            
            return False, "Token expirado ou inválido"
            
        else:
            TOKEN_STATUS['valid'] = False
            TOKEN_STATUS['error_message'] = f"Erro HTTP {response.status_code}"
            print(f"❌ Erro na verificação do token: {response.status_code}")
            
            return False, f"Erro HTTP {response.status_code}"
            
    except requests.exceptions.RequestException as e:
        TOKEN_STATUS['valid'] = False
        TOKEN_STATUS['error_message'] = f"Erro de conexão: {str(e)}"
        print(f"❌ Erro de conexão ao verificar token: {e}")
        
        return False, f"Erro de conexão: {str(e)}"

def get_token_info():
    """
    Obtém informações detalhadas sobre o token
    """
    try:
        url = "https://api.mercadolibre.com/users/me"
        headers = {
            "Authorization": f"Bearer {ML_ACCESS_TOKEN}"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            user_info = response.json()
            return {
                'valid': True,
                'user_id': user_info.get('id'),
                'nickname': user_info.get('nickname'),
                'email': user_info.get('email'),
                'country': user_info.get('country_id'),
                'status': 'Ativo'
            }
        else:
            return {
                'valid': False,
                'error': f"HTTP {response.status_code}",
                'status': 'Inválido'
            }
            
    except Exception as e:
        return {
            'valid': False,
            'error': str(e),
            'status': 'Erro de conexão'
        }

def log_token_status(user_id, status, error_message=None):
    """
    Registra o status do token no banco de dados
    """
    try:
        with app.app_context():
            log_entry = TokenLog(
                user_id=user_id,
                token_status=status,
                error_message=error_message
            )
            db.session.add(log_entry)
            db.session.commit()
    except Exception as e:
        print(f"❌ Erro ao registrar log do token: {e}")

def monitor_token_status():
    """
    Monitora o status do token continuamente
    """
    while True:
        try:
            with app.app_context():
                user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
                if user:
                    is_valid, message = check_token_validity(user.access_token)
                    
                    # Registrar no log
                    status = 'valid' if is_valid else 'expired'
                    log_token_status(user.id, status, message if not is_valid else None)
                    
                    # Atualizar status no banco se necessário
                    if not is_valid and user.token_expires_at:
                        user.token_expires_at = get_local_time_utc() - timedelta(hours=1)  # Marcar como expirado
                        db.session.commit()
                
                # Verificar a cada 5 minutos
                time.sleep(300)
                
        except Exception as e:
            print(f"❌ Erro no monitoramento do token: {e}")
            time.sleep(300)

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
        elif response.status_code == 401:
            print(f"❌ Token expirado ao responder pergunta {question_id}")
            # Atualizar status do token
            TOKEN_STATUS['valid'] = False
            TOKEN_STATUS['error_message'] = "Token expirado durante resposta"
            return False
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
        elif response.status_code == 401:
            print("❌ Token expirado ao buscar perguntas")
            # Atualizar status do token
            TOKEN_STATUS['valid'] = False
            TOKEN_STATUS['error_message'] = "Token expirado durante busca"
            return []
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
                # Verificar token antes de processar
                is_valid, message = check_token_validity()
                if not is_valid:
                    print(f"❌ Token inválido, pulando processamento: {message}")
                    return
                
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
                
                # Verificar token inicial
                is_valid, message = check_token_validity()
                log_token_status(user.id, 'valid' if is_valid else 'expired', message if not is_valid else None)
                
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
                print(f"🕐 Fuso horário configurado: UTC-3 (São Paulo)")
                
    except Exception as e:
        print(f"❌ Erro ao inicializar banco: {e}")

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
    
    # Status do token
    token_info = get_token_info()
    
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
        'avg_response_time': avg_response_time,
        'token_info': token_info
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
    token_info = stats.get('token_info', {})
    
    # Status do token com cores
    if token_info.get('valid'):
        token_status = "✅ Válido"
        token_class = "connected"
        token_details = f"Usuário: {token_info.get('nickname', 'N/A')}"
    else:
        token_status = "❌ Inválido"
        token_class = "warning"
        token_details = f"Erro: {token_info.get('error', 'Desconhecido')}"
    
    # Horário local atual
    current_local_time = get_local_time().strftime('%H:%M:%S')
    
    # Última verificação do token
    last_check = TOKEN_STATUS.get('last_check')
    last_check_str = last_check.strftime('%H:%M:%S') if last_check else 'Nunca'
    
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
            .status-card.error {{ border-left: 6px solid #dc3545; }}
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
            .token-status {{ background: linear-gradient(135deg, #17a2b8, #138496); color: white; }}
            .token-status .stat-number {{ color: white; font-size: 1.5em; }}
            .token-status .stat-label {{ color: rgba(255,255,255,0.9); }}
            .check-token-btn {{ background: #28a745; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin-top: 10px; }}
            .check-token-btn:hover {{ background: #218838; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Bot do Mercado Livre</h1>
                <p>Sistema Automatizado de Respostas - Fuso Horário: UTC-3 (São Paulo)</p>
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
                <div class="stat-card token-status">
                    <div class="stat-number">{token_status}</div>
                    <div class="stat-label">Status do Token ML</div>
                </div>
            </div>
            
            <div class="status">
                <div class="status-card {token_class}">
                    <h3>🔑 Status do Token</h3>
                    <p><strong>Status:</strong> {token_status}</p>
                    <p><strong>Detalhes:</strong> {token_details}</p>
                    <p><strong>Última Verificação:</strong> {last_check_str}</p>
                    <p><strong>Token:</strong> {ML_ACCESS_TOKEN[:20]}...</p>
                    <button class="check-token-btn" onclick="checkToken()">🔄 Verificar Agora</button>
                </div>
                <div class="status-card connected">
                    <h3>📊 Sistema</h3>
                    <p><strong>Monitoramento:</strong> Ativo</p>
                    <p><strong>Banco:</strong> Persistente ({DATABASE_PATH})</p>
                    <p><strong>Fuso Horário:</strong> UTC-3 (São Paulo)</p>
                    <p><strong>Regras Ativas:</strong> {stats['active_rules']}</p>
                    <p><strong>Configurações de Ausência:</strong> {stats['absence_configs']}</p>
                </div>
                <div class="status-card connected">
                    <h3>📈 Estatísticas</h3>
                    <p><strong>Respostas Automáticas:</strong> {stats['auto_responses']}</p>
                    <p><strong>Respostas de Ausência:</strong> {stats['absence_responses']}</p>
                    <p><strong>Última Verificação:</strong> {current_local_time}</p>
                    <p><strong>Performance:</strong> {stats['success_rate']}% de sucesso</p>
                </div>
            </div>
            
            <div class="navigation">
                <div class="nav-card">
                    <h3>🔍 Verificar Token</h3>
                    <p>Status e logs do token</p>
                    <a href="/token-status">Acessar →</a>
                </div>
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
            </div>
        </div>
        
        <script>
            async function checkToken() {{
                try {{
                    const response = await fetch('/api/token/check', {{ method: 'POST' }});
                    const result = await response.json();
                    
                    if (result.valid) {{
                        alert('✅ Token válido!\\n' + result.message);
                    }} else {{
                        alert('❌ Token inválido!\\n' + result.message);
                    }}
                    
                    // Recarregar página para atualizar status
                    setTimeout(() => location.reload(), 1000);
                }} catch (error) {{
                    alert('❌ Erro ao verificar token: ' + error.message);
                }}
            }}
        </script>
    </body>
    </html>
    """
    return html

@app.route('/token-status')
def token_status_page():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    # Obter logs recentes do token
    token_logs = TokenLog.query.filter_by(user_id=user.id).order_by(TokenLog.checked_at.desc()).limit(20).all()
    
    # Informações detalhadas do token
    token_info = get_token_info()
    
    logs_html = ""
    for log in token_logs:
        status_icon = "✅" if log.token_status == 'valid' else "❌"
        local_time = format_local_time(log.checked_at)
        display_time = local_time.strftime('%d/%m/%Y %H:%M:%S') if local_time else log.checked_at.strftime('%d/%m/%Y %H:%M:%S')
        
        logs_html += f"""
        <div class="log-item">
            <div class="log-header">
                <span class="status-icon">{status_icon}</span>
                <span class="status-text">{log.token_status.title()}</span>
                <span class="log-time">{display_time}</span>
            </div>
            {f'<div class="log-error">Erro: {log.error_message}</div>' if log.error_message else ''}
        </div>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Status do Token - Bot ML</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
            .container {{ max-width: 1000px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }}
            .back-btn {{ display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }}
            .info-card {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin-bottom: 20px; }}
            .info-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
            .info-item {{ padding: 15px; background: #f8f9fa; border-radius: 8px; }}
            .info-label {{ font-weight: bold; color: #666; margin-bottom: 5px; }}
            .info-value {{ color: #333; }}
            .logs-card {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
            .log-item {{ padding: 15px; border-bottom: 1px solid #eee; }}
            .log-header {{ display: flex; justify-content: space-between; align-items: center; }}
            .status-icon {{ font-size: 1.2em; }}
            .status-text {{ font-weight: bold; }}
            .log-time {{ color: #666; font-size: 0.9em; }}
            .log-error {{ color: #dc3545; margin-top: 5px; font-size: 0.9em; }}
            .check-btn {{ background: #28a745; color: white; padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; margin-bottom: 20px; }}
            .check-btn:hover {{ background: #218838; }}
            .status-valid {{ color: #00a650; }}
            .status-invalid {{ color: #dc3545; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            <button class="check-btn" onclick="checkToken()">🔄 Verificar Token Agora</button>
            
            <div class="header">
                <h1>🔑 Status do Token ML</h1>
                <p>Monitoramento e logs de verificação</p>
            </div>
            
            <div class="info-card">
                <h3>📊 Informações do Token</h3>
                <div class="info-grid">
                    <div class="info-item">
                        <div class="info-label">Status</div>
                        <div class="info-value {'status-valid' if token_info.get('valid') else 'status-invalid'}">
                            {'✅ Válido' if token_info.get('valid') else '❌ Inválido'}
                        </div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Usuário</div>
                        <div class="info-value">{token_info.get('nickname', 'N/A')}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">User ID</div>
                        <div class="info-value">{token_info.get('user_id', 'N/A')}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">País</div>
                        <div class="info-value">{token_info.get('country', 'N/A')}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Token (Início)</div>
                        <div class="info-value">{ML_ACCESS_TOKEN[:30]}...</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Última Verificação</div>
                        <div class="info-value">{TOKEN_STATUS.get('last_check', 'Nunca')}</div>
                    </div>
                </div>
                {f'<div style="margin-top: 15px; color: #dc3545;"><strong>Erro:</strong> {token_info.get("error", "")}</div>' if not token_info.get('valid') else ''}
            </div>
            
            <div class="logs-card">
                <h3>📋 Histórico de Verificações</h3>
                {logs_html if logs_html else '<p>Nenhum log encontrado.</p>'}
            </div>
        </div>
        
        <script>
            async function checkToken() {{
                try {{
                    const response = await fetch('/api/token/check', {{ method: 'POST' }});
                    const result = await response.json();
                    
                    if (result.valid) {{
                        alert('✅ Token válido!\\n' + result.message);
                    }} else {{
                        alert('❌ Token inválido!\\n' + result.message);
                    }}
                    
                    // Recarregar página para atualizar logs
                    setTimeout(() => location.reload(), 1000);
                }} catch (error) {{
                    alert('❌ Erro ao verificar token: ' + error.message);
                }}
            }}
        </script>
    </body>
    </html>
    """
    return html

# API para verificar token manualmente
@app.route('/api/token/check', methods=['POST'])
def api_check_token():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    
    is_valid, message = check_token_validity(user.access_token)
    
    # Registrar no log
    status = 'valid' if is_valid else 'expired'
    log_token_status(user.id, status, message if not is_valid else None)
    
    return jsonify({
        "valid": is_valid,
        "message": message,
        "checked_at": get_local_time().isoformat()
    })

# API para obter status do token
@app.route('/api/token/status')
def api_token_status():
    token_info = get_token_info()
    return jsonify({
        "token_info": token_info,
        "global_status": TOKEN_STATUS,
        "last_check": TOKEN_STATUS.get('last_check').isoformat() if TOKEN_STATUS.get('last_check') else None
    })


# Inicializar aplicação
initialize_database()

# Iniciar monitoramento de perguntas
monitor_thread = threading.Thread(target=monitor_questions, daemon=True)
monitor_thread.start()
print("✅ Monitoramento de perguntas iniciado!")

# Iniciar monitoramento de token
token_monitor_thread = threading.Thread(target=monitor_token_status, daemon=True)
token_monitor_thread.start()
print("✅ Monitoramento de token iniciado!")

print("🚀 Bot do Mercado Livre iniciado com sucesso!")
print(f"🗄️ Banco de dados: {DATABASE_PATH}")
print(f"🔑 Token: {ML_ACCESS_TOKEN[:20]}...")
print(f"👤 User ID: {ML_USER_ID}")

# Verificação inicial do token
initial_check, initial_message = check_token_validity()
print(f"🔍 Verificação inicial do token: {'✅ Válido' if initial_check else '❌ Inválido'} - {initial_message}")

if __name__ == '__main__':
    # Executar aplicação
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)

