import os
import time
import threading
import webbrowser
import json
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests
import sqlite3
from urllib.parse import urlparse, parse_qs

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
ML_ACCESS_TOKEN = os.getenv('ML_ACCESS_TOKEN', 'APP_USR-5510376630479325-072511-3ae2fcd67777738f910e1dc08131b55d-180617463')
ML_USER_ID = os.getenv('ML_USER_ID', '180617463')
ML_REFRESH_TOKEN = os.getenv('ML_REFRESH_TOKEN', 'TG-68839d65f4c795000...')

# URLs de redirect possíveis (para flexibilidade)
REDIRECT_URIS = [
    "https://bot-mercadolivre-dettech.onrender.com/api/ml/auth-callback",
    "https://bot-mercadolivre-dettech.onrender.com/api/ml/webhook",
    "http://localhost:5000/api/ml/auth-callback",
    "http://localhost:5000/api/ml/webhook"
]

# Variáveis globais para status do token
TOKEN_STATUS = {
    'valid': False,
    'last_check': None,
    'error_message': None,
    'expires_at': None,
    'time_remaining': None,
    'current_token': ML_ACCESS_TOKEN,
    'refresh_token': ML_REFRESH_TOKEN
}

# Lock para operações thread-safe
token_lock = threading.Lock()

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

class WebhookLog(db.Model):
    __tablename__ = 'webhook_logs'
    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(100))
    resource = db.Column(db.String(200))
    user_id_ml = db.Column(db.String(50))
    application_id = db.Column(db.String(50))
    attempts = db.Column(db.Integer, default=1)
    sent = db.Column(db.DateTime)
    received = db.Column(db.DateTime, default=get_local_time_utc)

# Variável global para controlar inicialização
_initialized = False
_db_lock = threading.Lock()

# ========== SISTEMA DE RENOVAÇÃO AUTOMÁTICA DE TOKEN ==========

def refresh_access_token():
    """Renova o access token usando o refresh token"""
    global TOKEN_STATUS
    
    with token_lock:
        try:
            refresh_token = TOKEN_STATUS.get('refresh_token') or ML_REFRESH_TOKEN
            
            if not refresh_token:
                print("❌ Refresh token não encontrado!")
                return False, "Refresh token não disponível"
            
            print("🔄 Tentando renovar token...")
            
            url = "https://api.mercadolibre.com/oauth/token"
            data = {
                'grant_type': 'refresh_token',
                'client_id': ML_CLIENT_ID,
                'client_secret': ML_CLIENT_SECRET,
                'refresh_token': refresh_token
            }
            
            response = requests.post(url, data=data, timeout=30)
            
            if response.status_code == 200:
                token_data = response.json()
                
                # Atualizar tokens globais
                new_access_token = token_data['access_token']
                new_refresh_token = token_data.get('refresh_token', refresh_token)
                
                TOKEN_STATUS['current_token'] = new_access_token
                TOKEN_STATUS['refresh_token'] = new_refresh_token
                TOKEN_STATUS['valid'] = True
                TOKEN_STATUS['error_message'] = None
                TOKEN_STATUS['last_check'] = get_local_time()
                
                # Atualizar variáveis de ambiente (para próximas execuções)
                os.environ['ML_ACCESS_TOKEN'] = new_access_token
                if new_refresh_token != refresh_token:
                    os.environ['ML_REFRESH_TOKEN'] = new_refresh_token
                
                # Salvar no banco de dados
                save_tokens_to_db(new_access_token, new_refresh_token)
                
                print(f"✅ Token renovado com sucesso!")
                print(f"🔑 Novo token: {new_access_token[:20]}...")
                
                return True, "Token renovado com sucesso"
                
            else:
                error_msg = f"Erro na renovação: {response.status_code} - {response.text}"
                print(f"❌ {error_msg}")
                TOKEN_STATUS['error_message'] = error_msg
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Erro na renovação do token: {str(e)}"
            print(f"💥 {error_msg}")
            TOKEN_STATUS['error_message'] = error_msg
            return False, error_msg

def save_tokens_to_db(access_token, refresh_token):
    """Salva os tokens no banco de dados"""
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if user:
                user.access_token = access_token
                user.refresh_token = refresh_token
                user.token_expires_at = get_local_time_utc() + timedelta(hours=6)
                user.updated_at = get_local_time_utc()
                db.session.commit()
                print("💾 Tokens salvos no banco de dados")
    except Exception as e:
        print(f"❌ Erro ao salvar tokens no banco: {e}")

def check_token_validity(token=None):
    """Verifica se o token está válido fazendo uma requisição de teste"""
    global TOKEN_STATUS
    
    if token is None:
        token = TOKEN_STATUS.get('current_token') or ML_ACCESS_TOKEN
    
    try:
        url = "https://api.mercadolibre.com/users/me"
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.get(url, headers=headers, timeout=10)
        TOKEN_STATUS['last_check'] = get_local_time()
        
        if response.status_code == 200:
            TOKEN_STATUS['valid'] = True
            TOKEN_STATUS['error_message'] = None
            user_info = response.json()
            print(f"✅ Token válido! Usuário: {user_info.get('nickname', 'N/A')}")
            return True, "Token válido"
            
        elif response.status_code == 401:
            TOKEN_STATUS['valid'] = False
            TOKEN_STATUS['error_message'] = "Token expirado"
            print("⚠️ Token expirado (401)")
            return False, "Token expirado"
            
        else:
            TOKEN_STATUS['valid'] = False
            error_msg = f"Erro {response.status_code}: {response.text}"
            TOKEN_STATUS['error_message'] = error_msg
            print(f"❌ Erro na verificação: {error_msg}")
            return False, error_msg
            
    except Exception as e:
        TOKEN_STATUS['valid'] = False
        error_msg = f"Erro na verificação: {str(e)}"
        TOKEN_STATUS['error_message'] = error_msg
        print(f"💥 {error_msg}")
        return False, error_msg

