import os
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests

# Configuração da aplicação
app = Flask(__name__)
CORS(app)

# Configuração do banco SQLite em memória
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
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

# Variável global para controlar inicialização
_initialized = False

# Função para criar tabelas e dados iniciais
def initialize_database():
    global _initialized
    if _initialized:
        return
    
    try:
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
        initialize_database()  # Garantir que banco está inicializado
        
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
            process_questions()
            time.sleep(60)  # Verificar a cada 60 segundos
        except Exception as e:
            print(f"❌ Erro no monitoramento: {e}")
            time.sleep(60)

# Rotas da aplicação
@app.route('/')
def dashboard():
    initialize_database()  # Garantir que banco está inicializado
    
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
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            
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
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            
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
            threading.Thread(target=process_questions, daemon=True).start()
            
            return jsonify({"status": "ok", "message": "notificação processada"})
        
        return jsonify({"status": "ok", "message": "webhook recebido"})
        
    except Exception as e:
        print(f"❌ Erro no webhook: {e}")
        return jsonify({"error": str(e)}), 500

# APIs para dados
@app.route('/api/ml/rules')
def api_rules():
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

# Inicializar banco na primeira requisição
@app.before_first_request
def before_first_request():
    initialize_database()
    
    # Iniciar monitoramento em thread separada
    monitor_thread = threading.Thread(target=monitor_questions, daemon=True)
    monitor_thread.start()
    print("✅ Monitoramento de perguntas iniciado!")
    
    print("🚀 Bot do Mercado Livre iniciado com sucesso!")
    print(f"🔑 Token: {ML_ACCESS_TOKEN[:20]}...")
    print(f"👤 User ID: {ML_USER_ID}")

if __name__ == '__main__':
    # Executar aplicação
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)

