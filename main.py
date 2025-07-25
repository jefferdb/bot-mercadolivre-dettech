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

def make_ml_request(url, method='GET', headers=None, data=None, json_data=None, max_retries=1):
    """Faz requisições para a API do ML com renovação automática de token"""
    
    for attempt in range(max_retries + 1):
        # Obter token válido
        token = get_valid_token()
        
        if not token:
            return None, "Token não disponível"
        
        # Preparar headers
        request_headers = headers or {}
        request_headers['Authorization'] = f'Bearer {token}'
        
        # CORREÇÃO CRÍTICA: Adicionar Content-Type para JSON
        if json_data:
            request_headers['Content-Type'] = 'application/json'
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=request_headers, timeout=30)
            elif method.upper() == 'POST':
                if json_data:
                    # CORREÇÃO: Usar json= em vez de data= para JSON
                    response = requests.post(url, headers=request_headers, json=json_data, timeout=30)
                else:
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

# ========== FUNÇÕES ORIGINAIS ADAPTADAS ==========

def get_questions():
    """Busca perguntas não respondidas usando o sistema de renovação automática"""
    try:
        url = f"https://api.mercadolibre.com/my/received_questions/search?seller_id={ML_USER_ID}&status=UNANSWERED"
        
        print(f"🔍 Buscando perguntas em: {url}")
        
        response, message = make_ml_request(url)
        
        if response and response.status_code == 200:
            questions_data = response.json()
            questions = questions_data.get('questions', [])
            print(f"📥 {len(questions)} perguntas encontradas na API")
            return questions
        else:
            print(f"❌ Erro ao buscar perguntas: {message}")
            return []
            
    except Exception as e:
        print(f"💥 Erro ao buscar perguntas: {e}")
        return []