def get_valid_token():
    """Retorna um token válido, renovando automaticamente se necessário"""
    global TOKEN_STATUS
    
    # Verificar se token atual é válido
    is_valid, message = check_token_validity()
    
    if is_valid:
        return TOKEN_STATUS['current_token']
    
    # Token inválido, tentar renovar
    print("🔄 Token inválido, tentando renovar automaticamente...")
    success, message = refresh_access_token()
    
    if success:
        return TOKEN_STATUS['current_token']
    else:
        print(f"❌ Falha na renovação automática: {message}")
        print("🚨 AÇÃO NECESSÁRIA: Renovar token manualmente!")
        return None

def make_ml_request(url, method='GET', headers=None, data=None, max_retries=1):
    """Faz requisições para a API do ML com renovação automática de token"""
    
    for attempt in range(max_retries + 1):
        # Obter token válido
        token = get_valid_token()
        
        if not token:
            return None, "Token não disponível"
        
        # Preparar headers
        request_headers = headers or {}
        request_headers['Authorization'] = f'Bearer {token}'
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=request_headers, timeout=30)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=request_headers, data=data, timeout=30)
            else:
                return None, f"Método {method} não suportado"
            
            # Se sucesso, retornar resposta
            if response.status_code in [200, 201]:
                return response, "Sucesso"
            
            # Se erro 401 e ainda temos tentativas, tentar novamente
            elif response.status_code == 401 and attempt < max_retries:
                print(f"🔄 Erro 401 na tentativa {attempt + 1}, tentando renovar token...")
                TOKEN_STATUS['valid'] = False  # Forçar renovação na próxima tentativa
                continue
            
            else:
                return response, f"Erro {response.status_code}: {response.text}"
                
        except Exception as e:
            if attempt < max_retries:
                print(f"🔄 Erro na tentativa {attempt + 1}: {e}")
                continue
            else:
                return None, f"Erro na requisição: {str(e)}"
    
    return None, "Máximo de tentativas excedido"

# ========== SISTEMA DE RENOVAÇÃO DE TOKENS FLEXÍVEL ==========

def generate_auth_url(redirect_uri=None):
    """Gera URL para autorização no Mercado Livre com redirect_uri flexível"""
    if redirect_uri is None:
        redirect_uri = REDIRECT_URIS[0]  # Usar o primeiro como padrão
    
    base_url = "https://auth.mercadolivre.com.br/authorization"
    params = {
        "response_type": "code",
        "client_id": ML_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "offline_access read write"
    }
    
    url_params = "&".join([f"{k}={v}" for k, v in params.items()])
    return f"{base_url}?{url_params}"

def get_tokens_from_code_flexible(authorization_code, redirect_uri=None):
    """Obtém tokens usando o código de autorização com múltiplas tentativas de redirect_uri"""
    url = "https://api.mercadolibre.com/oauth/token"
    
    # Lista de redirect_uris para tentar
    redirect_uris_to_try = [redirect_uri] if redirect_uri else REDIRECT_URIS
    
    for redirect_uri_attempt in redirect_uris_to_try:
        data = {
            "grant_type": "authorization_code",
            "client_id": ML_CLIENT_ID,
            "client_secret": ML_CLIENT_SECRET,
            "code": authorization_code,
            "redirect_uri": redirect_uri_attempt
        }
        
        try:
            print(f"🔄 Tentando com redirect_uri: {redirect_uri_attempt}")
            response = requests.post(url, data=data, timeout=30)
            
            if response.status_code == 200:
                print(f"✅ Sucesso com redirect_uri: {redirect_uri_attempt}")
                return response.json(), None
            else:
                print(f"❌ Falha com {redirect_uri_attempt}: {response.status_code} - {response.text}")
                continue
                
        except requests.exceptions.RequestException as e:
            print(f"❌ Erro de conexão com {redirect_uri_attempt}: {e}")
            continue
    
    # Se chegou aqui, todas as tentativas falharam
    return None, "Falha em todas as tentativas de redirect_uri. Verifique se o código é válido."

def get_user_info(access_token):
    """Obtém informações do usuário"""
    url = "https://api.mercadolibre.com/users/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json(), None
        else:
            return None, f"Erro ao obter user info: {response.status_code}"
    except requests.exceptions.RequestException as e:
        return None, f"Erro: {e}"

def update_system_tokens(tokens_data, user_info=None):
    """Atualiza tokens no sistema"""
    global TOKEN_STATUS, ML_ACCESS_TOKEN, ML_USER_ID, ML_REFRESH_TOKEN
    
    try:
        # Atualizar variáveis globais
        new_access_token = tokens_data.get("access_token")
        new_refresh_token = tokens_data.get("refresh_token")
        new_user_id = str(user_info.get("id")) if user_info else ML_USER_ID
        
        TOKEN_STATUS['current_token'] = new_access_token
        TOKEN_STATUS['refresh_token'] = new_refresh_token
        TOKEN_STATUS['valid'] = True
        TOKEN_STATUS['error_message'] = None
        TOKEN_STATUS['last_check'] = get_local_time()
        
        # Atualizar variáveis de ambiente
        os.environ['ML_ACCESS_TOKEN'] = new_access_token
        os.environ['ML_REFRESH_TOKEN'] = new_refresh_token
        os.environ['ML_USER_ID'] = new_user_id
        
        ML_ACCESS_TOKEN = new_access_token
        ML_REFRESH_TOKEN = new_refresh_token
        ML_USER_ID = new_user_id
        
        # Salvar no banco
        save_tokens_to_db(new_access_token, new_refresh_token)
        
        print(f"✅ Sistema atualizado com novos tokens!")
        print(f"🔑 Access Token: {new_access_token[:20]}...")
        print(f"🔄 Refresh Token: {new_refresh_token[:20]}...")
        print(f"👤 User ID: {new_user_id}")
        
        return True, "Tokens atualizados com sucesso"
        
    except Exception as e:
        error_msg = f"Erro ao atualizar tokens: {str(e)}"
        print(f"❌ {error_msg}")
        return False, error_msg

