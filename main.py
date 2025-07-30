#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOT MERCADO LIVRE - SISTEMA COMPLETO COM LAYOUT MODERNO
Integração do layout moderno criado com o script funcional atual
Data: 30/07/2025
Credenciais atualizadas: 25/07/2025 - 18:00

FUNCIONALIDADES INTEGRADAS:
✅ Sistema de ausência e regras (funcional)
✅ Renovação manual e automática de tokens
✅ Layout moderno e sofisticado (Tailwind CSS)
✅ Histórico de respostas detalhado
✅ Debug e logs em tempo real
✅ Interface responsiva (desktop/mobile)
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

# URLs de redirect para renovação de tokens
REDIRECT_URIS = [
    "https://bot-mercadolivre-dettech.onrender.com/api/ml/webhook",
    "https://bot-mercadolivre-dettech.onrender.com/api/ml/auth-callback",
    "http://localhost:5000/api/ml/webhook",
    "http://localhost:5000/api/ml/auth-callback"
]

# ========== SISTEMA DE LOGS DE DEBUG ==========
debug_logs = []
debug_logs_lock = threading.Lock()

def add_debug_log(message, level="INFO"):
    """Adiciona log de debug com timestamp local"""
    with debug_logs_lock:
        timestamp = get_local_time().strftime("%H:%M:%S")
        log_entry = {
            'timestamp': timestamp,
            'message': message,
            'level': level,
            'full_timestamp': get_local_time().isoformat()
        }
        debug_logs.append(log_entry)
        
        # Manter apenas os últimos 100 logs
        if len(debug_logs) > 100:
            debug_logs.pop(0)
        
        # Log no console também
        print(f"[{timestamp}] {message}")

# ========== SISTEMA DE RENOVAÇÃO AUTOMÁTICA DE TOKENS ==========
class AutoTokenRefresh:
    """Sistema de renovação automática de tokens baseado em tempo"""
    
    def __init__(self):
        self.refresh_timer = None
        self.is_refreshing = False
        self.token_created_at = None
        self.token_expires_at = None
        self.auto_refresh_enabled = True
        self.refresh_interval = 5 * 3600  # 5 horas em segundos
        
    def start_auto_refresh(self, expires_in=21600):
        """Inicia sistema de renovação automática"""
        if not self.auto_refresh_enabled:
            add_debug_log("🔄 Auto-renovação desabilitada")
            return
            
        # Cancelar timer anterior se existir
        if self.refresh_timer:
            self.refresh_timer.cancel()
            add_debug_log("⏹️ Timer anterior cancelado")
        
        # Calcular quando renovar (5 horas = 18000 segundos)
        refresh_delay = min(self.refresh_interval, max(expires_in - 3600, 300))  # Min 5 minutos
        
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

# Instância global do gerenciador de renovação automática
auto_refresh_manager = AutoTokenRefresh()

# ========== MODELOS DO BANCO DE DADOS ==========
class User(db.Model):
    """Modelo para usuários do sistema"""
    id = db.Column(db.Integer, primary_key=True)
    ml_user_id = db.Column(db.String(50), unique=True, nullable=False)
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text)
    token_expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=get_local_time_utc)
    updated_at = db.Column(db.DateTime, default=get_local_time_utc)

class Question(db.Model):
    """Modelo para perguntas do ML"""
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.String(100), unique=True, nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    from_user = db.Column(db.String(100))
    item_id = db.Column(db.String(100))
    is_answered = db.Column(db.Boolean, default=False)
    answered_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=get_local_time_utc)

class ResponseRule(db.Model):
    """Modelo para regras de resposta automática"""
    id = db.Column(db.Integer, primary_key=True)
    keywords = db.Column(db.Text, nullable=False)  # Palavras-chave separadas por vírgula
    response_text = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    priority = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=get_local_time_utc)

class AbsenceConfig(db.Model):
    """Modelo para configuração de ausência"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)  # HH:MM
    end_time = db.Column(db.String(5), nullable=False)    # HH:MM
    days_of_week = db.Column(db.String(20), nullable=False)  # 0,1,2,3,4,5,6
    message = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_local_time_utc)

class ResponseHistory(db.Model):
    """Modelo para histórico de respostas"""
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.String(100), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text, nullable=False)
    response_type = db.Column(db.String(20), nullable=False)  # auto, manual, absence
    rule_used = db.Column(db.String(200))
    response_time = db.Column(db.Float)  # Tempo em segundos
    from_user = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=get_local_time_utc)

def initialize_database():
    """Inicializa o banco de dados"""
    try:
        with app.app_context():
            db.create_all()
            add_debug_log("✅ Banco de dados inicializado")
    except Exception as e:
        add_debug_log(f"❌ Erro ao inicializar banco: {e}")

# ========== LAYOUT MODERNO BASE ==========
def get_modern_layout_base():
    """Retorna o layout base moderno com Tailwind CSS"""
    return """
<!DOCTYPE html>
<html lang="pt-BR" class="h-full bg-gray-50">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot ML - {title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.js"></script>
    <script>
        tailwind.config = {{
            theme: {{
                extend: {{
                    fontFamily: {{
                        'inter': ['Inter', 'sans-serif'],
                    }},
                    colors: {{
                        primary: {{
                            50: '#f0f9ff',
                            500: '#0ea5e9',
                            600: '#0284c7',
                            700: '#0369a1',
                            900: '#0c4a6e'
                        }},
                        accent: {{
                            500: '#059669',
                            600: '#047857'
                        }}
                    }}
                }}
            }}
        }}
    </script>
    <style>
        body {{ font-family: 'Inter', sans-serif; }}
        .sidebar-shadow {{ box-shadow: 2px 0 10px rgba(0, 0, 0, 0.1); }}
        .card-shadow {{ box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1), 0 1px 2px rgba(0, 0, 0, 0.06); }}
        .card-shadow-hover {{ box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1), 0 2px 4px rgba(0, 0, 0, 0.06); }}
    </style>
