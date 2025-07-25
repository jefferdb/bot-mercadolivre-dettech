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
                                <p><strong>Redirect URI usado:</strong> ${{data.redirect_uri_used || 'N/A'}}</p>
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

@app.route('/api/ml/webhook')
def webhook_callback():
    """Callback alternativo para webhook"""
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
    <h1>❌ Código não encontrado (Webhook)</h1>
    <p>Não foi possível obter o código de autorização.</p>
    <a href="/renovar-tokens">🔄 Tentar Novamente</a>
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
    
    print("✅ Sistema iniciado com renovação flexível de tokens!")
    print("🔧 Suporte a múltiplas URLs de redirect configurado")

if __name__ == '__main__':
    start_background_tasks()
    app.run(host='0.0.0.0', port=5000, debug=False)

