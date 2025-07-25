import os
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import requests

# Configuração da aplicação
app = Flask(__name__)
CORS(app)

# Configuração do banco SQLite simples
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bot_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configurações do Mercado Livre
ML_ACCESS_TOKEN = 'APP_USR-5510376630479325-072423-41cbc33fddb983f73eaf5aa1b1b7f699-180617463'
ML_CLIENT_ID = '5510376630479325'
ML_CLIENT_SECRET = 'jlR4As2x8uFY3RTpysLpuPhzC9yM9d35'
ML_USER_ID = '180617463'

# Variáveis globais
current_token = ML_ACCESS_TOKEN
token_expires_at = datetime.utcnow() + timedelta(hours=6)
bot_status = "Iniciando..."

# Modelo simples do usuário
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ml_user_id = db.Column(db.String(50), unique=True, nullable=False)
    access_token = db.Column(db.String(200), nullable=False)
    refresh_token = db.Column(db.String(200))
    token_expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Modelo simples de perguntas
class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.String(100), unique=True, nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text)
    is_answered = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Inicialização simples
def init_db():
    global bot_status
    try:
        bot_status = "Criando banco..."
        db.create_all()
        
        # Verificar se usuário existe
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user:
            bot_status = "Criando usuário..."
            user = User(
                ml_user_id=ML_USER_ID,
                access_token=ML_ACCESS_TOKEN,
                refresh_token='placeholder',
                token_expires_at=token_expires_at
            )
            db.session.add(user)
            db.session.commit()
        
        bot_status = "Funcionando"
        print("✅ Banco inicializado com sucesso!")
        return True
    except Exception as e:
        bot_status = f"Erro: {e}"
        print(f"❌ Erro ao inicializar: {e}")
        return False

# Função simples para buscar perguntas
def get_questions():
    try:
        url = f"https://api.mercadolibre.com/my/received_questions/search?status=UNANSWERED"
        headers = {"Authorization": f"Bearer {current_token}"}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('questions', [])
        else:
            print(f"❌ Erro API: {response.status_code}")
            return []
    except Exception as e:
        print(f"❌ Erro ao buscar perguntas: {e}")
        return []