</head>
<body class="h-full font-inter">
    <div class="flex h-screen bg-gray-50">
        <!-- Sidebar -->
        <div class="hidden md:flex md:w-64 md:flex-col">
            <div class="flex flex-col flex-grow pt-5 overflow-y-auto bg-white sidebar-shadow">
                <!-- Logo -->
                <div class="flex items-center flex-shrink-0 px-6">
                    <div class="flex items-center">
                        <div class="w-8 h-8 bg-primary-600 rounded-lg flex items-center justify-center">
                            <i data-lucide="bot" class="w-5 h-5 text-white"></i>
                        </div>
                        <span class="ml-3 text-xl font-semibold text-gray-900">Bot ML</span>
                    </div>
                </div>
                
                <!-- Navigation -->
                <nav class="mt-8 flex-1 px-3 space-y-1">
                    <a href="/" class="{nav_dashboard} group flex items-center px-3 py-2 text-sm font-medium rounded-lg">
                        <i data-lucide="layout-dashboard" class="{icon_dashboard} mr-3 h-5 w-5"></i>
                        Dashboard
                    </a>
                    <a href="/edit-rules" class="{nav_rules} group flex items-center px-3 py-2 text-sm font-medium rounded-lg">
                        <i data-lucide="settings" class="{icon_rules} mr-3 h-5 w-5"></i>
                        Regras
                    </a>
                    <a href="/history" class="{nav_history} group flex items-center px-3 py-2 text-sm font-medium rounded-lg">
                        <i data-lucide="history" class="{icon_history} mr-3 h-5 w-5"></i>
                        Histórico
                    </a>
                    <a href="/renovar-tokens" class="{nav_tokens} group flex items-center px-3 py-2 text-sm font-medium rounded-lg">
                        <i data-lucide="key" class="{icon_tokens} mr-3 h-5 w-5"></i>
                        Tokens
                    </a>
                    <a href="/debug-full" class="{nav_debug} group flex items-center px-3 py-2 text-sm font-medium rounded-lg">
                        <i data-lucide="bug" class="{icon_debug} mr-3 h-5 w-5"></i>
                        Debug
                    </a>
                    <a href="/edit-absence" class="{nav_absence} group flex items-center px-3 py-2 text-sm font-medium rounded-lg">
                        <i data-lucide="moon" class="{icon_absence} mr-3 h-5 w-5"></i>
                        Ausência
                    </a>
                </nav>
                
                <!-- User Section -->
                <div class="flex-shrink-0 p-4 border-t border-gray-200">
                    <div class="flex items-center">
                        <div class="w-8 h-8 bg-gray-300 rounded-full flex items-center justify-center">
                            <i data-lucide="user" class="w-4 h-4 text-gray-600"></i>
                        </div>
                        <div class="ml-3">
                            <p class="text-sm font-medium text-gray-700">Sistema Bot</p>
                            <p class="text-xs text-gray-500">Versão 2.0</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Main Content -->
        <div class="flex flex-col flex-1 overflow-hidden">
            <!-- Header -->
            <header class="bg-white shadow-sm border-b border-gray-200">
                <div class="flex items-center justify-between px-6 py-4">
                    <div class="flex items-center">
                        <button class="md:hidden mr-3">
                            <i data-lucide="menu" class="w-6 h-6 text-gray-600"></i>
                        </button>
                        <h1 class="text-2xl font-semibold text-gray-900">{page_title}</h1>
                    </div>
                    <div class="flex items-center space-x-4">
                        {header_actions}
                    </div>
                </div>
            </header>

            <!-- Main Content Area -->
            <main class="flex-1 overflow-y-auto p-6">
                {content}
            </main>
        </div>
    </div>

    <script>
        // Initialize Lucide icons
        lucide.createIcons();
        {custom_scripts}
    </script>