# ========== FUNÇÕES ORIGINAIS ADAPTADAS ==========

def get_questions():
    """Busca perguntas não respondidas usando o sistema de renovação automática"""
    try:
        url = f"https://api.mercadolibre.com/my/received_questions/search?seller_id={ML_USER_ID}&status=UNANSWERED"
        
        response, message = make_ml_request(url)
        
        if response and response.status_code == 200:
            questions_data = response.json()
            return questions_data.get('questions', [])
        else:
            print(f"❌ Erro ao buscar perguntas: {message}")
            return []
            
    except Exception as e:
        print(f"💥 Erro ao buscar perguntas: {e}")
        return []

def answer_question(question_id, answer_text):
    """Responde uma pergunta usando o sistema de renovação automática"""
    try:
        url = f"https://api.mercadolibre.com/answers"
        data = {
            'question_id': question_id,
            'text': answer_text
        }
        
        response, message = make_ml_request(url, method='POST', data=data)
        
        if response and response.status_code in [200, 201]:
            print(f"✅ Pergunta {question_id} respondida com sucesso!")
            return True
        else:
            print(f"❌ Erro ao responder pergunta {question_id}: {message}")
            return False
            
    except Exception as e:
        print(f"💥 Erro ao responder pergunta {question_id}: {e}")
        return False

# ========== FUNÇÕES DE PROCESSAMENTO ==========

def init_database():
    """Inicializa o banco de dados"""
    global _initialized
    
    with _db_lock:
        if _initialized:
            return
        
        try:
            with app.app_context():
                db.create_all()
                
                # Verificar se usuário existe, se não, criar
                user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
                if not user:
                    user = User(
                        ml_user_id=ML_USER_ID,
                        access_token=ML_ACCESS_TOKEN,
                        refresh_token=ML_REFRESH_TOKEN,
                        token_expires_at=get_local_time_utc() + timedelta(hours=6)
                    )
                    db.session.add(user)
                    db.session.commit()
                    print(f"✅ Usuário {ML_USER_ID} criado no banco")
                else:
                    # Atualizar tokens se necessário
                    user.access_token = ML_ACCESS_TOKEN
                    if ML_REFRESH_TOKEN:
                        user.refresh_token = ML_REFRESH_TOKEN
                    user.updated_at = get_local_time_utc()
                    db.session.commit()
                    print(f"✅ Usuário {ML_USER_ID} atualizado")
                
                # Criar regras padrão se não existirem
                if not AutoResponse.query.filter_by(user_id=user.id).first():
                    default_responses = [
                        {
                            'keywords': 'preço,valor,quanto custa,preço,custo',
                            'response_text': 'Olá! O preço está na descrição do anúncio. Qualquer dúvida, estou à disposição!'
                        },
                        {
                            'keywords': 'entrega,prazo,demora,quando chega',
                            'response_text': 'Olá! O prazo de entrega varia conforme sua localização. Você pode verificar na página do produto. Obrigado!'
                        },
                        {
                            'keywords': 'disponível,estoque,tem,possui',
                            'response_text': 'Olá! Sim, temos o produto disponível. Pode fazer sua compra com tranquilidade!'
                        }
                    ]
                    
                    for resp in default_responses:
                        auto_resp = AutoResponse(
                            user_id=user.id,
                            keywords=resp['keywords'],
                            response_text=resp['response_text']
                        )
                        db.session.add(auto_resp)
                    
                    db.session.commit()
                    print("✅ Regras padrão criadas")
                
                _initialized = True
                print("✅ Banco de dados inicializado com sucesso")
                
        except Exception as e:
            print(f"❌ Erro ao inicializar banco: {e}")

def log_token_check(status, error_message=None):
    """Registra verificação de token no banco"""
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if user:
                log_entry = TokenLog(
                    user_id=user.id,
                    token_status=status,
                    error_message=error_message
                )
                db.session.add(log_entry)
                db.session.commit()
    except Exception as e:
        print(f"❌ Erro ao registrar log de token: {e}")

def log_webhook(topic=None, resource=None, user_id_ml=None, application_id=None, attempts=1, sent=None):
    """Registra webhook recebido no banco"""
    try:
        with app.app_context():
            webhook_log = WebhookLog(
                topic=topic,
                resource=resource,
                user_id_ml=user_id_ml,
                application_id=application_id,
                attempts=attempts,
                sent=sent
            )
            db.session.add(webhook_log)
            db.session.commit()
            print(f"📝 Webhook registrado: {topic} - {resource}")
    except Exception as e:
        print(f"❌ Erro ao registrar webhook: {e}")

