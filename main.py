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

# Configuração do banco SQLite persistente
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////opt/render/project/src/data/bot_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configurações do Mercado Livre - TOKENS ATUALIZADOS
ML_ACCESS_TOKEN = 'APP_USR-5510376630479325-072423-41cbc33fddb983f73eaf5aa1b1b7f699-180617463'
ML_CLIENT_ID = '5510376630479325'
ML_CLIENT_SECRET = 'jlR4As2x8uFY3RTpysLpuPhzC9yM9d35'
ML_USER_ID = '180617463'

# Variável global para controlar token
current_token = ML_ACCESS_TOKEN
token_expires_at = None

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

# Função para GARANTIR criação do usuário
def ensure_user_exists():
    global token_expires_at
    
    try:
        print(f"🔍 Procurando usuário com ML_USER_ID: {ML_USER_ID}")
        
        # Buscar usuário
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        
        if user:
            print(f"✅ Usuário encontrado: ID {user.id}")
            token_expires_at = user.token_expires_at
            return user
        
        print("❌ Usuário não encontrado. Criando novo usuário...")
        
        # Criar usuário
        user = User(
            ml_user_id=ML_USER_ID,
            access_token=ML_ACCESS_TOKEN,
            refresh_token='TG-6882f8e7f04d54000...',  # Placeholder
            token_expires_at=datetime.utcnow() + timedelta(hours=6)
        )
        
        db.session.add(user)
        db.session.commit()
        
        print(f"✅ Usuário criado com sucesso! ID: {user.id}")
        
        # Criar regras de resposta padrão
        default_responses = [
            ("preço,valor,custa,quanto", "Obrigado pela pergunta! O preço está na descrição do anúncio. Qualquer dúvida, estamos à disposição!"),
            ("entrega,envio,frete", "Trabalhamos com entrega para todo o Brasil via Mercado Envios. O prazo e valor aparecem no anúncio."),
            ("disponível,estoque,tem", "Sim, temos disponível! Pode fazer sua compra com tranquilidade."),
            ("garantia", "Oferecemos garantia conforme especificado no anúncio. Estamos sempre à disposição!"),
            ("desconto,promoção", "Os melhores preços já estão aplicados! Aproveite nossas ofertas."),
            ("pagamento,cartão,pix", "Aceitamos todas as formas de pagamento do Mercado Livre: cartão, PIX, boleto."),
            ("dúvida,informação,detalhes", "Ficamos felizes em ajudar! Todas as informações estão na descrição. Qualquer dúvida, pergunte!"),
            ("horário,atendimento", "Nosso horário de atendimento é das 8h às 18h, de segunda a sexta. Responderemos assim que possível!"),
            ("qualidade,original", "Trabalhamos apenas com produtos de qualidade e originais. Sua satisfação é nossa prioridade!"),
            ("tamanho,medida,dimensão", "As medidas e especificações estão detalhadas na descrição do produto. Confira lá!")
        ]
        
        for keywords, response in default_responses:
            auto_response = AutoResponse(
                user_id=user.id,
                keywords=keywords,
                response_text=response
            )
            db.session.add(auto_response)
        
        # Criar configurações de ausência padrão
        absence_configs = [
            ("Horário Comercial", "Obrigado pela pergunta! Nosso atendimento é das 8h às 18h. Responderemos em breve!", "18:00", "08:00", "0,1,2,3,4,5,6"),
            ("Final de Semana", "Obrigado pelo contato! Não trabalhamos aos finais de semana. Responderemos na segunda-feira!", "00:00", "23:59", "5,6")
        ]
        
        for name, message, start, end, days in absence_configs:
            config = AbsenceConfig(
                user_id=user.id,
                name=name,
                message=message,
                start_time=start,
                end_time=end,
                days_of_week=days,
                is_active=False  # Desativado por padrão
            )
            db.session.add(config)
        
        db.session.commit()
        print("✅ Dados iniciais criados com sucesso!")
        
        token_expires_at = user.token_expires_at
        return user
        
    except Exception as e:
        print(f"❌ Erro ao garantir usuário: {e}")
        db.session.rollback()
        return None

# Função para inicializar banco
def initialize_database():
    global _initialized
    if _initialized:
        return
    
    try:
        with app.app_context():
            print("🔄 Inicializando banco de dados...")
            
            # Criar todas as tabelas
            db.create_all()
            print("✅ Tabelas criadas/verificadas")
            
            # Garantir que usuário existe
            user = ensure_user_exists()
            if user:
                print("✅ Usuário garantido no banco")
                _initialized = True
            else:
                print("❌ Falha ao garantir usuário")
                
    except Exception as e:
        print(f"❌ Erro ao inicializar banco: {e}")