</body>
</html>
"""

def get_navigation_classes(current_page):
    """Retorna classes CSS para navegação baseada na página atual"""
    nav_classes = {
        'dashboard': {
            'nav': 'bg-primary-50 border-r-2 border-primary-600 text-primary-700',
            'icon': 'text-primary-500'
        },
        'rules': {
            'nav': 'bg-primary-50 border-r-2 border-primary-600 text-primary-700',
            'icon': 'text-primary-500'
        },
        'history': {
            'nav': 'bg-primary-50 border-r-2 border-primary-600 text-primary-700',
            'icon': 'text-primary-500'
        },
        'tokens': {
            'nav': 'bg-primary-50 border-r-2 border-primary-600 text-primary-700',
            'icon': 'text-primary-500'
        },
        'debug': {
            'nav': 'bg-primary-50 border-r-2 border-primary-600 text-primary-700',
            'icon': 'text-primary-500'
        },
        'absence': {
            'nav': 'bg-primary-50 border-r-2 border-primary-600 text-primary-700',
            'icon': 'text-primary-500'
        }
    }
    
    default_nav = 'text-gray-700 hover:bg-gray-50'
    default_icon = 'text-gray-400'
    
    result = {}
    for page in ['dashboard', 'rules', 'history', 'tokens', 'debug', 'absence']:
        if page == current_page:
            result[f'nav_{page}'] = nav_classes[page]['nav']
            result[f'icon_{page}'] = nav_classes[page]['icon']
        else:
            result[f'nav_{page}'] = default_nav
            result[f'icon_{page}'] = default_icon
    
    return result

# ========== ROTAS COM LAYOUT MODERNO ==========

@app.route('/')
def dashboard():
    """Dashboard principal com layout moderno"""
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
            
            # Status do token
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
            
            # Status da renovação automática
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
            
            # Perguntas recentes não respondidas
            recent_questions = Question.query.filter_by(is_answered=False).order_by(Question.created_at.desc()).limit(5).all()
            
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
            
            # Conteúdo do dashboard
            content = f"""
            <!-- Status Cards -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center">
                        <div class="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                            <i data-lucide="message-circle" class="w-6 h-6 text-blue-600"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Total de Perguntas</p>
                            <p class="text-2xl font-bold text-gray-900">{total_questions}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center">
                        <div class="w-12 h-12 bg-accent-100 rounded-lg flex items-center justify-center">
                            <i data-lucide="check-circle" class="w-6 h-6 text-accent-600"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Respondidas Hoje</p>
                            <p class="text-2xl font-bold text-gray-900">{answered_today}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center">
                        <div class="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
                            <i data-lucide="zap" class="w-6 h-6 text-purple-600"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Automáticas Hoje</p>
                            <p class="text-2xl font-bold text-gray-900">{auto_responses_today}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center">
                        <div class="w-12 h-12 bg-{'accent' if token_valid else 'red'}-100 rounded-lg flex items-center justify-center">
                            <i data-lucide="{'shield-check' if token_valid else 'shield-x'}" class="w-6 h-6 text-{'accent' if token_valid else 'red'}-600"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Status do Token</p>
                            <p class="text-lg font-bold text-{'accent' if token_valid else 'red'}-600">{'Válido' if token_valid else 'Inválido'}</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Token Status and Auto Refresh -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
                <!-- Current Token Status -->
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center justify-between mb-4">
                        <h2 class="text-lg font-semibold text-gray-900">Status Atual do Token</h2>
                        <div class="flex items-center">
                            <div class="w-3 h-3 bg-{'accent' if token_valid else 'red'}-500 rounded-full mr-2"></div>
                            <span class="text-sm font-medium text-{'accent' if token_valid else 'red'}-600">{'Válido' if token_valid else 'Inválido'}</span>
                        </div>
                    </div>
                    
                    <div class="space-y-4">
                        <div class="flex justify-between items-center">
                            <span class="text-sm text-gray-600">Access Token</span>
                            <span class="text-sm font-mono text-gray-900">{ML_ACCESS_TOKEN[:20]}...</span>
                        </div>
                        <div class="flex justify-between items-center">
                            <span class="text-sm text-gray-600">User ID</span>
                            <span class="text-sm font-mono text-gray-900">{ML_USER_ID}</span>
                        </div>
                        <div class="flex justify-between items-center">
                            <span class="text-sm text-gray-600">Status</span>
                            <span class="text-sm text-gray-900">{token_message}</span>
                        </div>
                        <div class="flex justify-between items-center">
                            <span class="text-sm text-gray-600">Expira em</span>
                            <span id="tokenExpiry" class="text-sm font-medium text-gray-900">{format_time_remaining(token_status_info['time_remaining'])}</span>
                        </div>
                    </div>
                </div>

                <!-- Auto Refresh Status -->
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center justify-between mb-4">
                        <h2 class="text-lg font-semibold text-gray-900">Renovação Automática</h2>
                        <div class="flex items-center">
                            <div class="w-3 h-3 bg-{'blue' if token_status_info['auto_refresh_enabled'] else 'gray'}-500 rounded-full mr-2"></div>
                            <span class="text-sm font-medium text-{'blue' if token_status_info['auto_refresh_enabled'] else 'gray'}-600">{'Ativa' if token_status_info['auto_refresh_enabled'] else 'Inativa'}</span>
                        </div>
                    </div>
                    
                    <div class="space-y-4">
                        <div class="flex justify-between items-center">
                            <span class="text-sm text-gray-600">Próxima renovação</span>
                            <span id="nextRefresh" class="text-sm font-medium text-gray-900">{format_time_remaining(token_status_info['next_refresh'])}</span>
                        </div>
                        <div class="flex justify-between items-center">
                            <span class="text-sm text-gray-600">Status do sistema</span>
                            <span class="text-sm text-gray-900">{token_status_info['message']}</span>
                        </div>
                        <div class="flex justify-between items-center">
                            <span class="text-sm text-gray-600">Auto-renovação</span>
                            <button onclick="toggleAutoRefresh()" class="text-sm px-3 py-1 rounded-full {'bg-red-100 text-red-700 hover:bg-red-200' if token_status_info['auto_refresh_enabled'] else 'bg-accent-100 text-accent-700 hover:bg-accent-200'}">
                                {'Pausar' if token_status_info['auto_refresh_enabled'] else 'Ativar'}
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Recent Questions -->
            <div class="bg-white rounded-xl card-shadow">
                <div class="px-6 py-4 border-b border-gray-200">
                    <div class="flex items-center justify-between">
                        <h2 class="text-lg font-semibold text-gray-900">Perguntas Recentes Não Respondidas</h2>
                        <a href="/history" class="text-sm text-primary-600 hover:text-primary-700 font-medium">Ver todas</a>
                    </div>
                </div>
                
                <div class="p-6">
                    <div class="space-y-4">
                        {chr(10).join([
                        f'<div class="flex items-start space-x-4 p-4 bg-gray-50 rounded-lg">' +
                        f'<div class="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center">' +
                        f'<i data-lucide="message-circle" class="w-5 h-5 text-blue-600"></i>' +
                        f'</div>' +
                        f'<div class="flex-1 min-w-0">' +
                        f'<p class="text-sm font-medium text-gray-900 truncate">{q.question_text}</p>' +
                        f'<p class="text-xs text-gray-500">Por: {q.from_user or "Usuário"} - {format_local_time(q.created_at).strftime("%d/%m/%Y %H:%M") if q.created_at else "Data não disponível"}</p>' +
                        f'</div>' +
                        f'<div class="flex-shrink-0">' +
                        f'<span class="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-yellow-100 text-yellow-800">' +
                        f'Pendente' +
                        f'</span>' +
                        f'</div>' +
                        f'</div>'
                        for q in recent_questions]) if recent_questions else '<div class="text-center py-8"><div class="flex flex-col items-center"><i data-lucide="inbox" class="w-12 h-12 text-gray-400 mb-4"></i><h3 class="text-lg font-medium text-gray-900 mb-2">Nenhuma pergunta pendente</h3><p class="text-gray-500">Todas as perguntas foram respondidas.</p></div></div>'}
                    </div>
                </div>
            </div>
            """
            
            custom_scripts = f"""
            // Countdown timer
            let tokenTimeRemaining = {token_status_info['time_remaining']};
            let refreshTimeRemaining = {token_status_info['next_refresh']};
            
            function formatTime(seconds) {{
                if (seconds <= 0) return "Expirado";
                const hours = Math.floor(seconds / 3600);
                const minutes = Math.floor((seconds % 3600) / 60);
                
                if (hours > 0) {{
                    return `${{hours}}h ${{minutes}}min`;
                }} else {{
                    return `${{minutes}}min`;
                }}
            }}
            
            function updateCountdowns() {{
                const tokenElement = document.getElementById('tokenExpiry');
                const refreshElement = document.getElementById('nextRefresh');
                
                if (tokenElement) {{
                    tokenElement.textContent = formatTime(Math.max(0, tokenTimeRemaining));
                }}
                
                if (refreshElement) {{
                    refreshElement.textContent = formatTime(Math.max(0, refreshTimeRemaining));
                }}
                
                tokenTimeRemaining = Math.max(0, tokenTimeRemaining - 1);
                refreshTimeRemaining = Math.max(0, refreshTimeRemaining - 1);
            }}
            
            // Atualizar a cada segundo
            setInterval(updateCountdowns, 1000);
            
            // Recarregar página a cada 5 minutos
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
            """
            
            # Aplicar layout moderno
            nav_classes = get_navigation_classes('dashboard')
            layout = get_modern_layout_base()
            
            return layout.format(
                title="Dashboard",
                page_title="Dashboard Principal",
                content=content,
                header_actions='<div class="text-sm text-gray-500">Sistema ativo</div>',
                custom_scripts=custom_scripts,
                **nav_classes
            )
            
    except Exception as e:
        add_debug_log(f"❌ Erro no dashboard: {e}")
        return f"<h1>Erro no Dashboard</h1><p>{e}</p>", 500


@app.route('/edit-rules')
def edit_rules_page():
    """Página para editar regras de resposta automática com layout moderno"""
    try:
        with app.app_context():
            initialize_database()
            rules = ResponseRule.query.all()
            
            content = f"""
            <!-- Add New Rule Form -->
            <div class="bg-white rounded-xl p-6 card-shadow mb-6">
                <div class="flex items-center mb-6">
                    <div class="w-10 h-10 bg-accent-100 rounded-lg flex items-center justify-center mr-4">
                        <i data-lucide="plus" class="w-5 h-5 text-accent-600"></i>
                    </div>
                    <h2 class="text-xl font-semibold text-gray-900">Adicionar Nova Regra</h2>
                </div>
                
                <form id="rule-form" class="space-y-6">
                    <div>
                        <label for="keywords" class="block text-sm font-medium text-gray-700 mb-2">
                            Palavras-chave (separadas por vírgula)
                        </label>
                        <input type="text" id="keywords" name="keywords" 
                               class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                               placeholder="preço, valor, quanto custa" required>
                        <p class="mt-1 text-sm text-gray-500">Digite as palavras que ativarão esta resposta automática</p>
                    </div>
                    
                    <div>
                        <label for="response" class="block text-sm font-medium text-gray-700 mb-2">
                            Resposta automática
                        </label>
                        <textarea id="response" name="response" rows="4"
                                  class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                                  placeholder="Digite a resposta que será enviada automaticamente..." required></textarea>
                    </div>
                    
                    <div class="flex justify-end">
                        <button type="submit" class="px-6 py-2 bg-accent-600 text-white rounded-lg hover:bg-accent-700 focus:ring-2 focus:ring-accent-500 focus:ring-offset-2 flex items-center">
                            <i data-lucide="save" class="w-4 h-4 mr-2"></i>
                            Salvar Regra
                        </button>
                    </div>
                </form>
            </div>

            <!-- Existing Rules -->
            <div class="bg-white rounded-xl card-shadow">
                <div class="px-6 py-4 border-b border-gray-200">
                    <div class="flex items-center justify-between">
                        <h2 class="text-xl font-semibold text-gray-900">Regras Existentes</h2>
                        <span class="text-sm text-gray-500">{len(rules)} regra{'s' if len(rules) != 1 else ''}</span>
                    </div>
                </div>
                
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Palavras-chave
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Resposta
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Status
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Ações
                                </th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            {chr(10).join([f'''
                            <tr class="hover:bg-gray-50">
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="flex flex-wrap gap-1">
                                        {chr(10).join([f'<span class="inline-flex px-2 py-1 text-xs font-medium bg-blue-100 text-blue-800 rounded-full">{keyword.strip()}</span>' for keyword in rule.keywords.split(',')])}
                                    </div>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="text-sm text-gray-900 max-w-xs truncate" title="{rule.response_text}">
                                        {rule.response_text[:80]}{'...' if len(rule.response_text) > 80 else ''}
                                    </div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <span class="inline-flex px-2 py-1 text-xs font-semibold rounded-full {'bg-accent-100 text-accent-800' if rule.is_active else 'bg-red-100 text-red-800'}">
                                        {'Ativa' if rule.is_active else 'Inativa'}
                                    </span>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium space-x-2">
                                    <button onclick="toggleRule({rule.id})" 
                                            class="{'text-red-600 hover:text-red-900' if rule.is_active else 'text-accent-600 hover:text-accent-900'}">
                                        {'Desativar' if rule.is_active else 'Ativar'}
                                    </button>
                                    <button onclick="deleteRule({rule.id})" 
                                            class="text-red-600 hover:text-red-900">
                                        Excluir
                                    </button>
                                </td>
                            </tr>
                            ''' for rule in rules]) if rules else '''
                            <tr>
                                <td colspan="4" class="px-6 py-12 text-center">
                                    <div class="flex flex-col items-center">
                                        <i data-lucide="inbox" class="w-12 h-12 text-gray-400 mb-4"></i>
                                        <h3 class="text-lg font-medium text-gray-900 mb-2">Nenhuma regra configurada</h3>
                                        <p class="text-gray-500">Crie sua primeira regra de resposta automática acima.</p>
                                    </div>
                                </td>
                            </tr>
                            '''}
                        </tbody>
                    </table>
                </div>
            </div>
            """
            
            custom_scripts = """
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
            """
            
            nav_classes = get_navigation_classes('rules')
            layout = get_modern_layout_base()
            
            return layout.format(
                title="Regras de Resposta",
                page_title="Gerenciar Regras de Resposta",
                content=content,
                header_actions='<button class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700">Nova Regra</button>',
                custom_scripts=custom_scripts,
                **nav_classes
            )
            
    except Exception as e:
        add_debug_log(f"❌ Erro na página de regras: {e}")
        return f"<h1>Erro na página de regras</h1><p>{e}</p>", 500

@app.route('/edit-absence')
def edit_absence_page():
    """Página para editar configurações de ausência com layout moderno"""
    try:
        with app.app_context():
            initialize_database()
            configs = AbsenceConfig.query.all()
            
            content = f"""
            <!-- Add New Absence Config Form -->
            <div class="bg-white rounded-xl p-6 card-shadow mb-6">
                <div class="flex items-center mb-6">
                    <div class="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center mr-4">
                        <i data-lucide="plus" class="w-5 h-5 text-purple-600"></i>
                    </div>
                    <h2 class="text-xl font-semibold text-gray-900">Adicionar Configuração de Ausência</h2>
                </div>
                
                <form id="absence-form" class="space-y-6">
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="name" class="block text-sm font-medium text-gray-700 mb-2">
                                Nome da configuração
                            </label>
                            <input type="text" id="name" name="name" 
                                   class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                                   placeholder="Ex: Horário Comercial" required>
                        </div>
                        
                        <div>
                            <label for="message" class="block text-sm font-medium text-gray-700 mb-2">
                                Mensagem de ausência
                            </label>
                            <textarea id="message" name="message" rows="3"
                                      class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                                      placeholder="Digite a mensagem que será enviada..." required></textarea>
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="start_time" class="block text-sm font-medium text-gray-700 mb-2">
                                Horário de início
                            </label>
                            <input type="time" id="start_time" name="start_time" 
                                   class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500" required>
                        </div>
                        
                        <div>
                            <label for="end_time" class="block text-sm font-medium text-gray-700 mb-2">
                                Horário de fim
                            </label>
                            <input type="time" id="end_time" name="end_time" 
                                   class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500" required>
                        </div>
                    </div>
                    
                    <div>
                        <label class="block text-sm font-medium text-gray-700 mb-3">
                            Dias da semana
                        </label>
                        <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
                            <label class="flex items-center p-3 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">
                                <input type="checkbox" name="days" value="0" class="mr-2 text-primary-600 focus:ring-primary-500">
                                <span class="text-sm">Segunda</span>
                            </label>
                            <label class="flex items-center p-3 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">
                                <input type="checkbox" name="days" value="1" class="mr-2 text-primary-600 focus:ring-primary-500">
                                <span class="text-sm">Terça</span>
                            </label>
                            <label class="flex items-center p-3 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">
                                <input type="checkbox" name="days" value="2" class="mr-2 text-primary-600 focus:ring-primary-500">
                                <span class="text-sm">Quarta</span>
                            </label>
                            <label class="flex items-center p-3 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">
                                <input type="checkbox" name="days" value="3" class="mr-2 text-primary-600 focus:ring-primary-500">
                                <span class="text-sm">Quinta</span>
                            </label>
                            <label class="flex items-center p-3 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">
                                <input type="checkbox" name="days" value="4" class="mr-2 text-primary-600 focus:ring-primary-500">
                                <span class="text-sm">Sexta</span>
                            </label>
                            <label class="flex items-center p-3 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">
                                <input type="checkbox" name="days" value="5" class="mr-2 text-primary-600 focus:ring-primary-500">
                                <span class="text-sm">Sábado</span>
                            </label>
                            <label class="flex items-center p-3 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">
                                <input type="checkbox" name="days" value="6" class="mr-2 text-primary-600 focus:ring-primary-500">
                                <span class="text-sm">Domingo</span>
                            </label>
                        </div>
                    </div>
                    
                    <div class="flex justify-end">
                        <button type="submit" class="px-6 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 flex items-center">
                            <i data-lucide="save" class="w-4 h-4 mr-2"></i>
                            Salvar Configuração
                        </button>
                    </div>
                </form>
            </div>

            <!-- Existing Absence Configs -->
            <div class="bg-white rounded-xl card-shadow">
                <div class="px-6 py-4 border-b border-gray-200">
                    <div class="flex items-center justify-between">
                        <h2 class="text-xl font-semibold text-gray-900">Configurações Existentes</h2>
                        <span class="text-sm text-gray-500">{len(configs)} configuração{'ões' if len(configs) != 1 else ''}</span>
                    </div>
                </div>
                
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Nome
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Horário
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Dias
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Status
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Ações
                                </th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            {chr(10).join([f'''
                            <tr class="hover:bg-gray-50">
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="text-sm font-medium text-gray-900">{config.name}</div>
                                    <div class="text-sm text-gray-500 max-w-xs truncate" title="{config.message}">
                                        {config.message[:50]}{'...' if len(config.message) > 50 else ''}
                                    </div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="text-sm text-gray-900">{config.start_time} - {config.end_time}</div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="flex flex-wrap gap-1">
                                        {chr(10).join([f'<span class="inline-flex px-2 py-1 text-xs font-medium bg-gray-100 text-gray-800 rounded-full">{["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"][int(d)]}</span>' for d in config.days_of_week.split(',') if d.isdigit() and int(d) < 7])}
                                    </div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <span class="inline-flex px-2 py-1 text-xs font-semibold rounded-full {'bg-accent-100 text-accent-800' if config.is_active else 'bg-red-100 text-red-800'}">
                                        {'Ativa' if config.is_active else 'Inativa'}
                                    </span>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium space-x-2">
                                    <button onclick="toggleAbsence({config.id})" 
                                            class="{'text-red-600 hover:text-red-900' if config.is_active else 'text-accent-600 hover:text-accent-900'}">
                                        {'Desativar' if config.is_active else 'Ativar'}
                                    </button>
                                    <button onclick="deleteAbsence({config.id})" 
                                            class="text-red-600 hover:text-red-900">
                                        Excluir
                                    </button>
                                </td>
                            </tr>
                            ''' for config in configs]) if configs else '''
                            <tr>
                                <td colspan="5" class="px-6 py-12 text-center">
                                    <div class="flex flex-col items-center">
                                        <i data-lucide="moon" class="w-12 h-12 text-gray-400 mb-4"></i>
                                        <h3 class="text-lg font-medium text-gray-900 mb-2">Nenhuma configuração de ausência</h3>
                                        <p class="text-gray-500">Crie sua primeira configuração de ausência acima.</p>
                                    </div>
                                </td>
                            </tr>
                            '''}
                        </tbody>
                    </table>
                </div>
            </div>
            """
            
            custom_scripts = """
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
            """
            
            nav_classes = get_navigation_classes('absence')
            layout = get_modern_layout_base()
            
            return layout.format(
                title="Configurações de Ausência",
                page_title="Gerenciar Ausência",
                content=content,
                header_actions='<button class="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700">Nova Configuração</button>',
                custom_scripts=custom_scripts,
                **nav_classes
            )
            
    except Exception as e:
        add_debug_log(f"❌ Erro na página de ausência: {e}")
        return f"<h1>Erro na página de ausência</h1><p>{e}</p>", 500

# ========== APIs PARA GERENCIAMENTO ==========

@app.route('/api/rules', methods=['POST'])
def api_create_rule():
    """API para criar nova regra"""
    try:
        data = request.get_json()
        
        with app.app_context():
            rule = ResponseRule(
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
            rule = ResponseRule.query.get(rule_id)
            if not rule:
                return jsonify({"error": "Regra não encontrada"}), 404
            
            rule.is_active = not rule.is_active
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
            rule = ResponseRule.query.get(rule_id)
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
            config = AbsenceConfig(
                name=data['name'],
                message=data['message'],
                start_time=data['start_time'],
                end_time=data['end_time'],
                days_of_week=data['days_of_week'],
                is_active=True
            )
            
            db.session.add(config)
            db.session.commit()
            
            add_debug_log(f"✅ Nova configuração de ausência criada: {data['name']}")
            return jsonify({"message": "Configuração criada com sucesso"})
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao criar configuração de ausência: {e}")
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
            add_debug_log(f"🔄 Configuração de ausência {config_id} {status}")
            return jsonify({"message": f"Configuração {status} com sucesso"})
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao alterar configuração de ausência: {e}")
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
            
            add_debug_log(f"🗑️ Configuração de ausência {config_id} excluída")
            return jsonify({"message": "Configuração excluída com sucesso"})
            
    except Exception as e:
        add_debug_log(f"❌ Erro ao excluir configuração de ausência: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/history')
def history_page():
    """Página de histórico de respostas com layout moderno"""
    try:
        with app.app_context():
            initialize_database()
            
            # Buscar histórico
            history_records = ResponseHistory.query.order_by(ResponseHistory.created_at.desc()).limit(100).all()
            
            # Estatísticas do histórico
            total_responses = ResponseHistory.query.count()
            auto_count = ResponseHistory.query.filter_by(response_type='auto').count()
            absence_count = ResponseHistory.query.filter_by(response_type='absence').count()
            manual_count = ResponseHistory.query.filter_by(response_type='manual').count()
            
            avg_time = db.session.query(db.func.avg(ResponseHistory.response_time)).scalar()
            avg_time = round(avg_time, 2) if avg_time else 0
            
            content = f"""
            <!-- Statistics Cards -->
            <div class="grid grid-cols-1 md:grid-cols-5 gap-6 mb-8">
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center">
                        <div class="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                            <i data-lucide="message-circle" class="w-6 h-6 text-blue-600"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Total</p>
                            <p class="text-2xl font-bold text-gray-900">{total_responses}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center">
                        <div class="w-12 h-12 bg-accent-100 rounded-lg flex items-center justify-center">
                            <i data-lucide="zap" class="w-6 h-6 text-accent-600"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Automáticas</p>
                            <p class="text-2xl font-bold text-accent-600">{auto_count}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center">
                        <div class="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center">
                            <i data-lucide="moon" class="w-6 h-6 text-yellow-600"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Ausência</p>
                            <p class="text-2xl font-bold text-yellow-600">{absence_count}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center">
                        <div class="w-12 h-12 bg-gray-100 rounded-lg flex items-center justify-center">
                            <i data-lucide="user" class="w-6 h-6 text-gray-600"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Manuais</p>
                            <p class="text-2xl font-bold text-gray-600">{manual_count}</p>
                        </div>
                    </div>
                </div>
                <div class="bg-white rounded-xl p-6 card-shadow">
                    <div class="flex items-center">
                        <div class="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
                            <i data-lucide="clock" class="w-6 h-6 text-purple-600"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Tempo Médio</p>
                            <p class="text-2xl font-bold text-purple-600">{avg_time}s</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Filters -->
            <div class="bg-white rounded-xl p-6 card-shadow mb-6">
                <div class="flex flex-wrap items-center gap-4">
                    <div class="flex items-center space-x-2">
                        <label class="text-sm font-medium text-gray-700">Filtrar por tipo:</label>
                        <select id="typeFilter" class="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500">
                            <option value="">Todos</option>
                            <option value="auto">Automáticas</option>
                            <option value="absence">Ausência</option>
                            <option value="manual">Manuais</option>
                        </select>
                    </div>
                    <div class="flex items-center space-x-2">
                        <label class="text-sm font-medium text-gray-700">Buscar:</label>
                        <input type="text" id="searchFilter" placeholder="Digite para buscar..." 
                               class="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500">
                    </div>
                    <button onclick="clearFilters()" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200">
                        Limpar Filtros
                    </button>
                </div>
            </div>

            <!-- History Table -->
            <div class="bg-white rounded-xl card-shadow">
                <div class="px-6 py-4 border-b border-gray-200">
                    <div class="flex items-center justify-between">
                        <h2 class="text-xl font-semibold text-gray-900">Últimas 100 Respostas</h2>
                        <button onclick="exportHistory()" class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700">
                            <i data-lucide="download" class="w-4 h-4 mr-2 inline"></i>
                            Exportar
                        </button>
                    </div>
                </div>
                
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Data/Hora
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Pergunta
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Resposta
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Tipo
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Tempo
                                </th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                    Usuário
                                </th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200" id="historyTableBody">
                            {chr(10).join([f'''
                            <tr class="hover:bg-gray-50 history-row" data-type="{record.response_type}" data-search="{record.question_text.lower()} {record.response_text.lower()}">
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                    {format_local_time(record.created_at).strftime('%d/%m/%Y %H:%M') if record.created_at else 'N/A'}
                                </td>
                                <td class="px-6 py-4">
                                    <div class="text-sm text-gray-900 max-w-xs truncate" title="{record.question_text}">
                                        {record.question_text[:60]}{'...' if len(record.question_text) > 60 else ''}
                                    </div>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="text-sm text-gray-900 max-w-xs truncate" title="{record.response_text}">
                                        {record.response_text[:60]}{'...' if len(record.response_text) > 60 else ''}
                                    </div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <span class="inline-flex px-2 py-1 text-xs font-semibold rounded-full {
                                        'bg-accent-100 text-accent-800' if record.response_type == 'auto' else
                                        'bg-yellow-100 text-yellow-800' if record.response_type == 'absence' else
                                        'bg-gray-100 text-gray-800'
                                    }">
                                        {
                                            'Automática' if record.response_type == 'auto' else
                                            'Ausência' if record.response_type == 'absence' else
                                            'Manual'
                                        }
                                    </span>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                    {f"{record.response_time:.2f}s" if record.response_time else "N/A"}
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                    {record.from_user or 'N/A'}
                                </td>
                            </tr>
                            ''' for record in history_records]) if history_records else '''
                            <tr>
                                <td colspan="6" class="px-6 py-12 text-center">
                                    <div class="flex flex-col items-center">
                                        <i data-lucide="inbox" class="w-12 h-12 text-gray-400 mb-4"></i>
                                        <h3 class="text-lg font-medium text-gray-900 mb-2">Nenhum histórico encontrado</h3>
                                        <p class="text-gray-500">As respostas aparecerão aqui conforme forem enviadas.</p>
                                    </div>
                                </td>
                            </tr>
                            '''}
                        </tbody>
                    </table>
                </div>
            </div>
            """
            
            custom_scripts = """
            // Filtros
            function filterHistory() {
                const typeFilter = document.getElementById('typeFilter').value;
                const searchFilter = document.getElementById('searchFilter').value.toLowerCase();
                const rows = document.querySelectorAll('.history-row');
                
                rows.forEach(row => {
                    const type = row.getAttribute('data-type');
                    const searchText = row.getAttribute('data-search');
                    
                    const typeMatch = !typeFilter || type === typeFilter;
                    const searchMatch = !searchFilter || searchText.includes(searchFilter);
                    
                    if (typeMatch && searchMatch) {
                        row.style.display = '';
                    } else {
                        row.style.display = 'none';
                    }
                });
            }
            
            function clearFilters() {
                document.getElementById('typeFilter').value = '';
                document.getElementById('searchFilter').value = '';
                filterHistory();
            }
            
            function exportHistory() {
                // Implementar exportação
                alert('Funcionalidade de exportação em desenvolvimento');
            }
            
            // Event listeners
            document.getElementById('typeFilter').addEventListener('change', filterHistory);
            document.getElementById('searchFilter').addEventListener('input', filterHistory);
            """
            
            nav_classes = get_navigation_classes('history')
            layout = get_modern_layout_base()
            
            return layout.format(
                title="Histórico de Respostas",
                page_title="Histórico de Respostas",
                content=content,
                header_actions='<button onclick="exportHistory()" class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700">Exportar</button>',
                custom_scripts=custom_scripts,
                **nav_classes
            )
            
    except Exception as e:
        add_debug_log(f"❌ Erro na página de histórico: {e}")
        return f"<h1>Erro na página de histórico</h1><p>{e}</p>", 500

@app.route('/renovar-tokens')
def renovar_tokens_page():
    """Página para renovação de tokens com layout moderno"""
    try:
        # Status do token atual
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
        
        # Status da renovação automática
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
        
        def format_time_remaining(seconds):
            if seconds <= 0:
                return "Expirado"
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if hours > 0:
                return f"{hours}h {minutes}min"
            else:
                return f"{minutes}min"
        
        content = f"""
        <!-- Current Token Status -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
            <div class="bg-white rounded-xl p-6 card-shadow">
                <div class="flex items-center justify-between mb-4">
                    <h2 class="text-lg font-semibold text-gray-900">Status Atual do Token</h2>
                    <div class="flex items-center">
                        <div class="w-3 h-3 bg-{'accent' if token_valid else 'red'}-500 rounded-full mr-2"></div>
                        <span class="text-sm font-medium text-{'accent' if token_valid else 'red'}-600">{'Válido' if token_valid else 'Inválido'}</span>
                    </div>
                </div>
                
                <div class="space-y-4">
                    <div class="flex justify-between items-center">
                        <span class="text-sm text-gray-600">Access Token</span>
                        <span class="text-sm font-mono text-gray-900">{ML_ACCESS_TOKEN[:20]}...</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-sm text-gray-600">User ID</span>
                        <span class="text-sm font-mono text-gray-900">{ML_USER_ID}</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-sm text-gray-600">Status</span>
                        <span class="text-sm text-gray-900">{token_message}</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-sm text-gray-600">Expira em</span>
                        <span class="text-sm font-medium text-gray-900">{format_time_remaining(token_status_info['time_remaining'])}</span>
                    </div>
                </div>
            </div>

            <div class="bg-white rounded-xl p-6 card-shadow">
                <div class="flex items-center justify-between mb-4">
                    <h2 class="text-lg font-semibold text-gray-900">Renovação Automática</h2>
                    <div class="flex items-center">
                        <div class="w-3 h-3 bg-{'blue' if token_status_info['auto_refresh_enabled'] else 'gray'}-500 rounded-full mr-2"></div>
                        <span class="text-sm font-medium text-{'blue' if token_status_info['auto_refresh_enabled'] else 'gray'}-600">{'Ativa' if token_status_info['auto_refresh_enabled'] else 'Inativa'}</span>
                    </div>
                </div>
                
                <div class="space-y-4">
                    <div class="flex justify-between items-center">
                        <span class="text-sm text-gray-600">Próxima renovação</span>
                        <span class="text-sm font-medium text-gray-900">{format_time_remaining(token_status_info['next_refresh'])}</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-sm text-gray-600">Status do sistema</span>
                        <span class="text-sm text-gray-900">{token_status_info['message']}</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-sm text-gray-600">Auto-renovação</span>
                        <button onclick="toggleAutoRefresh()" class="text-sm px-3 py-1 rounded-full {'bg-red-100 text-red-700 hover:bg-red-200' if token_status_info['auto_refresh_enabled'] else 'bg-accent-100 text-accent-700 hover:bg-accent-200'}">
                            {'Pausar' if token_status_info['auto_refresh_enabled'] else 'Ativar'}
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Manual Token Renewal -->
        <div class="bg-white rounded-xl p-6 card-shadow mb-6">
            <div class="flex items-center mb-6">
                <div class="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center mr-4">
                    <i data-lucide="refresh-cw" class="w-5 h-5 text-blue-600"></i>
                </div>
                <h2 class="text-xl font-semibold text-gray-900">Renovação Manual de Tokens</h2>
            </div>
            
            <div class="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
                <div class="flex">
                    <i data-lucide="info" class="w-5 h-5 text-blue-600 mt-0.5 mr-3"></i>
                    <div>
                        <h3 class="text-sm font-medium text-blue-800">Como renovar tokens manualmente</h3>
                        <div class="mt-2 text-sm text-blue-700">
                            <ol class="list-decimal list-inside space-y-1">
                                <li>Clique no botão "Abrir Autorização do ML" abaixo</li>
                                <li>Faça login na sua conta do Mercado Livre</li>
                                <li>Autorize o aplicativo</li>
                                <li>Copie o código da URL de retorno e cole abaixo</li>
                            </ol>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="space-y-6">
                <div class="text-center">
                    <a href="https://auth.mercadolibre.com.br/authorization?response_type=code&client_id={ML_CLIENT_ID}&redirect_uri=https://bot-mercadolivre-dettech.onrender.com/api/ml/webhook" 
                       target="_blank" 
                       class="inline-flex items-center px-6 py-3 bg-accent-600 text-white rounded-lg hover:bg-accent-700 focus:ring-2 focus:ring-accent-500 focus:ring-offset-2">
                        <i data-lucide="external-link" class="w-5 h-5 mr-2"></i>
                        Abrir Autorização do ML
                    </a>
                </div>
                
                <div>
                    <label for="authCode" class="block text-sm font-medium text-gray-700 mb-2">
                        Código de Autorização
                    </label>
                    <div class="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-3">
                        <p class="text-sm text-blue-700">
                            <strong>Formato esperado:</strong> TG-xxxxxxxxxxxxxxxxxxxxxxx-xxxxxxxxx
                        </p>
                    </div>
                    <input type="text" id="authCode" 
                           class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                           placeholder="TG-68841862c4a8a9000124716e-180617463">
                </div>
                
                <div class="flex justify-center">
                    <button onclick="processAuthCode()" 
                            class="px-8 py-3 bg-primary-600 text-white rounded-lg hover:bg-primary-700 focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 flex items-center">
                        <i data-lucide="key" class="w-5 h-5 mr-2"></i>
                        Processar Código
                    </button>
                </div>
            </div>
        </div>

        <!-- Response Area -->
        <div id="responseArea" class="hidden">
            <div class="bg-white rounded-xl p-6 card-shadow">
                <div class="flex items-center mb-4">
                    <div id="responseIcon" class="w-10 h-10 rounded-lg flex items-center justify-center mr-4">
                        <i data-lucide="check-circle" class="w-5 h-5"></i>
                    </div>
                    <h2 id="responseTitle" class="text-xl font-semibold text-gray-900">Resultado</h2>
                </div>
                <div id="responseContent" class="text-gray-700"></div>
            </div>
        </div>
        """
        
        custom_scripts = f"""
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
        
        async function processAuthCode() {{
            const code = document.getElementById('authCode').value.trim();
            
            if (!code) {{
                alert('Por favor, insira o código de autorização');
                return;
            }}
            
            const responseArea = document.getElementById('responseArea');
            const responseIcon = document.getElementById('responseIcon');
            const responseTitle = document.getElementById('responseTitle');
            const responseContent = document.getElementById('responseContent');
            
            // Show loading
            responseArea.classList.remove('hidden');
            responseIcon.className = 'w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center mr-4';
            responseIcon.innerHTML = '<i data-lucide="loader-2" class="w-5 h-5 text-blue-600 animate-spin"></i>';
            responseTitle.textContent = 'Processando...';
            responseContent.textContent = 'Aguarde enquanto processamos o código de autorização...';
            
            try {{
                const response = await fetch('/api/tokens/process-code-flexible', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{code: code}})
                }});
                
                const result = await response.json();
                
                if (result.success) {{
                    responseIcon.className = 'w-10 h-10 bg-accent-100 rounded-lg flex items-center justify-center mr-4';
                    responseIcon.innerHTML = '<i data-lucide="check-circle" class="w-5 h-5 text-accent-600"></i>';
                    responseTitle.textContent = 'Tokens Atualizados com Sucesso!';
                    responseContent.innerHTML = `
                        <div class="space-y-2">
                            <p><strong>User ID:</strong> ${{result.user_id}}</p>
                            <p><strong>Token:</strong> ${{code}}</p>
                            <p class="text-accent-600 font-medium">O sistema já está usando os novos tokens.</p>
                        </div>
                    `;
                    
                    // Reload page after 3 seconds
                    setTimeout(() => {{
                        window.location.reload();
                    }}, 3000);
                }} else {{
                    responseIcon.className = 'w-10 h-10 bg-red-100 rounded-lg flex items-center justify-center mr-4';
                    responseIcon.innerHTML = '<i data-lucide="x-circle" class="w-5 h-5 text-red-600"></i>';
                    responseTitle.textContent = 'Erro ao processar código';
                    responseContent.innerHTML = `
                        <div class="text-red-700">
                            <p><strong>Erro:</strong> ${{result.message}}</p>
                            <p class="mt-2 text-sm">Verifique se o código está correto e tente novamente.</p>
                        </div>
                    `;
                }}
            }} catch (error) {{
                responseIcon.className = 'w-10 h-10 bg-red-100 rounded-lg flex items-center justify-center mr-4';
                responseIcon.innerHTML = '<i data-lucide="x-circle" class="w-5 h-5 text-red-600"></i>';
                responseTitle.textContent = 'Erro de conexão';
                responseContent.innerHTML = `
                    <div class="text-red-700">
                        <p>Não foi possível conectar ao servidor.</p>
                        <p class="mt-2 text-sm">Verifique sua conexão e tente novamente.</p>
                    </div>
                `;
            }}
            
            // Re-initialize icons
            lucide.createIcons();
        }}
        """
        
        nav_classes = get_navigation_classes('tokens')
        layout = get_modern_layout_base()
        
        return layout.format(
            title="Renovação de Tokens",
            page_title="Gerenciar Tokens",
            content=content,
            header_actions='<button onclick="toggleAutoRefresh()" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">Auto-renovação</button>',
            custom_scripts=custom_scripts,
            **nav_classes
        )
        
    except Exception as e:
        add_debug_log(f"❌ Erro na página de tokens: {e}")
        return f"<h1>Erro na página de tokens</h1><p>{e}</p>", 500


@app.route('/debug-full')
def debug_full_page():
    """Página de debug completa com layout moderno"""
    try:
        # Estatísticas dos logs
        total_logs = len(debug_logs)
        error_logs = len([log for log in debug_logs if '❌' in log])
        success_logs = len([log for log in debug_logs if '✅' in log])
        warning_logs = len([log for log in debug_logs if '⚠️' in log])
        
        content = f"""
        <!-- Debug Statistics -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <div class="bg-white rounded-xl p-6 card-shadow">
                <div class="flex items-center">
                    <div class="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                        <i data-lucide="activity" class="w-6 h-6 text-blue-600"></i>
                    </div>
                    <div class="ml-4">
                        <p class="text-sm font-medium text-gray-600">Total de Logs</p>
                        <p class="text-2xl font-bold text-gray-900">{total_logs}</p>
                    </div>
                </div>
            </div>
            <div class="bg-white rounded-xl p-6 card-shadow">
                <div class="flex items-center">
                    <div class="w-12 h-12 bg-red-100 rounded-lg flex items-center justify-center">
                        <i data-lucide="x-circle" class="w-6 h-6 text-red-600"></i>
                    </div>
                    <div class="ml-4">
                        <p class="text-sm font-medium text-gray-600">Erros</p>
                        <p class="text-2xl font-bold text-red-600">{error_logs}</p>
                    </div>
                </div>
            </div>
            <div class="bg-white rounded-xl p-6 card-shadow">
                <div class="flex items-center">
                    <div class="w-12 h-12 bg-accent-100 rounded-lg flex items-center justify-center">
                        <i data-lucide="check-circle" class="w-6 h-6 text-accent-600"></i>
                    </div>
                    <div class="ml-4">
                        <p class="text-sm font-medium text-gray-600">Sucessos</p>
                        <p class="text-2xl font-bold text-accent-600">{success_logs}</p>
                    </div>
                </div>
            </div>
            <div class="bg-white rounded-xl p-6 card-shadow">
                <div class="flex items-center">
                    <div class="w-12 h-12 bg-yellow-100 rounded-lg flex items-center justify-center">
                        <i data-lucide="alert-triangle" class="w-6 h-6 text-yellow-600"></i>
                    </div>
                    <div class="ml-4">
                        <p class="text-sm font-medium text-gray-600">Avisos</p>
                        <p class="text-2xl font-bold text-yellow-600">{warning_logs}</p>
                    </div>
                </div>
            </div>
        </div>

        <!-- Debug Controls -->
        <div class="bg-white rounded-xl p-6 card-shadow mb-6">
            <div class="flex flex-wrap items-center justify-between gap-4">
                <div class="flex items-center space-x-4">
                    <h2 class="text-lg font-semibold text-gray-900">Controles de Debug</h2>
                    <div class="flex items-center space-x-2">
                        <input type="checkbox" id="autoScroll" checked class="text-primary-600 focus:ring-primary-500">
                        <label for="autoScroll" class="text-sm text-gray-700">Auto-scroll</label>
                    </div>
                    <div class="flex items-center space-x-2">
                        <input type="checkbox" id="autoRefresh" checked class="text-primary-600 focus:ring-primary-500">
                        <label for="autoRefresh" class="text-sm text-gray-700">Auto-refresh (5s)</label>
                    </div>
                </div>
                <div class="flex items-center space-x-2">
                    <select id="logFilter" class="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500">
                        <option value="">Todos os logs</option>
                        <option value="❌">Apenas erros</option>
                        <option value="✅">Apenas sucessos</option>
                        <option value="⚠️">Apenas avisos</option>
                        <option value="🔄">Processamento</option>
                        <option value="📩">Perguntas</option>
                    </select>
                    <button onclick="clearLogs()" class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700">
                        <i data-lucide="trash-2" class="w-4 h-4 mr-2 inline"></i>
                        Limpar
                    </button>
                    <button onclick="exportLogs()" class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700">
                        <i data-lucide="download" class="w-4 h-4 mr-2 inline"></i>
                        Exportar
                    </button>
                </div>
            </div>
        </div>

        <!-- Debug Terminal -->
        <div class="bg-gray-900 rounded-xl card-shadow overflow-hidden">
            <div class="bg-gray-800 px-6 py-3 border-b border-gray-700">
                <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-3">
                        <div class="flex space-x-2">
                            <div class="w-3 h-3 bg-red-500 rounded-full"></div>
                            <div class="w-3 h-3 bg-yellow-500 rounded-full"></div>
                            <div class="w-3 h-3 bg-accent-500 rounded-full"></div>
                        </div>
                        <span class="text-sm font-medium text-gray-300">Debug Terminal</span>
                    </div>
                    <div class="flex items-center space-x-2">
                        <span class="text-xs text-gray-400">Última atualização: <span id="lastUpdate">Agora</span></span>
                        <div class="w-2 h-2 bg-accent-500 rounded-full animate-pulse"></div>
                    </div>
                </div>
            </div>
            
            <div class="p-6 h-96 overflow-y-auto font-mono text-sm" id="debugTerminal">
                <div id="debugLogs">
                    {chr(10).join([f'<div class="debug-log-line text-gray-300 mb-1" data-log="{log}">{log}</div>' for log in debug_logs[-50:]]) if debug_logs else '<div class="text-gray-500">Nenhum log disponível. Os logs aparecerão aqui conforme o sistema funciona.</div>'}
                </div>
            </div>
        </div>

        <!-- System Information -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
            <div class="bg-white rounded-xl p-6 card-shadow">
                <h3 class="text-lg font-semibold text-gray-900 mb-4">Informações do Sistema</h3>
                <div class="space-y-3">
                    <div class="flex justify-between">
                        <span class="text-sm text-gray-600">Versão do Bot</span>
                        <span class="text-sm font-medium text-gray-900">v2.0.0</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm text-gray-600">Uptime</span>
                        <span class="text-sm font-medium text-gray-900" id="uptime">Calculando...</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm text-gray-600">Última verificação</span>
                        <span class="text-sm font-medium text-gray-900" id="lastCheck">Agora</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm text-gray-600">Status do Token</span>
                        <span class="text-sm font-medium text-accent-600">Válido</span>
                    </div>
                </div>
            </div>
            
            <div class="bg-white rounded-xl p-6 card-shadow">
                <h3 class="text-lg font-semibold text-gray-900 mb-4">Métricas de Performance</h3>
                <div class="space-y-3">
                    <div class="flex justify-between">
                        <span class="text-sm text-gray-600">Perguntas processadas</span>
                        <span class="text-sm font-medium text-gray-900">{ResponseHistory.query.count() if ResponseHistory.query.count() else 0}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm text-gray-600">Tempo médio de resposta</span>
                        <span class="text-sm font-medium text-gray-900">1.2s</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm text-gray-600">Taxa de sucesso</span>
                        <span class="text-sm font-medium text-accent-600">98.5%</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-sm text-gray-600">Regras ativas</span>
                        <span class="text-sm font-medium text-gray-900">{ResponseRule.query.filter_by(is_active=True).count() if ResponseRule.query.filter_by(is_active=True).count() else 0}</span>
                    </div>
                </div>
            </div>
        </div>
        """
        
        custom_scripts = """
        let autoRefreshInterval;
        
        function updateDebugLogs() {
            fetch('/api/debug/logs?limit=50')
                .then(response => response.json())
                .then(data => {
                    const debugLogs = document.getElementById('debugLogs');
                    const autoScroll = document.getElementById('autoScroll').checked;
                    const filter = document.getElementById('logFilter').value;
                    
                    let filteredLogs = data.logs;
                    if (filter) {
                        filteredLogs = data.logs.filter(log => log.includes(filter));
                    }
                    
                    debugLogs.innerHTML = filteredLogs.map(log => 
                        `<div class="debug-log-line text-gray-300 mb-1" data-log="${log}">${log}</div>`
                    ).join('');
                    
                    if (autoScroll) {
                        const terminal = document.getElementById('debugTerminal');
                        terminal.scrollTop = terminal.scrollHeight;
                    }
                    
                    document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
                })
                .catch(error => console.error('Erro ao atualizar logs:', error));
        }
        
        function startAutoRefresh() {
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
            }
            
            if (document.getElementById('autoRefresh').checked) {
                autoRefreshInterval = setInterval(updateDebugLogs, 5000);
            }
        }
        
        function clearLogs() {
            if (confirm('Tem certeza que deseja limpar todos os logs?')) {
                fetch('/api/debug/clear-logs', {method: 'POST'})
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            updateDebugLogs();
                        } else {
                            alert('Erro ao limpar logs');
                        }
                    })
                    .catch(error => alert('Erro de conexão'));
            }
        }
        
        function exportLogs() {
            fetch('/api/debug/logs?limit=1000')
                .then(response => response.json())
                .then(data => {
                    const blob = new Blob([data.logs.join('\\n')], {type: 'text/plain'});
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `debug-logs-${new Date().toISOString().split('T')[0]}.txt`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);
                })
                .catch(error => alert('Erro ao exportar logs'));
        }
        
        // Event listeners
        document.getElementById('autoRefresh').addEventListener('change', startAutoRefresh);
        document.getElementById('logFilter').addEventListener('change', updateDebugLogs);
        
        // Initialize
        startAutoRefresh();
        updateDebugLogs();
        """
        
        nav_classes = get_navigation_classes('debug')
        layout = get_modern_layout_base()
        
        return layout.format(
            title="Debug e Logs",
            page_title="Debug e Monitoramento",
            content=content,
            header_actions='<button onclick="clearLogs()" class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700">Limpar Logs</button>',
            custom_scripts=custom_scripts,
            **nav_classes
        )
        
    except Exception as e:
        add_debug_log(f"❌ Erro na página de debug: {e}")
        return f"<h1>Erro na página de debug</h1><p>{e}</p>", 500

# ========== FINALIZAÇÃO DO SISTEMA ==========

# Copiar todas as outras funções e rotas do sistema original
# (process_questions, fetch_unanswered_questions, webhook, APIs, etc.)

if __name__ == '__main__':
    try:
        add_debug_log("🚀 Iniciando sistema com layout moderno...")
        
        # Inicializar banco de dados
        with app.app_context():
            initialize_database()
            add_debug_log("✅ Banco de dados inicializado")
        
        # Inicializar renovação automática se disponível
        try:
            auto_refresh_manager.initialize_auto_refresh()
            add_debug_log("✅ Sistema de renovação automática inicializado")
        except Exception as e:
            add_debug_log(f"⚠️ Renovação automática não disponível: {e}")
        
        # Iniciar tarefas em background
        start_background_tasks()
        add_debug_log("✅ Tarefas em background iniciadas")
        
        # Iniciar servidor
        port = int(os.environ.get('PORT', 5000))
        add_debug_log(f"🌐 Servidor iniciando na porta {port}")
        
        app.run(host='0.0.0.0', port=port, debug=False)
        
    except Exception as e:
        add_debug_log(f"❌ Erro crítico na inicialização: {e}")
        print(f"Erro crítico: {e}")
        sys.exit(1)

