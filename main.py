#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOT MERCADO LIVRE - SISTEMA COMPLETO FUNCIONAL
Criado com base nos módulos funcionais salvos e testados
Data: 25/07/2025
Credenciais atualizadas: 25/07/2025 - 18:00

FUNCIONALIDADES INTEGRADAS:
✅ Sistema de ausência e regras (main(1).py)
✅ Renovação manual de tokens (interface web)
✅ Layout minimalista e responsivo
✅ Histórico de respostas detalhado
✅ Debug e logs em tempo real
✅ Configuração de dados persistentes
✅ Fuso horário São Paulo (UTC-3)
"""

import os
import time
import threading
import json
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests
import sqlite3

# ========== CONFIGURAÇÃO DA APLICAÇÃO ==========
app = Flask(__name__)
CORS(app)

# ========== CONFIGURAÇÃO DO FUSO HORÁRIO ==========
# Fuso horário de São Paulo (UTC-3)
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

# ========== CONFIGURAÇÃO DE DADOS PERSISTENTES ==========
# Baseado no módulo configuracao_dados_render.py
RENDER_DATA_DIR = "/opt/render/project/src/data"
DATA_DIR = os.getenv('DATA_DIR', RENDER_DATA_DIR)
if not os.path.exists(DATA_DIR):
    DATA_DIR = './data'
    os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_PATH = os.path.join(DATA_DIR, 'bot_ml.db')
LOGS_PATH = os.path.join(DATA_DIR, 'logs')
BACKUP_PATH = os.path.join(DATA_DIR, 'backups')

# Garantir que diretórios existam
for directory in [DATA_DIR, LOGS_PATH, BACKUP_PATH]:
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

# ========== CONFIGURAÇÃO DO BANCO SQLITE ==========
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ========== CREDENCIAIS ATUALIZADAS DO MERCADO LIVRE ==========
ML_ACCESS_TOKEN = os.getenv('ML_ACCESS_TOKEN', 'APP_USR-5510376630479325-072518-5543447b8156889e3edf9c10f3bf19e8-180617463')
ML_CLIENT_ID = os.getenv('ML_CLIENT_ID', '5510376630479325')
ML_CLIENT_SECRET = os.getenv('ML_CLIENT_SECRET', 'jlR4As2x8uFY3RTpysLpuPhzC9yM9d35')
ML_USER_ID = os.getenv('ML_USER_ID', '180617463')
ML_REFRESH_TOKEN = os.getenv('ML_REFRESH_TOKEN', '')

# URLs de redirect para renovação de tokens (webhook como padrão)
REDIRECT_URIS = [
    "https://bot-mercadolivre-dettech.onrender.com/api/ml/webhook",
    "https://bot-mercadolivre-dettech.onrender.com/api/ml/auth-callback",
    "http://localhost:5000/api/ml/webhook",
    "http://localhost:5000/api/ml/auth-callback"
]

# ========== SISTEMA DE RENOVAÇÃO AUTOMÁTICA DE TOKENS ==========
# Implementação da Estratégia 3: Renovação Baseada em Tempo
# Renovação automática a cada 5 horas (1 hora de sobra)

import threading
import time

class AutoTokenRefresh:
    """Sistema de renovação automática de tokens baseado em tempo (multi-conta-ready)."""

    def __init__(self):
        self.ml_user_id = None  # identifica o usuário dono do token
        self.refresh_timer = None
        self.is_refreshing = False
        self.token_created_at = None
        self.token_expires_at = None
        self.auto_refresh_enabled = True
        self.refresh_interval = 5 * 3600  # 5 horas em segundos

    def start_auto_refresh(self, expires_in=21600):
        """
        Inicia sistema de renovação automática.
        :param expires_in: Tempo de expiração do access token em segundos (padrão: 6 horas).
        """
        if not self.auto_refresh_enabled:
            add_debug_log("🔄 Auto-renovação desabilitada")
            return

        # Cancelar timer anterior se existir
        if self.refresh_timer:
            self.refresh_timer.cancel()
            add_debug_log("⏹️ Timer anterior cancelado")

        # Calcular quando renovar (5 horas = 18000 segundos)
        refresh_delay = min(self.refresh_interval, max(expires_in - 3600, 300))  # mínimo 5 minutos

        # Atualizar timestamps
        self.token_created_at = time.time()
        self.token_expires_at = self.token_created_at + expires_in

        # Agendar renovação
        self.refresh_timer = threading.Timer(refresh_delay, self.auto_refresh)
        self.refresh_timer.start()

        # Log detalhado
        refresh_time = datetime.fromtimestamp(self.token_created_at + refresh_delay)
        expires_time = datetime.fromtimestamp(self.token_expires_at)
        add_debug_log(f"🕐 Auto-renovação agendada para {refresh_delay}s ({refresh_time.strftime('%H:%M:%S')})")
        add_debug_log(f"⏰ Token expira em: {expires_time.strftime('%H:%M:%S')}")

    def auto_refresh(self):
        """Executa renovação automática do token."""
        if self.is_refreshing:
            add_debug_log("⚠️ Renovação já em andamento, ignorando")
            return

        self.is_refreshing = True
        try:
            add_debug_log("🔄 Iniciando renovação automática de token...")
            success, result = self.process_refresh_token_internal()

            if success:
                self.update_system_tokens_internal(
                    result['access_token'],
                    result.get('refresh_token', ''),
                    result.get('user_id')
                )
                self.start_auto_refresh(result.get('expires_in', 21600))
                add_debug_log("✅ Renovação automática concluída com sucesso")
            else:
                retry_delay = 600  # 10 min
                self.refresh_timer = threading.Timer(retry_delay, self.auto_refresh)
                self.refresh_timer.start()
                add_debug_log(f"❌ Falha na renovação automática, tentando novamente em {retry_delay//60} min")
        except Exception as e:
            add_debug_log(f"❌ Erro na renovação automática: {e}")
            retry_delay = 300  # 5 min
            self.refresh_timer = threading.Timer(retry_delay, self.auto_refresh)
            self.refresh_timer.start()
            add_debug_log(f"🔄 Reagendando tentativa em {retry_delay//60} min")
        finally:
            self.is_refreshing = False

    def process_refresh_token_internal(self):
        """Processa renovação usando refresh token do usuário configurado (ou global como fallback)."""
        rt = None
        uid = None
        try:
            if self.ml_user_id:
                with app.app_context():
                    u = User.query.filter_by(ml_user_id=str(self.ml_user_id)).first()
                    if u and u.refresh_token:
                        rt = u.refresh_token
                        uid = str(self.ml_user_id)
            if not rt:
                # fallback compatível com o comportamento antigo
                rt = ML_REFRESH_TOKEN
                uid = ML_USER_ID

            if not rt:
                return False, {'error': 'Refresh token não disponível'}

            url = "https://api.mercadolibre.com/oauth/token"
            data = {
                'grant_type': 'refresh_token',
                'client_id': ML_CLIENT_ID,
                'client_secret': ML_CLIENT_SECRET,
                'refresh_token': rt
            }

            add_debug_log("🔄 Enviando requisição de renovação...")
            response = requests.post(url, data=data, timeout=30)

            if response.status_code == 200:
                token_data = response.json()
                result = {
                    'success': True,
                    'access_token': token_data['access_token'],
                    'refresh_token': token_data.get('refresh_token', ''),
                    'user_id': str(token_data.get('user_id', uid)),
                    'expires_in': token_data.get('expires_in', 21600)
                }
                add_debug_log("✅ Renovação via refresh token bem-sucedida")
                return True, result

            error_msg = f"Erro {response.status_code}: {response.text}"
            add_debug_log(f"❌ Falha na renovação: {error_msg}")
            return False, {'error': error_msg}

        except Exception as e:
            add_debug_log(f"❌ Erro na requisição de renovação: {e}")
            return False, {'error': str(e)}

    def update_system_tokens_internal(self, access_token, refresh_token, user_id):
        """Atualiza tokens no sistema"""
        global ML_ACCESS_TOKEN, ML_REFRESH_TOKEN, ML_USER_ID

        # Atualizar variáveis globais
        ML_ACCESS_TOKEN = access_token
        ML_REFRESH_TOKEN = refresh_token
        ML_USER_ID = user_id

        # Atualizar no banco de dados
        try:
            user = User.query.filter_by(ml_user_id=user_id).first()
            if user:
                user.access_token = access_token
                user.refresh_token = refresh_token
                user.token_expires_at = datetime.utcnow() + timedelta(hours=6)
                user.updated_at = get_local_time_utc()
                db.session.commit()
                add_debug_log("💾 Tokens atualizados no banco de dados")
            else:
                add_debug_log("⚠️ Usuário não encontrado no banco para atualizar tokens")

        except Exception as e:
            add_debug_log(f"❌ Erro ao atualizar tokens no banco: {e}")

    def get_token_status(self):
        """Retorna status atual do token"""
        if not self.token_created_at or not self.token_expires_at:
            return {
                'status': 'unknown',
                'message': 'Token não inicializado',
                'time_remaining': 0,
                'next_refresh': 0,
                'auto_refresh_enabled': self.auto_refresh_enabled,
                'is_refreshing': getattr(self, 'is_refreshing', False)
            }

        current_time = time.time()
        time_remaining = max(0, self.token_expires_at - current_time)

        # Calcular próxima renovação
        next_refresh_time = self.token_created_at + self.refresh_interval
        next_refresh = max(0, next_refresh_time - current_time)

        # Determinar status
        if time_remaining <= 0:
            status = 'expired'
            message = 'Token expirado'
        elif time_remaining <= 3600:  # Menos de 1 hora
            status = 'expiring'
            message = f'Token expira em {int(time_remaining//60)} minutos'
        else:
            status = 'active'
            message = f'Token válido por {int(time_remaining//3600)}h {int((time_remaining%3600)//60)}min'

        return {
            'status': status,
            'message': message,
            'time_remaining': int(time_remaining),
            'next_refresh': int(next_refresh),
            'auto_refresh_enabled': self.auto_refresh_enabled,
            'is_refreshing': getattr(self, 'is_refreshing', False)
        }

    def stop_auto_refresh(self):
        """Para o sistema de renovação automática"""
        if self.refresh_timer:
            self.refresh_timer.cancel()
            self.refresh_timer = None
            add_debug_log("⏹️ Sistema de auto-renovação parado")

    def enable_auto_refresh(self):
        """Habilita renovação automática"""
        self.auto_refresh_enabled = True
        add_debug_log("✅ Auto-renovação habilitada")

    def disable_auto_refresh(self):
        """Desabilita renovação automática"""
        self.auto_refresh_enabled = False
        self.stop_auto_refresh()
        add_debug_log("❌ Auto-renovação desabilitada")
auto_refresh_manager = AutoTokenRefresh()

    # ====== MULTI-CONTA: gerenciador de auto-refresh por usuário ======

class AutoTokenRefreshManager:
    def __init__(self):
        self.instances = {}  # ml_user_id -> AutoTokenRefresh

    def get(self, ml_user_id: str) -> AutoTokenRefresh:
        key = str(ml_user_id)
        if key not in self.instances:
            inst = AutoTokenRefresh()
            inst.ml_user_id = key
            self.instances[key] = inst
        return self.instances[key]

multi_refresh = AutoTokenRefreshManager()


def initialize_auto_refresh():
    """Inicializa sistema de renovação automática baseado no token atual"""
    try:
        # Verificar se temos refresh token
        if not ML_REFRESH_TOKEN:
            add_debug_log("⚠️ Refresh token não disponível, auto-renovação não iniciada")
            return False
        
        # Calcular tempo restante do token atual (assumindo 6 horas de validade)
        # Em produção, isso seria obtido do banco de dados
        current_time = time.time()
        
        # Verificar se temos informação de quando o token foi criado
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if user and user.token_expires_at:
            # Usar informação do banco
            expires_at = user.token_expires_at.timestamp()
            time_remaining = max(0, expires_at - current_time)
        else:
            # Assumir token recém-criado (6 horas de validade)
            time_remaining = 21600  # 6 horas
        
        if time_remaining > 0:
            auto_refresh_manager.start_auto_refresh(int(time_remaining))
            add_debug_log(f"🚀 Sistema de auto-renovação inicializado com {int(time_remaining//3600)}h restantes")
            return True
        else:
            add_debug_log("⚠️ Token já expirado, auto-renovação não iniciada")
            return False
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao inicializar auto-renovação: {e}")
        return False

# ========== SISTEMA DE DEBUG E LOGS ==========
# Baseado no módulo modulo_debug_logs_tempo_real.py
DEBUG_LOGS = []
MAX_DEBUG_LOGS = 100
debug_lock = threading.Lock()

def add_debug_log(message):
    """Adiciona log de debug com timestamp"""
    global DEBUG_LOGS
    
    with debug_lock:
        timestamp = get_local_time().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        DEBUG_LOGS.append(log_entry)
        
        if len(DEBUG_LOGS) > MAX_DEBUG_LOGS:
            DEBUG_LOGS.pop(0)
        
        print(log_entry)

def get_debug_logs(limit=None):
    """Retorna os logs de debug"""
    with debug_lock:
        if limit:
            return DEBUG_LOGS[-limit:] if DEBUG_LOGS else ["Nenhum log ainda"]
        return DEBUG_LOGS.copy() if DEBUG_LOGS else ["Nenhum log ainda"]

def clear_debug_logs():
    """Limpa todos os logs de debug"""
    global DEBUG_LOGS
    
    with debug_lock:
        DEBUG_LOGS.clear()
        add_debug_log("🗑️ Logs de debug limpos")

# ========== MODELOS DO BANCO DE DADOS ==========
# Baseado nos módulos funcionais salvos

class User(db.Model):
    """Usuários do sistema"""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    ml_user_id = db.Column(db.String(50), unique=True, nullable=False)
    access_token = db.Column(db.String(200), nullable=False)
    refresh_token = db.Column(db.String(200))
    token_expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=get_local_time_utc)
    updated_at = db.Column(db.DateTime, default=get_local_time_utc, onupdate=get_local_time_utc)

class AutoResponse(db.Model):
    """Regras de resposta automática por palavras-chave"""
    __tablename__ = 'auto_responses'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    keywords = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_local_time_utc)
    updated_at = db.Column(db.DateTime, default=get_local_time_utc, onupdate=get_local_time_utc)

class Question(db.Model):
    """Perguntas recebidas do Mercado Livre"""
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
    """Configurações de mensagens de ausência por horário"""
    __tablename__ = 'absence_configs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)  # HH:MM
    end_time = db.Column(db.String(5), nullable=False)    # HH:MM
    days_of_week = db.Column(db.String(20), nullable=False)  # 0,1,2,3,4,5,6
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_local_time_utc)

class ResponseHistory(db.Model):
    """Histórico de respostas enviadas"""
    __tablename__ = 'response_history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    response_type = db.Column(db.String(20), nullable=False)  # 'auto', 'absence', 'manual'
    keywords_matched = db.Column(db.String(200))
    response_time = db.Column(db.Float)  # tempo em segundos para responder
    created_at = db.Column(db.DateTime, default=get_local_time_utc)

class TokenLog(db.Model):
    """Logs de verificação de token"""
    __tablename__ = 'token_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token_status = db.Column(db.String(20), nullable=False)  # 'valid', 'expired', 'error'
    error_message = db.Column(db.Text)
    checked_at = db.Column(db.DateTime, default=get_local_time_utc)

class WebhookLog(db.Model):
    """Logs de webhooks recebidos"""
    __tablename__ = 'webhook_logs'
    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(100))
    resource = db.Column(db.String(200))
    user_id_ml = db.Column(db.String(50))
    application_id = db.Column(db.String(50))
    attempts = db.Column(db.Integer, default=1)
    sent = db.Column(db.DateTime)
    received = db.Column(db.DateTime, default=get_local_time_utc)



# ====== MULTI-CONTA: utilidades de tokens por usuário ======
def get_user_tokens_by_ml_id(ml_user_id: str):
    """Retorna (access_token, refresh_token) do usuário no banco."""
    with app.app_context():
        u = User.query.filter_by(ml_user_id=str(ml_user_id)).first()
        if not u or not u.access_token:
            raise RuntimeError(f"Sem tokens salvos para o user {ml_user_id}")
        return u.access_token, u.refresh_token

def answer_question_ml_with_token(access_token: str, question_id: str, answer_text: str) -> bool:
    """Variante que responde usando um access token específico (multi-conta)."""
    url = "https://api.mercadolibre.com/answers"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    data = {"question_id": int(question_id), "text": answer_text}
    try:
        add_debug_log(f"📤 Enviando resposta (user token) para pergunta {question_id}")
        r = requests.post(url, headers=headers, json=data, timeout=30)
        if r.status_code == 200:
            add_debug_log("✅ Resposta enviada com sucesso!")
            return True
        add_debug_log(f"❌ Erro ao enviar resposta: {r.status_code}: {r.text}")
    except Exception as e:
        add_debug_log(f"❌ Erro na requisição: {e}")
    return False

def fetch_question_by_id_with_token(access_token: str, qid: str, user_id_for_refresh: str = None):
    """Busca uma pergunta diretamente por ID (evita buracos da listagem)."""
    url = f"https://api.mercadolibre.com/questions/{qid}"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            return r.json()
        # Retry on 401 once (refresh per-user on the fly)
        if user_id_for_refresh and r.status_code == 401:
            try:
                inst = multi_refresh.get(str(user_id_for_refresh))
                ok, res = inst.process_refresh_token_internal()
                if ok and 'access_token' in res:
                    inst.update_system_tokens_internal(res['access_token'], res.get('refresh_token',''), str(user_id_for_refresh))
                    headers_retry = {"Authorization": f"Bearer {res['access_token']}"}
                    r2 = requests.get(url, headers=headers_retry, timeout=30)
                    if r2.status_code == 200:
                        return r2.json()
                    else:
                        add_debug_log(f"❌ Retry após refresh falhou: {r2.status_code}: {r2.text}")
                else:
                    add_debug_log("⚠️ Refresh imediato não retornou access_token")
            except Exception as _e:
                add_debug_log(f"⚠️ Falha no refresh imediato (401) para user {user_id_for_refresh}: {_e}")
        add_debug_log(f"❌ Erro ao buscar pergunta {qid}: {r.status_code}: {r.text}")
    except Exception as e:
        add_debug_log(f"❌ Erro ao buscar pergunta {qid}: {e}")
    return None


@app.route("/", methods=["GET"])
def home():
    return (
        "<h2>Bot Mercado Livre</h2>"
        "<p>Online ✅</p>"
        "<ul>"
        "<li>Webhook: <code>/api/ml/webhook</code></li>"
        "<li>Health: <code>/health</code></li>"
        "</ul>"
    ), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