# Função SIMPLES para renovar token
def renew_token_simple():
    global current_token, token_expires_at
    
    try:
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user or not user.refresh_token:
            print("❌ Usuário ou refresh_token não encontrado")
            return False
        
        # Dados para renovação
        data = {
            "grant_type": "refresh_token",
            "client_id": ML_CLIENT_ID,
            "client_secret": ML_CLIENT_SECRET,
            "refresh_token": user.refresh_token
        }
        
        print("🔄 Renovando token...")
        response = requests.post("https://api.mercadolibre.com/oauth/token", data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            
            # Atualizar token
            new_token = token_data.get("access_token")
            new_refresh = token_data.get("refresh_token", user.refresh_token)
            expires_in = token_data.get("expires_in", 21600)
            
            # Atualizar no banco
            user.access_token = new_token
            user.refresh_token = new_refresh
            user.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            user.updated_at = datetime.utcnow()
            
            # Atualizar variáveis globais
            current_token = new_token
            token_expires_at = user.token_expires_at
            
            # Log da renovação
            log = TokenLog(
                user_id=user.id,
                action="renewed",
                old_token=current_token[:20] + "..." if current_token else None,
                new_token=new_token[:20] + "..." if new_token else None,
                expires_at=token_expires_at,
                message=f"Token renovado com sucesso. Expira em {expires_in} segundos."
            )
            db.session.add(log)
            db.session.commit()
            
            print(f"✅ Token renovado! Expira em {expires_in} segundos")
            return True
        else:
            print(f"❌ Erro ao renovar token: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Erro na renovação: {e}")
        return False

# Função para verificar se token precisa renovação
def check_and_renew_token():
    global token_expires_at
    
    try:
        if not token_expires_at:
            return True
            
        now = datetime.utcnow()
        time_left = token_expires_at - now
        
        # Se faltam menos de 1 hora, renovar
        if time_left.total_seconds() < 3600:  # 1 hora
            print(f"⏰ Token expira em {time_left}. Renovando...")
            return renew_token_simple()
        else:
            hours_left = int(time_left.total_seconds() / 3600)
            print(f"✅ Token válido por mais {hours_left} horas")
            return True
            
    except Exception as e:
        print(f"❌ Erro ao verificar token: {e}")
        return False

# Função para verificar se está em horário de ausência
def is_absence_time():
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

def find_auto_response(question_text):
    question_lower = question_text.lower()
    
    auto_responses = AutoResponse.query.filter_by(is_active=True).all()
    
    for response in auto_responses:
        keywords = [k.strip().lower() for k in response.keywords.split(',')]
        
        for keyword in keywords:
            if keyword in question_lower:
                return response.response_text
    
    return None

def answer_question(question_id, answer_text):
    try:
        url = f"https://api.mercadolibre.com/answers"
        
        data = {
            "question_id": question_id,
            "text": answer_text
        }
        
        headers = {
            "Authorization": f"Bearer {current_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 200:
            print(f"✅ Pergunta {question_id} respondida com sucesso!")
            return True
        else:
            print(f"❌ Erro ao responder pergunta {question_id}: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Erro ao responder pergunta: {e}")
        return False

def get_unanswered_questions():
    try:
        # Verificar e renovar token se necessário
        if not check_and_renew_token():
            print("❌ Falha ao verificar/renovar token")
            return []
        
        url = f"https://api.mercadolibre.com/my/received_questions/search?status=UNANSWERED"
        
        headers = {
            "Authorization": f"Bearer {current_token}"
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            questions = data.get('questions', [])
            print(f"📨 Encontradas {len(questions)} perguntas não respondidas")
            return questions
        else:
            print(f"❌ Erro ao buscar perguntas: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ Erro ao buscar perguntas: {e}")
        return []

def process_questions():
    try:
        initialize_database()
        
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user:
            print("❌ Usuário não encontrado")
            return
        
        questions = get_unanswered_questions()
        
        for q in questions:
            question_id = q.get('id')
            question_text = q.get('text', '')
            item_id = q.get('item_id', '')
            
            # Verificar se já processamos esta pergunta
            existing = Question.query.filter_by(question_id=str(question_id)).first()
            if existing:
                continue
            
            # Salvar pergunta no banco
            question_record = Question(
                user_id=user.id,
                question_id=str(question_id),
                item_id=str(item_id),
                question_text=question_text
            )
            db.session.add(question_record)
            
            print(f"📝 Nova pergunta: {question_text}")
            
            # Verificar horário de ausência
            absence_msg = is_absence_time()
            if absence_msg:
                answer_text = absence_msg
                print(f"🌙 Horário de ausência - Respondendo: {answer_text}")
            else:
                # Buscar resposta automática
                answer_text = find_auto_response(question_text)
                if answer_text:
                    print(f"🤖 Resposta automática encontrada: {answer_text}")
                else:
                    print(f"❓ Nenhuma resposta automática encontrada")
                    continue
            
            # Responder pergunta
            if answer_question(question_id, answer_text):
                question_record.response_text = answer_text
                question_record.is_answered = True
                question_record.answered_at = datetime.utcnow()
                print(f"✅ Pergunta respondida automaticamente!")
            
            db.session.commit()
            
    except Exception as e:
        print(f"❌ Erro ao processar perguntas: {e}")

# Função de monitoramento SIMPLES
def monitor_questions():
    token_check_counter = 0
    while True:
        try:
            with app.app_context():
                # Verificar token a cada 5 horas (300 ciclos de 60s)
                if token_check_counter % 300 == 0:
                    check_and_renew_token()
                
                process_questions()
                token_check_counter += 1
                
            time.sleep(60)  # Verificar perguntas a cada 60 segundos
        except Exception as e:
            print(f"❌ Erro no monitoramento: {e}")
            time.sleep(60)

# Rotas da aplicação
@app.route('/')
def dashboard():
    try:
        initialize_database()
        
        # Debug: Listar todos os usuários
        all_users = User.query.all()
        print(f"🔍 DEBUG: Total de usuários no banco: {len(all_users)}")
        for u in all_users:
            print(f"   - ID: {u.id}, ML_USER_ID: {u.ml_user_id}")
        
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user:
            print(f"❌ DEBUG: Usuário com ML_USER_ID '{ML_USER_ID}' não encontrado")
            # Tentar criar usuário na hora
            user = ensure_user_exists()
            if not user:
                return f"❌ Erro: Não foi possível criar usuário com ML_USER_ID: {ML_USER_ID}", 404
        
        print(f"✅ DEBUG: Usuário encontrado - ID: {user.id}")
        
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
                .header { background: #3483fa; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
                .stat-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .stat-number { font-size: 2em; font-weight: bold; color: #3483fa; }
                .stat-label { color: #666; margin-top: 5px; }
                .section { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }
                .question-card { border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 10px; }
                .question-header { display: flex; justify-content: space-between; margin-bottom: 10px; }
                .status { font-size: 1.2em; }
                .date { color: #666; font-size: 0.9em; }
                .nav { display: flex; gap: 10px; margin-bottom: 20px; }
                .nav a { background: #3483fa; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }
                .nav a:hover { background: #2968c8; }
                .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; }
                .status-item { padding: 10px; background: #f8f9fa; border-radius: 5px; }
                .success { background: #d4edda; color: #155724; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
                .debug { background: #fff3cd; color: #856404; padding: 15px; border-radius: 5px; margin-bottom: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="success">
                    ✅ <strong>Usuário encontrado e funcionando!</strong> Sistema operacional.
                </div>
                
                <div class="debug">
                    🔍 <strong>Debug Info:</strong> User ID: {{ user.id }} | ML_USER_ID: {{ user.ml_user_id }}
                </div>
                
                <div class="header">
                    <h1>🤖 Bot Mercado Livre - Dashboard</h1>
                    <p>Sistema de Resposta Automática - Renovação a cada 5 horas</p>
                </div>
                
                <div class="nav">
                    <a href="/">📊 Dashboard</a>
                    <a href="/rules">📝 Regras de Resposta</a>
                    <a href="/absence">🌙 Configurações de Ausência</a>
                    <a href="/questions">❓ Perguntas Recebidas</a>
                </div>
                
                <div class="stats">
                    <div class="stat-card">
                        <div class="stat-number">{{ total_questions }}</div>
                        <div class="stat-label">Total de Perguntas</div>
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
                            <strong>🔗 Status:</strong> Conectado
                            <br><small>Bot funcionando normalmente</small>
                        </div>
                        <div class="status-item">
                            <strong>🔑 Token:</strong> {{ token_status }}
                            <br><small>Expira em: {{ token_expires }}</small>
                        </div>
                        <div class="status-item">
                            <strong>📝 Regras Ativas:</strong> {{ active_rules }}
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
        user=user,
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

# Webhook do Mercado Livre
@app.route('/api/ml/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        
        if data and data.get('topic') == 'questions':
            print("📨 Webhook recebido - Nova pergunta!")
            # Processar em background
            threading.Thread(target=process_questions, daemon=True).start()
            
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"❌ Erro no webhook: {e}")
        return jsonify({"error": str(e)}), 500

# Outras rotas simplificadas
@app.route('/rules')
def rules():
    return "<h1>Regras de Resposta</h1><p>Em desenvolvimento...</p>"

@app.route('/absence')
def absence():
    return "<h1>Configurações de Ausência</h1><p>Em desenvolvimento...</p>"

@app.route('/questions')
def questions():
    return "<h1>Perguntas Recebidas</h1><p>Em desenvolvimento...</p>"

# Inicializar aplicação
initialize_database()

# Iniciar monitoramento
monitor_thread = threading.Thread(target=monitor_questions, daemon=True)
monitor_thread.start()
print("✅ Monitoramento iniciado - Verifica token a cada 5 horas!")

print("🚀 Bot do Mercado Livre iniciado com sucesso!")
print(f"🔑 Token: {current_token[:20]}...")
print(f"👤 User ID: {ML_USER_ID}")

if __name__ == '__main__':
    # Executar aplicação
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)

