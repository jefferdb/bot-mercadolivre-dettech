import os
import time
import threading
from threading import Lock
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests

# Configuração da aplicação
app = Flask(__name__)
CORS(app)

# Configuração do banco SQLite persistente
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////opt/render/project/src/data/bot_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Lock para controle de acesso ao banco
db_lock = Lock()

# Configurações do Mercado Livre - TOKENS ATUALIZADOS
ML_ACCESS_TOKEN = 'APP_USR-5510376630479325-072423-41cbc33fddb983f73eaf5aa1b1b7f699-180617463'
ML_CLIENT_ID = '5510376630479325'
ML_CLIENT_SECRET = 'jlR4As2x8uFY3RTpysLpuPhzC9yM9d35'
ML_USER_ID = '180617463'

# Modelos do banco de dados
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    ml_user_id = db.Column(db.String(50), unique=True, nullable=False)
    access_token = db.Column(db.String(200), nullable=False)
    refresh_token = db.Column(db.String(200), nullable=False)
    token_expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.String(100), unique=True, nullable=False)
    item_id = db.Column(db.String(100), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text)
    is_answered = db.Column(db.Boolean, default=False)
    answered_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AutoResponse(db.Model):
    __tablename__ = 'auto_responses'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    keywords = db.Column(db.String(500), nullable=False)
    response_text = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
def create_tables_and_data():
    global _initialized
    if _initialized:
        return
    
    with db_lock:
        try:
            with app.app_context():
                db.create_all()
                
                # Verificar se usuário já existe
                user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
                if not user:
                    # Criar usuário com tokens atuais
                    expires_at = datetime.utcnow() + timedelta(seconds=21600)  # 6 horas
                    user = User(
                        ml_user_id=ML_USER_ID,
                        access_token=ML_ACCESS_TOKEN,
                        refresh_token='TG-6882f8e7f04d54000...',  # Será atualizado na primeira renovação
                        token_expires_at=expires_at
                    )
                    db.session.add(user)
                
                # Criar respostas automáticas padrão se não existirem
                if AutoResponse.query.filter_by(user_id=user.id if user.id else 1).count() == 0:
                    default_responses = [
                        ("preço,valor,custa,quanto", "Obrigado pela pergunta! O preço está na descrição do anúncio. Qualquer dúvida, estou à disposição!"),
                        ("entrega,envio,frete", "Trabalhamos com entrega para todo o Brasil! O prazo e valor do frete são calculados automaticamente no checkout."),
                        ("disponível,estoque,tem", "Sim, temos disponível! Pode fazer sua compra com tranquilidade."),
                        ("garantia,defeito,problema", "Oferecemos garantia conforme legislação. Em caso de problemas, entre em contato que resolveremos rapidamente!"),
                        ("pagamento,cartão,boleto,pix", "Aceitamos todas as formas de pagamento do Mercado Livre: cartão, boleto, Pix e Mercado Pago."),
                        ("tamanho,medida,dimensão", "As medidas estão detalhadas na descrição do produto. Qualquer dúvida específica, me informe!"),
                        ("cor,cores,colorido", "Temos as cores disponíveis mostradas nas fotos. Você pode escolher na hora da compra!"),
                        ("usado,novo,estado", "Todos os nossos produtos são novos e originais, conforme descrito no anúncio."),
                        ("horário,atendimento,funciona", "Nosso horário de atendimento é das 8h às 18h, de segunda a sexta. Responderemos assim que possível!"),
                        ("dúvida,pergunta,informação", "Fico à disposição para esclarecer qualquer dúvida! Pode perguntar que respondo rapidamente.")
                    ]
                    
                    for keywords, response in default_responses:
                        auto_response = AutoResponse(
                            user_id=user.id if user.id else 1,
                            keywords=keywords,
                            response_text=response
                        )
                        db.session.add(auto_response)
                
                # Criar configurações de ausência padrão
                if AbsenceConfig.query.filter_by(user_id=user.id if user.id else 1).count() == 0:
                    absence_configs = [
                        ("Horário Noturno", "Obrigado pela pergunta! Nosso atendimento é das 8h às 18h. Responderemos sua dúvida no próximo dia útil!", "18:00", "08:00", "0,1,2,3,4,5,6"),
                        ("Final de Semana", "Obrigado pelo contato! Atendemos de segunda a sexta. Sua pergunta será respondida no próximo dia útil!", "00:00", "23:59", "0,6")
                    ]
                    
                    for name, message, start_time, end_time, days in absence_configs:
                        config = AbsenceConfig(
                            user_id=user.id if user.id else 1,
                            name=name,
                            message=message,
                            start_time=start_time,
                            end_time=end_time,
                            days_of_week=days
                        )
                        db.session.add(config)
                
                db.session.commit()
                print("✅ Banco de dados inicializado com sucesso!")
                _initialized = True
                
        except Exception as e:
            print(f"❌ Erro ao inicializar banco: {e}")

def initialize_database():
    if not _initialized:
        create_tables_and_data()

# Função para verificar se está em horário de ausência
def is_absence_time():
    with db_lock:
        try:
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
        except Exception as e:
            print(f"❌ Erro ao verificar horário de ausência: {e}")
            return None