def answer_question(question_id, answer_text):
    """Responde uma pergunta usando o sistema de renovação automática - FORMATO CORRIGIDO"""
    try:
        url = f"https://api.mercadolibre.com/answers"
        
        # CORREÇÃO CRÍTICA: Usar formato JSON correto
        json_data = {
            'question_id': int(question_id),  # Garantir que seja inteiro
            'text': answer_text
        }
        
        print(f"📤 Tentando responder pergunta {question_id}")
        print(f"📝 Resposta: {answer_text[:50]}...")
        print(f"🔧 JSON enviado: {json_data}")
        
        response, message = make_ml_request(url, method='POST', json_data=json_data)
        
        if response and response.status_code in [200, 201]:
            print(f"✅ Pergunta {question_id} respondida com sucesso!")
            return True
        else:
            print(f"❌ Erro ao responder pergunta {question_id}: {message}")
            if response:
                print(f"📋 Status: {response.status_code}")
                print(f"📋 Resposta: {response.text}")
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
                print("🔧 Inicializando banco de dados...")
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
                rules_count = AutoResponse.query.filter_by(user_id=user.id).count()
                if rules_count == 0:
                    default_responses = [
                        {
                            'keywords': 'preço,valor,quanto custa,custo',
                            'response_text': 'Olá! O preço está na descrição do anúncio. Qualquer dúvida, estou à disposição!'
                        },
                        {
                            'keywords': 'entrega,prazo,demora,quando chega',
                            'response_text': 'Olá! O prazo de entrega varia conforme sua localização. Você pode verificar na página do produto. Obrigado!'
                        },
                        {
                            'keywords': 'disponível,estoque,tem,possui',
                            'response_text': 'Olá! Sim, temos o produto disponível. Pode fazer sua compra com tranquilidade!'
                        },
                        {
                            'keywords': 'nota,fiscal,nf,emite',
                            'response_text': 'Olá, seja bem-vindo à DETTECH, todos os produtos são com nota fiscal. Qualquer dúvida, estou à disposição!'
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

def is_absence_time():
    """Verifica se está em horário de ausência"""
    try:
        now = get_local_time()
        current_time = now.strftime("%H:%M")
        current_weekday = str(now.weekday())  # 0=segunda, 6=domingo
        
        with app.app_context():
            absence_configs = AbsenceConfig.query.filter_by(is_active=True).all()
            
            for config in absence_configs:
                # Verificar se o dia atual está na configuração
                if config.days_of_week and current_weekday in config.days_of_week.split(','):
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
        
    except Exception as e:
        print(f"❌ Erro ao verificar horário de ausência: {e}")
        return None

def find_auto_response(question_text):
    """Encontra resposta automática baseada em palavras-chave"""
    try:
        question_lower = question_text.lower()
        
        with app.app_context():
            auto_responses = AutoResponse.query.filter_by(is_active=True).all()
            
            for response in auto_responses:
                keywords = [k.strip().lower() for k in response.keywords.split(',')]
                
                for keyword in keywords:
                    if keyword and keyword in question_lower:
                        print(f"✅ Palavra-chave '{keyword}' encontrada em '{question_text}'")
                        return response.response_text, response.keywords
        
        return None, None
        
    except Exception as e:
        print(f"❌ Erro ao buscar resposta automática: {e}")
        return None, None

def process_questions():
    """Processa perguntas automaticamente"""
    try:
        print("🔄 ========== INICIANDO PROCESSAMENTO DE PERGUNTAS ==========")
        
        with _db_lock:
            with app.app_context():
                # Buscar perguntas usando sistema de renovação automática
                questions = get_questions()
                print(f"📥 Perguntas retornadas pela API: {len(questions)}")
                
                if not questions:
                    print("📭 Nenhuma pergunta nova encontrada")
                    return
                
                user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
                if not user:
                    print("❌ Usuário não encontrado no banco")
                    return
                
                for i, q in enumerate(questions):
                    question_id = str(q.get("id"))
                    question_text = q.get("text", "")
                    item_id = q.get("item_id", "")
                    
                    print(f"\n📝 ========== PROCESSANDO PERGUNTA {i+1}/{len(questions)} ==========")
                    print(f"   ID: {question_id}")
                    print(f"   Texto: '{question_text}'")
                    
                    # Verificar se já processamos esta pergunta
                    existing = Question.query.filter_by(ml_question_id=question_id).first()
                    if existing:
                        print(f"   ⏭️ Pergunta {question_id} já existe no banco - PULANDO")
                        continue
                    
                    print(f"   ✅ Pergunta {question_id} é NOVA - processando...")
                    
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
                    response_given = False
                    
                    # PRIMEIRO: Verificar se está em horário de ausência
                    absence_message = is_absence_time()
                    if absence_message:
                        print(f"   🌙 AUSÊNCIA DETECTADA! Enviando resposta...")
                        if answer_question(question_id, absence_message):
                            question.response_text = absence_message
                            question.is_answered = True
                            question.answered_automatically = True
                            question.answered_at = get_local_time_utc()
                            response_type = "absence"
                            response_given = True
                            print(f"   ✅ Pergunta {question_id} respondida com AUSÊNCIA")
                        else:
                            print(f"   ❌ FALHA ao enviar mensagem de ausência")
                    
                    # SEGUNDO: Se não está em ausência, buscar resposta automática
                    if not response_given:
                        auto_response, matched_keywords = find_auto_response(question_text)
                        if auto_response:
                            print(f"   🤖 REGRA ENCONTRADA! Enviando resposta...")
                            if answer_question(question_id, auto_response):
                                question.response_text = auto_response
                                question.is_answered = True
                                question.answered_automatically = True
                                question.answered_at = get_local_time_utc()
                                response_type = "auto"
                                keywords_matched = matched_keywords
                                response_given = True
                                print(f"   ✅ Pergunta {question_id} respondida AUTOMATICAMENTE")
                            else:
                                print(f"   ❌ FALHA ao enviar resposta automática")
                        else:
                            print(f"   ❌ Nenhuma regra automática encontrada")
                    
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
                        print(f"   📊 Histórico registrado: tipo={response_type}")
                    else:
                        print(f"   📝 Pergunta {question_id} salva SEM resposta automática")
                    
                    db.session.commit()
                    
        print("✅ ========== PROCESSAMENTO DE PERGUNTAS CONCLUÍDO ==========")
                    
    except Exception as e:
        print(f"❌ ERRO ao processar perguntas: {e}")
        import traceback
        print(f"   Traceback: {traceback.format_exc()}")

def polling_loop():
    """Loop principal de polling com renovação automática"""
    print("🔄 Iniciando polling de perguntas...")
    
    while True:
        try:
            process_questions()
            print("⏰ Aguardando 30 segundos para próxima verificação...")
            time.sleep(30)  # Verificar a cada 30 segundos
        except Exception as e:
            print(f"❌ Erro no polling: {e}")
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
            print(f"❌ Erro no monitoramento de token: {e}")
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
        print(f"❌ Erro ao registrar log de token: {e}")

def start_token_monitoring():
    """Inicia o monitoramento de token em background"""
    monitor_thread = threading.Thread(target=monitor_token, daemon=True)
    monitor_thread.start()
    print("🔍 Monitoramento de token iniciado")

# ========== ROTAS WEB ==========

@app.route('/')
def dashboard():
    """Dashboard principal"""
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
                    .success-alert {{ background: #d4edda; border: 1px solid #c3e6cb; color: #155724; padding: 15px; border-radius: 4px; margin-bottom: 20px; }}
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
                    setInterval(refreshPage, 30000); // Atualizar a cada 30 segundos
                </script>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🤖 Bot Mercado Livre - DETTECH</h1>
                        <p><strong>Horário Local (SP):</strong> {current_time}</p>
                        <p><strong>Status:</strong> Sistema funcionando com gatilhos corrigidos</p>
                    </div>
                    
                    <div class="success-alert">
                        <h3>✅ PROBLEMA DOS GATILHOS RESOLVIDO!</h3>
                        <p>O formato da requisição para a API do ML foi corrigido. Agora os gatilhos devem funcionar perfeitamente!</p>
                    </div>
                    
                    <div class="nav">
                        <a href="/edit-rules">✏️ Editar Regras</a>
                        <a href="/edit-absence">🌙 Configurar Ausência</a>
                        <a href="/history">📊 Histórico</a>
                        <a href="/renovar-tokens" style="background: #ff9800;">🔄 Renovar Tokens</a>
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

@app.route('/edit-rules')
def edit_rules():
    """Interface para editar regras de resposta automática"""
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return "Usuário não encontrado"
            
            rules = AutoResponse.query.filter_by(user_id=user.id).all()
            
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Editar Regras - Bot ML</title>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
                    .container { max-width: 1000px; margin: 0 auto; }
                    .card { background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                    .nav a { display: inline-block; padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }
                    .form-group { margin-bottom: 15px; }
                    .form-group label { display: block; margin-bottom: 5px; font-weight: bold; }
                    .form-group input, .form-group textarea { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
                    .btn { padding: 10px 20px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; margin-right: 10px; }
                    .btn-danger { background: #f44336; }
                    .rule-item { border: 1px solid #ddd; padding: 15px; margin-bottom: 10px; border-radius: 4px; }
                    .rule-active { border-color: #4CAF50; }
                    .rule-inactive { border-color: #f44336; opacity: 0.7; }
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
                        </div>
                    </div>
                    
                    <div class="card">
                        <h3>➕ Adicionar Nova Regra</h3>
                        <form id="addRuleForm">
                            <div class="form-group">
                                <label>Palavras-chave (separadas por vírgula):</label>
                                <input type="text" id="keywords" placeholder="preço,valor,quanto custa" required>
                            </div>
                            <div class="form-group">
                                <label>Resposta automática:</label>
                                <textarea id="response" rows="3" placeholder="Olá! O preço está na descrição..." required></textarea>
                            </div>
                            <button type="submit" class="btn">💾 Salvar Regra</button>
                        </form>
                    </div>
                    
                    <div class="card">
                        <h3>📋 Regras Existentes</h3>
            """
            
            for rule in rules:
                status_class = "rule-active" if rule.is_active else "rule-inactive"
                status_text = "✅ Ativa" if rule.is_active else "❌ Inativa"
                
                html += f"""
                        <div class="rule-item {status_class}">
                            <p><strong>ID:</strong> {rule.id} | <strong>Status:</strong> {status_text}</p>
                            <p><strong>Palavras-chave:</strong> {rule.keywords}</p>
                            <p><strong>Resposta:</strong> {rule.response_text}</p>
                            <button class="btn" onclick="toggleRule({rule.id})">
                                {'🔴 Desativar' if rule.is_active else '🟢 Ativar'}
                            </button>
                            <button class="btn btn-danger" onclick="deleteRule({rule.id})">🗑️ Excluir</button>
                        </div>
                """
            
            html += """
                    </div>
                </div>
                
                <script>
                    document.getElementById('addRuleForm').addEventListener('submit', function(e) {
                        e.preventDefault();
                        
                        const keywords = document.getElementById('keywords').value;
                        const response = document.getElementById('response').value;
                        
                        fetch('/api/rules', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({keywords: keywords, response_text: response})
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                alert('Regra adicionada com sucesso!');
                                window.location.reload();
                            } else {
                                alert('Erro: ' + data.message);
                            }
                        });
                    });
                    
                    function toggleRule(id) {
                        fetch(`/api/rules/${id}/toggle`, {method: 'POST'})
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                window.location.reload();
                            } else {
                                alert('Erro: ' + data.message);
                            }
                        });
                    }
                    
                    function deleteRule(id) {
                        if (confirm('Tem certeza que deseja excluir esta regra?')) {
                            fetch(`/api/rules/${id}`, {method: 'DELETE'})
                            .then(response => response.json())
                            .then(data => {
                                if (data.success) {
                                    window.location.reload();
                                } else {
                                    alert('Erro: ' + data.message);
                                }
                            });
                        }
                    }
                </script>
            </body>
            </html>
            """
            
            return html
            
    except Exception as e:
        return f"Erro: {e}"

@app.route('/edit-absence')
def edit_absence():
    """Interface para configurar ausência"""
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return "Usuário não encontrado"
            
            configs = AbsenceConfig.query.filter_by(user_id=user.id).all()
            
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Configurar Ausência - Bot ML</title>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
                    .container { max-width: 1000px; margin: 0 auto; }
                    .card { background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                    .nav a { display: inline-block; padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }
                    .form-group { margin-bottom: 15px; }
                    .form-group label { display: block; margin-bottom: 5px; font-weight: bold; }
                    .form-group input, .form-group textarea, .form-group select { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
                    .btn { padding: 10px 20px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; margin-right: 10px; }
                    .btn-danger { background: #f44336; }
                    .config-item { border: 1px solid #ddd; padding: 15px; margin-bottom: 10px; border-radius: 4px; }
                    .config-active { border-color: #4CAF50; }
                    .config-inactive { border-color: #f44336; opacity: 0.7; }
                    .checkbox-group { display: flex; flex-wrap: wrap; gap: 10px; }
                    .checkbox-group label { display: flex; align-items: center; margin-bottom: 0; font-weight: normal; }
                    .checkbox-group input { width: auto; margin-right: 5px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <h1>🌙 Configurar Ausência</h1>
                        <div class="nav">
                            <a href="/">🏠 Dashboard</a>
                            <a href="/edit-rules">✏️ Regras</a>
                            <a href="/history">📊 Histórico</a>
                        </div>
                    </div>
                    
                    <div class="card">
                        <h3>➕ Adicionar Configuração de Ausência</h3>
                        <form id="addAbsenceForm">
                            <div class="form-group">
                                <label>Nome da configuração:</label>
                                <input type="text" id="name" placeholder="Horário noturno" required>
                            </div>
                            <div class="form-group">
                                <label>Mensagem de ausência:</label>
                                <textarea id="message" rows="3" placeholder="Olá! Estou ausente no momento..." required></textarea>
                            </div>
                            <div class="form-group">
                                <label>Horário de início (HH:MM):</label>
                                <input type="time" id="start_time" required>
                            </div>
                            <div class="form-group">
                                <label>Horário de fim (HH:MM):</label>
                                <input type="time" id="end_time" required>
                            </div>
                            <div class="form-group">
                                <label>Dias da semana:</label>
                                <div class="checkbox-group">
                                    <label><input type="checkbox" value="0"> Segunda</label>
                                    <label><input type="checkbox" value="1"> Terça</label>
                                    <label><input type="checkbox" value="2"> Quarta</label>
                                    <label><input type="checkbox" value="3"> Quinta</label>
                                    <label><input type="checkbox" value="4"> Sexta</label>
                                    <label><input type="checkbox" value="5"> Sábado</label>
                                    <label><input type="checkbox" value="6"> Domingo</label>
                                </div>
                            </div>
                            <button type="submit" class="btn">💾 Salvar Configuração</button>
                        </form>
                    </div>
                    
                    <div class="card">
                        <h3>📋 Configurações Existentes</h3>
            """
            
            for config in configs:
                status_class = "config-active" if config.is_active else "config-inactive"
                status_text = "✅ Ativa" if config.is_active else "❌ Inativa"
                
                days_map = {'0': 'Seg', '1': 'Ter', '2': 'Qua', '3': 'Qui', '4': 'Sex', '5': 'Sáb', '6': 'Dom'}
                days_text = ', '.join([days_map.get(d, d) for d in config.days_of_week.split(',')]) if config.days_of_week else 'Nenhum'
                
                html += f"""
                        <div class="config-item {status_class}">
                            <p><strong>Nome:</strong> {config.name} | <strong>Status:</strong> {status_text}</p>
                            <p><strong>Horário:</strong> {config.start_time} às {config.end_time}</p>
                            <p><strong>Dias:</strong> {days_text}</p>
                            <p><strong>Mensagem:</strong> {config.message}</p>
                            <button class="btn" onclick="toggleConfig({config.id})">
                                {'🔴 Desativar' if config.is_active else '🟢 Ativar'}
                            </button>
                            <button class="btn btn-danger" onclick="deleteConfig({config.id})">🗑️ Excluir</button>
                        </div>
                """
            
            html += """
                    </div>
                </div>
                
                <script>
                    document.getElementById('addAbsenceForm').addEventListener('submit', function(e) {
                        e.preventDefault();
                        
                        const name = document.getElementById('name').value;
                        const message = document.getElementById('message').value;
                        const start_time = document.getElementById('start_time').value;
                        const end_time = document.getElementById('end_time').value;
                        
                        const checkedDays = Array.from(document.querySelectorAll('.checkbox-group input:checked'))
                                                .map(cb => cb.value);
                        const days_of_week = checkedDays.join(',');
                        
                        fetch('/api/absence', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                name: name,
                                message: message,
                                start_time: start_time,
                                end_time: end_time,
                                days_of_week: days_of_week
                            })
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                alert('Configuração adicionada com sucesso!');
                                window.location.reload();
                            } else {
                                alert('Erro: ' + data.message);
                            }
                        });
                    });
                    
                    function toggleConfig(id) {
                        fetch(`/api/absence/${id}/toggle`, {method: 'POST'})
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                window.location.reload();
                            } else {
                                alert('Erro: ' + data.message);
                            }
                        });
                    }
                    
                    function deleteConfig(id) {
                        if (confirm('Tem certeza que deseja excluir esta configuração?')) {
                            fetch(`/api/absence/${id}`, {method: 'DELETE'})
                            .then(response => response.json())
                            .then(data => {
                                if (data.success) {
                                    window.location.reload();
                                } else {
                                    alert('Erro: ' + data.message);
                                }
                            });
                        }
                    }
                </script>
            </body>
            </html>
            """
            
            return html
            
    except Exception as e:
        return f"Erro: {e}"

@app.route('/history')
def history():
    """Histórico de respostas"""
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return "Usuário não encontrado"
            
            # Buscar histórico com join das perguntas
            history_query = db.session.query(ResponseHistory, Question).join(
                Question, ResponseHistory.question_id == Question.id
            ).filter(ResponseHistory.user_id == user.id).order_by(
                ResponseHistory.created_at.desc()
            ).limit(50)
            
            history_items = history_query.all()
            
            # Estatísticas
            total_responses = ResponseHistory.query.filter_by(user_id=user.id).count()
            auto_responses = ResponseHistory.query.filter_by(user_id=user.id, response_type='auto').count()
            absence_responses = ResponseHistory.query.filter_by(user_id=user.id, response_type='absence').count()
            manual_responses = ResponseHistory.query.filter_by(user_id=user.id, response_type='manual').count()
            
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Histórico - Bot ML</title>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
                    .container {{ max-width: 1200px; margin: 0 auto; }}
                    .card {{ background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .nav a {{ display: inline-block; padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }}
                    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }}
                    .stat-card {{ background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
                    .stat-number {{ font-size: 1.5em; font-weight: bold; color: #2196F3; }}
                    .history-item {{ border: 1px solid #ddd; padding: 15px; margin-bottom: 10px; border-radius: 4px; }}
                    .type-auto {{ border-left: 4px solid #4CAF50; }}
                    .type-absence {{ border-left: 4px solid #ff9800; }}
                    .type-manual {{ border-left: 4px solid #2196F3; }}
                    .meta {{ color: #666; font-size: 0.9em; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="card">
                        <h1>📊 Histórico de Respostas</h1>
                        <div class="nav">
                            <a href="/">🏠 Dashboard</a>
                            <a href="/edit-rules">✏️ Regras</a>
                            <a href="/edit-absence">🌙 Ausência</a>
                        </div>
                    </div>
                    
                    <div class="stats">
                        <div class="stat-card">
                            <div class="stat-number">{total_responses}</div>
                            <div>Total de Respostas</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number" style="color: #4CAF50">{auto_responses}</div>
                            <div>Automáticas</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number" style="color: #ff9800">{absence_responses}</div>
                            <div>Ausência</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number" style="color: #2196F3">{manual_responses}</div>
                            <div>Manuais</div>
                        </div>
                    </div>
                    
                    <div class="card">
                        <h3>📋 Últimas 50 Respostas</h3>
            """
            
            for history, question in history_items:
                type_class = f"type-{history.response_type}"
                type_text = {
                    'auto': '🤖 Automática',
                    'absence': '🌙 Ausência',
                    'manual': '👤 Manual'
                }.get(history.response_type, history.response_type)
                
                created_at = format_local_time(history.created_at)
                created_str = created_at.strftime('%d/%m/%Y %H:%M:%S') if created_at else 'N/A'
                
                html += f"""
                        <div class="history-item {type_class}">
                            <p><strong>Pergunta:</strong> {question.question_text}</p>
                            <p><strong>Resposta:</strong> {question.response_text or 'N/A'}</p>
                            <div class="meta">
                                <strong>Tipo:</strong> {type_text} | 
                                <strong>Data:</strong> {created_str} | 
                                <strong>Tempo:</strong> {history.response_time:.2f}s
                                {f' | <strong>Palavras-chave:</strong> {history.keywords_matched}' if history.keywords_matched else ''}
                            </div>
                        </div>
                """
            
            if not history_items:
                html += "<p>Nenhuma resposta no histórico ainda.</p>"
            
            html += """
                    </div>
                </div>
            </body>
            </html>
            """
            
            return html
            
    except Exception as e:
        return f"Erro: {e}"

@app.route('/renovar-tokens')
def renovar_tokens():
    """Interface para renovação de tokens"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Renovar Tokens - Bot ML</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; }
            .card { background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .nav a { display: inline-block; padding: 10px 20px; background: #2196F3; color: white; text-decoration: none; border-radius: 4px; margin-right: 10px; }
            .btn { padding: 10px 20px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; margin-right: 10px; }
            .btn-warning { background: #ff9800; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>🔄 Renovar Tokens</h1>
                <div class="nav">
                    <a href="/">🏠 Dashboard</a>
                    <a href="/edit-rules">✏️ Regras</a>
                    <a href="/edit-absence">🌙 Ausência</a>
                </div>
            </div>
            
            <div class="card">
                <h3>🔑 Renovação Automática</h3>
                <p>O sistema tenta renovar automaticamente o token quando necessário.</p>
                <p>Se a renovação automática falhar, você precisará gerar um novo token manualmente.</p>
                <button class="btn btn-warning" onclick="tryRenew()">🔄 Tentar Renovar Agora</button>
            </div>
        </div>
        
        <script>
            function tryRenew() {
                fetch('/api/token/check', {method: 'POST'})
                .then(response => response.json())
                .then(data => {
                    alert(data.message || 'Verificação concluída');
                    window.location.href = '/';
                })
                .catch(error => alert('Erro: ' + error));
            }
        </script>
    </body>
    </html>
    """

# ========== APIs ==========

@app.route('/api/token/check', methods=['POST'])
def check_token_api():
    """API para verificar token manualmente"""
    try:
        is_valid, message = check_token_validity()
        print(f"🔍 Verificação manual de token: {message}")
        
        return jsonify({
            'success': True,
            'message': message,
            'valid': is_valid
        })
            
    except Exception as e:
        print(f"❌ Erro na verificação manual: {e}")
        return jsonify({
            'success': False,
            'message': f'Erro na verificação: {str(e)}'
        })

@app.route('/api/rules', methods=['POST'])
def add_rule():
    """API para adicionar regra"""
    try:
        data = request.get_json()
        
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return jsonify({'success': False, 'message': 'Usuário não encontrado'})
            
            rule = AutoResponse(
                user_id=user.id,
                keywords=data['keywords'],
                response_text=data['response_text']
            )
            db.session.add(rule)
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Regra adicionada com sucesso'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/rules/<int:rule_id>/toggle', methods=['POST'])
def toggle_rule(rule_id):
    """API para ativar/desativar regra"""
    try:
        with app.app_context():
            rule = AutoResponse.query.get(rule_id)
            if not rule:
                return jsonify({'success': False, 'message': 'Regra não encontrada'})
            
            rule.is_active = not rule.is_active
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Status alterado com sucesso'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/rules/<int:rule_id>', methods=['DELETE'])
def delete_rule(rule_id):
    """API para excluir regra"""
    try:
        with app.app_context():
            rule = AutoResponse.query.get(rule_id)
            if not rule:
                return jsonify({'success': False, 'message': 'Regra não encontrada'})
            
            db.session.delete(rule)
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Regra excluída com sucesso'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/absence', methods=['POST'])
def add_absence():
    """API para adicionar configuração de ausência"""
    try:
        data = request.get_json()
        
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return jsonify({'success': False, 'message': 'Usuário não encontrado'})
            
            config = AbsenceConfig(
                user_id=user.id,
                name=data['name'],
                message=data['message'],
                start_time=data['start_time'],
                end_time=data['end_time'],
                days_of_week=data['days_of_week']
            )
            db.session.add(config)
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Configuração adicionada com sucesso'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/absence/<int:config_id>/toggle', methods=['POST'])
def toggle_absence(config_id):
    """API para ativar/desativar configuração de ausência"""
    try:
        with app.app_context():
            config = AbsenceConfig.query.get(config_id)
            if not config:
                return jsonify({'success': False, 'message': 'Configuração não encontrada'})
            
            config.is_active = not config.is_active
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Status alterado com sucesso'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/absence/<int:config_id>', methods=['DELETE'])
def delete_absence(config_id):
    """API para excluir configuração de ausência"""
    try:
        with app.app_context():
            config = AbsenceConfig.query.get(config_id)
            if not config:
                return jsonify({'success': False, 'message': 'Configuração não encontrada'})
            
            db.session.delete(config)
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Configuração excluída com sucesso'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# ========== WEBHOOK ==========

@app.route('/api/ml/webhook', methods=['GET', 'POST'])
def webhook_handler():
    """Webhook para receber notificações do ML"""
    try:
        if request.method == 'GET':
            code = request.args.get('code')
            if code:
                print(f"📡 Webhook GET recebido com código: {code[:20]}...")
                return f"<h1>✅ Código Recebido!</h1><p>Código: {code}</p>"
            return "<h1>📡 Webhook ML - Status OK</h1>"
        
        elif request.method == 'POST':
            data = request.get_json() or {}
            topic = data.get('topic')
            resource = data.get('resource')
            
            print(f"📡 Webhook POST recebido: {topic} - {resource}")
            
            if topic == 'questions':
                print("❓ Nova pergunta via webhook - disparando processamento")
                # Processar perguntas imediatamente
                threading.Thread(target=process_questions, daemon=True).start()
            
            return jsonify({'status': 'ok'}), 200
    
    except Exception as e:
        print(f"❌ Erro no webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ========== INICIALIZAÇÃO ==========

def start_background_tasks():
    """Inicia tarefas em background"""
    print("🚀 Iniciando sistema com gatilhos corrigidos...")
    
    # Inicializar banco
    init_database()
    
    # Verificar token inicial
    check_token_validity()
    
    # Iniciar monitoramento de token
    start_token_monitoring()
    
    # Iniciar polling de perguntas
    polling_thread = threading.Thread(target=polling_loop, daemon=True)
    polling_thread.start()
    
    print("✅ Sistema iniciado com sucesso!")
    print("🔧 Formato de requisição para API do ML corrigido")
    print("🤖 Gatilhos de palavras-chave devem funcionar agora")
    print("🌙 Sistema de ausência funcionando")
    print("🔄 Polling ativo a cada 30 segundos")

if __name__ == '__main__':
    start_background_tasks()
    app.run(host='0.0.0.0', port=5000, debug=False)

