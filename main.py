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
            with app.app_context():
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
        add_debug_log(f"❌ Erro ao buscar pergunta {qid}: {r.status_code}: {r.text}")
    except Exception as e:
        add_debug_log(f"❌ Erro ao buscar pergunta {qid}: {e}")
    return None

def fetch_unanswered_questions_with_token(access_token: str, limit: int = 50, user_id_for_refresh: str = None):
    """Listagem de perguntas não respondidas para um token específico (multi-conta)."""
    url = "https://api.mercadolibre.com/my/received_questions/search"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"status": "UNANSWERED", "limit": limit}
    try:
        add_debug_log("📥 Buscando perguntas não respondidas (user token)...")
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 200:
            qs = r.json().get("questions", [])
            add_debug_log(f"   Encontradas: {len(qs)} perguntas")
            return qs
        add_debug_log(f"❌ Erro na listagem: {r.status_code}: {r.text}")
    except Exception as e:
        add_debug_log(f"❌ Erro na listagem: {e}")
    return []

# ========== VARIÁVEIS GLOBAIS DE CONTROLE ==========
_initialized = False
_db_lock = threading.Lock()

# ========== INICIALIZAÇÃO DO BANCO DE DADOS ==========
def initialize_database():
    """Inicializa o banco de dados com dados padrão"""
    global _initialized
    
    if _initialized:
        return
    
    try:
        with _db_lock:
            with app.app_context():
                add_debug_log("🔄 Inicializando banco de dados...")
                
                # Criar todas as tabelas
                db.create_all()
                add_debug_log("✅ Tabelas criadas com sucesso")
                
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
                    add_debug_log(f"✅ Usuário padrão criado: {ML_USER_ID}")
                else:
                    # Atualizar token se necessário
                    user.access_token = ML_ACCESS_TOKEN
                    user.token_expires_at = get_local_time_utc() + timedelta(hours=6)
                    user.updated_at = get_local_time_utc()
                    db.session.commit()
                    add_debug_log(f"✅ Usuário atualizado: {ML_USER_ID}")
                
                _initialized = True
                add_debug_log(f"✅ Banco inicializado: {DATABASE_PATH}")
                
    except Exception as e:
        add_debug_log(f"❌ Erro ao inicializar banco: {e}")
        print(f"❌ Erro crítico na inicialização: {e}")

# ========== INICIALIZAÇÃO AUTOMÁTICA ==========
add_debug_log("🚀 Iniciando sistema Bot ML...")
add_debug_log(f"📁 Diretório de dados: {DATA_DIR}")
add_debug_log(f"🗄️ Banco de dados: {DATABASE_PATH}")
add_debug_log(f"🔑 Token: {ML_ACCESS_TOKEN[:20]}...")
add_debug_log(f"👤 User ID: {ML_USER_ID}")

print("🤖 Bot do Mercado Livre - Sistema Completo Funcional")
print(f"📁 Dados: {DATA_DIR}")
print(f"🔑 Token: {ML_ACCESS_TOKEN[:20]}...")
print(f"👤 User: {ML_USER_ID}")


# ========== SISTEMA DE AUSÊNCIA E REGRAS AUTOMÁTICAS ==========
# Baseado no módulo modulo_ausencia_regras_sistema.py - 100% FUNCIONAL

def is_absence_time():
    """
    Verifica se está em horário de ausência
    Retorna: mensagem de ausência ou None
    """
    try:
        now = get_local_time()
        current_time = now.strftime("%H:%M")
        current_weekday = str(now.weekday())  # 0=segunda, 6=domingo
        
        add_debug_log(f"🌙 Verificando ausência - Horário: {current_time}, Dia: {current_weekday}")
        
        absence_configs = AbsenceConfig.query.filter_by(is_active=True).all()
        add_debug_log(f"   Configurações ativas: {len(absence_configs)}")
        
        for config in absence_configs:
            if current_weekday in config.days_of_week.split(','):
                start_time = config.start_time
                end_time = config.end_time
                
                add_debug_log(f"   Testando: {config.name} ({start_time}-{end_time})")
                
                # Se start_time > end_time, significa que cruza meia-noite
                if start_time > end_time:
                    if current_time >= start_time or current_time <= end_time:
                        add_debug_log(f"   ✅ AUSÊNCIA ATIVA: {config.name}")
                        return config.message
                else:
                    if start_time <= current_time <= end_time:
                        add_debug_log(f"   ✅ AUSÊNCIA ATIVA: {config.name}")
                        return config.message
        
        add_debug_log("   ❌ Nenhuma configuração de ausência ativa")
        return None
        
    except Exception as e:
        add_debug_log(f"❌ Erro ao verificar ausência: {e}")
        return None

def find_auto_response(question_text):
    """
    Encontra resposta automática baseada em palavras-chave
    Retorna: (response_text, keywords) ou (None, None)
    """
    try:
        question_lower = question_text.lower()
        add_debug_log(f"🔍 Buscando resposta para: '{question_text[:30]}...'")
        
        auto_responses = AutoResponse.query.filter_by(is_active=True).all()
        add_debug_log(f"   Regras ativas: {len(auto_responses)}")
        
        for response in auto_responses:
            keywords = [k.strip().lower() for k in response.keywords.split(',')]
            
            for keyword in keywords:
                if keyword and keyword in question_lower:
                    add_debug_log(f"   ✅ MATCH: '{keyword}' -> {response.response_text[:30]}...")
                    return response.response_text, response.keywords
        
        add_debug_log("   ❌ Nenhuma palavra-chave encontrada")
        return None, None
        
    except Exception as e:
        add_debug_log(f"❌ Erro ao buscar resposta: {e}")
        return None, None

def answer_question_ml(question_id, answer_text):
    """
    Responde uma pergunta no Mercado Livre
    Retorna: True se sucesso, False se erro
    """
    url = f"https://api.mercadolibre.com/answers"
    
    headers = {
        "Authorization": f"Bearer {ML_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = {
        "question_id": int(question_id),
        "text": answer_text
    }
    
    try:
        add_debug_log(f"📤 Enviando resposta para pergunta {question_id}")
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            add_debug_log(f"✅ Resposta enviada com sucesso!")
            return True
        else:
            error_msg = f"Erro {response.status_code}: {response.text}"
            add_debug_log(f"❌ Erro ao enviar resposta: {error_msg}")
            return False
            
    except Exception as e:
        add_debug_log(f"❌ Erro na requisição: {e}")
        return False

def fetch_unanswered_questions():
    """
    Busca perguntas não respondidas do Mercado Livre
    Retorna: lista de perguntas
    """
    url = f"https://api.mercadolibre.com/my/received_questions/search"
    
    headers = {
        "Authorization": f"Bearer {ML_ACCESS_TOKEN}"
    }
    
    params = {
        "status": "UNANSWERED",
        "limit": 50
    }
    
    try:
        add_debug_log("📥 Buscando perguntas não respondidas...")
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            questions = response.json().get("questions", [])
            add_debug_log(f"   Encontradas: {len(questions)} perguntas")
            return questions
        else:
            add_debug_log(f"❌ Erro ao buscar perguntas: {response.status_code}")
            return []
            
    except Exception as e:
        add_debug_log(f"❌ Erro na requisição: {e}")
        return []

def process_questions():
    """
    Processa perguntas automaticamente aplicando regras de ausência e palavras-chave
    Esta é a função principal que integra todo o sistema
    """
    try:
        add_debug_log("🔄 ========== PROCESSANDO PERGUNTAS ==========")
        
        with _db_lock:
            with app.app_context():
                questions = fetch_unanswered_questions()
                
                if not questions:
                    add_debug_log("📭 Nenhuma pergunta nova")
                    return
                
                user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
                if not user:
                    add_debug_log("❌ Usuário não encontrado")
                    return
                
                for q in questions:
                    question_id = str(q.get("id"))
                    question_text = q.get("text", "")
                    item_id = q.get("item_id", "")
                    
                    add_debug_log(f"📩 Pergunta #{question_id}: '{question_text[:50]}...'")
                    
                    # Verificar se já processamos esta pergunta
                    existing = Question.query.filter_by(ml_question_id=question_id).first()
                    if existing and existing.is_answered:
                        add_debug_log(f"   ⏭️ Pergunta já respondida")
                        continue
                    
                    # Se pergunta existe mas não foi respondida, reprocessar
                    if existing and not existing.is_answered:
                        add_debug_log(f"   🔄 Reprocessando pergunta não respondida")
                        question = existing
                        start_time = time.time()  # Tempo para reprocessamento
                    else:
                        # Nova pergunta - salvar no banco
                        start_time = time.time()
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
                    
                    # 1. BUSCAR RESPOSTA AUTOMÁTICA POR PALAVRAS-CHAVE PRIMEIRO
                    auto_response, matched_keywords = find_auto_response(question_text)
                    if auto_response:
                        if answer_question_ml(question_id, auto_response):
                            question.response_text = auto_response
                            question.is_answered = True
                            question.answered_automatically = True
                            question.answered_at = get_local_time_utc()
                            response_type = "auto"
                            keywords_matched = matched_keywords
                            add_debug_log(f"✅ Respondida automaticamente")
                    else:
                        # 2. SE NÃO HOUVER REGRA, VERIFICAR HORÁRIO DE AUSÊNCIA
                        absence_message = is_absence_time()
                        if absence_message:
                            if answer_question_ml(question_id, absence_message):
                                question.response_text = absence_message
                                question.is_answered = True
                                question.answered_automatically = True
                                question.answered_at = get_local_time_utc()
                                response_type = "absence"
                                add_debug_log(f"✅ Respondida com mensagem de ausência")
                    
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
                    
                add_debug_log("✅ Processamento concluído")
                
    except Exception as e:
        add_debug_log(f"❌ Erro ao processar perguntas: {e}")
        import traceback
        add_debug_log(f"   Traceback: {traceback.format_exc()}")