# Função para renovar token automaticamente
def renew_access_token():
    global ML_ACCESS_TOKEN
    
    with db_lock:
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
            
            print(f"🔄 Renovando token para usuário {ML_USER_ID}...")
            
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
                
                # Atualizar token global
                ML_ACCESS_TOKEN = new_access_token
                
                # Log da renovação
                log = TokenLog(
                    user_id=user.id,
                    action="renewed",
                    old_token=old_token[:20] + "..." if old_token else None,
                    new_token=new_access_token[:20] + "..." if new_access_token else None,
                    expires_at=user.token_expires_at,
                    message=f"Token renovado com sucesso. Expira em {expires_in} segundos."
                )
                db.session.add(log)
                db.session.commit()
                
                print(f"✅ Token renovado com sucesso! Expira em {expires_in} segundos")
                return True
            else:
                error_msg = f"Erro ao renovar token: {response.status_code} - {response.text}"
                print(f"❌ {error_msg}")
                
                log = TokenLog(
                    user_id=user.id,
                    action="renewal_failed",
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
    with db_lock:
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

def find_auto_response(question_text):
    with db_lock:
        try:
            question_lower = question_text.lower()
            
            # Forçar busca nova do banco
            db.session.expire_all()
            auto_responses = AutoResponse.query.filter_by(is_active=True).all()
            
            for response in auto_responses:
                keywords = [k.strip().lower() for k in response.keywords.split(',')]
                
                for keyword in keywords:
                    if keyword in question_lower:
                        return response.response_text
            
            return None
        except Exception as e:
            print(f"❌ Erro ao buscar resposta automática: {e}")
            return None

def get_questions_from_ml():
    with db_lock:
        try:
            url = f"https://api.mercadolibre.com/my/received_questions/search"
            headers = {"Authorization": f"Bearer {ML_ACCESS_TOKEN}"}
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('questions', [])
            else:
                print(f"❌ Erro ao buscar perguntas: {response.status_code}")
                return []
        except Exception as e:
            print(f"❌ Erro ao conectar com ML: {e}")
            return []

def answer_question(question_id, answer_text):
    with db_lock:
        try:
            url = f"https://api.mercadolibre.com/answers"
            headers = {
                "Authorization": f"Bearer {ML_ACCESS_TOKEN}",
                "Content-Type": "application/json"
            }
            
            data = {
                "question_id": question_id,
                "text": answer_text
            }
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                print(f"✅ Pergunta {question_id} respondida com sucesso!")
                return True
            else:
                print(f"❌ Erro ao responder pergunta {question_id}: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Erro ao responder pergunta: {e}")
            return False

def process_questions():
    with db_lock:
        try:
            initialize_database()
            
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                print("❌ Usuário não encontrado")
                return
            
            questions = get_questions_from_ml()
            
            for q in questions:
                if q.get('status') == 'UNANSWERED':
                    question_id = str(q.get('id'))
                    question_text = q.get('text', '')
                    item_id = str(q.get('item_id', ''))
                    
                    # Verificar se já processamos esta pergunta
                    existing = Question.query.filter_by(question_id=question_id).first()
                    if existing:
                        continue
                    
                    print(f"📝 Nova pergunta: {question_text}")
                    
                    # Verificar horário de ausência
                    absence_message = is_absence_time()
                    if absence_message:
                        response_text = absence_message
                        print(f"🌙 Horário de ausência - enviando: {response_text}")
                    else:
                        # Buscar resposta automática
                        response_text = find_auto_response(question_text)
                        if response_text:
                            print(f"🤖 Resposta automática encontrada: {response_text}")
                        else:
                            print("❓ Nenhuma resposta automática encontrada")
                            continue
                    
                    # Responder a pergunta
                    if answer_question(question_id, response_text):
                        # Salvar no banco
                        question_record = Question(
                            user_id=user.id,
                            question_id=question_id,
                            item_id=item_id,
                            question_text=question_text,
                            response_text=response_text,
                            is_answered=True,
                            answered_at=datetime.utcnow()
                        )
                        db.session.add(question_record)
                        db.session.commit()
                        print(f"✅ Pergunta salva no banco de dados")
                    
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
    with db_lock:
        try:
            initialize_database()
            
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return "❌ Usuário não encontrado", 404
            
            # Estatísticas
            total_questions = Question.query.filter_by(user_id=user.id).count()
            answered_questions = Question.query.filter_by(user_id=user.id, is_answered=True).count()
            pending_questions = total_questions - answered_questions
            success_rate = (answered_questions / total_questions * 100) if total_questions > 0 else 0
            
            # Perguntas recentes
            recent_questions = Question.query.filter_by(user_id=user.id).order_by(Question.created_at.desc()).limit(10).all()
            
            # Status do token
            token_status = "Válido"
            token_expires = "N/A"
            if user.token_expires_at:
                now = datetime.utcnow()
                if user.token_expires_at > now:
                    time_left = user.token_expires_at - now
                    hours = int(time_left.total_seconds() // 3600)
                    minutes = int((time_left.total_seconds() % 3600) // 60)
                    token_expires = f"{hours}h {minutes}m"
                else:
                    token_status = "Expirado"
                    token_expires = "Expirado"
            
            # Contadores de regras e configurações
            active_rules = AutoResponse.query.filter_by(user_id=user.id, is_active=True).count()
            active_configs = AbsenceConfig.query.filter_by(user_id=user.id, is_active=True).count()
            
            questions_html = ""
            for q in recent_questions:
                status_icon = "✅" if q.is_answered else "❓"
                answered_text = f"<br><strong>Resposta:</strong> {q.response_text}" if q.response_text else ""
                questions_html += f"""
                <div class="question-card">
                    <div class="question-header">
                        <span class="status">{status_icon}</span>
                        <span class="date">{q.created_at.strftime('%d/%m/%Y %H:%M')}</span>
                    </div>
                    <div class="question-content">
                        <strong>Pergunta:</strong> {q.question_text}
                        {answered_text}
                    </div>
                </div>
                """
            
            return render_template_string("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Bot Mercado Livre - Dashboard</title>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    * { margin: 0; padding: 0; box-sizing: border-box; }
                    body { font-family: Arial, sans-serif; background: #f5f5f5; }
                    .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
                    .header { background: #3483fa; color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
                    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }
                    .stat-card { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); text-align: center; }
                    .stat-number { font-size: 2em; font-weight: bold; color: #3483fa; }
                    .stat-label { color: #666; margin-top: 5px; }
                    .section { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin-bottom: 20px; }
                    .section h2 { color: #333; margin-bottom: 15px; }
                    .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; }
                    .status-item { padding: 15px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #3483fa; }
                    .question-card { background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid #3483fa; }
                    .question-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
                    .status { font-size: 1.2em; }
                    .date { color: #666; font-size: 0.9em; }
                    .question-content { line-height: 1.5; }
                    .nav-buttons { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
                    .btn { padding: 10px 20px; background: #3483fa; color: white; text-decoration: none; border-radius: 5px; display: inline-block; }
                    .btn:hover { background: #2968c8; }
                    .success { color: #28a745; }
                    .warning { color: #ffc107; }
                    .danger { color: #dc3545; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🤖 Bot do Mercado Livre - Dashboard</h1>
                        <p>Monitoramento e automação de respostas</p>
                    </div>
                    
                    <div class="nav-buttons">
                        <a href="/rules" class="btn">📋 Regras de Resposta</a>
                        <a href="/absence" class="btn">🌙 Configurações de Ausência</a>
                        <a href="/questions" class="btn">❓ Perguntas Recebidas</a>
                        <a href="/questions/sync" class="btn">🔄 Sincronizar Perguntas</a>
                    </div>
                    
                    <div class="stats">
                        <div class="stat-card">
                            <div class="stat-number">{{ total_questions }}</div>
                            <div class="stat-label">Perguntas Recebidas</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{{ answered_questions }}</div>
                            <div class="stat-label">Respondidas</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{{ pending_questions }}</div>
                            <div class="stat-label">Pendentes</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">{{ "%.1f"|format(success_rate) }}%</div>
                            <div class="stat-label">Taxa de Sucesso</div>
                        </div>
                    </div>
                    
                    <div class="section">
                        <h2>📊 Status do Sistema</h2>
                        <div class="status-grid">
                            <div class="status-item">
                                <strong>🔑 Token:</strong> 
                                <span class="{{ 'success' if token_status == 'Válido' else 'danger' }}">{{ token_status }}</span>
                                <br><small>Expira em: {{ token_expires }}</small>
                            </div>
                            <div class="status-item">
                                <strong>🤖 Status:</strong> 
                                <span class="success">Conectado</span>
                                <br><small>Monitoramento ativo</small>
                            </div>
                            <div class="status-item">
                                <strong>📋 Regras Ativas:</strong> {{ active_rules }}
                                <br><small>Respostas automáticas</small>
                            </div>
                            <div class="status-item">
                                <strong>🌙 Configurações:</strong> {{ active_configs }}
                                <br><small>Horários de ausência</small>
                            </div>
                        </div>
                    </div>
                    
                    <div class="section">
                        <h2>❓ Perguntas Recentes</h2>
                        {{ questions_html|safe if questions_html else '<div class="question-card"><p>Aguardando perguntas... Bot monitorando a cada 60 segundos.</p></div>' }}
                    </div>
                </div>
            </body>
            </html>
            """, 
            total_questions=total_questions,
            answered_questions=answered_questions, 
            pending_questions=pending_questions,
            success_rate=success_rate,
            questions_html=questions_html,
            token_status=token_status,
            token_expires=token_expires,
            active_rules=active_rules,
            active_configs=active_configs
            )
        except Exception as e:
            return f"❌ Erro: {e}", 500

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

print("🚀 Bot do Mercado Livre iniciado com sucesso!")
print(f"🔑 Token: {ML_ACCESS_TOKEN[:20]}...")
print(f"👤 User ID: {ML_USER_ID}")

if __name__ == '__main__':
    # Executar aplicação
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)

