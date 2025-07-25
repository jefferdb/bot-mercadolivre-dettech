import os
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests

# Configuração da aplicação
app = Flask(__name__)
CORS(app)

# Configuração do banco SQLite em memória
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////opt/render/project/src/data/bot_data.db'
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
    
class TokenLog(db.Model):
    __tablename__ = 'token_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    old_token = db.Column(db.String(200))
    new_token = db.Column(db.String(200))
    expires_at = db.Column(db.DateTime)
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Variável global para controlar inicialização
_initialized = False

# Função para criar tabelas e dados iniciais
def initialize_database():
    global _initialized
    if _initialized:
        return
    
    try:
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
            print("✅ Banco de dados inicializado com sucesso!")
            
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
    # Função para renovar token automaticamente
def renew_access_token():
    global ML_ACCESS_TOKEN
    
    try:
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user or not user.refresh_token:
            print("❌ Usuário ou refresh_token não encontrado")
            return False
        
        url = "https://api.mercadolibre.com/oauth/token"
        
        data = {
            "grant_type": "refresh_token",
            "client_id": ML_CLIENT_ID,
            "client_secret": ML_CLIENT_SECRET,
            "refresh_token": user.refresh_token
        }
        
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        print(f"🔄 Renovando token para usuário {ML_USER_ID}..." )
        
        response = requests.post(url, data=data, headers=headers)
        
        if response.status_code == 200:
            token_data = response.json()
            
            old_token = user.access_token
            new_access_token = token_data.get("access_token")
            new_refresh_token = token_data.get("refresh_token", user.refresh_token)
            expires_in = token_data.get("expires_in", 21600)
            
            user.access_token = new_access_token
            user.refresh_token = new_refresh_token
            user.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            user.updated_at = datetime.utcnow()
            
            ML_ACCESS_TOKEN = new_access_token
            
            log = TokenLog(
                user_id=user.id,
                action="renewed",
                old_token=old_token[:20] + "...",
                new_token=new_access_token[:20] + "...",
                expires_at=user.token_expires_at,
                message=f"Token renovado com sucesso. Expira em {expires_in} segundos."
            )
            db.session.add(log)
            db.session.commit()
            
            print(f"✅ Token renovado com sucesso! Expira em {expires_in} segundos")
            return True
            
        else:
            error_msg = f"Erro {response.status_code}: {response.text}"
            print(f"❌ Erro ao renovar token: {error_msg}")
            
            log = TokenLog(
                user_id=user.id,
                action="failed",
                message=error_msg
            )
            db.session.add(log)
            db.session.commit()
            return False
            
    except Exception as e:
        error_msg = f"Exceção ao renovar token: {str(e)}"
        print(f"❌ {error_msg}")
        return False

# Função para verificar se token precisa ser renovado
def check_token_expiration():
    try:
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user or not user.token_expires_at:
            print("⚠️ Usuário ou data de expiração não encontrada")
            return False
        
        now = datetime.utcnow()
        expires_at = user.token_expires_at
        time_until_expiry = expires_at - now
        
        if time_until_expiry.total_seconds() < 1800:  # 30 minutos
            print(f"⏰ Token expira em {time_until_expiry}. Renovando...")
            return renew_access_token()
        else:
            minutes_left = int(time_until_expiry.total_seconds() / 60)
            print(f"✅ Token válido por mais {minutes_left} minutos")
            
            log = TokenLog(
                user_id=user.id,
                action="checked",
                expires_at=expires_at,
                message=f"Token verificado. Válido por mais {minutes_left} minutos."
            )
            db.session.add(log)
            db.session.commit()
            return True
            
    except Exception as e:
        print(f"❌ Erro ao verificar expiração do token: {e}")
        return False