# ========== DADOS PADRÃO PARA INICIALIZAÇÃO ==========
def create_default_data():
    """Cria dados padrão se não existirem"""
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return
            
            # Criar regras padrão se não existirem
            if AutoResponse.query.filter_by(user_id=user.id).count() == 0:
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
                        "keywords": "nota, fiscal, nf, emite",
                        "response": "Olá, seja bem-vindo à DETTECH, todos os produtos são com nota fiscal, pode ficar tranquilo!"
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
                add_debug_log(f"✅ {len(default_rules)} regras padrão criadas")
            
            # Criar configurações de ausência padrão se não existirem
            if AbsenceConfig.query.filter_by(user_id=user.id).count() == 0:
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
                add_debug_log(f"✅ {len(absence_configs)} configurações de ausência criadas")
                
    except Exception as e:
        add_debug_log(f"❌ Erro ao criar dados padrão: {e}")

# ========== MONITORAMENTO CONTÍNUO ==========


def monitor_questions():
    """Função de monitoramento contínuo de perguntas (multi-conta)."""
    while True:
        try:
            if _initialized:
                with app.app_context():
                    users = User.query.all()
                for u in users:
                    try:
                        qs = fetch_unanswered_questions_with_token(u.access_token, limit=50, user_id_for_refresh=str(u.ml_user_id))
                        if not qs:
                            continue
                        for q in qs:
                            qid = str(q.get("id"))
                            text = q.get("text", "")
                            item_id = q.get("item_id", "")
                            with app.app_context():
                                existing = Question.query.filter_by(ml_question_id=qid).first()
                                if existing and existing.is_answered:
                                    continue
                                if not existing:
                                    question = Question(
                                        ml_question_id=qid,
                                        user_id=u.id,
                                        item_id=item_id or "",
                                        question_text=text or "",
                                        is_answered=False
                                    )
                                    db.session.add(question)
                                    db.session.flush()
                                else:
                                    question = existing
                                auto_response, matched_keywords = find_auto_response(text or "")
                                reply = auto_response or is_absence_time()
                                if reply:
                                    if answer_question_ml_with_token(u.access_token, qid, reply):
                                        question.response_text = reply
                                        question.is_answered = True
                                        question.answered_automatically = True
                                        question.answered_at = get_local_time_utc()
                                        history = ResponseHistory(
                                            user_id=u.id,
                                            question_id=question.id,
                                            response_type=("auto" if auto_response else "absence"),
                                            keywords_matched=(matched_keywords),
                                            response_time=0.0
                                        )
                                        db.session.add(history)
                                db.session.commit()
                    except Exception as e:
                        try:
                            uid = getattr(u, "ml_user_id", None) or getattr(u, "id", "?")
                        except Exception:
                            uid = "?"
                        add_debug_log(f"❌ monitor/{uid}: {e}")
            time.sleep(30)
        except Exception as e:
            add_debug_log(f"❌ Erro no monitoramento: {e}")
            time.sleep(30)

# ========== SISTEMA DE RENOVAÇÃO MANUAL DE TOKENS ==========
# Baseado no módulo modulo_renovacao_token_manual.py - 100% FUNCIONAL

# Cache para evitar processamento duplicado de códigos
processed_codes = set()

def extract_code_from_input(input_str):
    """
    Extrai código de autorização de string ou URL
    Corrige problema de URL completa sendo enviada como código
    """
    input_str = input_str.strip()
    
    # Se contém 'code=', extrair da URL
    if 'code=' in input_str:
        try:
            import urllib.parse
            if input_str.startswith('http'):
                # É uma URL completa
                parsed = urllib.parse.urlparse(input_str)
                params = urllib.parse.parse_qs(parsed.query)
                code = params.get('code', [input_str])[0]
                add_debug_log(f"🔧 Código extraído da URL: {code}")
                return code
            else:
                # Pode ser só o parâmetro code=...
                if input_str.startswith('code='):
                    return input_str.split('code=')[1].split('&')[0]
        except Exception as e:
            add_debug_log(f"⚠️ Erro ao extrair código da URL: {e}")
    
    # Retornar como está (já é um código limpo)
    return input_str

def generate_auth_url():
    """Gera URL de autorização do Mercado Livre"""
    redirect_uri = REDIRECT_URIS[0]  # Usar webhook como padrão
    
    url = (
        f"https://auth.mercadolivre.com.br/authorization?"
        f"response_type=code&"
        f"client_id={ML_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        f"scope=offline_access read write"
    )
    
    add_debug_log(f"🔗 URL de autorização gerada: {redirect_uri}")
    return url

def process_auth_code_flexible(code):
    """
    Processa código de autorização tentando múltiplas URLs de redirect
    Retorna: (success: bool, result: dict)
    """
    try:
        # CORREÇÃO: Extrair código limpo da entrada
        clean_code = extract_code_from_input(code)
        add_debug_log(f"🔄 Processando código: {clean_code}")
        
        # CORREÇÃO: Verificar se código já foi processado
        if clean_code in processed_codes:
            add_debug_log(f"⚠️ Código já foi processado anteriormente: {clean_code}")
            return False, {
                'success': False,
                'error': 'Código já processado',
                'message': 'Este código de autorização já foi usado. Gere um novo código.'
            }
        
        # Adicionar ao cache de códigos processados
        processed_codes.add(clean_code)
        
        for i, redirect_uri in enumerate(REDIRECT_URIS):
            try:
                add_debug_log(f"🔄 Tentativa {i+1}/4 com redirect_uri: {redirect_uri}")
                
                url = "https://api.mercadolibre.com/oauth/token"
                data = {
                    'grant_type': 'authorization_code',
                    'client_id': ML_CLIENT_ID,
                    'client_secret': ML_CLIENT_SECRET,
                    'code': clean_code,  # CORREÇÃO: Usar código limpo
                    'redirect_uri': redirect_uri
                }
                
                response = requests.post(url, data=data)
                
                if response.status_code == 200:
                    token_data = response.json()
                    
                    # Buscar informações do usuário
                    user_info = get_user_info(token_data['access_token'])
                    
                    result = {
                        'success': True,
                        'access_token': token_data['access_token'],
                        'refresh_token': token_data.get('refresh_token', ''),
                        'user_id': str(token_data['user_id']),
                        'expires_in': token_data.get('expires_in', 21600),
                        'user_info': user_info,
                        'redirect_uri_used': redirect_uri
                    }
                    
                    add_debug_log(f"✅ Sucesso com redirect_uri: {redirect_uri}")
                    return True, result
                    
                else:
                    error_msg = f"Erro {response.status_code}: {response.text}"
                    add_debug_log(f"❌ Falha com redirect_uri {redirect_uri}: {error_msg}")
                    
            except Exception as e:
                add_debug_log(f"❌ Erro com redirect_uri {redirect_uri}: {str(e)}")
                continue
        
        # Remover do cache se todas as tentativas falharam
        processed_codes.discard(clean_code)
        
        add_debug_log("❌ Todas as tentativas falharam")
        return False, {
            'success': False,
            'error': 'Todas as tentativas falharam',
            'message': 'Código inválido, expirado ou já foi usado'
        }
        
    except Exception as e:
        add_debug_log(f"❌ Erro ao processar código: {e}")
        return False, {
            'success': False,
            'error': str(e),
            'message': f'Erro ao processar código: {str(e)}'
        }

def get_user_info(access_token):
    """Busca informações do usuário"""
    try:
        url = f"https://api.mercadolibre.com/users/me?access_token={access_token}"
        response = requests.get(url)
        
        if response.status_code == 200:
            return response.json()
        else:
            add_debug_log(f"❌ Erro ao buscar info do usuário: {response.status_code}")
            return None
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao buscar info do usuário: {e}")
        return None


def update_system_tokens(access_token, refresh_token, user_id):
    """Atualiza tokens no sistema (globais + DB) e inicia auto-refresh por usuário"""
    try:
        add_debug_log("🔄 Atualizando tokens no sistema...")
        global ML_ACCESS_TOKEN, ML_REFRESH_TOKEN, ML_USER_ID
        ML_ACCESS_TOKEN = access_token
        ML_REFRESH_TOKEN = refresh_token
        ML_USER_ID = user_id
        with app.app_context():
            user = User.query.filter_by(ml_user_id=user_id).first()
            if not user:
                user = User(ml_user_id=user_id)
                db.session.add(user)
            user.access_token = access_token
            user.refresh_token = refresh_token
            user.token_expires_at = get_local_time_utc() + timedelta(hours=6)
            user.updated_at = get_local_time_utc()
            db.session.commit()
        inst = multi_refresh.get(str(user_id))
        inst.update_system_tokens_internal(access_token, refresh_token, str(user_id))
        inst.start_auto_refresh(21600)
        add_debug_log("✅ Sistema atualizado com novos tokens!")
        add_debug_log(f"🔑 Access Token: {access_token[:20]}...")
        add_debug_log(f"🔄 Refresh Token: {refresh_token[:20]}...")
        add_debug_log(f"👤 User ID: {user_id}")
        return True, "Tokens atualizados com sucesso"
    except Exception as e:
        error_msg = f"Erro ao atualizar tokens: {str(e)}"
        add_debug_log(f"❌ {error_msg}")
        return False, error_msg
# ========== ROTAS FLASK PARA RENOVAÇÃO DE TOKENS ==========

