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

# URLs de redirect possíveis (para flexibilidade) - WEBHOOK COMO PADRÃO
REDIRECT_URIS = [
    "https://bot-mercadolivre-dettech.onrender.com/api/ml/webhook",
    "https://bot-mercadolivre-dettech.onrender.com/api/ml/auth-callback",
    "http://localhost:5000/api/ml/webhook",
    "http://localhost:5000/api/ml/auth-callback"
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

# VARIÁVEIS GLOBAIS PARA DEBUG
DEBUG_LOGS = []
MAX_DEBUG_LOGS = 100

def add_debug_log(message):
    """Adiciona log de debug com timestamp"""
    global DEBUG_LOGS
    timestamp = get_local_time().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    DEBUG_LOGS.append(log_entry)
    if len(DEBUG_LOGS) > MAX_DEBUG_LOGS:
        DEBUG_LOGS.pop(0)
    print(log_entry)

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
                add_debug_log("❌ Refresh token não encontrado!")
                return False, "Refresh token não disponível"
            
            add_debug_log("🔄 Tentando renovar token...")
            
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
                
                add_debug_log(f"✅ Token renovado com sucesso!")
                add_debug_log(f"🔑 Novo token: {new_access_token[:20]}...")
                
                return True, "Token renovado com sucesso"
                
            else:
                error_msg = f"Erro na renovação: {response.status_code} - {response.text}"
                add_debug_log(f"❌ {error_msg}")
                TOKEN_STATUS['error_message'] = error_msg
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Erro na renovação do token: {str(e)}"
            add_debug_log(f"💥 {error_msg}")
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
                add_debug_log("💾 Tokens salvos no banco de dados")
    except Exception as e:
        add_debug_log(f"❌ Erro ao salvar tokens no banco: {e}")

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
            add_debug_log(f"✅ Token válido! Usuário: {user_info.get('nickname', 'N/A')}")
            return True, "Token válido"
            
        elif response.status_code == 401:
            TOKEN_STATUS['valid'] = False
            TOKEN_STATUS['error_message'] = "Token expirado"
            add_debug_log("⚠️ Token expirado (401)")
            return False, "Token expirado"
            
        else:
            TOKEN_STATUS['valid'] = False
            error_msg = f"Erro {response.status_code}: {response.text}"
            TOKEN_STATUS['error_message'] = error_msg
            add_debug_log(f"❌ Erro na verificação: {error_msg}")
            return False, error_msg
            
    except Exception as e:
        TOKEN_STATUS['valid'] = False
        error_msg = f"Erro na verificação: {str(e)}"
        TOKEN_STATUS['error_message'] = error_msg
        add_debug_log(f"💥 {error_msg}")
        return False, error_msg

def get_valid_token():
    """Retorna um token válido, renovando automaticamente se necessário"""
    global TOKEN_STATUS
    
    # Verificar se token atual é válido
    is_valid, message = check_token_validity()
    
    if is_valid:
        return TOKEN_STATUS['current_token']
    
    # Token inválido, tentar renovar
    add_debug_log("🔄 Token inválido, tentando renovar automaticamente...")
    success, message = refresh_access_token()
    
    if success:
        return TOKEN_STATUS['current_token']
    else:
        add_debug_log(f"❌ Falha na renovação automática: {message}")
        add_debug_log("🚨 AÇÃO NECESSÁRIA: Renovar token manualmente!")
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
                add_debug_log(f"🔄 Erro 401 na tentativa {attempt + 1}, tentando renovar token...")
                TOKEN_STATUS['valid'] = False  # Forçar renovação na próxima tentativa
                continue
            
            else:
                return response, f"Erro {response.status_code}: {response.text}"
                
        except Exception as e:
            if attempt < max_retries:
                add_debug_log(f"🔄 Erro na tentativa {attempt + 1}: {e}")
                continue
            else:
                return None, f"Erro na requisição: {str(e)}"
    
    return None, "Máximo de tentativas excedido"

# ========== FUNÇÕES ORIGINAIS ADAPTADAS ==========

def get_questions():
    """Busca perguntas não respondidas usando o sistema de renovação automática"""
    try:
        url = f"https://api.mercadolibre.com/my/received_questions/search?seller_id={ML_USER_ID}&status=UNANSWERED"
        
        add_debug_log(f"🔍 Buscando perguntas em: {url}")
        
        response, message = make_ml_request(url)
        
        if response and response.status_code == 200:
            questions_data = response.json()
            questions = questions_data.get('questions', [])
            add_debug_log(f"📥 {len(questions)} perguntas encontradas na API")
            return questions
        else:
            add_debug_log(f"❌ Erro ao buscar perguntas: {message}")
            return []
            
    except Exception as e:
        add_debug_log(f"💥 Erro ao buscar perguntas: {e}")
        return []

def answer_question(question_id, answer_text):
    """Responde uma pergunta usando o sistema de renovação automática"""
    try:
        url = f"https://api.mercadolibre.com/answers"
        data = {
            'question_id': question_id,
            'text': answer_text
        }
        
        add_debug_log(f"📤 Tentando responder pergunta {question_id}")
        add_debug_log(f"📝 Resposta: {answer_text[:50]}...")
        
        response, message = make_ml_request(url, method='POST', data=data)
        
        if response and response.status_code in [200, 201]:
            add_debug_log(f"✅ Pergunta {question_id} respondida com sucesso!")
            return True
        else:
            add_debug_log(f"❌ Erro ao responder pergunta {question_id}: {message}")
            return False
            
    except Exception as e:
        add_debug_log(f"💥 Erro ao responder pergunta {question_id}: {e}")
        return False

# ========== FUNÇÕES DE PROCESSAMENTO COM DEBUG INTENSIVO ==========

def init_database():
    """Inicializa o banco de dados"""
    global _initialized
    
    with _db_lock:
        if _initialized:
            return
        
        try:
            with app.app_context():
                add_debug_log("🔧 Inicializando banco de dados...")
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
                    add_debug_log(f"✅ Usuário {ML_USER_ID} criado no banco")
                else:
                    # Atualizar tokens se necessário
                    user.access_token = ML_ACCESS_TOKEN
                    if ML_REFRESH_TOKEN:
                        user.refresh_token = ML_REFRESH_TOKEN
                    user.updated_at = get_local_time_utc()
                    db.session.commit()
                    add_debug_log(f"✅ Usuário {ML_USER_ID} atualizado")
                
                # Verificar regras existentes
                rules_count = AutoResponse.query.filter_by(user_id=user.id).count()
                add_debug_log(f"📋 Regras de resposta no banco: {rules_count}")
                
                # Verificar configurações de ausência
                absence_count = AbsenceConfig.query.filter_by(user_id=user.id).count()
                add_debug_log(f"🌙 Configurações de ausência no banco: {absence_count}")
                
                # Criar regras padrão se não existirem
                if rules_count == 0:
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
                    add_debug_log("✅ Regras padrão criadas")
                
                _initialized = True
                add_debug_log("✅ Banco de dados inicializado com sucesso")
                
        except Exception as e:
            add_debug_log(f"❌ Erro ao inicializar banco: {e}")

def is_absence_time():
    """Verifica se está em horário de ausência - COM DEBUG INTENSIVO"""
    try:
        now = get_local_time()
        current_time = now.strftime("%H:%M")
        current_weekday = str(now.weekday())  # 0=segunda, 6=domingo
        
        add_debug_log(f"🔍 VERIFICANDO AUSÊNCIA:")
        add_debug_log(f"   Horário atual: {current_time}")
        add_debug_log(f"   Dia da semana: {current_weekday} (0=seg, 6=dom)")
        
        with app.app_context():
            absence_configs = AbsenceConfig.query.filter_by(is_active=True).all()
            add_debug_log(f"   Configurações ativas encontradas: {len(absence_configs)}")
            
            if not absence_configs:
                add_debug_log("   ❌ NENHUMA configuração de ausência ativa!")
                return None
            
            for i, config in enumerate(absence_configs):
                add_debug_log(f"   🔍 Testando config {i+1}: '{config.name}'")
                add_debug_log(f"      Dias configurados: '{config.days_of_week}'")
                add_debug_log(f"      Horário: {config.start_time} - {config.end_time}")
                add_debug_log(f"      Ativa: {config.is_active}")
                
                # Verificar se o dia atual está na configuração
                if config.days_of_week and current_weekday in config.days_of_week.split(','):
                    add_debug_log(f"      ✅ Dia {current_weekday} ESTÁ na configuração")
                    
                    start_time = config.start_time
                    end_time = config.end_time
                    
                    # Se start_time > end_time, significa que cruza meia-noite
                    if start_time > end_time:
                        add_debug_log(f"      🌙 Configuração cruza meia-noite")
                        if current_time >= start_time or current_time <= end_time:
                            add_debug_log(f"      ✅ AUSÊNCIA ATIVA! Config: {config.name}")
                            add_debug_log(f"      📝 Mensagem: {config.message[:50]}...")
                            return config.message
                        else:
                            add_debug_log(f"      ❌ Fora do horário de ausência")
                    else:
                        add_debug_log(f"      🕐 Configuração no mesmo dia")
                        if start_time <= current_time <= end_time:
                            add_debug_log(f"      ✅ AUSÊNCIA ATIVA! Config: {config.name}")
                            add_debug_log(f"      📝 Mensagem: {config.message[:50]}...")
                            return config.message
                        else:
                            add_debug_log(f"      ❌ Fora do horário: {current_time} não está entre {start_time} e {end_time}")
                else:
                    add_debug_log(f"      ❌ Dia {current_weekday} NÃO está na configuração '{config.days_of_week}'")
        
        add_debug_log("   ❌ NENHUMA configuração de ausência corresponde ao horário atual")
        return None
        
    except Exception as e:
        add_debug_log(f"❌ ERRO ao verificar horário de ausência: {e}")
        import traceback
        add_debug_log(f"   Traceback: {traceback.format_exc()}")
        return None

def find_auto_response(question_text):
    """Encontra resposta automática baseada em palavras-chave - COM DEBUG INTENSIVO"""
    try:
        question_lower = question_text.lower()
        add_debug_log(f"🔍 BUSCANDO RESPOSTA AUTOMÁTICA:")
        add_debug_log(f"   Pergunta original: '{question_text}'")
        add_debug_log(f"   Pergunta lowercase: '{question_lower}'")
        
        with app.app_context():
            auto_responses = AutoResponse.query.filter_by(is_active=True).all()
            add_debug_log(f"   Regras ativas encontradas: {len(auto_responses)}")
            
            if not auto_responses:
                add_debug_log("   ❌ NENHUMA regra ativa encontrada!")
                return None, None
            
            for i, response in enumerate(auto_responses):
                add_debug_log(f"   🔍 Testando regra {i+1}:")
                add_debug_log(f"      ID: {response.id}")
                add_debug_log(f"      Keywords: '{response.keywords}'")
                add_debug_log(f"      Ativa: {response.is_active}")
                add_debug_log(f"      Resposta: '{response.response_text[:30]}...'")
                
                keywords = [k.strip().lower() for k in response.keywords.split(',')]
                add_debug_log(f"      Keywords processadas: {keywords}")
                
                for j, keyword in enumerate(keywords):
                    add_debug_log(f"         Testando keyword {j+1}: '{keyword}'")
                    if keyword and keyword in question_lower:
                        add_debug_log(f"         ✅ MATCH! Palavra-chave '{keyword}' encontrada!")
                        add_debug_log(f"         🎯 Resposta selecionada: {response.response_text[:50]}...")
                        return response.response_text, response.keywords
                    else:
                        add_debug_log(f"         ❌ Palavra-chave '{keyword}' NÃO encontrada")
        
        add_debug_log("   ❌ NENHUMA palavra-chave correspondente encontrada")
        return None, None
        
    except Exception as e:
        add_debug_log(f"❌ ERRO ao buscar resposta automática: {e}")
        import traceback
        add_debug_log(f"   Traceback: {traceback.format_exc()}")
        return None, None

def process_questions():
    """Processa perguntas automaticamente - COM DEBUG INTENSIVO"""
    try:
        add_debug_log("🔄 ========== INICIANDO PROCESSAMENTO DE PERGUNTAS ==========")
        
        with _db_lock:
            with app.app_context():
                # Buscar perguntas usando sistema de renovação automática
                questions = get_questions()
                add_debug_log(f"📥 Perguntas retornadas pela API: {len(questions)}")
                
                if not questions:
                    add_debug_log("📭 Nenhuma pergunta nova encontrada - finalizando processamento")
                    return
                
                user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
                if not user:
                    add_debug_log("❌ Usuário não encontrado no banco - ERRO CRÍTICO")
                    return
                
                add_debug_log(f"👤 Usuário encontrado: ID {user.id}")
                
                for i, q in enumerate(questions):
                    question_id = str(q.get("id"))
                    question_text = q.get("text", "")
                    item_id = q.get("item_id", "")
                    
                    add_debug_log(f"\n📝 ========== PROCESSANDO PERGUNTA {i+1}/{len(questions)} ==========")
                    add_debug_log(f"   ID: {question_id}")
                    add_debug_log(f"   Item: {item_id}")
                    add_debug_log(f"   Texto: '{question_text}'")
                    
                    # Verificar se já processamos esta pergunta
                    existing = Question.query.filter_by(ml_question_id=question_id).first()
                    if existing:
                        add_debug_log(f"   ⏭️ Pergunta {question_id} já existe no banco - PULANDO")
                        continue
                    
                    add_debug_log(f"   ✅ Pergunta {question_id} é NOVA - processando...")
                    
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
                    add_debug_log(f"   💾 Pergunta salva no banco com ID: {question.id}")
                    
                    response_type = None
                    keywords_matched = None
                    response_given = False
                    
                    # PRIMEIRO: Verificar se está em horário de ausência
                    add_debug_log(f"   🌙 ========== VERIFICANDO AUSÊNCIA ==========")
                    absence_message = is_absence_time()
                    if absence_message:
                        add_debug_log(f"   🌙 AUSÊNCIA DETECTADA! Enviando resposta...")
                        if answer_question(question_id, absence_message):
                            question.response_text = absence_message
                            question.is_answered = True
                            question.answered_automatically = True
                            question.answered_at = get_local_time_utc()
                            response_type = "absence"
                            response_given = True
                            add_debug_log(f"   ✅ Pergunta {question_id} respondida com AUSÊNCIA")
                        else:
                            add_debug_log(f"   ❌ FALHA ao enviar mensagem de ausência para {question_id}")
                    else:
                        add_debug_log(f"   ❌ Não está em horário de ausência")
                    
                    # SEGUNDO: Se não está em ausência, buscar resposta automática
                    if not response_given:
                        add_debug_log(f"   🤖 ========== VERIFICANDO REGRAS AUTOMÁTICAS ==========")
                        auto_response, matched_keywords = find_auto_response(question_text)
                        if auto_response:
                            add_debug_log(f"   🤖 REGRA ENCONTRADA! Enviando resposta...")
                            if answer_question(question_id, auto_response):
                                question.response_text = auto_response
                                question.is_answered = True
                                question.answered_automatically = True
                                question.answered_at = get_local_time_utc()
                                response_type = "auto"
                                keywords_matched = matched_keywords
                                response_given = True
                                add_debug_log(f"   ✅ Pergunta {question_id} respondida AUTOMATICAMENTE")
                            else:
                                add_debug_log(f"   ❌ FALHA ao enviar resposta automática para {question_id}")
                        else:
                            add_debug_log(f"   ❌ Nenhuma regra automática encontrada")
                    
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
                        add_debug_log(f"   📊 Histórico registrado: tipo={response_type}, tempo={response_time:.2f}s")
                    else:
                        add_debug_log(f"   📝 Pergunta {question_id} salva SEM resposta automática")
                    
                    db.session.commit()
                    add_debug_log(f"   💾 Pergunta {question_id} processada e commitada no banco")
                    
        add_debug_log("✅ ========== PROCESSAMENTO DE PERGUNTAS CONCLUÍDO ==========")
                    
    except Exception as e:
        add_debug_log(f"❌ ERRO CRÍTICO ao processar perguntas: {e}")
        import traceback
        add_debug_log(f"   Traceback completo: {traceback.format_exc()}")

def polling_loop():
    """Loop principal de polling com renovação automática"""
    add_debug_log("🔄 Iniciando polling de perguntas...")
    
    while True:
        try:
            process_questions()
            add_debug_log("⏰ Aguardando 30 segundos para próxima verificação...")
            time.sleep(30)  # Verificar a cada 30 segundos
        except Exception as e:
            add_debug_log(f"❌ Erro no polling: {e}")
            time.sleep(60)  # Esperar mais tempo em caso de erro

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
            add_debug_log(f"❌ Erro no monitoramento de token: {e}")
            time.sleep(300)

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
        add_debug_log(f"❌ Erro ao registrar log de token: {e}")

def start_token_monitoring():
    """Inicia o monitoramento de token em background"""
    monitor_thread = threading.Thread(target=monitor_token, daemon=True)
    monitor_thread.start()
    add_debug_log("🔍 Monitoramento de token iniciado")

# ========== ROTAS WEB COM DEBUG ==========

@app.route('/')
def dashboard():
    """Dashboard principal com status do token e logs de debug"""
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
            
            # Status do token
            token_status = {
                'valid': is_valid,
                'message': message,
                'last_check': TOKEN_STATUS.get('last_check'),
                'current_token': TOKEN_STATUS.get('current_token', '')[:20] + '...' if TOKEN_STATUS.get('current_token') else 'N/A'
            }
            
            current_time = get_local_time().strftime("%H:%M:%S")
            
            # Últimos logs de debug
            recent_logs = DEBUG_LOGS[-20:] if DEBUG_LOGS else ["Nenhum log ainda"]
            
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Bot ML - Dashboard DEBUG</title>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                    .container {{ max-width: 1400px; margin: 0 auto; }}
                    .header {{ background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }}
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
                    .debug-logs {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
                    .log-container {{ background: #000; color: #0f0; padding: 15px; border-radius: 4px; font-family: monospace; font-size: 12px; max-height: 400px; overflow-y: auto; }}
                    .log-line {{ margin-bottom: 2px; }}
                    .debug-alert {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 4px; margin-bottom: 20px; }}
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
                    function clearLogs() {{
                        fetch('/api/debug/clear-logs', {{method: 'POST'}})
                        .then(() => refreshPage());
                    }}
                    setInterval(refreshPage, 30000); // Atualizar a cada 30 segundos
                </script>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🤖 Bot ML - Dashboard DEBUG</h1>
                        <p><strong>Horário Local (SP):</strong> {current_time}</p>
                        <p><strong>Status:</strong> Sistema com DEBUG INTENSIVO ativo</p>
                    </div>
                    
                    <div class="debug-alert">
                        <h3>🔍 MODO DEBUG ATIVO</h3>
                        <p>Esta versão possui logs detalhados para identificar por que os gatilhos não funcionam.</p>
                        <p><strong>Problema:</strong> Perguntas chegam ({stats['total_questions']} total) mas gatilhos não acionam (0 automáticas).</p>
                    </div>
                    
                    <div class="nav">
                        <a href="/edit-rules">✏️ Regras</a>
                        <a href="/edit-absence">🌙 Ausência</a>
                        <a href="/history">📊 Histórico</a>
                        <a href="/renovar-tokens" style="background: #ff9800;">🔄 Renovar Tokens</a>
                        <a href="/debug-full">🔍 Debug Completo</a>
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
                        <h3>🔍 Logs de Debug (Últimos 20)</h3>
                        <button class="btn btn-warning" onclick="clearLogs()">🗑️ Limpar Logs</button>
                        <button class="btn" onclick="refreshPage()">🔄 Atualizar</button>
                        <div class="log-container">
            """
            
            for log in recent_logs:
                html += f'<div class="log-line">{log}</div>'
            
            html += """
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

@app.route('/debug-full')
def debug_full():
    """Página com todos os logs de debug"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Debug Completo - Bot ML</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
            .container { max-width: 1200px; margin: 0 auto; }
            .card { background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .nav a { display: inline-block; padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }
            .log-container { background: #000; color: #0f0; padding: 15px; border-radius: 4px; font-family: monospace; font-size: 12px; max-height: 600px; overflow-y: auto; }
            .log-line { margin-bottom: 2px; }
            .btn { padding: 8px 16px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; margin-right: 10px; }
        </style>
        <script>
            function clearLogs() {
                fetch('/api/debug/clear-logs', {method: 'POST'})
                .then(() => window.location.reload());
            }
            function refreshPage() { window.location.reload(); }
            setInterval(refreshPage, 15000); // Atualizar a cada 15 segundos
        </script>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>🔍 Debug Completo</h1>
                <div class="nav">
                    <a href="/">🏠 Dashboard</a>
                    <a href="/edit-rules">✏️ Regras</a>
                    <a href="/edit-absence">🌙 Ausência</a>
                </div>
            </div>
            
            <div class="card">
                <h3>📋 Todos os Logs de Debug</h3>
                <button class="btn" onclick="clearLogs()">🗑️ Limpar Logs</button>
                <button class="btn" onclick="refreshPage()">🔄 Atualizar</button>
                <div class="log-container">
    """
    
    for log in DEBUG_LOGS:
        html += f'<div class="log-line">{log}</div>'
    
    if not DEBUG_LOGS:
        html += '<div class="log-line">Nenhum log de debug ainda...</div>'
    
    html += """
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html

@app.route('/api/debug/clear-logs', methods=['POST'])
def clear_debug_logs():
    """API para limpar logs de debug"""
    global DEBUG_LOGS
    DEBUG_LOGS.clear()
    add_debug_log("🗑️ Logs de debug limpos")
    return jsonify({'success': True})

# ========== OUTRAS ROTAS ESSENCIAIS (simplificadas para debug) ==========

@app.route('/edit-rules')
def edit_rules():
    """Interface simplificada para editar regras"""
    return "<h1>✏️ Regras</h1><p>Interface simplificada no modo debug</p><a href='/'>🏠 Voltar</a>"

@app.route('/edit-absence')
def edit_absence():
    """Interface simplificada para ausência"""
    return "<h1>🌙 Ausência</h1><p>Interface simplificada no modo debug</p><a href='/'>🏠 Voltar</a>"

@app.route('/history')
def history():
    """Interface simplificada para histórico"""
    return "<h1>📊 Histórico</h1><p>Interface simplificada no modo debug</p><a href='/'>🏠 Voltar</a>"

@app.route('/renovar-tokens')
def renovar_tokens():
    """Interface simplificada para renovação"""
    return "<h1>🔄 Renovar Tokens</h1><p>Interface simplificada no modo debug</p><a href='/'>🏠 Voltar</a>"

@app.route('/api/token/check', methods=['POST'])
def check_token_api():
    """API para verificar token manualmente"""
    try:
        is_valid, message = check_token_validity()
        add_debug_log(f"🔍 Verificação manual de token: {message}")
        
        return jsonify({
            'success': True,
            'message': message,
            'valid': is_valid
        })
            
    except Exception as e:
        add_debug_log(f"❌ Erro na verificação manual: {e}")
        return jsonify({
            'success': False,
            'message': f'Erro na verificação: {str(e)}'
        })

# ========== WEBHOOK SIMPLIFICADO ==========

@app.route('/api/ml/webhook', methods=['GET', 'POST'])
def webhook_handler():
    """Webhook simplificado para debug"""
    try:
        if request.method == 'GET':
            code = request.args.get('code')
            if code:
                add_debug_log(f"📡 Webhook GET recebido com código: {code[:20]}...")
                return f"<h1>✅ Código Recebido!</h1><p>Código: {code}</p>"
            return "<h1>📡 Webhook ML - Status OK</h1>"
        
        elif request.method == 'POST':
            data = request.get_json() or {}
            topic = data.get('topic')
            resource = data.get('resource')
            
            add_debug_log(f"📡 Webhook POST recebido: {topic} - {resource}")
            
            if topic == 'questions':
                add_debug_log("❓ Nova pergunta via webhook - disparando processamento")
                # Processar perguntas imediatamente
                threading.Thread(target=process_questions, daemon=True).start()
            
            return jsonify({'status': 'ok'}), 200
    
    except Exception as e:
        add_debug_log(f"❌ Erro no webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ========== INICIALIZAÇÃO ==========

def start_background_tasks():
    """Inicia tarefas em background"""
    add_debug_log("🚀 Iniciando sistema com DEBUG INTENSIVO...")
    
    # Inicializar banco
    init_database()
    
    # Verificar token inicial
    check_token_validity()
    
    # Iniciar monitoramento de token
    start_token_monitoring()
    
    # Iniciar polling de perguntas
    polling_thread = threading.Thread(target=polling_loop, daemon=True)
    polling_thread.start()
    
    add_debug_log("✅ Sistema iniciado com DEBUG INTENSIVO!")
    add_debug_log("🔍 Todos os logs serão registrados para identificar problemas")
    add_debug_log("🤖 Verificando se gatilhos funcionam corretamente")
    add_debug_log("🌙 Verificando se sistema de ausência funciona")
    add_debug_log("🔄 Polling ativo a cada 30 segundos")

if __name__ == '__main__':
    start_background_tasks()
    app.run(host='0.0.0.0', port=5000, debug=False)