# Função para encontrar resposta automática
def find_auto_response(question_text):
    question_lower = question_text.lower()
    
    auto_responses = AutoResponse.query.filter_by(is_active=True).all()
    
    for response in auto_responses:
        keywords = [k.strip().lower() for k in response.keywords.split(',')]
        
        for keyword in keywords:
            if keyword in question_lower:
                return response.response_text
    
    return None

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
            
            # Salvar pergunta no banco
            question = Question(
                ml_question_id=question_id,
                user_id=user.id,
                item_id=item_id,
                question_text=question_text,
                is_answered=False
            )
            db.session.add(question)
            
            # Verificar se está em horário de ausência
            absence_message = is_absence_time()
            if absence_message:
                if answer_question_ml(question_id, absence_message):
                    question.response_text = absence_message
                    question.is_answered = True
                    question.answered_automatically = True
                    question.answered_at = datetime.utcnow()
                    print(f"✅ Pergunta {question_id} respondida com mensagem de ausência")
            else:
                # Buscar resposta automática
                auto_response = find_auto_response(question_text)
                if auto_response:
                    if answer_question_ml(question_id, auto_response):
                        question.response_text = auto_response
                        question.is_answered = True
                        question.answered_automatically = True
                        question.answered_at = datetime.utcnow()
                        print(f"✅ Pergunta {question_id} respondida automaticamente")
            
            db.session.commit()
    except Exception as e:
        print(f"❌ Erro ao processar perguntas: {e}")

# Função de monitoramento contínuo
def monitor_questions():
    while True:
        try:
            with app.app_context():
                process_questions()
            time.sleep(60)  # Verificar a cada 60 segundos
        except Exception as e:
            print(f"❌ Erro no monitoramento: {e}")
            time.sleep(60)
# Função de monitoramento de token
def monitor_token():
    while True:
        try:
            with app.app_context():
                check_token_expiration()
            time.sleep(3600)  # Verificar a cada 1 hora
        except Exception as e:
            print(f"❌ Erro no monitoramento de token: {e}")
            time.sleep(3600)