# Função simples para responder
def answer_question(question_id, answer_text):
    try:
        url = "https://api.mercadolibre.com/answers"
        data = {"question_id": question_id, "text": answer_text}
        headers = {
            "Authorization": f"Bearer {current_token}",
            "Content-Type": "application/json"
        }
        response = requests.post(url, json=data, headers=headers, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Erro ao responder: {e}")
        return False

# Função simples de processamento
def process_questions():
    try:
        questions = get_questions()
        for q in questions:
            question_id = q.get('id')
            question_text = q.get('text', '').lower()
            
            # Verificar se já processou
            existing = Question.query.filter_by(question_id=str(question_id)).first()
            if existing:
                continue
            
            # Resposta simples baseada em palavras-chave
            answer = None
            if any(word in question_text for word in ['preço', 'valor', 'custa', 'quanto']):
                answer = "Obrigado pela pergunta! O preço está na descrição do anúncio. Qualquer dúvida, estamos à disposição!"
            elif any(word in question_text for word in ['entrega', 'envio', 'frete']):
                answer = "Trabalhamos com entrega para todo o Brasil via Mercado Envios. O prazo e valor aparecem no anúncio."
            elif any(word in question_text for word in ['disponível', 'estoque', 'tem']):
                answer = "Sim, temos disponível! Pode fazer sua compra com tranquilidade."
            elif any(word in question_text for word in ['garantia']):
                answer = "Oferecemos garantia conforme especificado no anúncio. Estamos sempre à disposição!"
            else:
                answer = "Obrigado pela pergunta! Todas as informações estão na descrição do produto. Qualquer dúvida, estamos à disposição!"
            
            # Salvar pergunta
            question_record = Question(
                question_id=str(question_id),
                question_text=q.get('text', ''),
                response_text=answer,
                is_answered=False
            )
            db.session.add(question_record)
            
            # Tentar responder
            if answer_question(question_id, answer):
                question_record.is_answered = True
                print(f"✅ Pergunta {question_id} respondida!")
            
            db.session.commit()
            
    except Exception as e:
        print(f"❌ Erro no processamento: {e}")

# Monitoramento simples
def monitor():
    while True:
        try:
            with app.app_context():
                process_questions()
            time.sleep(120)  # 2 minutos
        except Exception as e:
            print(f"❌ Erro no monitor: {e}")
            time.sleep(120)

# Rota principal
@app.route('/')
def dashboard():
    try:
        # Estatísticas simples
        total_questions = Question.query.count()
        answered_questions = Question.query.filter_by(is_answered=True).count()
        pending_questions = total_questions - answered_questions
        
        # Perguntas recentes
        recent_questions = Question.query.order_by(Question.created_at.desc()).limit(5).all()
        
        # Status do token
        now = datetime.utcnow()
        if token_expires_at > now:
            time_left = token_expires_at - now
            hours = int(time_left.total_seconds() // 3600)
            token_status = f"Válido por {hours}h"
        else:
            token_status = "Expirado"
        
        questions_html = ""
        for q in recent_questions:
            status = "✅" if q.is_answered else "❓"
            questions_html += f"""
            <div style="border: 1px solid #ddd; padding: 10px; margin: 5px 0; border-radius: 5px;">
                <strong>{status} {q.created_at.strftime('%d/%m %H:%M')}</strong><br>
                <strong>P:</strong> {q.question_text}<br>
                {f'<strong>R:</strong> {q.response_text}' if q.response_text else ''}
            </div>
            """
        
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Bot Mercado Livre</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
                .container { max-width: 800px; margin: 0 auto; }
                .header { background: #3483fa; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; text-align: center; }
                .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 20px; }
                .stat { background: white; padding: 15px; border-radius: 8px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .stat-number { font-size: 2em; font-weight: bold; color: #3483fa; }
                .section { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                .status { padding: 10px; background: #d4edda; color: #155724; border-radius: 5px; margin-bottom: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤖 Bot Mercado Livre</h1>
                    <p>Sistema de Resposta Automática</p>
                </div>
                
                <div class="status">
                    ✅ <strong>Status:</strong> {{ bot_status }} | <strong>Token:</strong> {{ token_status }}
                </div>
                
                <div class="stats">
                    <div class="stat">
                        <div class="stat-number">{{ total_questions }}</div>
                        <div>Total</div>
                    </div>
                    <div class="stat">
                        <div class="stat-number">{{ answered_questions }}</div>
                        <div>Respondidas</div>
                    </div>
                    <div class="stat">
                        <div class="stat-number">{{ pending_questions }}</div>
                        <div>Pendentes</div>
                    </div>
                </div>
                
                <div class="section">
                    <h2>❓ Perguntas Recentes</h2>
                    {{ questions_html|safe if questions_html else '<p>Aguardando perguntas...</p>' }}
                </div>
                
                <div class="section">
                    <h2>ℹ️ Informações</h2>
                    <p><strong>Monitoramento:</strong> A cada 2 minutos</p>
                    <p><strong>Respostas:</strong> Automáticas baseadas em palavras-chave</p>
                    <p><strong>Token:</strong> Renovação manual quando necessário</p>
                </div>
            </div>
        </body>
        </html>
        """, 
        bot_status=bot_status,
        token_status=token_status,
        total_questions=total_questions,
        answered_questions=answered_questions,
        pending_questions=pending_questions,
        questions_html=questions_html
        )
    except Exception as e:
        return f"❌ Erro: {e}", 500

# Webhook simples
@app.route('/api/ml/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if data and data.get('topic') == 'questions':
            # Processar em background
            threading.Thread(target=process_questions, daemon=True).start()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Health check
@app.route('/health')
def health():
    return jsonify({"status": "ok", "bot_status": bot_status}), 200

# Inicialização
if __name__ == '__main__':
    # Inicializar banco
    with app.app_context():
        init_db()
    
    # Iniciar monitoramento
    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    
    print("🚀 Bot iniciado com sucesso!")
    print(f"🔑 Token: {current_token[:20]}...")
    print(f"👤 User ID: {ML_USER_ID}")
    
    # Executar aplicação
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)