@app.route('/renovar-tokens')
def renovar_tokens_page():
    """Interface web para renovação manual de tokens"""
    
    auth_url = generate_auth_url()
    
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Renovar Tokens - Bot ML</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }}
            .card {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin-bottom: 20px; }}
            .btn {{ display: inline-block; padding: 12px 24px; background: #3483fa; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 10px 5px; }}
            .btn:hover {{ background: #2968c8; }}
            .btn-success {{ background: #28a745; }}
            .btn-success:hover {{ background: #218838; }}
            .btn-warning {{ background: #ffc107; color: #212529; }}
            .btn-warning:hover {{ background: #e0a800; }}
            .form-group {{ margin-bottom: 15px; }}
            .form-group label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
            .form-group input {{ width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }}
            .alert {{ padding: 15px; margin-bottom: 20px; border-radius: 5px; }}
            .alert-info {{ background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }}
            .alert-success {{ background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
            .alert-error {{ background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
            .step {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 15px; border-left: 4px solid #3483fa; }}
            .code-input {{ font-family: monospace; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🔄 Renovar Tokens do Mercado Livre</h1>
                <p>Interface para renovação manual de tokens de acesso</p>
            </div>
            
            <div class="card">
                <h3>📋 Instruções</h3>
                <div class="step">
                    <strong>Passo 1:</strong> Clique no botão abaixo para abrir a autorização do Mercado Livre
                </div>
                <div class="step">
                    <strong>Passo 2:</strong> Faça login na sua conta do Mercado Livre
                </div>
                <div class="step">
                    <strong>Passo 3:</strong> Autorize o aplicativo
                </div>
                <div class="step">
                    <strong>Passo 4:</strong> Copie o código da URL de retorno e cole abaixo
                </div>
                
                <div style="text-align: center; margin: 20px 0;">
                    <a href="{auth_url}" target="_blank" class="btn btn-success">
                        🌐 Abrir Autorização do ML
                    </a>
                </div>
            </div>
            
            <div class="card">
                <h3>🔑 Processar Código de Autorização</h3>
                <div class="alert alert-info">
                    <strong>Formato esperado:</strong> TG-xxxxxxxxxxxxxxxxxxxxxxx-xxxxxxxxx
                </div>
                
                <form id="token-form">
                    <div class="form-group">
                        <label for="auth-code">Código de Autorização:</label>
                        <input type="text" id="auth-code" name="auth-code" class="code-input" 
                               placeholder="TG-xxxxxxxxxxxxxxxxxxxxxxx-xxxxxxxxx" required>
                    </div>
                    <button type="submit" class="btn">🔄 Processar Código</button>
                </form>
                
                <div id="result-container" style="margin-top: 20px;"></div>
            </div>
            
            <div class="card">
                <h3>🏠 Navegação</h3>
                <a href="/" class="btn">← Voltar ao Dashboard</a>
                <a href="/debug-full" class="btn btn-warning">🔍 Ver Logs</a>
            </div>
        </div>
        
        <script>
            document.getElementById('token-form').addEventListener('submit', async function(e) {{
                e.preventDefault();
                
                const code = document.getElementById('auth-code').value.trim();
                const resultContainer = document.getElementById('result-container');
                
                if (!code) {{
                    resultContainer.innerHTML = '<div class="alert alert-error">Por favor, insira o código de autorização.</div>';
                    return;
                }}
                
                resultContainer.innerHTML = '<div class="alert alert-info">🔄 Processando código...</div>';
                
                try {{
                    const response = await fetch('/api/tokens/process-code-flexible', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json'
                        }},
                        body: JSON.stringify({{ code: code }})
                    }});
                    
                    const result = await response.json();
                    
                    if (result.success) {{
                        resultContainer.innerHTML = `
                            <div class="alert alert-success">
                                <h4>✅ Tokens atualizados com sucesso!</h4>
                                <p><strong>Access Token:</strong> ${{result.access_token.substring(0, 20)}}...</p>
                                <p><strong>User ID:</strong> ${{result.user_id}}</p>
                                <p><strong>Expira em:</strong> ${{result.expires_in}} segundos</p>
                                <p><strong>Redirect URI usado:</strong> ${{result.redirect_uri_used}}</p>
                                ${{result.user_info ? `<p><strong>Email:</strong> ${{result.user_info.email}}</p>` : ''}}
                            </div>
                        `;
                        
                        // Limpar formulário
                        document.getElementById('auth-code').value = '';
                        
                        // Redirecionar após 3 segundos
                        setTimeout(() => {{
                            window.location.href = '/';
                        }}, 3000);
                        
                    }} else {{
                        resultContainer.innerHTML = `
                            <div class="alert alert-error">
                                <h4>❌ Erro ao processar código</h4>
                                <p><strong>Erro:</strong> ${{result.message}}</p>
                                <p>Verifique se o código está correto e tente novamente.</p>
                            </div>
                        `;
                    }}
                    
                }} catch (error) {{
                    resultContainer.innerHTML = `
                        <div class="alert alert-error">
                            <h4>❌ Erro de conexão</h4>
                            <p>Não foi possível processar o código. Tente novamente.</p>
                        </div>
                    `;
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    return html

@app.route('/api/tokens/process-code-flexible', methods=['POST'])
def api_process_code_flexible():
    """API para processar código de autorização com múltiplas tentativas"""
    try:
        data = request.get_json()
        code = data.get('code', '').strip()
        
        if not code:
            return jsonify({
                'success': False,
                'message': 'Código não fornecido'
            }), 400
        
        # Processar código
        success, result = process_auth_code_flexible(code)
        
        if success:
            # Atualizar sistema com novos tokens
            update_success, update_message = update_system_tokens(
                result['access_token'],
                result['refresh_token'],
                result['user_id']
            )
            
            if update_success:
                return jsonify(result)
            else:
                return jsonify({
                    'success': False,
                    'message': f'Tokens obtidos mas erro ao atualizar sistema: {update_message}'
                }), 500
        else:
            return jsonify(result), 400
            
    except Exception as e:
        add_debug_log(f"❌ Erro na API de processamento: {e}")
        return jsonify({
            'success': False,
            'message': f'Erro interno: {str(e)}'
        }), 500

@app.route('/api/ml/webhook', methods=['GET', 'POST'])
def webhook_ml():
    """Webhook para receber códigos de autorização e notificações do ML"""
    try:
        if request.method == 'GET':
            # Verificar se há código de autorização na URL
            code = request.args.get('code')
            if code:
                add_debug_log(f"🔗 Código recebido via webhook GET: {code}")
                
                # Processar código automaticamente
                success, result = process_auth_code_flexible(code)
                
                if success:
                    update_system_tokens(
                        result['access_token'],
                        result['refresh_token'],
                        result['user_id']
                    )
                    
                    return f"""
                    <!DOCTYPE html>
                    <html>
                    <head><title>Autorização Concluída</title></head>
                    <body>
                        <h1>✅ Tokens Atualizados com Sucesso!</h1>
                        <p><strong>User ID:</strong> {result['user_id']}</p>
                        <p><strong>Token:</strong> {code}</p>
                        <p>O sistema já está usando os novos tokens.</p>
                        <p><a href="/">← Voltar ao Dashboard</a></p>
                    </body>
                    </html>
                    """
                else:
                    return f"""
                    <!DOCTYPE html>
                    <html>
                    <head><title>Erro na Autorização</title></head>
                    <body>
                        <h1>❌ Erro na Autorização</h1>
                        <p>{result.get('message', 'Erro desconhecido')}</p>
                        <p><a href="/renovar-tokens">← Tentar Novamente</a></p>
                    </body>
                    </html>
                    """
            else:
                return jsonify({"message": "webhook funcionando!", "status": "webhook_active"})
        
        elif request.method == 'POST':
            # Processar notificação do ML
            data = request.get_json()
            
            if data and data.get('topic') == 'questions':
                add_debug_log(f"📨 Notificação de pergunta recebida: {data}")

                # Salvar log do webhook
                webhook_log = WebhookLog(
                    topic=data.get('topic'),
                    resource=data.get('resource'),
                    user_id_ml=str(data.get('user_id')),
                    application_id=data.get('application_id'),
                    sent=datetime.fromisoformat(data.get('sent', '').replace('Z', '+00:00')) if data.get('sent') else None
                )
                db.session.add(webhook_log)
                db.session.commit()

                resource = data.get('resource', '')
                qid = resource.split('/')[-1] if resource else None
                user_id_ml = str(data.get('user_id'))

                def worker():
                    try:
                        if not qid or not user_id_ml:
                            add_debug_log("⚠️ Webhook sem qid ou user_id")
                            return
                        access_token, _rt = get_user_tokens_by_ml_id(user_id_ml)
                        q = fetch_question_by_id_with_token(access_token, qid, user_id_for_refresh=user_id_ml)
                        if not q:
                            # fallback leve: tenta via listagem do próprio usuário
                            qs = fetch_unanswered_questions_with_token(access_token, limit=50, user_id_for_refresh=user_id_ml)
                            for x in qs:
                                if str(x.get("id")) == str(qid):
                                    q = x
                                    break
                        if not q:
                            add_debug_log(f"⚠️ Pergunta {qid} não disponível ainda; será capturada no próximo ciclo")
                            return

                        text = q.get('text', '')
                        item_id = q.get('item_id', '')

                        with app.app_context():
                            user = User.query.filter_by(ml_user_id=user_id_ml).first()
                            if not user:
                                user = User(ml_user_id=user_id_ml, access_token=access_token, token_expires_at=get_local_time_utc() + timedelta(hours=6))
                                db.session.add(user)
                                db.session.commit()

                            existing = Question.query.filter_by(ml_question_id=str(qid)).first()
                            if existing and existing.is_answered:
                                add_debug_log("⏭️ Pergunta já respondida")
                                return

                            question = existing or Question(
                                ml_question_id=str(qid),
                                user_id=user.id,
                                item_id=item_id or "",
                                question_text=text or "",
                                is_answered=False
                            )
                            if not existing:
                                db.session.add(question)
                                db.session.flush()

                            start_time = time.time()
                            response_type = None
                            keywords_matched = None

                            auto_response, matched_keywords = find_auto_response(text or "")
                            reply = auto_response or is_absence_time()
                            if reply:
                                if answer_question_ml_with_token(access_token, str(qid), reply):
                                    question.response_text = reply
                                    question.is_answered = True
                                    question.answered_automatically = True
                                    question.answered_at = get_local_time_utc()
                                    response_type = "auto" if auto_response else "absence"
                                    keywords_matched = matched_keywords

                            if response_type:
                                history = ResponseHistory(
                                    user_id=user.id,
                                    question_id=question.id,
                                    response_type=response_type,
                                    keywords_matched=keywords_matched,
                                    response_time=time.time() - start_time
                                )
                                db.session.add(history)

                            db.session.commit()
                            add_debug_log("✅ Webhook processado por ID com sucesso")
                    except Exception as e:
                        add_debug_log(f"❌ Erro ao processar webhook/ID: {e}")

                threading.Thread(target=worker, daemon=True).start()
                return jsonify({"status": "ok", "message": "notificação processada"})
            return jsonify({"status": "ok", "message": "webhook recebido"})
        
    except Exception as e:
        add_debug_log(f"❌ Erro no webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ========== LAYOUT MINIMALISTA E SISTEMA DE HISTÓRICO ==========
# Baseado nos módulos modulo_layout_minimalista.py e modulo_historico_respostas.py

# CSS Base para todas as páginas
BASE_CSS = """
* { 
    margin: 0; 
    padding: 0; 
    box-sizing: border-box; 
}

body { 
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
    background: #f8f9fa; 
    line-height: 1.6;
}

.container { 
    max-width: 1200px; 
    margin: 0 auto; 
    padding: 20px; 
}

/* Header principal */
.header { 
    background: linear-gradient(135deg, #3483fa, #2968c8); 
    color: white; 
    padding: 30px; 
    border-radius: 12px; 
    margin-bottom: 30px; 
    text-align: center;
}

.header h1 { 
    font-size: 2.5em; 
    margin-bottom: 10px; 
    font-weight: 600;
}

.header p { 
    font-size: 1.2em; 
    opacity: 0.9; 
}

/* Navegação */
.nav { 
    margin-bottom: 30px; 
}

.nav a { 
    display: inline-block; 
    padding: 12px 24px; 
    background: #3483fa; 
    color: white; 
    text-decoration: none; 
    border-radius: 8px; 
    margin-right: 10px; 
    margin-bottom: 10px;
    font-weight: 500;
    transition: all 0.3s ease;
}

.nav a:hover { 
    background: #2968c8; 
    transform: translateY(-1px);
}

.nav a.active { 
    background: #28a745; 
}

/* Grid de estatísticas */
.stats { 
    display: grid; 
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
    gap: 20px; 
    margin-bottom: 30px; 
}

.stat-card { 
    background: white; 
    padding: 25px; 
    border-radius: 12px; 
    box-shadow: 0 4px 15px rgba(0,0,0,0.08); 
    text-align: center;
    transition: transform 0.3s ease;
}

.stat-card:hover {
    transform: translateY(-2px);
}

.stat-number { 
    font-size: 2.5em; 
    font-weight: bold; 
    color: #3483fa; 
    margin-bottom: 10px;
}

.stat-label { 
    color: #666; 
    font-size: 1.1em;
}

/* Cards gerais */
.card { 
    background: white; 
    padding: 25px; 
    border-radius: 12px; 
    box-shadow: 0 4px 15px rgba(0,0,0,0.08); 
    margin-bottom: 20px; 
}

.card h3 { 
    color: #333; 
    margin-bottom: 20px; 
    font-size: 1.4em;
}

/* Botões */
.btn { 
    display: inline-block; 
    padding: 10px 20px; 
    background: #3483fa; 
    color: white; 
    text-decoration: none; 
    border-radius: 6px; 
    border: none; 
    cursor: pointer; 
    font-size: 14px;
    font-weight: 500;
    transition: all 0.3s ease;
}

.btn:hover { 
    background: #2968c8; 
    transform: translateY(-1px);
}

.btn-success { 
    background: #28a745; 
}

.btn-success:hover { 
    background: #218838; 
}

.btn-warning { 
    background: #ffc107; 
    color: #212529; 
}

.btn-warning:hover { 
    background: #e0a800; 
}

.btn-danger { 
    background: #dc3545; 
}

.btn-danger:hover { 
    background: #c82333; 
}

/* Tabelas */
.table { 
    width: 100%; 
    border-collapse: collapse; 
    margin-top: 20px;
}

.table th, .table td { 
    padding: 12px; 
    text-align: left; 
    border-bottom: 1px solid #ddd; 
}

.table th { 
    background: #f8f9fa; 
    font-weight: 600;
    color: #333;
}

.table tr:hover { 
    background: #f8f9fa; 
}

/* Formulários */
.form-group { 
    margin-bottom: 20px; 
}

.form-group label { 
    display: block; 
    margin-bottom: 8px; 
    font-weight: 600;
    color: #333;
}

.form-group input, .form-group textarea, .form-group select { 
    width: 100%; 
    padding: 12px; 
    border: 1px solid #ddd; 
    border-radius: 6px; 
    font-size: 14px;
}

.form-group input:focus, .form-group textarea:focus, .form-group select:focus { 
    outline: none; 
    border-color: #3483fa; 
    box-shadow: 0 0 0 3px rgba(52, 131, 250, 0.1);
}

/* Alertas */
.alert { 
    padding: 15px; 
    margin-bottom: 20px; 
    border-radius: 6px; 
    border: 1px solid transparent;
}

.alert-success { 
    background: #d4edda; 
    color: #155724; 
    border-color: #c3e6cb; 
}

.alert-warning { 
    background: #fff3cd; 
    color: #856404; 
    border-color: #ffeaa7; 
}

.alert-danger { 
    background: #f8d7da; 
    color: #721c24; 
    border-color: #f5c6cb; 
}

.alert-info { 
    background: #d1ecf1; 
    color: #0c5460; 
    border-color: #bee5eb; 
}

/* Responsividade */
@media (max-width: 768px) {
    .container { 
        padding: 10px; 
    }
    
    .header h1 { 
        font-size: 2em; 
    }
    
    .stats { 
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); 
        gap: 15px; 
    }
    
    .stat-card { 
        padding: 20px; 
    }
    
    .stat-number { 
        font-size: 2em; 
    }
    
    .nav a { 
        padding: 10px 16px; 
        font-size: 14px; 
    }
    
    .table { 
        font-size: 12px; 
    }
    
    .table th, .table td { 
        padding: 8px; 
    }
}
"""

def create_base_template(title, content, current_page=""):
    """Cria template base com layout minimalista"""
    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - Bot ML</title>
        <style>{BASE_CSS}</style>
    </head>
    <body>
        <div class="container">
            {content}
        </div>
    </body>
    </html>
    """

def create_navigation(current_page=""):
    """Cria navegação principal"""
    nav_items = [
        ("", "🏠 Dashboard"),
        ("edit-rules", "✏️ Regras"),
        ("edit-absence", "🌙 Ausência"),
        ("history", "📊 Histórico"),
        ("renovar-tokens", "🔄 Tokens"),
        ("debug-full", "🔍 Debug")
    ]
    
    nav_html = '<div class="nav">'
    for page, label in nav_items:
        active_class = ' active' if page == current_page else ''
        href = f"/{page}" if page else "/"
        nav_html += f'<a href="{href}" class="{active_class.strip()}">{label}</a>'
    nav_html += '</div>'
    
    return nav_html

def create_header(title, subtitle=""):
    """Cria header principal"""
    return f"""
    <div class="header">
        <h1>{title}</h1>
        {f'<p>{subtitle}</p>' if subtitle else ''}
    </div>
    """

def create_stat_card(number, label, color="#3483fa"):
    """Cria card de estatística"""
    return f"""
    <div class="stat-card">
        <div class="stat-number" style="color: {color}">{number}</div>
        <div class="stat-label">{label}</div>
    </div>
    """

# ========== DASHBOARD PRINCIPAL ==========
@app.route('/')
def dashboard():
    """Dashboard principal com estatísticas e status"""
    try:
        initialize_database()
        
        with app.app_context():
            # Buscar estatísticas
            total_questions = Question.query.count()
            today = get_local_time().date()
            today_start = datetime.combine(today, datetime.min.time())
            today_start_utc = today_start.replace(tzinfo=SAO_PAULO_TZ).astimezone(timezone.utc).replace(tzinfo=None)
            
            answered_today = Question.query.filter(
                Question.answered_at >= today_start_utc,
                Question.is_answered == True
            ).count()
            
            auto_responses_today = ResponseHistory.query.filter(
                ResponseHistory.created_at >= today_start_utc,
                ResponseHistory.response_type == 'auto'
            ).count()
            
            absence_responses_today = ResponseHistory.query.filter(
                ResponseHistory.created_at >= today_start_utc,
                ResponseHistory.response_type == 'absence'
            ).count()
            
            # Tempo médio de resposta
            avg_response = db.session.query(db.func.avg(ResponseHistory.response_time)).scalar()
            avg_response = round(avg_response, 2) if avg_response else 0
            
            # Status do token com renovação automática
            token_valid = True
            token_message = "Token válido"
            try:
                url = "https://api.mercadolibre.com/users/me"
                headers = {"Authorization": f"Bearer {ML_ACCESS_TOKEN}"}
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 200:
                    token_valid = False
                    token_message = f"Erro {response.status_code}"
            except:
                token_valid = False
                token_message = "Erro de conexão"
            
            # Obter status da renovação automática com tratamento de erro
            try:
                token_status_info = auto_refresh_manager.get_token_status()
            except Exception as e:
                add_debug_log(f"❌ Erro ao obter status de renovação: {e}")
                token_status_info = {
                    'status': 'unknown',
                    'message': 'Erro ao obter status',
                    'time_remaining': 0,
                    'next_refresh': 0,
                    'auto_refresh_enabled': False,
                    'is_refreshing': False
                }
            
            current_time = get_local_time().strftime("%H:%M:%S")
            
            # Criar conteúdo do dashboard
            content = create_header("🤖 Bot do Mercado Livre", f"Sistema ativo - {current_time}")
            content += create_navigation("")
            
            # Status do token com renovação automática
            token_color = "#28a745" if token_valid else "#dc3545"
            token_status = "✅ Válido" if token_valid else "❌ Inválido"
            
            # Cores para status de renovação
            status_colors = {
                'active': '#28a745',
                'expiring': '#ffc107', 
                'expired': '#dc3545',
                'unknown': '#6c757d'
            }
            
            refresh_color = status_colors.get(token_status_info['status'], '#6c757d')
            
            # Formatação de tempo
            def format_time_remaining(seconds):
                if seconds <= 0:
                    return "Expirado"
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                if hours > 0:
                    return f"{hours}h {minutes}min"
                else:
                    return f"{minutes}min"
            
            content += f"""
            <div class="card">
                <h3>🔑 Status do Token e Renovação Automática</h3>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px;">
                    <div>
                        <h4>📊 Status Atual</h4>
                        <p><strong>Status:</strong> <span style="color: {token_color}; font-weight: bold;">{token_status}</span></p>
                        <p><strong>Token:</strong> {ML_ACCESS_TOKEN[:20]}...</p>
                        <p><strong>User ID:</strong> {ML_USER_ID}</p>
                        <p><strong>Conexão:</strong> {token_message}</p>
                    </div>
                    <div>
                        <h4>🔄 Renovação Automática</h4>
                        <p><strong>Status:</strong> <span style="color: {refresh_color}; font-weight: bold;">{token_status_info['message']}</span></p>
                        <p><strong>Tempo restante:</strong> <span id="time-remaining" style="font-weight: bold; color: {refresh_color};">{format_time_remaining(token_status_info['time_remaining'])}</span></p>
                        <p><strong>Próxima renovação:</strong> <span id="next-refresh" style="font-weight: bold;">{format_time_remaining(token_status_info['next_refresh'])}</span></p>
                        <p><strong>Auto-renovação:</strong> <span style="color: {'#28a745' if token_status_info['auto_refresh_enabled'] else '#dc3545'}; font-weight: bold;">{'✅ Ativa' if token_status_info['auto_refresh_enabled'] else '❌ Inativa'}</span></p>
                        {f'<p><strong>Status:</strong> <span style="color: #ffc107; font-weight: bold;">🔄 Renovando...</span></p>' if token_status_info['is_refreshing'] else ''}
                    </div>
                </div>
                
                <div style="background: #f8f9fa; padding: 15px; border-radius: 6px; margin-top: 15px;">
                    <h4 style="margin-top: 0;">⏱️ Countdown em Tempo Real</h4>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                        <div style="text-align: center; padding: 15px; background: white; border-radius: 6px; border: 2px solid {refresh_color};">
                            <h5 style="margin: 0; color: {refresh_color};">Token Expira Em</h5>
                            <div id="token-countdown" style="font-size: 1.5em; font-weight: bold; color: {refresh_color}; margin-top: 10px;">
                                {format_time_remaining(token_status_info['time_remaining'])}
                            </div>
                        </div>
                        <div style="text-align: center; padding: 15px; background: white; border-radius: 6px; border: 2px solid #3483fa;">
                            <h5 style="margin: 0; color: #3483fa;">Renovação Em</h5>
                            <div id="refresh-countdown" style="font-size: 1.5em; font-weight: bold; color: #3483fa; margin-top: 10px;">
                                {format_time_remaining(token_status_info['next_refresh'])}
                            </div>
                        </div>
                    </div>
                </div>
                
                <div style="margin-top: 15px; text-align: center;">
                    <button onclick="toggleAutoRefresh()" class="btn {'btn-danger' if token_status_info['auto_refresh_enabled'] else 'btn-success'}" style="margin-right: 10px;">
                        {'🛑 Desabilitar Auto-renovação' if token_status_info['auto_refresh_enabled'] else '🚀 Habilitar Auto-renovação'}
                    </button>
                    <button onclick="forceRefresh()" class="btn btn-warning" style="margin-right: 10px;">
                        🔄 Forçar Renovação Agora
                    </button>
                    <a href="/renovar-tokens" class="btn">🔧 Renovação Manual</a>
                </div>
            </div>
            
            <script>
                // Atualizar countdown a cada segundo
                let tokenTimeRemaining = {token_status_info['time_remaining']};
                let refreshTimeRemaining = {token_status_info['next_refresh']};
                
                function formatTime(seconds) {{
                    if (seconds <= 0) return "Expirado";
                    const hours = Math.floor(seconds / 3600);
                    const minutes = Math.floor((seconds % 3600) / 60);
                    const secs = seconds % 60;
                    
                    if (hours > 0) {{
                        return `${{hours}}h ${{minutes}}min ${{secs}}s`;
                    }} else if (minutes > 0) {{
                        return `${{minutes}}min ${{secs}}s`;
                    }} else {{
                        return `${{secs}}s`;
                    }}
                }}
                
                function updateCountdowns() {{
                    const tokenElement = document.getElementById('token-countdown');
                    const refreshElement = document.getElementById('refresh-countdown');
                    
                    if (tokenElement) {{
                        tokenElement.textContent = formatTime(Math.max(0, tokenTimeRemaining));
                        if (tokenTimeRemaining <= 0) {{
                            tokenElement.style.color = '#dc3545';
                            tokenElement.parentElement.style.borderColor = '#dc3545';
                        }} else if (tokenTimeRemaining <= 3600) {{
                            tokenElement.style.color = '#ffc107';
                            tokenElement.parentElement.style.borderColor = '#ffc107';
                        }}
                    }}
                    
                    if (refreshElement) {{
                        refreshElement.textContent = formatTime(Math.max(0, refreshTimeRemaining));
                    }}
                    
                    tokenTimeRemaining = Math.max(0, tokenTimeRemaining - 1);
                    refreshTimeRemaining = Math.max(0, refreshTimeRemaining - 1);
                }}
                
                // Atualizar a cada segundo
                setInterval(updateCountdowns, 1000);
                
                // Recarregar página a cada 5 minutos para atualizar dados
                setTimeout(() => {{
                    window.location.reload();
                }}, 300000);
                
                async function toggleAutoRefresh() {{
                    try {{
                        const response = await fetch('/api/tokens/toggle-auto-refresh', {{
                            method: 'POST'
                        }});
                        const result = await response.json();
                        if (result.success) {{
                            window.location.reload();
                        }} else {{
                            alert('Erro: ' + result.message);
                        }}
                    }} catch (error) {{
                        alert('Erro ao alterar auto-renovação');
                    }}
                }}
                
                async function forceRefresh() {{
                    if (confirm('Deseja forçar a renovação do token agora?')) {{
                        try {{
                            const response = await fetch('/api/tokens/force-refresh', {{
                                method: 'POST'
                            }});
                            const result = await response.json();
                            if (result.success) {{
                                alert('Token renovado com sucesso!');
                                window.location.reload();
                            }} else {{
                                alert('Erro na renovação: ' + result.message);
                            }}
                        }} catch (error) {{
                            alert('Erro ao forçar renovação');
                        }}
                    }}
                }}
            </script>
            """
            
            # Estatísticas
            content += '<div class="stats">'
            content += create_stat_card(total_questions, "Total de Perguntas")
            content += create_stat_card(answered_today, "Respondidas Hoje")
            content += create_stat_card(auto_responses_today, "Respostas Automáticas", "#28a745" if auto_responses_today > 0 else "#dc3545")
            content += create_stat_card(absence_responses_today, "Respostas Ausência", "#ffc107")
            content += create_stat_card(f"{avg_response}s", "Tempo Médio")
            content += '</div>'
            
            # Últimas perguntas
            recent_questions = Question.query.order_by(Question.created_at.desc()).limit(5).all()
            
            content += """
            <div class="card">
                <h3>📩 Últimas Perguntas</h3>
                <table class="table">
                    <thead>
                        <tr>
                            <th>Pergunta</th>
                            <th>Status</th>
                            <th>Data</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            
            for q in recent_questions:
                status = "✅ Respondida" if q.is_answered else "⏳ Pendente"
                status_color = "#28a745" if q.is_answered else "#ffc107"
                local_time = format_local_time(q.created_at)
                time_str = local_time.strftime("%d/%m %H:%M") if local_time else "N/A"
                
                content += f"""
                <tr>
                    <td>{q.question_text[:50]}...</td>
                    <td style="color: {status_color}; font-weight: bold;">{status}</td>
                    <td>{time_str}</td>
                </tr>
                """
            
            content += """
                    </tbody>
                </table>
            </div>
            """
            
            return create_base_template("Dashboard", content)
            
    except Exception as e:
        add_debug_log(f"❌ Erro no dashboard: {e}")
        error_content = create_header("❌ Erro no Sistema")
        error_content += f"""
        <div class="card">
            <div class="alert alert-danger">
                <h4>Erro no Dashboard</h4>
                <p>Erro: {e}</p>
                <p>O sistema está inicializando, tente novamente em alguns segundos.</p>
            </div>
            <a href="/" class="btn">🔄 Recarregar</a>
        </div>
        """
        return create_base_template("Erro", error_content)

# ========== PÁGINA DE HISTÓRICO ==========
@app.route('/history')
def history_page():
    """Página de histórico de respostas"""
    try:
        with app.app_context():
            # Buscar histórico com joins - CORRIGIDO
            history_query = db.session.query(
                ResponseHistory,
                Question,
                User
            ).select_from(ResponseHistory).join(Question).join(User).order_by(ResponseHistory.created_at.desc()).limit(100)
            
            history_records = history_query.all()
            
            # Estatísticas do histórico
            total_responses = ResponseHistory.query.count()
            auto_count = ResponseHistory.query.filter_by(response_type='auto').count()
            absence_count = ResponseHistory.query.filter_by(response_type='absence').count()
            manual_count = ResponseHistory.query.filter_by(response_type='manual').count()
            
            avg_time = db.session.query(db.func.avg(ResponseHistory.response_time)).scalar()
            avg_time = round(avg_time, 2) if avg_time else 0
            
            content = create_header("📊 Histórico de Respostas", "Análise detalhada das respostas enviadas")
            content += create_navigation("history")
            
            # Estatísticas do histórico
            content += '<div class="stats">'
            content += create_stat_card(total_responses, "Total de Respostas")
            content += create_stat_card(auto_count, "Automáticas", "#28a745")
            content += create_stat_card(absence_count, "Ausência", "#ffc107")
            content += create_stat_card(manual_count, "Manuais", "#6c757d")
            content += create_stat_card(f"{avg_time}s", "Tempo Médio")
            content += '</div>'
            
            # Tabela de histórico
            content += """
            <div class="card">
                <h3>📋 Últimas 100 Respostas</h3>
                <table class="table">
                    <thead>
                        <tr>
                            <th>Data/Hora</th>
                            <th>Pergunta</th>
                            <th>Tipo</th>
                            <th>Palavras-chave</th>
                            <th>Tempo</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            
            for history, question, user in history_records:
                local_time = format_local_time(history.created_at)
                time_str = local_time.strftime("%d/%m %H:%M") if local_time else "N/A"
                
                type_colors = {
                    'auto': '#28a745',
                    'absence': '#ffc107',
                    'manual': '#6c757d'
                }
                
                type_labels = {
                    'auto': '🤖 Automática',
                    'absence': '🌙 Ausência',
                    'manual': '👤 Manual'
                }
                
                type_color = type_colors.get(history.response_type, '#6c757d')
                type_label = type_labels.get(history.response_type, history.response_type)
                
                keywords = history.keywords_matched or "-"
                response_time = f"{history.response_time:.2f}s" if history.response_time else "-"
                
                content += f"""
                <tr>
                    <td>{time_str}</td>
                    <td>{question.question_text[:40]}...</td>
                    <td style="color: {type_color}; font-weight: bold;">{type_label}</td>
                    <td>{keywords}</td>
                    <td>{response_time}</td>
                </tr>
                """
            
            content += """
                    </tbody>
                </table>
            </div>
            """
            
            return create_base_template("Histórico", content)
            
    except Exception as e:
        add_debug_log(f"❌ Erro na página de histórico: {e}")
        error_content = create_header("❌ Erro no Histórico")
        error_content += create_navigation("history")
        error_content += f"""
        <div class="card">
            <div class="alert alert-danger">
                <h4>Erro ao carregar histórico</h4>
                <p>Erro: {e}</p>
            </div>
            <a href="/" class="btn">← Voltar ao Dashboard</a>
        </div>
        """
        return create_base_template("Erro", error_content)


# ========== SISTEMA DE DEBUG E PÁGINAS DE EDIÇÃO ==========

@app.route('/debug-full')
def debug_full():
    """Página com todos os logs de debug"""
    all_logs = get_debug_logs()
    current_time = get_local_time().strftime("%H:%M:%S")
    
    content = create_header("🔍 Debug Completo", f"Logs detalhados do sistema - {current_time}")
    content += create_navigation("debug-full")
    
    content += f"""
    <div class="card">
        <h3>📋 Todos os Logs de Debug</h3>
        <p><strong>Total de logs:</strong> {len(all_logs)}</p>
        <button class="btn btn-warning" onclick="clearLogs()">🗑️ Limpar Logs</button>
        <button class="btn" onclick="refreshPage()">🔄 Atualizar</button>
        
        <div style="background: #000; color: #0f0; padding: 15px; border-radius: 4px; font-family: monospace; font-size: 12px; max-height: 600px; overflow-y: auto; margin-top: 20px;">
    """
    
    for log in all_logs:
        content += f'<div style="margin-bottom: 2px;">{log}</div>'
    
    content += """
        </div>
    </div>
    
    <script>
        function clearLogs() {
            fetch('/api/debug/clear-logs', {method: 'POST'})
            .then(() => window.location.reload());
        }
        function refreshPage() { window.location.reload(); }
        setInterval(refreshPage, 15000); // Atualizar a cada 15 segundos
    </script>
    """
    
    return create_base_template("Debug Completo", content)

@app.route('/api/debug/clear-logs', methods=['POST'])
def api_clear_logs():
    """API para limpar logs de debug"""
    clear_debug_logs()
    return jsonify({"message": "Logs limpos com sucesso"})

@app.route('/api/debug/logs')
def api_get_logs():
    """API para obter logs de debug"""
    limit = request.args.get('limit', type=int)
    logs = get_debug_logs(limit)
    return jsonify({"logs": logs, "total": len(DEBUG_LOGS)})

# ========== PÁGINA DE EDIÇÃO DE REGRAS ==========
@app.route('/edit-rules')
def edit_rules_page():
    """Página para editar regras de resposta automática"""
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return redirect('/')
            
            rules = AutoResponse.query.filter_by(user_id=user.id).all()
            
            content = create_header("✏️ Editar Regras", "Gerenciar respostas automáticas por palavras-chave")
            content += create_navigation("edit-rules")
            
            # Formulário para nova regra
            content += """
            <div class="card">
                <h3>➕ Adicionar Nova Regra</h3>
                <form id="rule-form">
                    <div class="form-group">
                        <label for="keywords">Palavras-chave (separadas por vírgula):</label>
                        <input type="text" id="keywords" name="keywords" placeholder="preço, valor, quanto custa" required>
                    </div>
                    <div class="form-group">
                        <label for="response">Resposta automática:</label>
                        <textarea id="response" name="response" rows="3" placeholder="Digite a resposta que será enviada..." required></textarea>
                    </div>
                    <button type="submit" class="btn btn-success">💾 Salvar Regra</button>
                </form>
            </div>
            """
            
            # Lista de regras existentes
            content += """
            <div class="card">
                <h3>📋 Regras Existentes</h3>
                <table class="table">
                    <thead>
                        <tr>
                            <th>Palavras-chave</th>
                            <th>Resposta</th>
                            <th>Status</th>
                            <th>Ações</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            
            for rule in rules:
                status_color = "#28a745" if rule.is_active else "#dc3545"
                status_text = "✅ Ativa" if rule.is_active else "❌ Inativa"
                
                content += f"""
                <tr>
                    <td>{rule.keywords}</td>
                    <td>{rule.response_text[:50]}...</td>
                    <td style="color: {status_color}; font-weight: bold;">{status_text}</td>
                    <td>
                        <button class="btn btn-warning" onclick="toggleRule({rule.id})">
                            {'🔴 Desativar' if rule.is_active else '🟢 Ativar'}
                        </button>
                        <button class="btn btn-danger" onclick="deleteRule({rule.id})">🗑️ Excluir</button>
                    </td>
                </tr>
                """
            
            content += """
                    </tbody>
                </table>
            </div>
            
            <script>
                document.getElementById('rule-form').addEventListener('submit', async function(e) {
                    e.preventDefault();
                    
                    const keywords = document.getElementById('keywords').value;
                    const response = document.getElementById('response').value;
                    
                    try {
                        const result = await fetch('/api/rules', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({keywords: keywords, response: response})
                        });
                        
                        if (result.ok) {
                            alert('Regra salva com sucesso!');
                            window.location.reload();
                        } else {
                            alert('Erro ao salvar regra');
                        }
                    } catch (error) {
                        alert('Erro de conexão');
                    }
                });
                
                async function toggleRule(id) {
                    try {
                        const result = await fetch(`/api/rules/${id}/toggle`, {method: 'POST'});
                        if (result.ok) {
                            window.location.reload();
                        } else {
                            alert('Erro ao alterar status');
                        }
                    } catch (error) {
                        alert('Erro de conexão');
                    }
                }
                
                async function deleteRule(id) {
                    if (confirm('Tem certeza que deseja excluir esta regra?')) {
                        try {
                            const result = await fetch(`/api/rules/${id}`, {method: 'DELETE'});
                            if (result.ok) {
                                window.location.reload();
                            } else {
                                alert('Erro ao excluir regra');
                            }
                        } catch (error) {
                            alert('Erro de conexão');
                        }
                    }
                }
            </script>
            """
            
            return create_base_template("Editar Regras", content)
            
    except Exception as e:
        add_debug_log(f"❌ Erro na página de regras: {e}")
        return redirect('/')

# ========== PÁGINA DE EDIÇÃO DE AUSÊNCIA ==========
@app.route('/edit-absence')
def edit_absence_page():
    """Página para editar configurações de ausência"""
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return redirect('/')
            
            configs = AbsenceConfig.query.filter_by(user_id=user.id).all()
            
            content = create_header("🌙 Configurar Ausência", "Gerenciar mensagens automáticas por horário")
            content += create_navigation("edit-absence")
            
            # Formulário para nova configuração
            content += """
            <div class="card">
                <h3>➕ Adicionar Configuração de Ausência</h3>
                <form id="absence-form">
                    <div class="form-group">
                        <label for="name">Nome da configuração:</label>
                        <input type="text" id="name" name="name" placeholder="Ex: Horário Comercial" required>
                    </div>
                    <div class="form-group">
                        <label for="message">Mensagem de ausência:</label>
                        <textarea id="message" name="message" rows="3" placeholder="Digite a mensagem que será enviada..." required></textarea>
                    </div>
                    <div class="form-group">
                        <label for="start_time">Horário de início:</label>
                        <input type="time" id="start_time" name="start_time" required>
                    </div>
                    <div class="form-group">
                        <label for="end_time">Horário de fim:</label>
                        <input type="time" id="end_time" name="end_time" required>
                    </div>
                    <div class="form-group">
                        <label for="days">Dias da semana:</label>
                        <div style="display: flex; flex-wrap: wrap; gap: 10px;">
                            <label><input type="checkbox" name="days" value="0"> Segunda</label>
                            <label><input type="checkbox" name="days" value="1"> Terça</label>
                            <label><input type="checkbox" name="days" value="2"> Quarta</label>
                            <label><input type="checkbox" name="days" value="3"> Quinta</label>
                            <label><input type="checkbox" name="days" value="4"> Sexta</label>
                            <label><input type="checkbox" name="days" value="5"> Sábado</label>
                            <label><input type="checkbox" name="days" value="6"> Domingo</label>
                        </div>
                    </div>
                    <button type="submit" class="btn btn-success">💾 Salvar Configuração</button>
                </form>
            </div>
            """
            
            # Lista de configurações existentes
            content += """
            <div class="card">
                <h3>📋 Configurações Existentes</h3>
                <table class="table">
                    <thead>
                        <tr>
                            <th>Nome</th>
                            <th>Horário</th>
                            <th>Dias</th>
                            <th>Status</th>
                            <th>Ações</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            
            days_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
            
            for config in configs:
                status_color = "#28a745" if config.is_active else "#dc3545"
                status_text = "✅ Ativa" if config.is_active else "❌ Inativa"
                
                days_list = [days_names[int(d)] for d in config.days_of_week.split(',') if d.isdigit() and int(d) < 7]
                days_str = ", ".join(days_list)
                
                content += f"""
                <tr>
                    <td>{config.name}</td>
                    <td>{config.start_time} - {config.end_time}</td>
                    <td>{days_str}</td>
                    <td style="color: {status_color}; font-weight: bold;">{status_text}</td>
                    <td>
                        <button class="btn btn-warning" onclick="toggleAbsence({config.id})">
                            {'🔴 Desativar' if config.is_active else '🟢 Ativar'}
                        </button>
                        <button class="btn btn-danger" onclick="deleteAbsence({config.id})">🗑️ Excluir</button>
                    </td>
                </tr>
                """
            
            content += """
                    </tbody>
                </table>
            </div>
            
            <script>
                document.getElementById('absence-form').addEventListener('submit', async function(e) {
                    e.preventDefault();
                    
                    const name = document.getElementById('name').value;
                    const message = document.getElementById('message').value;
                    const start_time = document.getElementById('start_time').value;
                    const end_time = document.getElementById('end_time').value;
                    
                    const selectedDays = Array.from(document.querySelectorAll('input[name="days"]:checked'))
                        .map(cb => cb.value);
                    
                    if (selectedDays.length === 0) {
                        alert('Selecione pelo menos um dia da semana');
                        return;
                    }
                    
                    try {
                        const result = await fetch('/api/absence', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                name: name,
                                message: message,
                                start_time: start_time,
                                end_time: end_time,
                                days_of_week: selectedDays.join(',')
                            })
                        });
                        
                        if (result.ok) {
                            alert('Configuração salva com sucesso!');
                            window.location.reload();
                        } else {
                            alert('Erro ao salvar configuração');
                        }
                    } catch (error) {
                        alert('Erro de conexão');
                    }
                });
                
                async function toggleAbsence(id) {
                    try {
                        const result = await fetch(`/api/absence/${id}/toggle`, {method: 'POST'});
                        if (result.ok) {
                            window.location.reload();
                        } else {
                            alert('Erro ao alterar status');
                        }
                    } catch (error) {
                        alert('Erro de conexão');
                    }
                }
                
                async function deleteAbsence(id) {
                    if (confirm('Tem certeza que deseja excluir esta configuração?')) {
                        try {
                            const result = await fetch(`/api/absence/${id}`, {method: 'DELETE'});
                            if (result.ok) {
                                window.location.reload();
                            } else {
                                alert('Erro ao excluir configuração');
                            }
                        } catch (error) {
                            alert('Erro de conexão');
                        }
                    }
                }
            </script>
            """
            
            return create_base_template("Configurar Ausência", content)
            
    except Exception as e:
        add_debug_log(f"❌ Erro na página de ausência: {e}")
        return redirect('/')

# ========== APIs PARA GERENCIAMENTO ==========

@app.route('/api/rules', methods=['POST'])
def api_create_rule():
    """API para criar nova regra"""
    try:
        data = request.get_json()
        
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return jsonify({"error": "Usuário não encontrado"}), 404
            
            rule = AutoResponse(
                user_id=user.id,
                keywords=data['keywords'],
                response_text=data['response'],
                is_active=True
            )
            
            db.session.add(rule)
            db.session.commit()
            
            add_debug_log(f"✅ Nova regra criada: {data['keywords']}")
            return jsonify({"message": "Regra criada com sucesso"})
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao criar regra: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/rules/<int:rule_id>/toggle', methods=['POST'])
def api_toggle_rule(rule_id):
    """API para ativar/desativar regra"""
    try:
        with app.app_context():
            rule = AutoResponse.query.get(rule_id)
            if not rule:
                return jsonify({"error": "Regra não encontrada"}), 404
            
            rule.is_active = not rule.is_active
            rule.updated_at = get_local_time_utc()
            db.session.commit()
            
            status = "ativada" if rule.is_active else "desativada"
            add_debug_log(f"🔄 Regra {rule_id} {status}")
            return jsonify({"message": f"Regra {status} com sucesso"})
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao alterar regra: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/rules/<int:rule_id>', methods=['DELETE'])
def api_delete_rule(rule_id):
    """API para excluir regra"""
    try:
        with app.app_context():
            rule = AutoResponse.query.get(rule_id)
            if not rule:
                return jsonify({"error": "Regra não encontrada"}), 404
            
            db.session.delete(rule)
            db.session.commit()
            
            add_debug_log(f"🗑️ Regra {rule_id} excluída")
            return jsonify({"message": "Regra excluída com sucesso"})
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao excluir regra: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/absence', methods=['POST'])
def api_create_absence():
    """API para criar configuração de ausência"""
    try:
        data = request.get_json()
        
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return jsonify({"error": "Usuário não encontrado"}), 404
            
            config = AbsenceConfig(
                user_id=user.id,
                name=data['name'],
                message=data['message'],
                start_time=data['start_time'],
                end_time=data['end_time'],
                days_of_week=data['days_of_week'],
                is_active=True
            )
            
            db.session.add(config)
            db.session.commit()
            
            add_debug_log(f"✅ Nova configuração de ausência: {data['name']}")
            return jsonify({"message": "Configuração criada com sucesso"})
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao criar configuração: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/absence/<int:config_id>/toggle', methods=['POST'])
def api_toggle_absence(config_id):
    """API para ativar/desativar configuração de ausência"""
    try:
        with app.app_context():
            config = AbsenceConfig.query.get(config_id)
            if not config:
                return jsonify({"error": "Configuração não encontrada"}), 404
            
            config.is_active = not config.is_active
            db.session.commit()
            
            status = "ativada" if config.is_active else "desativada"
            add_debug_log(f"🔄 Configuração {config_id} {status}")
            return jsonify({"message": f"Configuração {status} com sucesso"})
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao alterar configuração: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/absence/<int:config_id>', methods=['DELETE'])
def api_delete_absence(config_id):
    """API para excluir configuração de ausência"""
    try:
        with app.app_context():
            config = AbsenceConfig.query.get(config_id)
            if not config:
                return jsonify({"error": "Configuração não encontrada"}), 404
            
            db.session.delete(config)
            db.session.commit()
            
            add_debug_log(f"🗑️ Configuração {config_id} excluída")
            return jsonify({"message": "Configuração excluída com sucesso"})
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao excluir configuração: {e}")
        return jsonify({"error": str(e)}), 500

# ========== APIs DE CONTROLE DE RENOVAÇÃO AUTOMÁTICA ==========

@app.route('/api/tokens/status', methods=['GET'])
def api_token_status():
    """API para obter status detalhado do token e renovação automática"""
    try:
        # Status do token via API ML
        token_valid = True
        token_message = "Token válido"
        user_info = None
        
        try:
            url = "https://api.mercadolibre.com/users/me"
            headers = {"Authorization": f"Bearer {ML_ACCESS_TOKEN}"}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                user_info = response.json()
                token_message = f"Conectado como {user_info.get('nickname', 'N/A')}"
            else:
                token_valid = False
                token_message = f"Erro {response.status_code}"
        except:
            token_valid = False
            token_message = "Erro de conexão"
        
        # Status da renovação automática
        refresh_status = auto_refresh_manager.get_token_status()
        
        return jsonify({
            "success": True,
            "token": {
                "valid": token_valid,
                "message": token_message,
                "access_token": ML_ACCESS_TOKEN[:20] + "..." if ML_ACCESS_TOKEN else "N/A",
                "user_id": ML_USER_ID,
                "user_info": user_info
            },
            "auto_refresh": refresh_status,
            "timestamp": get_local_time().isoformat()
        })
        
    except Exception as e:
        add_debug_log(f"❌ Erro ao obter status do token: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tokens/toggle-auto-refresh', methods=['POST'])
def api_toggle_auto_refresh():
    """API para habilitar/desabilitar renovação automática"""
    try:
        current_status = auto_refresh_manager.auto_refresh_enabled
        
        if current_status:
            auto_refresh_manager.disable_auto_refresh()
            message = "Auto-renovação desabilitada"
            add_debug_log("🛑 Auto-renovação desabilitada via API")
        else:
            auto_refresh_manager.enable_auto_refresh()
            # Tentar inicializar se temos refresh token
            if ML_REFRESH_TOKEN:
                initialize_auto_refresh()
            message = "Auto-renovação habilitada"
            add_debug_log("🚀 Auto-renovação habilitada via API")
        
        return jsonify({
            "success": True,
            "message": message,
            "auto_refresh_enabled": auto_refresh_manager.auto_refresh_enabled
        })
        
    except Exception as e:
        add_debug_log(f"❌ Erro ao alterar auto-renovação: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tokens/force-refresh', methods=['POST'])
def api_force_refresh():
    """API para forçar renovação imediata do token"""
    try:
        add_debug_log("🔄 Renovação forçada via API iniciada...")
        
        # Verificar se já está renovando
        if auto_refresh_manager.is_refreshing:
            return jsonify({
                "success": False,
                "error": "Renovação já em andamento"
            }), 400
        
        # Executar renovação
        success, result = auto_refresh_manager.process_refresh_token_internal()
        
        if success:
            # Atualizar tokens no sistema
            auto_refresh_manager.update_system_tokens_internal(
                result['access_token'],
                result['refresh_token'],
                result['user_id']
            )
            
            # Reiniciar auto-renovação com novo token
            auto_refresh_manager.start_auto_refresh(result.get('expires_in', 21600))
            
            add_debug_log("✅ Renovação forçada concluída com sucesso")
            
            return jsonify({
                "success": True,
                "message": "Token renovado com sucesso",
                "token_info": {
                    "access_token": result['access_token'][:20] + "...",
                    "user_id": result['user_id'],
                    "expires_in": result.get('expires_in', 21600)
                }
            })
        else:
            add_debug_log(f"❌ Falha na renovação forçada: {result.get('error', 'Erro desconhecido')}")
            return jsonify({
                "success": False,
                "error": result.get('error', 'Erro na renovação')
            }), 400
            
    except Exception as e:
        add_debug_log(f"❌ Erro na renovação forçada: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tokens/refresh-info', methods=['GET'])
def api_refresh_info():
    """API para obter informações detalhadas sobre renovação"""
    try:
        status = auto_refresh_manager.get_token_status()
        
        # Informações adicionais
        info = {
            "refresh_interval_hours": auto_refresh_manager.refresh_interval / 3600,
            "has_refresh_token": bool(ML_REFRESH_TOKEN),
            "system_time": get_local_time().isoformat(),
            "uptime_seconds": time.time() - (auto_refresh_manager.token_created_at or time.time())
        }
        
        return jsonify({
            "success": True,
            "status": status,
            "info": info
        })
        
    except Exception as e:
        add_debug_log(f"❌ Erro ao obter info de renovação: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ========== INICIALIZAÇÃO E MONITORAMENTO DO SISTEMA ==========

def start_background_tasks():
    """Inicia todas as tarefas em background do sistema"""
    add_debug_log("🚀 Iniciando sistema Bot ML completo...")
    
    try:
        # Inicializar banco de dados
        initialize_database()
        
        # Criar dados padrão se necessário
        create_default_data()
        
        # Inicializar sistema de renovação automática
        if ML_REFRESH_TOKEN:
            initialize_auto_refresh()
            add_debug_log("🔄 Sistema de renovação automática inicializado")
        else:
            add_debug_log("⚠️ Refresh token não disponível - renovação automática não iniciada")
        
        # Iniciar monitoramento de perguntas em thread separada
        monitor_thread = threading.Thread(target=monitor_questions, daemon=True)
        monitor_thread.start()
        add_debug_log("✅ Thread de monitoramento iniciada")
        
        add_debug_log("✅ Sistema Bot ML iniciado com sucesso!")
        add_debug_log("🔍 Debug ativo - todos os logs serão registrados")
        add_debug_log("🤖 Monitoramento de perguntas ativo (30s)")
        add_debug_log("🌙 Sistema de ausência configurado")
        add_debug_log("🔄 Renovação manual de tokens disponível")
        add_debug_log("🔄 Renovação automática de tokens ativa (5h)")
        add_debug_log("📊 Interface web completa disponível")
        
    except Exception as e:
        add_debug_log(f"❌ Erro crítico na inicialização: {e}")
        print(f"❌ ERRO CRÍTICO: {e}")

# ========== ROTA DE STATUS PARA MONITORAMENTO ==========
@app.route('/status')
def status():
    """Endpoint de status para monitoramento externo"""
    try:
        # Verificar banco de dados
        with app.app_context():
            user_count = User.query.count()
            question_count = Question.query.count()
            rule_count = AutoResponse.query.filter_by(is_active=True).count()
            absence_count = AbsenceConfig.query.filter_by(is_active=True).count()
        
        # Verificar token
        token_valid = True
        try:
            url = "https://api.mercadolibre.com/users/me"
            headers = {"Authorization": f"Bearer {ML_ACCESS_TOKEN}"}
            response = requests.get(url, headers=headers, timeout=5)
            token_valid = response.status_code == 200
        except:
            token_valid = False
        
        status_data = {
            "status": "ok",
            "timestamp": get_local_time().isoformat(),
            "database": {
                "users": user_count,
                "questions": question_count,
                "active_rules": rule_count,
                "active_absence_configs": absence_count
            },
            "token": {
                "valid": token_valid,
                "user_id": ML_USER_ID
            },
            "system": {
                "data_dir": DATA_DIR,
                "debug_logs": len(DEBUG_LOGS),
                "initialized": _initialized
            }
        }
        
        return jsonify(status_data)
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": get_local_time().isoformat()
        }), 500

# ========== ROTA DE SAÚDE PARA RENDER ==========
@app.route('/health')
def health():
    """Endpoint de saúde para o Render"""
    return jsonify({
        "status": "healthy",
        "timestamp": get_local_time().isoformat(),
        "service": "bot-mercadolivre"
    })

# ========== TRATAMENTO DE ERROS ==========
@app.errorhandler(404)
def not_found(error):
    """Página de erro 404 personalizada"""
    content = create_header("❌ Página Não Encontrada")
    content += """
    <div class="card">
        <div class="alert alert-warning">
            <h4>Página não encontrada</h4>
            <p>A página que você está procurando não existe.</p>
        </div>
        <a href="/" class="btn">🏠 Voltar ao Dashboard</a>
    </div>
    """
    return create_base_template("Erro 404", content), 404

@app.errorhandler(500)
def internal_error(error):
    """Página de erro 500 personalizada"""
    content = create_header("❌ Erro Interno")
    content += """
    <div class="card">
        <div class="alert alert-danger">
            <h4>Erro interno do servidor</h4>
            <p>Ocorreu um erro interno. Tente novamente em alguns instantes.</p>
        </div>
        <a href="/" class="btn">🏠 Voltar ao Dashboard</a>
        <a href="/debug-full" class="btn btn-warning">🔍 Ver Logs</a>
    </div>
    """
    return create_base_template("Erro 500", content), 500

# ========== FUNÇÃO PRINCIPAL ==========
if __name__ == '__main__':
    print("=" * 60)
    print("🤖 BOT DO MERCADO LIVRE - SISTEMA COMPLETO FUNCIONAL")
    print("=" * 60)
    print(f"📅 Data: {get_local_time().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"📁 Dados: {DATA_DIR}")
    print(f"🗄️ Banco: {DATABASE_PATH}")
    print(f"🔑 Token: {ML_ACCESS_TOKEN[:20]}...")
    print(f"👤 User ID: {ML_USER_ID}")
    print("=" * 60)
    print()
    print("FUNCIONALIDADES INTEGRADAS:")
    print("✅ Sistema de ausência e regras automáticas")
    print("✅ Renovação manual de tokens com interface web")
    print("✅ Layout minimalista e responsivo")
    print("✅ Histórico detalhado de respostas")
    print("✅ Debug e logs em tempo real")
    print("✅ Configuração de dados persistentes")
    print("✅ Fuso horário São Paulo (UTC-3)")
    print("✅ Interface web completa")
    print("✅ APIs REST para gerenciamento")
    print("✅ Monitoramento contínuo")
    print("✅ Webhook do Mercado Livre")
    print()
    print("PÁGINAS DISPONÍVEIS:")
    print("🏠 / - Dashboard principal")
    print("✏️ /edit-rules - Editar regras")
    print("🌙 /edit-absence - Configurar ausência")
    print("📊 /history - Histórico de respostas")
    print("🔄 /renovar-tokens - Renovar tokens")
    print("🔍 /debug-full - Debug completo")
    print("📊 /status - Status do sistema")
    print("❤️ /health - Saúde do serviço")
    print()
    print("WEBHOOK:")
    print("📨 /api/ml/webhook - Receber notificações do ML")
    print()
    
    # Inicializar sistema
    start_background_tasks()
    
    print("🚀 Iniciando servidor Flask...")
    print("🌐 Acesse: http://localhost:5000")
    print("=" * 60)
    
    # Iniciar servidor Flask
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=True
    )