# Rotas da aplicação
@app.route('/')
def dashboard():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    # Estatísticas
    total_questions = Question.query.filter_by(user_id=user.id).count()
    answered_auto = Question.query.filter_by(user_id=user.id, answered_automatically=True).count()
    pending_questions = Question.query.filter_by(user_id=user.id, is_answered=False).count()
    
    success_rate = round((answered_auto / total_questions * 100) if total_questions > 0 else 0, 1)
    
    # Status do token
    token_status = "Válido" if user.token_expires_at and user.token_expires_at > datetime.utcnow() else "Expirado"
    
    # Contadores
    active_rules = AutoResponse.query.filter_by(user_id=user.id, is_active=True).count()
    absence_configs = AbsenceConfig.query.filter_by(user_id=user.id, is_active=True).count()
    
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
            .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 25px; margin-bottom: 30px; }}
            .stat-card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); text-align: center; }}
            .stat-number {{ font-size: 3em; font-weight: bold; color: #3483fa; margin-bottom: 10px; }}
            .stat-label {{ font-size: 1.1em; color: #666; }}
            .status {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 25px; margin-bottom: 30px; }}
            .status-card {{ padding: 25px; background: white; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
            .status-card.connected {{ border-left: 6px solid #00a650; }}
            .status-card.warning {{ border-left: 6px solid #ff9500; }}
            .status-card h3 {{ margin-bottom: 15px; font-size: 1.3em; }}
            .navigation {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; }}
            .nav-card {{ background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); text-align: center; }}
            .nav-card a {{ text-decoration: none; color: #3483fa; font-weight: bold; font-size: 1.1em; }}
            .nav-card:hover {{ transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.12); }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Bot do Mercado Livre</h1>
                <p>Sistema Automatizado de Respostas</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{total_questions}</div>
                    <div class="stat-label">Total de Perguntas</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{answered_auto}</div>
                    <div class="stat-label">Respondidas Automaticamente</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{pending_questions}</div>
                    <div class="stat-label">Aguardando Resposta</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{success_rate}%</div>
                    <div class="stat-label">Taxa de Sucesso</div>
                </div>
            </div>
            
            <div class="status">
                <div class="status-card connected">
                    <h3>✅ Status da Conexão</h3>
                    <p><strong>Status:</strong> Conectado</p>
                    <p><strong>Token:</strong> {token_status}</p>
                    <p><strong>Monitoramento:</strong> Ativo</p>
                    <p><strong>Webhook:</strong> Funcionando</p>
                </div>
                <div class="status-card connected">
                    <h3>📊 Configurações Ativas</h3>
                    <p><strong>Regras Ativas:</strong> {active_rules}</p>
                    <p><strong>Configurações de Ausência:</strong> {absence_configs}</p>
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
                    <h3>❓ Perguntas Recebidas</h3>
                    <p>Histórico de perguntas</p>
                    <a href="/questions">Acessar →</a>
                </div>
                <div class="nav-card">
                    <h3>🌙 Configurações de Ausência</h3>
                    <p>Mensagens automáticas</p>
                    <a href="/absence">Acessar →</a>
                </div>
            </div>
        </div>
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
                <div class="rule-actions">
                    <span class="status {'active' if rule.is_active else 'inactive'}">{status}</span>
                    <a href="/rules/edit/{rule.id}" class="edit-btn">✏️ Editar</a>
                    <a href="/rules/toggle/{rule.id}" class="toggle-btn">{'❌ Desativar' if rule.is_active else '✅ Ativar'}</a>
                </div>
            </div>
            <div class="rule-content">
                <p><strong>Palavras-chave:</strong> {rule.keywords}</p>
                <p><strong>Resposta:</strong> {rule.response_text}</p>
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
            .rule-actions {{ display: flex; gap: 10px; align-items: center; }}
            .status.active {{ color: #00a650; font-weight: bold; }}
            .status.inactive {{ color: #ff3333; font-weight: bold; }}
            .rule-content p {{ margin-bottom: 10px; }}
            .back-btn, .edit-btn, .toggle-btn, .add-btn {{ display: inline-block; padding: 8px 16px; text-decoration: none; border-radius: 6px; font-size: 0.9em; }}
            .back-btn {{ background: #3483fa; color: white; margin-bottom: 20px; }}
            .edit-btn {{ background: #28a745; color: white; }}
            .toggle-btn {{ background: #ffc107; color: #212529; }}
            .add-btn {{ background: #17a2b8; color: white; margin-bottom: 20px; }}
            .actions {{ margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            
            <div class="header">
                <h1>📋 Regras de Resposta Automática</h1>
                <p>Total: {len(rules)} regras configuradas</p>
            </div>
            
            <div class="actions">
                <a href="/rules/add" class="add-btn">➕ Adicionar Nova Regra</a>
            </div>
            
            {rules_html}
        </div>
    </body>
    </html>
    """
    return html

@app.route('/rules/edit/<int:rule_id>', methods=['GET', 'POST'])
def edit_rule(rule_id):
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    rule = AutoResponse.query.filter_by(id=rule_id, user_id=user.id).first()
    if not rule:
        return "❌ Regra não encontrada", 404
    
    if request.method == 'POST':
        keywords = request.form.get('keywords', '').strip()
        response_text = request.form.get('response_text', '').strip()
        is_active = request.form.get('is_active') == 'on'
        
        if keywords and response_text:
            rule.keywords = keywords
            rule.response_text = response_text
            rule.is_active = is_active
            rule.updated_at = datetime.utcnow()
            db.session.commit()
            return redirect('/rules')
    
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Editar Regra - Bot ML</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }}
            .form-card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
            .form-group {{ margin-bottom: 20px; }}
            .form-group label {{ display: block; margin-bottom: 8px; font-weight: bold; color: #333; }}
            .form-group input, .form-group textarea {{ width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }}
            .form-group textarea {{ height: 120px; resize: vertical; }}
            .checkbox-group {{ display: flex; align-items: center; gap: 10px; }}
            .checkbox-group input {{ width: auto; }}
            .btn-group {{ display: flex; gap: 10px; margin-top: 20px; }}
            .btn {{ padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; text-align: center; border: none; cursor: pointer; }}
            .btn-primary {{ background: #3483fa; color: white; }}
            .btn-secondary {{ background: #6c757d; color: white; }}
            .back-btn {{ display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/rules" class="back-btn">← Voltar às Regras</a>
            
            <div class="header">
                <h1>✏️ Editar Regra #{rule.id}</h1>
            </div>
            
            <div class="form-card">
                <form method="POST">
                    <div class="form-group">
                        <label for="keywords">Palavras-chave (separadas por vírgula):</label>
                        <input type="text" id="keywords" name="keywords" value="{rule.keywords}" required>
                        <small>Exemplo: preço, valor, quanto custa</small>
                    </div>
                    
                    <div class="form-group">
                        <label for="response_text">Resposta automática:</label>
                        <textarea id="response_text" name="response_text" required>{rule.response_text}</textarea>
                    </div>
                    
                    <div class="form-group">
                        <div class="checkbox-group">
                            <input type="checkbox" id="is_active" name="is_active" {'checked' if rule.is_active else ''}>
                            <label for="is_active">Regra ativa</label>
                        </div>
                    </div>
                    
                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">💾 Salvar Alterações</button>
                        <a href="/rules" class="btn btn-secondary">❌ Cancelar</a>
                    </div>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/rules/add', methods=['GET', 'POST'])
def add_rule():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    if request.method == 'POST':
        keywords = request.form.get('keywords', '').strip()
        response_text = request.form.get('response_text', '').strip()
        is_active = request.form.get('is_active') == 'on'
        
        if keywords and response_text:
            new_rule = AutoResponse(
                user_id=user.id,
                keywords=keywords,
                response_text=response_text,
                is_active=is_active
            )
            db.session.add(new_rule)
            db.session.commit()
            return redirect('/rules')
    
    html = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Adicionar Regra - Bot ML</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }
            .container { max-width: 800px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }
            .form-card { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }
            .form-group { margin-bottom: 20px; }
            .form-group label { display: block; margin-bottom: 8px; font-weight: bold; color: #333; }
            .form-group input, .form-group textarea { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
            .form-group textarea { height: 120px; resize: vertical; }
            .checkbox-group { display: flex; align-items: center; gap: 10px; }
            .checkbox-group input { width: auto; }
            .btn-group { display: flex; gap: 10px; margin-top: 20px; }
            .btn { padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; text-align: center; border: none; cursor: pointer; }
            .btn-primary { background: #3483fa; color: white; }
            .btn-secondary { background: #6c757d; color: white; }
            .back-btn { display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/rules" class="back-btn">← Voltar às Regras</a>
            
            <div class="header">
                <h1>➕ Adicionar Nova Regra</h1>
            </div>
            
            <div class="form-card">
                <form method="POST">
                    <div class="form-group">
                        <label for="keywords">Palavras-chave (separadas por vírgula):</label>
                        <input type="text" id="keywords" name="keywords" required>
                        <small>Exemplo: preço, valor, quanto custa</small>
                    </div>
                    
                    <div class="form-group">
                        <label for="response_text">Resposta automática:</label>
                        <textarea id="response_text" name="response_text" required></textarea>
                    </div>
                    
                    <div class="form-group">
                        <div class="checkbox-group">
                            <input type="checkbox" id="is_active" name="is_active" checked>
                            <label for="is_active">Regra ativa</label>
                        </div>
                    </div>
                    
                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">💾 Salvar Regra</button>
                        <a href="/rules" class="btn btn-secondary">❌ Cancelar</a>
                    </div>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/rules/toggle/<int:rule_id>')
def toggle_rule(rule_id):
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    rule = AutoResponse.query.filter_by(id=rule_id, user_id=user.id).first()
    if rule:
        rule.is_active = not rule.is_active
        rule.updated_at = datetime.utcnow()
        db.session.commit()
    
    return redirect('/rules')

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
            .sync-btn {{ display: inline-block; background: #28a745; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; margin-left: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            <a href="/questions/sync" class="sync-btn">🔄 Sincronizar Perguntas</a>
            
            <div class="header">
                <h1>❓ Perguntas Recebidas</h1>
                <p>Últimas {len(questions)} perguntas</p>
            </div>
            
            {questions_html if questions_html else '<div class="question-card"><p>Nenhuma pergunta recebida ainda. O bot está monitorando a cada 60 segundos.</p></div>'}
        </div>
    </body>
    </html>
    """
    return html

@app.route('/questions/sync')
def sync_questions():
    if not _initialized:
        initialize_database()
    
    # Forçar sincronização de perguntas
    threading.Thread(target=lambda: process_questions(), daemon=True).start()
    
    return redirect('/questions')

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
                <div class="config-actions">
                    <span class="status {'active' if config.is_active else 'inactive'}">{status}</span>
                    <a href="/absence/edit/{config.id}" class="edit-btn">✏️ Editar</a>
                    <a href="/absence/toggle/{config.id}" class="toggle-btn">{'❌ Desativar' if config.is_active else '✅ Ativar'}</a>
                </div>
            </div>
            <div class="config-content">
                <p><strong>Mensagem:</strong> {config.message}</p>
                <p><strong>Horário:</strong> {config.start_time} às {config.end_time}</p>
                <p><strong>Dias:</strong> {', '.join(days)}</p>
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
            .config-actions {{ display: flex; gap: 10px; align-items: center; }}
            .status.active {{ color: #00a650; font-weight: bold; }}
            .status.inactive {{ color: #ff3333; font-weight: bold; }}
            .config-content p {{ margin-bottom: 10px; }}
            .back-btn, .edit-btn, .toggle-btn, .add-btn {{ display: inline-block; padding: 8px 16px; text-decoration: none; border-radius: 6px; font-size: 0.9em; }}
            .back-btn {{ background: #3483fa; color: white; margin-bottom: 20px; }}
            .edit-btn {{ background: #28a745; color: white; }}
            .toggle-btn {{ background: #ffc107; color: #212529; }}
            .add-btn {{ background: #17a2b8; color: white; margin-bottom: 20px; }}
            .actions {{ margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            
            <div class="header">
                <h1>🌙 Configurações de Ausência</h1>
                <p>Total: {len(configs)} configurações</p>
            </div>
            
            <div class="actions">
                <a href="/absence/add" class="add-btn">➕ Adicionar Nova Configuração</a>
            </div>
            
            {configs_html}
        </div>
    </body>
    </html>
    """
    return html

@app.route('/absence/edit/<int:config_id>', methods=['GET', 'POST'])
def edit_absence(config_id):
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    config = AbsenceConfig.query.filter_by(id=config_id, user_id=user.id).first()
    if not config:
        return "❌ Configuração não encontrada", 404
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        message = request.form.get('message', '').strip()
        start_time = request.form.get('start_time', '').strip()
        end_time = request.form.get('end_time', '').strip()
        days_of_week = ','.join(request.form.getlist('days_of_week'))
        is_active = request.form.get('is_active') == 'on'
        
        if name and message and start_time and end_time and days_of_week:
            config.name = name
            config.message = message
            config.start_time = start_time
            config.end_time = end_time
            config.days_of_week = days_of_week
            config.is_active = is_active
            db.session.commit()
            return redirect('/absence')
    
    selected_days = config.days_of_week.split(',')
    
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Editar Ausência - Bot ML</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }}
            .form-card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
            .form-group {{ margin-bottom: 20px; }}
            .form-group label {{ display: block; margin-bottom: 8px; font-weight: bold; color: #333; }}
            .form-group input, .form-group textarea {{ width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }}
            .form-group textarea {{ height: 120px; resize: vertical; }}
            .checkbox-group {{ display: flex; align-items: center; gap: 10px; }}
            .checkbox-group input {{ width: auto; }}
            .days-group {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }}
            .btn-group {{ display: flex; gap: 10px; margin-top: 20px; }}
            .btn {{ padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; text-align: center; border: none; cursor: pointer; }}
            .btn-primary {{ background: #3483fa; color: white; }}
            .btn-secondary {{ background: #6c757d; color: white; }}
            .back-btn {{ display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/absence" class="back-btn">← Voltar às Configurações</a>
            
            <div class="header">
                <h1>✏️ Editar Configuração de Ausência</h1>
            </div>
            
            <div class="form-card">
                <form method="POST">
                    <div class="form-group">
                        <label for="name">Nome da configuração:</label>
                        <input type="text" id="name" name="name" value="{config.name}" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="message">Mensagem de ausência:</label>
                        <textarea id="message" name="message" required>{config.message}</textarea>
                    </div>
                    
                    <div class="form-group">
                        <label for="start_time">Horário de início:</label>
                        <input type="time" id="start_time" name="start_time" value="{config.start_time}" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="end_time">Horário de fim:</label>
                        <input type="time" id="end_time" name="end_time" value="{config.end_time}" required>
                    </div>
                    
                    <div class="form-group">
                        <label>Dias da semana:</label>
                        <div class="days-group">
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_0" name="days_of_week" value="0" {'checked' if '0' in selected_days else ''}>
                                <label for="day_0">Segunda</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_1" name="days_of_week" value="1" {'checked' if '1' in selected_days else ''}>
                                <label for="day_1">Terça</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_2" name="days_of_week" value="2" {'checked' if '2' in selected_days else ''}>
                                <label for="day_2">Quarta</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_3" name="days_of_week" value="3" {'checked' if '3' in selected_days else ''}>
                                <label for="day_3">Quinta</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_4" name="days_of_week" value="4" {'checked' if '4' in selected_days else ''}>
                                <label for="day_4">Sexta</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_5" name="days_of_week" value="5" {'checked' if '5' in selected_days else ''}>
                                <label for="day_5">Sábado</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_6" name="days_of_week" value="6" {'checked' if '6' in selected_days else ''}>
                                <label for="day_6">Domingo</label>
                            </div>
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <div class="checkbox-group">
                            <input type="checkbox" id="is_active" name="is_active" {'checked' if config.is_active else ''}>
                            <label for="is_active">Configuração ativa</label>
                        </div>
                    </div>
                    
                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">💾 Salvar Alterações</button>
                        <a href="/absence" class="btn btn-secondary">❌ Cancelar</a>
                    </div>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/absence/add', methods=['GET', 'POST'])
def add_absence():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        message = request.form.get('message', '').strip()
        start_time = request.form.get('start_time', '').strip()
        end_time = request.form.get('end_time', '').strip()
        days_of_week = ','.join(request.form.getlist('days_of_week'))
        is_active = request.form.get('is_active') == 'on'
        
        if name and message and start_time and end_time and days_of_week:
            new_config = AbsenceConfig(
                user_id=user.id,
                name=name,
                message=message,
                start_time=start_time,
                end_time=end_time,
                days_of_week=days_of_week,
                is_active=is_active
            )
            db.session.add(new_config)
            db.session.commit()
            return redirect('/absence')
    
    html = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Adicionar Ausência - Bot ML</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }
            .container { max-width: 800px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; text-align: center; }
            .form-card { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }
            .form-group { margin-bottom: 20px; }
            .form-group label { display: block; margin-bottom: 8px; font-weight: bold; color: #333; }
            .form-group input, .form-group textarea { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
            .form-group textarea { height: 120px; resize: vertical; }
            .checkbox-group { display: flex; align-items: center; gap: 10px; }
            .checkbox-group input { width: auto; }
            .days-group { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
            .btn-group { display: flex; gap: 10px; margin-top: 20px; }
            .btn { padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; text-align: center; border: none; cursor: pointer; }
            .btn-primary { background: #3483fa; color: white; }
            .btn-secondary { background: #6c757d; color: white; }
            .back-btn { display: inline-block; background: #3483fa; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/absence" class="back-btn">← Voltar às Configurações</a>
            
            <div class="header">
                <h1>➕ Adicionar Configuração de Ausência</h1>
            </div>
            
            <div class="form-card">
                <form method="POST">
                    <div class="form-group">
                        <label for="name">Nome da configuração:</label>
                        <input type="text" id="name" name="name" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="message">Mensagem de ausência:</label>
                        <textarea id="message" name="message" required></textarea>
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
                        <label>Dias da semana:</label>
                        <div class="days-group">
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_0" name="days_of_week" value="0">
                                <label for="day_0">Segunda</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_1" name="days_of_week" value="1">
                                <label for="day_1">Terça</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_2" name="days_of_week" value="2">
                                <label for="day_2">Quarta</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_3" name="days_of_week" value="3">
                                <label for="day_3">Quinta</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_4" name="days_of_week" value="4">
                                <label for="day_4">Sexta</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_5" name="days_of_week" value="5">
                                <label for="day_5">Sábado</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="day_6" name="days_of_week" value="6">
                                <label for="day_6">Domingo</label>
                            </div>
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <div class="checkbox-group">
                            <input type="checkbox" id="is_active" name="is_active" checked>
                            <label for="is_active">Configuração ativa</label>
                        </div>
                    </div>
                    
                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">💾 Salvar Configuração</button>
                        <a href="/absence" class="btn btn-secondary">❌ Cancelar</a>
                    </div>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/absence/toggle/<int:config_id>')
def toggle_absence(config_id):
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return "❌ Usuário não encontrado", 404
    
    config = AbsenceConfig.query.filter_by(id=config_id, user_id=user.id).first()
    if config:
        config.is_active = not config.is_active
        db.session.commit()
    
    return redirect('/absence')

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

# APIs para dados
@app.route('/api/ml/rules')
def api_rules():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    
    rules = AutoResponse.query.filter_by(user_id=user.id).all()
    
    return jsonify([{
        "id": rule.id,
        "keywords": rule.keywords,
        "response": rule.response_text,
        "active": rule.is_active
    } for rule in rules])

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

@app.route('/api/ml/absence')
def api_absence():
    if not _initialized:
        initialize_database()
    
    user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
    if not user:
        return jsonify({"error": "Usuário não encontrado"}), 404
    
    configs = AbsenceConfig.query.filter_by(user_id=user.id).all()
    
    return jsonify([{
        "id": config.id,
        "name": config.name,
        "message": config.message,
        "start_time": config.start_time,
        "end_time": config.end_time,
        "days": config.days_of_week,
        "active": config.is_active
    } for config in configs])

# Inicializar aplicação
initialize_database()

# Iniciar monitoramento
monitor_thread = threading.Thread(target=monitor_questions, daemon=True)
monitor_thread.start()
print("✅ Monitoramento de perguntas iniciado!")

# Iniciar monitoramento de token
token_thread = threading.Thread(target=monitor_token, daemon=True)
token_thread.start()
print("✅ Monitoramento de token iniciado!")


# Iniciar monitoramento de token
token_thread = threading.Thread(target=monitor_token, daemon=True)
token_thread.start()
print("✅ Monitoramento de token iniciado!")


print("🚀 Bot do Mercado Livre iniciado com sucesso!")
print(f"🔑 Token: {ML_ACCESS_TOKEN[:20]}...")
print(f"👤 User ID: {ML_USER_ID}")

if __name__ == '__main__':
    # Executar aplicação
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)