def monitor_token():
    """Monitora o token a cada 5 minutos"""
    while True:
        try:
            is_valid, message = check_token_validity()
            
            if is_valid:
                log_token_check('valid')
            else:
                log_token_check('expired', message)
                
                # Tentar renovar automaticamente
                success, refresh_message = refresh_access_token()
                if success:
                    log_token_check('renewed', 'Token renovado automaticamente')
                else:
                    log_token_check('error', f'Falha na renovação: {refresh_message}')
            
            time.sleep(300)  # 5 minutos
            
        except Exception as e:
            print(f"❌ Erro no monitoramento de token: {e}")
            time.sleep(300)

def is_absence_time():
    """Verifica se está em horário de ausência"""
    now = get_local_time()
    current_time = now.strftime("%H:%M")
    current_weekday = str(now.weekday())  # 0=segunda, 6=domingo
    
    try:
        with app.app_context():
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
    except Exception as e:
        print(f"❌ Erro ao verificar horário de ausência: {e}")
    
    return None

def find_auto_response(question_text):
    """Encontra resposta automática baseada em palavras-chave"""
    question_lower = question_text.lower()
    
    try:
        with app.app_context():
            auto_responses = AutoResponse.query.filter_by(is_active=True).all()
            
            for response in auto_responses:
                keywords = [k.strip().lower() for k in response.keywords.split(',')]
                
                for keyword in keywords:
                    if keyword in question_lower:
                        return response.response_text, response.keywords
    except Exception as e:
        print(f"❌ Erro ao buscar resposta automática: {e}")
    
    return None, None

def process_questions():
    """Processa perguntas automaticamente com renovação de token"""
    try:
        with _db_lock:
            with app.app_context():
                # Buscar perguntas usando sistema de renovação automática
                questions = get_questions()
                
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
                        if answer_question(question_id, absence_message):
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
                            if answer_question(question_id, auto_response):
                                question.response_text = auto_response
                                question.is_answered = True
                                question.answered_automatically = True
                                question.answered_at = get_local_time_utc()
                                response_type = "auto"
                                keywords_matched = matched_keywords
                                print(f"✅ Pergunta {question_id} respondida automaticamente")
                    
                    # Registrar no histórico se foi respondida
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

def polling_loop():
    """Loop principal de polling com renovação automática"""
    print("🔄 Iniciando polling de perguntas...")
    
    while True:
        try:
            process_questions()
            time.sleep(30)  # Verificar a cada 30 segundos
        except Exception as e:
            print(f"❌ Erro no polling: {e}")
            time.sleep(60)  # Esperar mais tempo em caso de erro

def start_token_monitoring():
    """Inicia o monitoramento de token em background"""
    monitor_thread = threading.Thread(target=monitor_token, daemon=True)
    monitor_thread.start()
    print("🔍 Monitoramento de token iniciado")

# ========== ROTAS WEB ==========

