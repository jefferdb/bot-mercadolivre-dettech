import os
import time
import threading
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, redirect, url_for, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests
import json

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

# Variáveis globais para controlar token
current_token = ML_ACCESS_TOKEN
token_expires_at = None
bot_status = "Iniciando..."

# Lock para controle de concorrência
db_lock = threading.Lock()

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

class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(20), nullable=False)  # INFO, WARNING, ERROR
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Variável global para controlar inicialização
_initialized = False

# Função para FORÇAR recriação completa do banco
def force_recreate_database():
    global _initialized, token_expires_at, bot_status
    
    try:
        with app.app_context():
            bot_status = "Recriando banco de dados..."
            print("🔄 Forçando recriação COMPLETA do banco de dados...")
            
            # Dropar todas as tabelas
            db.drop_all()
            print("✅ Tabelas antigas removidas")
            
            # Criar todas as tabelas novamente
            db.create_all()
            print("✅ Tabelas novas criadas")
            
            # Verificar se usuário já existe
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                bot_status = "Criando usuário inicial..."
                # Criar usuário inicial
                user = User(
                    ml_user_id=ML_USER_ID,
                    access_token=ML_ACCESS_TOKEN,
                    refresh_token='TG-6882f8e7f04d54000...',  # Placeholder
                    token_expires_at=datetime.utcnow() + timedelta(hours=6)
                )
                db.session.add(user)
                
                # Criar regras de resposta padrão COMPLETAS
                default_responses = [
                    ("preço,valor,custa,quanto,custou,custará", "Obrigado pela pergunta! O preço está na descrição do anúncio. Qualquer dúvida, estamos à disposição!"),
                    ("entrega,envio,frete,correios,sedex,pac", "Trabalhamos com entrega para todo o Brasil via Mercado Envios. O prazo e valor aparecem no anúncio."),
                    ("disponível,estoque,tem,possui,há", "Sim, temos disponível! Pode fazer sua compra com tranquilidade."),
                    ("garantia,defeito,problema,troca", "Oferecemos garantia conforme especificado no anúncio. Estamos sempre à disposição!"),
                    ("desconto,promoção,oferta,barato", "Os melhores preços já estão aplicados! Aproveite nossas ofertas."),
                    ("pagamento,cartão,pix,boleto,parcelamento", "Aceitamos todas as formas de pagamento do Mercado Livre: cartão, PIX, boleto."),
                    ("dúvida,informação,detalhes,especificação", "Ficamos felizes em ajudar! Todas as informações estão na descrição. Qualquer dúvida, pergunte!"),
                    ("horário,atendimento,funcionamento,aberto", "Nosso horário de atendimento é das 8h às 18h, de segunda a sexta. Responderemos assim que possível!"),
                    ("qualidade,original,novo,usado", "Trabalhamos apenas com produtos de qualidade e originais. Sua satisfação é nossa prioridade!"),
                    ("tamanho,medida,dimensão,peso,altura", "As medidas e especificações estão detalhadas na descrição do produto. Confira lá!"),
                    ("cor,cores,colorido,preto,branco", "As cores disponíveis estão mostradas nas fotos e descrição do anúncio."),
                    ("instalação,montagem,manual,como usar", "Fornecemos manual de instalação. Em caso de dúvidas, nossa equipe pode orientar!"),
                    ("nota,fiscal,nf,recibo", "Emitimos nota fiscal para todas as vendas. Será enviada junto com o produto."),
                    ("prazo,demora,quando chega,rapidez", "O prazo de entrega está calculado no anúncio baseado no seu CEP."),
                    ("marca,fabricante,modelo,versão", "Todas as informações sobre marca e modelo estão na descrição detalhada do produto.")
                ]
                
                for keywords, response in default_responses:
                    auto_response = AutoResponse(
                        user_id=user.id,
                        keywords=keywords,
                        response_text=response
                    )
                    db.session.add(auto_response)
                
                # Criar configurações de ausência padrão COMPLETAS
                absence_configs = [
                    ("Horário Comercial", "Obrigado pela pergunta! Nosso atendimento é das 8h às 18h, de segunda a sexta. Responderemos em breve!", "18:00", "08:00", "0,1,2,3,4,5,6"),
                    ("Final de Semana", "Obrigado pelo contato! Não trabalhamos aos finais de semana. Responderemos na segunda-feira!", "00:00", "23:59", "5,6"),
                    ("Almoço", "Estamos no horário de almoço (12h às 13h). Responderemos em seguida!", "12:00", "13:00", "0,1,2,3,4"),
                    ("Madrugada", "Obrigado pela mensagem! Nosso atendimento retorna às 8h. Responderemos assim que possível!", "22:00", "08:00", "0,1,2,3,4,5,6")
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
                
                # Log inicial do sistema
                initial_log = SystemLog(
                    level="INFO",
                    message="Sistema inicializado com sucesso",
                    details=f"Usuário criado: {ML_USER_ID}, Token configurado, Regras padrão criadas"
                )
                db.session.add(initial_log)
                
                db.session.commit()
                print("✅ Dados iniciais criados com sucesso!")
                
            # Definir expiração do token
            token_expires_at = user.token_expires_at
            bot_status = "Sistema funcionando"
            _initialized = True
            print("✅ Banco de dados inicializado COMPLETAMENTE!")
                
    except Exception as e:
        bot_status = f"Erro na inicialização: {e}"
        print(f"❌ Erro ao inicializar banco: {e}")

def initialize_database():
    if not _initialized:
        force_recreate_database()

# Função para log do sistema
def log_system(level, message, details=None):
    try:
        with db_lock:
            log = SystemLog(
                level=level,
                message=message,
                details=details
            )
            db.session.add(log)
            db.session.commit()
    except Exception as e:
        print(f"❌ Erro ao salvar log: {e}")

# Função ROBUSTA para renovar token
def renew_access_token():
    global current_token, token_expires_at
    
    try:
        with db_lock:
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user or not user.refresh_token:
                log_system("ERROR", "Usuário ou refresh_token não encontrado para renovação")
                return False
            
            # Dados para renovação
            data = {
                "grant_type": "refresh_token",
                "client_id": ML_CLIENT_ID,
                "client_secret": ML_CLIENT_SECRET,
                "refresh_token": user.refresh_token
            }
            
            log_system("INFO", "Iniciando renovação de token")
            response = requests.post("https://api.mercadolibre.com/oauth/token", data=data, timeout=30)
            
            if response.status_code == 200:
                token_data = response.json()
                
                # Atualizar token
                new_token = token_data.get("access_token")
                new_refresh = token_data.get("refresh_token", user.refresh_token)
                expires_in = token_data.get("expires_in", 21600)
                
                # Atualizar no banco
                old_token = user.access_token
                user.access_token = new_token
                user.refresh_token = new_refresh
                user.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                user.updated_at = datetime.utcnow()
                
                # Atualizar variáveis globais
                current_token = new_token
                token_expires_at = user.token_expires_at
                
                # Log da renovação
                log_entry = TokenLog(
                    user_id=user.id,
                    action="renewed",
                    old_token=old_token[:20] + "..." if old_token else None,
                    new_token=new_token[:20] + "..." if new_token else None,
                    expires_at=token_expires_at,
                    message=f"Token renovado com sucesso. Expira em {expires_in} segundos."
                )
                db.session.add(log_entry)
                
                log_system("INFO", f"Token renovado com sucesso", f"Expira em {expires_in} segundos")
                db.session.commit()
                
                print(f"✅ Token renovado! Expira em {expires_in} segundos")
                return True
            else:
                error_msg = f"Erro HTTP {response.status_code}: {response.text}"
                log_system("ERROR", "Falha na renovação de token", error_msg)
                print(f"❌ Erro ao renovar token: {response.status_code}")
                return False
                
    except Exception as e:
        error_msg = f"Exceção durante renovação: {str(e)}"
        log_system("ERROR", "Erro na renovação de token", error_msg)
        print(f"❌ Erro na renovação: {e}")
        return False

# Função para verificar expiração do token
def check_token_expiration():
    global token_expires_at
    
    try:
        if not token_expires_at:
            log_system("WARNING", "Token sem data de expiração definida")
            return True
            
        now = datetime.utcnow()
        time_left = token_expires_at - now
        
        # Se faltam menos de 1 hora, renovar
        if time_left.total_seconds() < 3600:  # 1 hora
            log_system("INFO", f"Token expira em {time_left}. Iniciando renovação...")
            return renew_access_token()
        else:
            hours_left = int(time_left.total_seconds() / 3600)
            print(f"✅ Token válido por mais {hours_left} horas")
            return True
            
    except Exception as e:
        log_system("ERROR", "Erro ao verificar expiração do token", str(e))
        return False

# Função para verificar se está em horário de ausência
def is_absence_time():
    try:
        with db_lock:
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
                            log_system("INFO", f"Horário de ausência ativo: {config.name}")
                            return config.message
                    else:
                        if start_time <= current_time <= end_time:
                            log_system("INFO", f"Horário de ausência ativo: {config.name}")
                            return config.message
            
            return None
    except Exception as e:
        log_system("ERROR", "Erro ao verificar horário de ausência", str(e))
        return None

def find_auto_response(question_text):
    try:
        with db_lock:
            question_lower = question_text.lower()
            
            auto_responses = AutoResponse.query.filter_by(is_active=True).all()
            
            for response in auto_responses:
                keywords = [k.strip().lower() for k in response.keywords.split(',')]
                
                for keyword in keywords:
                    if keyword in question_lower:
                        log_system("INFO", f"Resposta automática encontrada para: {keyword}")
                        return response.response_text
            
            return None
    except Exception as e:
        log_system("ERROR", "Erro ao buscar resposta automática", str(e))
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
        
        response = requests.post(url, json=data, headers=headers, timeout=30)
        
        if response.status_code == 200:
            log_system("INFO", f"Pergunta {question_id} respondida com sucesso")
            print(f"✅ Pergunta {question_id} respondida com sucesso!")
            return True
        else:
            error_msg = f"HTTP {response.status_code}: {response.text}"
            log_system("ERROR", f"Erro ao responder pergunta {question_id}", error_msg)
            print(f"❌ Erro ao responder pergunta {question_id}: {response.status_code}")
            return False
            
    except Exception as e:
        log_system("ERROR", f"Erro ao responder pergunta {question_id}", str(e))
        print(f"❌ Erro ao responder pergunta: {e}")
        return False

def get_unanswered_questions():
    try:
        # Verificar e renovar token se necessário
        if not check_token_expiration():
            log_system("ERROR", "Falha ao verificar/renovar token")
            return []
        
        url = f"https://api.mercadolibre.com/my/received_questions/search?status=UNANSWERED"
        
        headers = {
            "Authorization": f"Bearer {current_token}"
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            questions = data.get('questions', [])
            log_system("INFO", f"Encontradas {len(questions)} perguntas não respondidas")
            print(f"📨 Encontradas {len(questions)} perguntas não respondidas")
            return questions
        else:
            error_msg = f"HTTP {response.status_code}: {response.text}"
            log_system("ERROR", "Erro ao buscar perguntas", error_msg)
            print(f"❌ Erro ao buscar perguntas: {response.status_code}")
            return []
            
    except Exception as e:
        log_system("ERROR", "Erro ao buscar perguntas", str(e))
        print(f"❌ Erro ao buscar perguntas: {e}")
        return []

def process_questions():
    try:
        initialize_database()
        
        with db_lock:
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                log_system("ERROR", "Usuário não encontrado para processamento")
                return
        
        questions = get_unanswered_questions()
        
        for q in questions:
            try:
                question_id = q.get('id')
                question_text = q.get('text', '')
                item_id = q.get('item_id', '')
                
                with db_lock:
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
                    db.session.commit()
                
                print(f"📝 Nova pergunta: {question_text}")
                log_system("INFO", f"Nova pergunta recebida: {question_id}")
                
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
                        log_system("WARNING", f"Nenhuma resposta automática para pergunta {question_id}")
                        continue
                
                # Responder pergunta
                if answer_question(question_id, answer_text):
                    with db_lock:
                        question_record.response_text = answer_text
                        question_record.is_answered = True
                        question_record.answered_at = datetime.utcnow()
                        db.session.commit()
                    print(f"✅ Pergunta respondida automaticamente!")
                
            except Exception as e:
                log_system("ERROR", f"Erro ao processar pergunta individual {question_id}", str(e))
                continue
            
    except Exception as e:
        log_system("ERROR", "Erro geral no processamento de perguntas", str(e))
        print(f"❌ Erro ao processar perguntas: {e}")

# Função de monitoramento de token
def monitor_token():
    while True:
        try:
            with app.app_context():
                check_token_expiration()
            time.sleep(3600)  # Verificar a cada hora
        except Exception as e:
            log_system("ERROR", "Erro no monitoramento de token", str(e))
            time.sleep(3600)

# Função de monitoramento de perguntas
def monitor_questions():
    while True:
        try:
            with app.app_context():
                process_questions()
            time.sleep(60)  # Verificar a cada 60 segundos
        except Exception as e:
            log_system("ERROR", "Erro no monitoramento de perguntas", str(e))
            time.sleep(60)

# Rotas da aplicação
@app.route('/')
def dashboard():
    try:
        initialize_database()
        
        with db_lock:
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
            
            # Logs recentes
            recent_logs = SystemLog.query.order_by(SystemLog.created_at.desc()).limit(5).all()
        
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
        
        logs_html = ""
        for log in recent_logs:
            level_color = {"INFO": "#28a745", "WARNING": "#ffc107", "ERROR": "#dc3545"}.get(log.level, "#6c757d")
            logs_html += f"""
            <div class="log-entry">
                <span class="log-level" style="color: {level_color};">[{log.level}]</span>
                <span class="log-time">{log.created_at.strftime('%d/%m %H:%M')}</span>
                <span class="log-message">{log.message}</span>
            </div>
            """
        
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Bot Mercado Livre - Dashboard Completo</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: Arial, sans-serif; background: #f5f5f5; }
                .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
                .header { background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
                .stat-card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; transition: transform 0.2s; }
                .stat-card:hover { transform: translateY(-2px); }
                .stat-number { font-size: 2.5em; font-weight: bold; color: #3483fa; margin-bottom: 5px; }
                .stat-label { color: #666; font-size: 0.9em; }
                .section { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }
                .question-card { border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; margin-bottom: 10px; background: #fafafa; }
                .question-header { display: flex; justify-content: space-between; margin-bottom: 10px; align-items: center; }
                .status { font-size: 1.2em; }
                .date { color: #666; font-size: 0.85em; }
                .nav { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
                .nav a { background: #3483fa; color: white; padding: 12px 20px; text-decoration: none; border-radius: 8px; transition: background 0.2s; }
                .nav a:hover { background: #2968c8; }
                .status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; }
                .status-item { padding: 15px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #3483fa; }
                .success { background: #d4edda; color: #155724; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #28a745; }
                .log-entry { padding: 8px 0; border-bottom: 1px solid #eee; font-family: monospace; font-size: 0.9em; }
                .log-level { font-weight: bold; margin-right: 10px; }
                .log-time { color: #666; margin-right: 10px; }
                h1 { margin-bottom: 10px; }
                h2 { color: #333; margin-bottom: 15px; }
                .version { font-size: 0.8em; opacity: 0.8; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="success">
                    ✅ <strong>Sistema Completo Funcionando!</strong> Banco recriado, todas as funcionalidades ativas.
                </div>
                
                <div class="header">
                    <h1>🤖 Bot Mercado Livre - Dashboard Completo</h1>
                    <p>Sistema Avançado de Resposta Automática</p>
                    <div class="version">Versão Final - Todas as Funcionalidades</div>
                </div>
                
                <div class="nav">
                    <a href="/">📊 Dashboard</a>
                    <a href="/rules">📝 Regras de Resposta</a>
                    <a href="/absence">🌙 Configurações de Ausência</a>
                    <a href="/questions">❓ Todas as Perguntas</a>
                    <a href="/logs">📋 Logs do Sistema</a>
                    <a href="/token">🔑 Status do Token</a>
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
                            <strong>🔗 Status:</strong> {{ bot_status }}
                            <br><small>Sistema operacional</small>
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
                
                <div class="section">
                    <h2>📋 Logs Recentes do Sistema</h2>
                    {{ logs_html|safe if logs_html else '<p>Nenhum log disponível.</p>' }}
                </div>
            </div>
        </body>
        </html>
        """, 
        bot_status=bot_status,
        total_questions=total_questions,
        answered_questions=answered_questions, 
        pending_questions=pending_questions,
        success_rate=success_rate,
        questions_html=questions_html,
        logs_html=logs_html,
        token_status=token_status,
        token_expires=token_expires,
        active_rules=active_rules,
        active_configs=active_configs
        )
    except Exception as e:
        return f"❌ Erro: {e}", 500

@app.route('/rules')
def rules():
    try:
        initialize_database()
        
        with db_lock:
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return "❌ Usuário não encontrado", 404
            
            auto_responses = AutoResponse.query.filter_by(user_id=user.id).all()
        
        rules_html = ""
        for rule in auto_responses:
            status_badge = "✅ Ativa" if rule.is_active else "❌ Inativa"
            status_color = "#28a745" if rule.is_active else "#dc3545"
            rules_html += f"""
            <div class="rule-card">
                <div class="rule-header">
                    <span class="rule-status" style="color: {status_color};">{status_badge}</span>
                    <span class="rule-date">{rule.created_at.strftime('%d/%m/%Y')}</span>
                </div>
                <div class="rule-content">
                    <strong>Palavras-chave:</strong> {rule.keywords}<br>
                    <strong>Resposta:</strong> {rule.response_text}
                </div>
            </div>
            """
        
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Regras de Resposta - Bot ML</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: Arial, sans-serif; background: #f5f5f5; }
                .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
                .header { background: #3483fa; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .nav { display: flex; gap: 10px; margin-bottom: 20px; }
                .nav a { background: #6c757d; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }
                .nav a.active { background: #3483fa; }
                .section { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .rule-card { border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
                .rule-header { display: flex; justify-content: space-between; margin-bottom: 10px; }
                .rule-status { font-weight: bold; }
                .rule-date { color: #666; font-size: 0.9em; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📝 Regras de Resposta Automática</h1>
                    <p>Configurações de palavras-chave e respostas</p>
                </div>
                
                <div class="nav">
                    <a href="/">📊 Dashboard</a>
                    <a href="/rules" class="active">📝 Regras de Resposta</a>
                    <a href="/absence">🌙 Configurações de Ausência</a>
                    <a href="/questions">❓ Todas as Perguntas</a>
                </div>
                
                <div class="section">
                    <h2>📋 Regras Configuradas</h2>
                    {{ rules_html|safe if rules_html else '<p>Nenhuma regra configurada.</p>' }}
                </div>
            </div>
        </body>
        </html>
        """, rules_html=rules_html)
    except Exception as e:
        return f"❌ Erro: {e}", 500

@app.route('/absence')
def absence():
    try:
        initialize_database()
        
        with db_lock:
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return "❌ Usuário não encontrado", 404
            
            absence_configs = AbsenceConfig.query.filter_by(user_id=user.id).all()
        
        configs_html = ""
        for config in absence_configs:
            status_badge = "✅ Ativa" if config.is_active else "❌ Inativa"
            status_color = "#28a745" if config.is_active else "#dc3545"
            days_names = {
                "0": "Seg", "1": "Ter", "2": "Qua", "3": "Qui", 
                "4": "Sex", "5": "Sáb", "6": "Dom"
            }
            days_list = [days_names.get(d, d) for d in config.days_of_week.split(',')]
            configs_html += f"""
            <div class="config-card">
                <div class="config-header">
                    <h3>{config.name}</h3>
                    <span class="config-status" style="color: {status_color};">{status_badge}</span>
                </div>
                <div class="config-content">
                    <strong>Horário:</strong> {config.start_time} às {config.end_time}<br>
                    <strong>Dias:</strong> {', '.join(days_list)}<br>
                    <strong>Mensagem:</strong> {config.message}
                </div>
            </div>
            """
        
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Configurações de Ausência - Bot ML</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: Arial, sans-serif; background: #f5f5f5; }
                .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
                .header { background: #3483fa; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .nav { display: flex; gap: 10px; margin-bottom: 20px; }
                .nav a { background: #6c757d; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }
                .nav a.active { background: #3483fa; }
                .section { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .config-card { border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
                .config-header { display: flex; justify-content: space-between; margin-bottom: 10px; align-items: center; }
                .config-status { font-weight: bold; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🌙 Configurações de Ausência</h1>
                    <p>Horários e mensagens automáticas de ausência</p>
                </div>
                
                <div class="nav">
                    <a href="/">📊 Dashboard</a>
                    <a href="/rules">📝 Regras de Resposta</a>
                    <a href="/absence" class="active">🌙 Configurações de Ausência</a>
                    <a href="/questions">❓ Todas as Perguntas</a>
                </div>
                
                <div class="section">
                    <h2>⏰ Configurações de Horário</h2>
                    {{ configs_html|safe if configs_html else '<p>Nenhuma configuração de ausência.</p>' }}
                </div>
            </div>
        </body>
        </html>
        """, configs_html=configs_html)
    except Exception as e:
        return f"❌ Erro: {e}", 500

@app.route('/questions')
def questions():
    try:
        initialize_database()
        
        with db_lock:
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return "❌ Usuário não encontrado", 404
            
            all_questions = Question.query.filter_by(user_id=user.id).order_by(Question.created_at.desc()).limit(50).all()
        
        questions_html = ""
        for q in all_questions:
            status_icon = "✅" if q.is_answered else "❓"
            status_text = "Respondida" if q.is_answered else "Pendente"
            answered_text = f"<br><strong>Resposta:</strong> {q.response_text}" if q.response_text else ""
            answered_time = f"<br><small>Respondida em: {q.answered_at.strftime('%d/%m/%Y %H:%M')}</small>" if q.answered_at else ""
            questions_html += f"""
            <div class="question-card">
                <div class="question-header">
                    <span class="status">{status_icon} {status_text}</span>
                    <span class="date">{q.created_at.strftime('%d/%m/%Y %H:%M')}</span>
                </div>
                <div class="question-content">
                    <strong>ID:</strong> {q.question_id}<br>
                    <strong>Item:</strong> {q.item_id}<br>
                    <strong>Pergunta:</strong> {q.question_text}
                    {answered_text}
                    {answered_time}
                </div>
            </div>
            """
        
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Todas as Perguntas - Bot ML</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: Arial, sans-serif; background: #f5f5f5; }
                .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
                .header { background: #3483fa; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .nav { display: flex; gap: 10px; margin-bottom: 20px; }
                .nav a { background: #6c757d; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }
                .nav a.active { background: #3483fa; }
                .section { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .question-card { border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
                .question-header { display: flex; justify-content: space-between; margin-bottom: 10px; }
                .status { font-weight: bold; }
                .date { color: #666; font-size: 0.9em; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>❓ Todas as Perguntas</h1>
                    <p>Histórico completo de perguntas recebidas</p>
                </div>
                
                <div class="nav">
                    <a href="/">📊 Dashboard</a>
                    <a href="/rules">📝 Regras de Resposta</a>
                    <a href="/absence">🌙 Configurações de Ausência</a>
                    <a href="/questions" class="active">❓ Todas as Perguntas</a>
                </div>
                
                <div class="section">
                    <h2>📋 Últimas 50 Perguntas</h2>
                    {{ questions_html|safe if questions_html else '<p>Nenhuma pergunta registrada.</p>' }}
                </div>
            </div>
        </body>
        </html>
        """, questions_html=questions_html)
    except Exception as e:
        return f"❌ Erro: {e}", 500

@app.route('/logs')
def logs():
    try:
        initialize_database()
        
        with db_lock:
            all_logs = SystemLog.query.order_by(SystemLog.created_at.desc()).limit(100).all()
        
        logs_html = ""
        for log in all_logs:
            level_color = {"INFO": "#28a745", "WARNING": "#ffc107", "ERROR": "#dc3545"}.get(log.level, "#6c757d")
            details_text = f"<br><small>{log.details}</small>" if log.details else ""
            logs_html += f"""
            <div class="log-entry">
                <div class="log-header">
                    <span class="log-level" style="color: {level_color};">[{log.level}]</span>
                    <span class="log-time">{log.created_at.strftime('%d/%m/%Y %H:%M:%S')}</span>
                </div>
                <div class="log-content">
                    {log.message}
                    {details_text}
                </div>
            </div>
            """
        
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Logs do Sistema - Bot ML</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: Arial, sans-serif; background: #f5f5f5; }
                .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
                .header { background: #3483fa; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .nav { display: flex; gap: 10px; margin-bottom: 20px; }
                .nav a { background: #6c757d; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }
                .nav a.active { background: #3483fa; }
                .section { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .log-entry { border-bottom: 1px solid #eee; padding: 10px 0; font-family: monospace; }
                .log-header { margin-bottom: 5px; }
                .log-level { font-weight: bold; margin-right: 10px; }
                .log-time { color: #666; }
                .log-content { font-size: 0.9em; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>📋 Logs do Sistema</h1>
                    <p>Registro detalhado de atividades</p>
                </div>
                
                <div class="nav">
                    <a href="/">📊 Dashboard</a>
                    <a href="/rules">📝 Regras de Resposta</a>
                    <a href="/absence">🌙 Configurações de Ausência</a>
                    <a href="/questions">❓ Todas as Perguntas</a>
                    <a href="/logs" class="active">📋 Logs do Sistema</a>
                </div>
                
                <div class="section">
                    <h2>📝 Últimos 100 Logs</h2>
                    {{ logs_html|safe if logs_html else '<p>Nenhum log disponível.</p>' }}
                </div>
            </div>
        </body>
        </html>
        """, logs_html=logs_html)
    except Exception as e:
        return f"❌ Erro: {e}", 500

@app.route('/token')
def token_status():
    try:
        initialize_database()
        
        with db_lock:
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return "❌ Usuário não encontrado", 404
            
            token_logs = TokenLog.query.filter_by(user_id=user.id).order_by(TokenLog.created_at.desc()).limit(20).all()
        
        # Status atual do token
        token_status = "Válido"
        token_expires = "N/A"
        time_left_seconds = 0
        
        if user.token_expires_at:
            now = datetime.utcnow()
            if user.token_expires_at > now:
                time_left = user.token_expires_at - now
                time_left_seconds = int(time_left.total_seconds())
                hours = int(time_left.total_seconds() // 3600)
                minutes = int((time_left.total_seconds() % 3600) // 60)
                token_expires = f"{hours}h {minutes}m"
            else:
                token_status = "Expirado"
                token_expires = "Expirado"
        
        logs_html = ""
        for log in token_logs:
            logs_html += f"""
            <div class="token-log">
                <div class="log-header">
                    <strong>{log.action.upper()}</strong>
                    <span class="log-time">{log.created_at.strftime('%d/%m/%Y %H:%M:%S')}</span>
                </div>
                <div class="log-content">
                    {log.message}
                    {f'<br><small>Token anterior: {log.old_token}</small>' if log.old_token else ''}
                    {f'<br><small>Novo token: {log.new_token}</small>' if log.new_token else ''}
                </div>
            </div>
            """
        
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Status do Token - Bot ML</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: Arial, sans-serif; background: #f5f5f5; }
                .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
                .header { background: #3483fa; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .nav { display: flex; gap: 10px; margin-bottom: 20px; }
                .nav a { background: #6c757d; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }
                .nav a.active { background: #3483fa; }
                .section { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
                .token-info { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
                .info-card { background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; }
                .info-value { font-size: 1.5em; font-weight: bold; color: #3483fa; }
                .token-log { border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 10px; }
                .log-header { display: flex; justify-content: space-between; margin-bottom: 10px; }
                .log-time { color: #666; font-size: 0.9em; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔑 Status do Token</h1>
                    <p>Informações detalhadas sobre autenticação</p>
                </div>
                
                <div class="nav">
                    <a href="/">📊 Dashboard</a>
                    <a href="/rules">📝 Regras de Resposta</a>
                    <a href="/absence">🌙 Configurações de Ausência</a>
                    <a href="/questions">❓ Todas as Perguntas</a>
                    <a href="/logs">📋 Logs do Sistema</a>
                    <a href="/token" class="active">🔑 Status do Token</a>
                </div>
                
                <div class="section">
                    <h2>📊 Informações do Token</h2>
                    <div class="token-info">
                        <div class="info-card">
                            <div class="info-value">{{ token_status }}</div>
                            <div>Status</div>
                        </div>
                        <div class="info-card">
                            <div class="info-value">{{ token_expires }}</div>
                            <div>Tempo Restante</div>
                        </div>
                        <div class="info-card">
                            <div class="info-value">{{ time_left_seconds }}</div>
                            <div>Segundos Restantes</div>
                        </div>
                        <div class="info-card">
                            <div class="info-value">{{ user.ml_user_id }}</div>
                            <div>User ID</div>
                        </div>
                    </div>
                </div>
                
                <div class="section">
                    <h2>📋 Histórico de Renovações</h2>
                    {{ logs_html|safe if logs_html else '<p>Nenhuma renovação registrada.</p>' }}
                </div>
            </div>
        </body>
        </html>
        """, 
        token_status=token_status,
        token_expires=token_expires,
        time_left_seconds=time_left_seconds,
        user=user,
        logs_html=logs_html
        )
    except Exception as e:
        return f"❌ Erro: {e}", 500

# Webhook do Mercado Livre
@app.route('/api/ml/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        
        if data and data.get('topic') == 'questions':
            log_system("INFO", "Webhook recebido - Nova pergunta!")
            print("📨 Webhook recebido - Nova pergunta!")
            # Processar em background
            threading.Thread(target=process_questions, daemon=True).start()
            
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        log_system("ERROR", "Erro no webhook", str(e))
        return jsonify({"error": str(e)}), 500

# Health check para Render
@app.route('/health')
def health():
    return jsonify({
        "status": "ok", 
        "bot_status": bot_status,
        "timestamp": datetime.utcnow().isoformat()
    }), 200

# API para forçar verificação de perguntas
@app.route('/api/check-questions', methods=['POST'])
def api_check_questions():
    try:
        threading.Thread(target=process_questions, daemon=True).start()
        return jsonify({"status": "ok", "message": "Verificação iniciada"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# API para forçar renovação de token
@app.route('/api/renew-token', methods=['POST'])
def api_renew_token():
    try:
        success = renew_access_token()
        if success:
            return jsonify({"status": "ok", "message": "Token renovado com sucesso"}), 200
        else:
            return jsonify({"status": "error", "message": "Falha na renovação"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Inicializar aplicação
initialize_database()

# Iniciar threads de monitoramento
monitor_questions_thread = threading.Thread(target=monitor_questions, daemon=True)
monitor_questions_thread.start()
print("✅ Monitoramento de perguntas iniciado!")

monitor_token_thread = threading.Thread(target=monitor_token, daemon=True)
monitor_token_thread.start()
print("✅ Monitoramento de token iniciado!")

print("🚀 Bot do Mercado Livre COMPLETO iniciado com sucesso!")
print(f"🔑 Token: {current_token[:20]}...")
print(f"👤 User ID: {ML_USER_ID}")
print(f"📊 Status: {bot_status}")

if __name__ == '__main__':
    # Executar aplicação
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)