@app.route('/')
def dashboard():
    """Dashboard principal com status do token - CORRIGIDO PARA RESOLVER 404"""
    try:
        with app.app_context():
            # Verificar token atual
            is_valid, message = check_token_validity()
            
            # Estatísticas
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if user:
                today = get_local_time_utc().date()
                
                total_questions = Question.query.filter_by(user_id=user.id).count()
                answered_today = Question.query.filter_by(user_id=user.id, is_answered=True).filter(
                    db.func.date(Question.answered_at) == today
                ).count()
                auto_responses_today = ResponseHistory.query.filter_by(user_id=user.id, response_type='auto').filter(
                    db.func.date(ResponseHistory.created_at) == today
                ).count()
                
                # Tempo médio de resposta
                avg_response = db.session.query(db.func.avg(ResponseHistory.response_time)).filter_by(user_id=user.id).scalar()
                avg_response = round(avg_response, 2) if avg_response else 0
                
                stats = {
                    'total_questions': total_questions,
                    'answered_today': answered_today,
                    'auto_responses_today': auto_responses_today,
                    'avg_response_time': avg_response
                }
            else:
                stats = {'total_questions': 0, 'answered_today': 0, 'auto_responses_today': 0, 'avg_response_time': 0}
            
            # Status do token
            token_status = {
                'valid': is_valid,
                'message': message,
                'last_check': TOKEN_STATUS.get('last_check'),
                'current_token': TOKEN_STATUS.get('current_token', '')[:20] + '...' if TOKEN_STATUS.get('current_token') else 'N/A'
            }
            
            current_time = get_local_time().strftime("%H:%M:%S")
            
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
                    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 20px; }}
                    .stat-card {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .stat-number {{ font-size: 2em; font-weight: bold; color: #2196F3; }}
                    .stat-label {{ color: #666; margin-top: 5px; }}
                    .token-status {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
                    .status-valid {{ color: #4CAF50; font-weight: bold; }}
                    .status-invalid {{ color: #f44336; font-weight: bold; }}
                    .nav {{ margin-bottom: 20px; }}
                    .nav a {{ display: inline-block; padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }}
                    .nav a:hover {{ background: #1976D2; }}
                    .btn {{ padding: 8px 16px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; }}
                    .btn:hover {{ background: #45a049; }}
                    .btn-warning {{ background: #ff9800; }}
                    .btn-warning:hover {{ background: #e68900; }}
                    .btn-danger {{ background: #f44336; }}
                    .btn-danger:hover {{ background: #da190b; }}
                </style>
                <script>
                    function refreshPage() {{ window.location.reload(); }}
                    function checkToken() {{
                        fetch('/api/token/check', {{method: 'POST'}})
                        .then(response => response.json())
                        .then(data => {{
                            alert(data.message || 'Verificação concluída');
                            refreshPage();
                        }})
                        .catch(error => alert('Erro: ' + error));
                    }}
                    setInterval(refreshPage, 60000); // Atualizar a cada minuto
                </script>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🤖 Bot Mercado Livre - Dashboard</h1>
                        <p><strong>Horário Local (SP):</strong> {current_time}</p>
                        <p><strong>Status:</strong> Sistema funcionando com renovação automática de token</p>
                        <p><strong>Deploy:</strong> ✅ Funcionando corretamente</p>
                    </div>
                    
                    <div class="nav">
                        <a href="/edit-rules">✏️ Editar Regras</a>
                        <a href="/edit-absence">🌙 Configurar Ausência</a>
                        <a href="/history">📊 Histórico</a>
                        <a href="/token-status">🔑 Status do Token</a>
                        <a href="/questions">❓ Perguntas</a>
                        <a href="/renovar-tokens" style="background: #ff9800;">🔄 Renovar Tokens</a>
                        <a href="/webhook-logs">📡 Logs Webhook</a>
                    </div>
                    
                    <div class="token-status">
                        <h3>🔑 Status do Token</h3>
                        <p><strong>Status:</strong> 
                            <span class="{'status-valid' if token_status['valid'] else 'status-invalid'}">
                                {'✅ Válido' if token_status['valid'] else '❌ Inválido'}
                            </span>
                        </p>
                        <p><strong>Token:</strong> {token_status['current_token']}</p>
                        <p><strong>Última Verificação:</strong> {token_status['last_check'].strftime('%H:%M:%S') if token_status['last_check'] else 'Nunca'}</p>
                        <p><strong>Mensagem:</strong> {token_status['message']}</p>
                        <button class="btn btn-warning" onclick="checkToken()">🔄 Verificar Agora</button>
                        {'<a href="/renovar-tokens" class="btn btn-danger">🚨 Renovar Tokens</a>' if not token_status['valid'] else ''}
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
                            <div class="stat-number">{stats['auto_responses_today']}</div>
                            <div class="stat-label">Respostas Automáticas Hoje</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{stats['avg_response_time']}s</div>
                            <div class="stat-label">Tempo Médio de Resposta</div>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """
            
            return html
            
    except Exception as e:
        return f"""
        <!DOCTYPE html>
        <html>
        <head><title>Bot ML - Erro</title></head>
        <body>
            <h1>❌ Erro no Dashboard</h1>
            <p>Erro: {e}</p>
            <p>O sistema está inicializando, tente novamente em alguns segundos.</p>
            <a href="/">🔄 Recarregar</a>
        </body>
        </html>
        """

# ========== WEBHOOK CORRIGIDO PARA RESOLVER 405 ==========

@app.route('/api/ml/webhook', methods=['GET', 'POST'])
def webhook_handler():
    """Webhook para receber notificações do ML - CORRIGIDO PARA ACEITAR GET E POST"""
    try:
        if request.method == 'GET':
            # GET request - pode ser callback de autorização
            code = request.args.get('code')
            error = request.args.get('error')
            
            if error:
                return f"""
                <h1>❌ Erro na Autorização (Webhook)</h1>
                <p>Erro: {error}</p>
                <p>Descrição: {request.args.get('error_description', 'N/A')}</p>
                <a href="/renovar-tokens">🔄 Tentar Novamente</a>
                """
            
            if code:
                return f"""
                <h1>✅ Código Recebido via Webhook!</h1>
                <p><strong>Código de Autorização:</strong></p>
                <div style="background: #f5f5f5; padding: 10px; border-radius: 4px; font-family: monospace; word-break: break-all;">
                    {code}
                </div>
                <p>Copie este código e cole na interface de renovação.</p>
                <a href="/renovar-tokens">🔄 Ir para Renovação</a>
                """
            
            return """
            <h1>📡 Webhook ML - Status</h1>
            <p>✅ Webhook funcionando corretamente</p>
            <p>🔄 Aguardando notificações do Mercado Livre</p>
            <a href="/">🏠 Voltar ao Dashboard</a>
            """
        
        elif request.method == 'POST':
            # POST request - notificação do ML
            try:
                # Obter dados do webhook
                data = request.get_json() or {}
                
                topic = data.get('topic')
                resource = data.get('resource')
                user_id_ml = data.get('user_id')
                application_id = data.get('application_id')
                attempts = data.get('attempts', 1)
                sent = data.get('sent')
                
                print(f"📡 Webhook recebido: {topic} - {resource}")
                
                # Registrar webhook no banco
                log_webhook(topic, resource, user_id_ml, application_id, attempts, sent)
                
                # Processar diferentes tipos de notificação
                if topic == 'questions':
                    print("❓ Nova pergunta recebida via webhook")
                    # Processar perguntas imediatamente
                    threading.Thread(target=process_questions, daemon=True).start()
                
                elif topic == 'orders_v2':
                    print("🛒 Nova ordem recebida via webhook")
                
                elif topic == 'items':
                    print("📦 Atualização de item via webhook")
                
                # Retornar resposta de sucesso para o ML
                return jsonify({'status': 'ok', 'message': 'Webhook processado com sucesso'}), 200
                
            except Exception as e:
                print(f"❌ Erro ao processar webhook: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500
    
    except Exception as e:
        print(f"❌ Erro geral no webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/webhook-logs')
def webhook_logs():
    """Página para visualizar logs de webhook"""
    try:
        with app.app_context():
            logs = WebhookLog.query.order_by(WebhookLog.received.desc()).limit(50).all()
            
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Logs Webhook - Bot ML</title>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
                    .container { max-width: 1200px; margin: 0 auto; }
                    .card { background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                    .nav a { display: inline-block; padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }
                    table { width: 100%; border-collapse: collapse; }
                    th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
                    th { background: #f5f5f5; }
                    .topic-questions { color: #2196F3; }
                    .topic-orders { color: #4CAF50; }
                    .topic-items { color: #ff9800; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <h1>📡 Logs de Webhook</h1>
                        <div class="nav">
                            <a href="/">🏠 Dashboard</a>
                            <a href="/edit-rules">✏️ Regras</a>
                            <a href="/history">📊 Histórico</a>
                            <a href="/renovar-tokens">🔄 Renovar Tokens</a>
                        </div>
                    </div>
                    
                    <div class="card">
                        <table>
                            <thead>
                                <tr>
                                    <th>Data/Hora</th>
                                    <th>Tópico</th>
                                    <th>Recurso</th>
                                    <th>User ID</th>
                                    <th>Tentativas</th>
                                </tr>
                            </thead>
                            <tbody>
            """
            
            for log in logs:
                received_at = format_local_time(log.received)
                date_str = received_at.strftime('%d/%m %H:%M:%S') if received_at else 'N/A'
                
                topic_class = f"topic-{log.topic}" if log.topic else ""
                
                html += f"""
                                <tr>
                                    <td>{date_str}</td>
                                    <td class="{topic_class}">{log.topic or 'N/A'}</td>
                                    <td>{log.resource or 'N/A'}</td>
                                    <td>{log.user_id_ml or 'N/A'}</td>
                                    <td>{log.attempts}</td>
                                </tr>
                """
            
            html += """
                            </tbody>
                        </table>
                    </div>
                </div>
            </body>
            </html>
            """
            
            return html
            
    except Exception as e:
        return f"Erro: {e}"

# ========== ROTAS DE RENOVAÇÃO DE TOKENS ==========

@app.route('/renovar-tokens')
def renovar_tokens_page():
    """Interface para renovação de tokens"""
    auth_url = generate_auth_url()
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Renovar Tokens - Bot ML</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .card {{ background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .nav a {{ display: inline-block; padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }}
            .nav a:hover {{ background: #1976D2; }}
            .btn {{ padding: 12px 24px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; display: inline-block; font-size: 16px; }}
            .btn:hover {{ background: #45a049; }}
            .btn-primary {{ background: #2196F3; }}
            .btn-primary:hover {{ background: #1976D2; }}
            .btn-warning {{ background: #ff9800; }}
            .btn-warning:hover {{ background: #e68900; }}
            .form-group {{ margin-bottom: 15px; }}
            label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
            input, textarea {{ width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; font-size: 14px; }}
            .alert {{ padding: 15px; border-radius: 4px; margin-bottom: 20px; }}
            .alert-info {{ background: #e3f2fd; border: 1px solid #2196F3; color: #1976D2; }}
            .alert-success {{ background: #e8f5e8; border: 1px solid #4CAF50; color: #2e7d32; }}
            .alert-danger {{ background: #ffebee; border: 1px solid #f44336; color: #c62828; }}
            .step {{ background: #f8f9fa; padding: 15px; border-left: 4px solid #2196F3; margin-bottom: 15px; }}
            .step h4 {{ margin: 0 0 10px 0; color: #1976D2; }}
            .code-box {{ background: #f5f5f5; padding: 10px; border-radius: 4px; font-family: monospace; word-break: break-all; }}
        </style>
        <script>
            function abrirAutorizacao() {{
                window.open('{auth_url}', '_blank');
            }}
            
            function processarCodigo() {{
                const codigo = document.getElementById('codigo').value.trim();
                if (!codigo) {{
                    alert('Por favor, insira o código de autorização');
                    return;
                }}
                
                document.getElementById('loading').style.display = 'block';
                document.getElementById('btn-processar').disabled = true;
                
                fetch('/api/tokens/process-code-flexible', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{code: codigo}})
                }})
                .then(response => response.json())
                .then(data => {{
                    document.getElementById('loading').style.display = 'none';
                    document.getElementById('btn-processar').disabled = false;
                    
                    if (data.success) {{
                        document.getElementById('resultado').innerHTML = `
                            <div class="alert alert-success">
                                <h4>✅ Tokens Atualizados com Sucesso!</h4>
                                <p><strong>Access Token:</strong> ${{data.access_token.substring(0, 30)}}...</p>
                                <p><strong>User ID:</strong> ${{data.user_id}}</p>
                                <p><strong>Email:</strong> ${{data.user_email}}</p>
                                <p><strong>Expira em:</strong> ${{data.expires_in}} segundos</p>
                                <p>🎉 Sistema atualizado automaticamente!</p>
                            </div>
                        `;
                        document.getElementById('codigo').value = '';
                        
                        // Recarregar página após 3 segundos
                        setTimeout(() => {{
                            window.location.href = '/';
                        }}, 3000);
                    }} else {{
                        document.getElementById('resultado').innerHTML = `
                            <div class="alert alert-danger">
                                <h4>❌ Erro ao Processar Código</h4>
                                <p>${{data.error}}</p>
                            </div>
                        `;
                    }}
                }})
                .catch(error => {{
                    document.getElementById('loading').style.display = 'none';
                    document.getElementById('btn-processar').disabled = false;
                    document.getElementById('resultado').innerHTML = `
                        <div class="alert alert-danger">
                            <h4>❌ Erro na Requisição</h4>
                            <p>${{error}}</p>
                        </div>
                    `;
                }});
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>🔄 Renovar Tokens do Bot</h1>
                <div class="nav">
                    <a href="/">🏠 Dashboard</a>
                    <a href="/token-status">🔑 Status Token</a>
                    <a href="/edit-rules">✏️ Regras</a>
                </div>
            </div>
            
            <div class="card">
                <div class="alert alert-info">
                    <h4>ℹ️ Como Renovar os Tokens</h4>
                    <p>Este sistema aceita códigos gerados com <strong>qualquer URL de redirect</strong>, resolvendo problemas de compatibilidade.</p>
                </div>
                
                <div class="step">
                    <h4>📋 Passo 1: Autorizar Aplicação</h4>
                    <p>Clique no botão abaixo para abrir a página de autorização do Mercado Livre:</p>
                    <button class="btn btn-primary" onclick="abrirAutorizacao()">
                        🌐 Abrir Autorização do ML
                    </button>
                </div>
                
                <div class="step">
                    <h4>🔑 Passo 2: Obter Código</h4>
                    <p>Após autorizar:</p>
                    <ol>
                        <li>✅ Faça login no Mercado Livre</li>
                        <li>✅ Autorize a aplicação</li>
                        <li>✅ Você será redirecionado (pode dar erro, é normal)</li>
                        <li>✅ <strong>Copie APENAS o código da URL</strong> (ex: TG-abc123...)</li>
                    </ol>
                    <p><strong>💡 Dica:</strong> O código funciona independente da URL de redirect usada!</p>
                </div>
                
                <div class="step">
                    <h4>🔄 Passo 3: Processar Código</h4>
                    <div class="form-group">
                        <label for="codigo">Cole APENAS o código de autorização aqui:</label>
                        <input type="text" id="codigo" placeholder="TG-abc123def456..." />
                        <small>Exemplo: TG-68839cdf8b73a2000176ea5f-180617463</small>
                    </div>
                    <button class="btn btn-warning" onclick="processarCodigo()" id="btn-processar">
                        🔄 Processar e Atualizar Tokens
                    </button>
                    <div id="loading" style="display: none; margin-top: 10px;">
                        <p>⏳ Processando código com múltiplas tentativas de redirect_uri...</p>
                    </div>
                </div>
                
                <div id="resultado"></div>
            </div>
            
            <div class="card">
                <h3>🔗 URLs de Redirect Suportadas</h3>
                <div class="code-box">
                    {chr(10).join(REDIRECT_URIS)}
                </div>
                <p><small>O sistema tenta automaticamente todas as URLs até encontrar a correta.</small></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html

@app.route('/api/tokens/process-code-flexible', methods=['POST'])
def process_authorization_code_flexible():
    """API para processar código de autorização com múltiplas tentativas de redirect_uri"""
    try:
        data = request.get_json()
        code = data.get('code', '').strip()
        
        if not code:
            return jsonify({'success': False, 'error': 'Código não fornecido'})
        
        print(f"🔄 Processando código: {code}")
        
        # Obter tokens do código com múltiplas tentativas
        tokens_data, error = get_tokens_from_code_flexible(code)
        if error:
            return jsonify({'success': False, 'error': error})
        
        # Obter informações do usuário
        user_info, error = get_user_info(tokens_data.get('access_token'))
        if error:
            print(f"⚠️ Aviso: {error}")
        
        # Atualizar sistema
        success, message = update_system_tokens(tokens_data, user_info)
        if not success:
            return jsonify({'success': False, 'error': message})
        
        return jsonify({
            'success': True,
            'message': 'Tokens atualizados com sucesso',
            'access_token': tokens_data.get('access_token'),
            'user_id': user_info.get('id') if user_info else 'N/A',
            'user_email': user_info.get('email') if user_info else 'N/A',
            'expires_in': tokens_data.get('expires_in'),
            'redirect_uri_used': 'Múltiplas tentativas - sucesso!'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/token/check', methods=['POST'])
def check_token_api():
    """API para verificar token manualmente"""
    try:
        is_valid, message = check_token_validity()
        
        if not is_valid:
            # Tentar renovar automaticamente
            success, refresh_message = refresh_access_token()
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Token renovado automaticamente!',
                    'status': 'renewed'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Token inválido. Use a interface de renovação para gerar novos tokens.',
                    'status': 'error'
                })
        else:
            return jsonify({
                'success': True,
                'message': 'Token válido!',
                'status': 'valid'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Erro na verificação: {str(e)}',
            'status': 'error'
        })

# ========== CALLBACKS ALTERNATIVOS ==========

@app.route('/api/ml/auth-callback')
def auth_callback():
    """Callback para receber código de autorização"""
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
        return f"""
        <h1>❌ Erro na Autorização</h1>
        <p>Erro: {error}</p>
        <p>Descrição: {request.args.get('error_description', 'N/A')}</p>
        <a href="/renovar-tokens">🔄 Tentar Novamente</a>
        """
    
    if code:
        return f"""
        <h1>✅ Código Recebido!</h1>
        <p><strong>Código de Autorização:</strong></p>
        <div style="background: #f5f5f5; padding: 10px; border-radius: 4px; font-family: monospace; word-break: break-all;">
            {code}
        </div>
        <p>Copie este código e cole na interface de renovação.</p>
        <a href="/renovar-tokens">🔄 Ir para Renovação</a>
        """
    
    return """
    <h1>❌ Código não encontrado</h1>
    <p>Não foi possível obter o código de autorização.</p>
    <a href="/renovar-tokens">🔄 Tentar Novamente</a>
    """

# ========== OUTRAS ROTAS ESSENCIAIS ==========

@app.route('/edit-rules')
def edit_rules():
    """Interface para editar regras de resposta"""
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if user:
                rules = AutoResponse.query.filter_by(user_id=user.id).all()
            else:
                rules = []
            
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Editar Regras - Bot ML</title>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
                    .container { max-width: 800px; margin: 0 auto; }
                    .card { background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                    .form-group { margin-bottom: 15px; }
                    label { display: block; margin-bottom: 5px; font-weight: bold; }
                    input, textarea { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
                    textarea { height: 80px; resize: vertical; }
                    .btn { padding: 10px 20px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; }
                    .btn:hover { background: #45a049; }
                    .btn-danger { background: #f44336; }
                    .btn-danger:hover { background: #da190b; }
                    .rule-item { border: 1px solid #ddd; padding: 15px; margin-bottom: 10px; border-radius: 4px; }
                    .nav a { display: inline-block; padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <h1>✏️ Editar Regras de Resposta</h1>
                        <div class="nav">
                            <a href="/">🏠 Dashboard</a>
                            <a href="/edit-absence">🌙 Ausência</a>
                            <a href="/history">📊 Histórico</a>
                            <a href="/renovar-tokens">🔄 Renovar Tokens</a>
                        </div>
                    </div>
                    
                    <div class="card">
                        <h3>➕ Adicionar Nova Regra</h3>
                        <form method="POST" action="/api/rules">
                            <div class="form-group">
                                <label>Palavras-chave (separadas por vírgula):</label>
                                <input type="text" name="keywords" placeholder="preço,valor,quanto custa" required>
                            </div>
                            <div class="form-group">
                                <label>Resposta:</label>
                                <textarea name="response_text" placeholder="Olá! O preço está na descrição..." required></textarea>
                            </div>
                            <button type="submit" class="btn">💾 Salvar Regra</button>
                        </form>
                    </div>
                    
                    <div class="card">
                        <h3>📋 Regras Existentes</h3>
            """
            
            for rule in rules:
                status = "✅ Ativa" if rule.is_active else "❌ Inativa"
                html += f"""
                        <div class="rule-item">
                            <p><strong>Palavras-chave:</strong> {rule.keywords}</p>
                            <p><strong>Resposta:</strong> {rule.response_text}</p>
                            <p><strong>Status:</strong> {status}</p>
                            <button class="btn btn-danger" onclick="deleteRule({rule.id})">🗑️ Excluir</button>
                        </div>
                """
            
            html += """
                    </div>
                </div>
                
                <script>
                    function deleteRule(id) {
                        if (confirm('Tem certeza que deseja excluir esta regra?')) {
                            fetch('/api/rules/' + id, {method: 'DELETE'})
                            .then(() => window.location.reload())
                            .catch(error => alert('Erro: ' + error));
                        }
                    }
                </script>
            </body>
            </html>
            """
            
            return html
            
    except Exception as e:
        return f"Erro: {e}"

@app.route('/api/rules', methods=['POST'])
def add_rule():
    """API para adicionar nova regra"""
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return jsonify({'error': 'Usuário não encontrado'}), 404
            
            keywords = request.form.get('keywords')
            response_text = request.form.get('response_text')
            
            if not keywords or not response_text:
                return jsonify({'error': 'Campos obrigatórios'}), 400
            
            rule = AutoResponse(
                user_id=user.id,
                keywords=keywords,
                response_text=response_text
            )
            
            db.session.add(rule)
            db.session.commit()
            
            return redirect('/edit-rules')
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/rules/<int:rule_id>', methods=['DELETE'])
def delete_rule(rule_id):
    """API para excluir regra"""
    try:
        with app.app_context():
            rule = AutoResponse.query.get(rule_id)
            if rule:
                db.session.delete(rule)
                db.session.commit()
                return jsonify({'success': True})
            else:
                return jsonify({'error': 'Regra não encontrada'}), 404
                
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Adicionar outras rotas essenciais (history, questions, edit-absence, token-status)
@app.route('/history')
def history():
    """Página de histórico de respostas"""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Histórico - Bot ML</title></head>
    <body>
        <h1>📊 Histórico de Respostas</h1>
        <p>Página em desenvolvimento...</p>
        <a href="/">🏠 Voltar ao Dashboard</a>
    </body>
    </html>
    """

@app.route('/questions')
def questions_page():
    """Página de perguntas recebidas"""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Perguntas - Bot ML</title></head>
    <body>
        <h1>❓ Perguntas Recebidas</h1>
        <p>Página em desenvolvimento...</p>
        <a href="/">🏠 Voltar ao Dashboard</a>
    </body>
    </html>
    """

@app.route('/edit-absence')
def edit_absence():
    """Interface para configurar mensagens de ausência"""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Configurar Ausência - Bot ML</title></head>
    <body>
        <h1>🌙 Configurar Ausência</h1>
        <p>Página em desenvolvimento...</p>
        <a href="/">🏠 Voltar ao Dashboard</a>
    </body>
    </html>
    """

@app.route('/token-status')
def token_status_page():
    """Página detalhada do status do token"""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Status do Token - Bot ML</title></head>
    <body>
        <h1>🔑 Status do Token</h1>
        <p>Página em desenvolvimento...</p>
        <a href="/">🏠 Voltar ao Dashboard</a>
    </body>
    </html>
    """

# ========== INICIALIZAÇÃO ==========

def start_background_tasks():
    """Inicia tarefas em background"""
    # Inicializar banco
    init_database()
    
    # Verificar token inicial
    check_token_validity()
    
    # Iniciar monitoramento de token
    start_token_monitoring()
    
    # Iniciar polling de perguntas
    polling_thread = threading.Thread(target=polling_loop, daemon=True)
    polling_thread.start()
    
    print("✅ Sistema iniciado com correções para deploy!")
    print("🔧 Erros 404 e 405 corrigidos")
    print("📡 Webhook funcionando com GET e POST")

if __name__ == '__main__':
    start_background_tasks()
    app.run(host='0.0.0.0', port=5000, debug=False)

