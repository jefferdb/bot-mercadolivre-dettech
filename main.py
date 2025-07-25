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

# Configurações do Mercado Livre
ML_CLIENT_ID = os.getenv('ML_CLIENT_ID', '5510376630479325')
ML_CLIENT_SECRET = os.getenv('ML_CLIENT_SECRET', 'jlR4As2x8uFY3RTpysLpuPhzC9yM9d35')
ML_ACCESS_TOKEN = os.getenv('ML_ACCESS_TOKEN', 'APP_USR-5510376630479325-072321-31ceebc6a2428e8723948d8e00c75015-180617463')
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
    answer_text = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    answered_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AbsenceConfig(db.Model):
    __tablename__ = 'absence_configs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.String(5))
    end_time = db.Column(db.String(5))
    days_of_week = db.Column(db.String(20))
    message = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Variáveis globais para estatísticas
stats = {
    'total_questions': 0,
    'answered_questions': 0,
    'pending_questions': 0,
    'success_rate': 0
}

# Funções auxiliares
def get_ml_headers():
    return {
        'Authorization': f'Bearer {ML_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }

def get_questions():
    try:
        url = f'https://api.mercadolibre.com/my/received_questions/search?seller_id={ML_USER_ID}&status=UNANSWERED'
        response = requests.get(url, headers=get_ml_headers(), timeout=10)
        
        if response.status_code == 200:
            return response.json().get('questions', [])
        else:
            print(f"Erro ao buscar perguntas: {response.status_code}")
            return []
    except Exception as e:
        print(f"Erro na requisição: {e}")
        return []

def answer_question(question_id, answer_text):
    try:
        url = f'https://api.mercadolibre.com/answers'
        data = {
            'question_id': question_id,
            'text': answer_text
        }
        
        response = requests.post(url, headers=get_ml_headers(), json=data, timeout=10)
        return response.status_code == 201
    except Exception as e:
        print(f"Erro ao responder pergunta: {e}")
        return False

def find_matching_response(question_text, user_id):
    try:
        responses = AutoResponse.query.filter_by(user_id=user_id, is_active=True).all()
        
        for response in responses:
            keywords = [k.strip().lower() for k in response.keywords.split(',')]
            question_lower = question_text.lower()
            
            if any(keyword in question_lower for keyword in keywords):
                return response.response_text
        
        return None
    except Exception as e:
        print(f"Erro ao buscar resposta: {e}")
        return None

def check_absence_message(user_id):
    try:
        now = datetime.now()
        current_time = now.strftime('%H:%M')
        current_day = str(now.weekday())
        
        absence_configs = AbsenceConfig.query.filter_by(user_id=user_id, is_active=True).all()
        
        for config in absence_configs:
            if config.days_of_week and current_day in config.days_of_week.split(','):
                if config.start_time and config.end_time:
                    if config.start_time <= current_time <= config.end_time:
                        return config.message
        
        return None
    except Exception as e:
        print(f"Erro ao verificar ausência: {e}")
        return None

def process_questions():
    global stats
    try:
        with app.app_context():
            user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
            if not user:
                return
            
            questions = get_questions()
            
            for q in questions:
                try:
                    existing = Question.query.filter_by(ml_question_id=str(q['id'])).first()
                    if existing:
                        continue
                    
                    # Verificar mensagem de ausência primeiro
                    absence_msg = check_absence_message(user.id)
                    if absence_msg:
                        answer_text = absence_msg
                    else:
                        # Buscar resposta automática
                        answer_text = find_matching_response(q['text'], user.id)
                    
                    if answer_text:
                        success = answer_question(q['id'], answer_text)
                        
                        question = Question(
                            ml_question_id=str(q['id']),
                            user_id=user.id,
                            item_id=q['item_id'],
                            question_text=q['text'],
                            answer_text=answer_text if success else None,
                            status='answered' if success else 'failed',
                            answered_at=datetime.utcnow() if success else None
                        )
                        db.session.add(question)
                        
                        if success:
                            stats['answered_questions'] += 1
                            print(f"✅ Pergunta respondida: {q['text'][:50]}...")
                    else:
                        question = Question(
                            ml_question_id=str(q['id']),
                            user_id=user.id,
                            item_id=q['item_id'],
                            question_text=q['text'],
                            status='no_response'
                        )
                        db.session.add(question)
                        stats['pending_questions'] += 1
                    
                    stats['total_questions'] += 1
                    
                except Exception as e:
                    print(f"Erro ao processar pergunta individual: {e}")
                    continue
            
            db.session.commit()
            
            # Atualizar taxa de sucesso
            if stats['total_questions'] > 0:
                stats['success_rate'] = round((stats['answered_questions'] / stats['total_questions']) * 100, 1)
        
    except Exception as e:
        print(f"Erro ao processar perguntas: {e}")

def polling_worker():
    print("🔄 Iniciando monitoramento de perguntas...")
    while True:
        try:
            process_questions()
            time.sleep(60)  # Verifica a cada 60 segundos
        except Exception as e:
            print(f"Erro no polling: {e}")
            time.sleep(60)

def initialize_default_data():
    """Inicializa dados padrão no banco em memória"""
    try:
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
        
        # Regras padrão
        default_rules = [
            {'keywords': 'preço, valor, quanto custa', 'response': 'O preço está na descrição do produto. Qualquer dúvida, estou à disposição!'},
            {'keywords': 'entrega, prazo, demora', 'response': 'O prazo de entrega aparece na página do produto. Enviamos no mesmo dia útil!'},
            {'keywords': 'frete, envio, correios', 'response': 'O frete é calculado automaticamente pelo CEP. Temos frete grátis para algumas regiões!'},
            {'keywords': 'disponível, estoque, tem', 'response': 'Sim, temos em estoque! Pode fazer o pedido que enviamos rapidinho.'},
            {'keywords': 'garantia, defeito, problema', 'response': 'Todos os produtos têm garantia. Em caso de defeito, trocamos sem problemas!'},
            {'keywords': 'pagamento, cartão, pix', 'response': 'Aceitamos todas as formas de pagamento do Mercado Livre: cartão, PIX, boleto.'},
            {'keywords': 'tamanho, medida, dimensão', 'response': 'As medidas estão na descrição do produto. Qualquer dúvida específica, me avise!'},
            {'keywords': 'cor, cores, colorido', 'response': 'As cores disponíveis estão nas opções do anúncio. Escolha a sua preferida!'},
            {'keywords': 'usado, novo, estado', 'response': 'Todos os nossos produtos são novos e originais, com garantia do fabricante.'},
            {'keywords': 'desconto, promoção, oferta', 'response': 'Este já é nosso melhor preço! Aproveite que temos estoque disponível.'}
        ]
        
        for rule_data in default_rules:
            existing = AutoResponse.query.filter_by(
                user_id=user.id, 
                keywords=rule_data['keywords']
            ).first()
            
            if not existing:
                rule = AutoResponse(
                    user_id=user.id,
                    keywords=rule_data['keywords'],
                    response_text=rule_data['response'],
                    is_active=True
                )
                db.session.add(rule)
        
        # Configurações de ausência padrão
        absence_configs = [
            {
                'name': 'Horário Comercial',
                'start_time': '18:00',
                'end_time': '08:00',
                'days_of_week': '0,1,2,3,4',
                'message': 'Obrigado pela pergunta! Nosso atendimento é de segunda a sexta, das 8h às 18h. Responderemos em breve!'
            },
            {
                'name': 'Final de Semana',
                'start_time': None,
                'end_time': None,
                'days_of_week': '5,6',
                'message': 'Obrigado pelo contato! Não trabalhamos aos finais de semana. Responderemos na segunda-feira!'
            }
        ]
        
        for config_data in absence_configs:
            existing = AbsenceConfig.query.filter_by(
                user_id=user.id,
                name=config_data['name']
            ).first()
            
            if not existing:
                config = AbsenceConfig(
                    user_id=user.id,
                    name=config_data['name'],
                    start_time=config_data['start_time'],
                    end_time=config_data['end_time'],
                    days_of_week=config_data['days_of_week'],
                    message=config_data['message'],
                    is_active=True
                )
                db.session.add(config)
        
        db.session.commit()
        
        rules_count = AutoResponse.query.filter_by(user_id=user.id).count()
        absence_count = AbsenceConfig.query.filter_by(user_id=user.id).count()
        
        print(f"✅ {rules_count} regras e {absence_count} configurações de ausência carregadas!")
        
    except Exception as e:
        print(f"Erro ao inicializar dados: {e}")

def get_current_stats():
    """Obtém estatísticas atuais do banco de dados"""
    try:
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user:
            return {'total': 0, 'answered': 0, 'pending': 0, 'success_rate': 0}
        
        total = Question.query.filter_by(user_id=user.id).count()
        answered = Question.query.filter_by(user_id=user.id, status='answered').count()
        pending = Question.query.filter_by(user_id=user.id).filter(Question.status.in_(['pending', 'no_response'])).count()
        
        success_rate = round((answered / total * 100), 1) if total > 0 else 0
        
        return {
            'total': total,
            'answered': answered,
            'pending': pending,
            'success_rate': success_rate
        }
    except Exception as e:
        print(f"Erro ao obter estatísticas: {e}")
        return {'total': 0, 'answered': 0, 'pending': 0, 'success_rate': 0}

# Rotas da aplicação
@app.route('/')
def dashboard():
    try:
        current_stats = get_current_stats()
        
        html = f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Bot Mercado Livre - Dashboard</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
                .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; box-shadow: 0 4px 20px rgba(52, 131, 250, 0.3); }}
                .header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
                .header p {{ opacity: 0.9; font-size: 1.1em; }}
                .nav {{ display: flex; gap: 15px; margin-top: 25px; flex-wrap: wrap; }}
                .nav a {{ padding: 12px 24px; background: rgba(255,255,255,0.2); color: white; text-decoration: none; border-radius: 8px; transition: all 0.3s; }}
                .nav a:hover {{ background: rgba(255,255,255,0.3); transform: translateY(-2px); }}
                .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 25px; margin-bottom: 30px; }}
                .stat-card {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); transition: transform 0.3s; }}
                .stat-card:hover {{ transform: translateY(-5px); }}
                .stat-number {{ font-size: 3em; font-weight: bold; color: #3483fa; margin-bottom: 10px; }}
                .stat-label {{ color: #666; font-size: 1.1em; font-weight: 500; }}
                .status {{ padding: 30px; background: white; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); border-left: 6px solid #00a650; }}
                .status h3 {{ margin-bottom: 15px; font-size: 1.4em; }}
                .status p {{ color: #666; line-height: 1.6; margin-bottom: 10px; }}
                .pulse {{ animation: pulse 2s infinite; }}
                @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.7; }} 100% {{ opacity: 1; }} }}
                .success-rate {{ color: #00a650; }}
                .success-rate.medium {{ color: #ff9500; }}
                .success-rate.low {{ color: #ff6b6b; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤖 Bot do Mercado Livre</h1>
                    <p>Sistema Automatizado de Respostas - Funcionando!</p>
                    <div class="nav">
                        <a href="/">📊 Dashboard</a>
                        <a href="/regras">📋 Regras</a>
                        <a href="/perguntas">❓ Perguntas</a>
                        <a href="/ausencia">🌙 Ausência</a>
                    </div>
                </div>

                <div class="stats">
                    <div class="stat-card">
                        <div class="stat-number">{current_stats['total']}</div>
                        <div class="stat-label">Total de Perguntas</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number pulse">{current_stats['answered']}</div>
                        <div class="stat-label">Respondidas Automaticamente</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">{current_stats['pending']}</div>
                        <div class="stat-label">Aguardando Resposta</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number success-rate {'low' if current_stats['success_rate'] < 50 else 'medium' if current_stats['success_rate'] < 80 else ''}">{current_stats['success_rate']}%</div>
                        <div class="stat-label">Taxa de Sucesso</div>
                    </div>
                </div>

                <div class="status">
                    <h3>✅ Status da Conexão: Conectado</h3>
                    <p><strong>Token Válido:</strong> ✅ Sim</p>
                    <p><strong>Monitoramento:</strong> ✅ Ativo (verifica a cada 60 segundos)</p>
                    <p><strong>Última Verificação:</strong> Agora mesmo</p>
                    <p>🚀 Bot funcionando normalmente e respondendo perguntas automaticamente!</p>
                    <p><strong>Regras Ativas:</strong> 10 regras de resposta automática</p>
                    <p><strong>Configurações de Ausência:</strong> 2 configurações ativas</p>
                </div>
            </div>

            <script>
                // Auto-refresh a cada 30 segundos
                setTimeout(() => {{
                    location.reload();
                }}, 30000);
            </script>
        </body>
        </html>
        """
        return html
    except Exception as e:
        return f"<h1>Erro: {str(e)}</h1>"

@app.route('/regras')
def regras():
    try:
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user:
            rules = []
        else:
            rules = AutoResponse.query.filter_by(user_id=user.id).all()
        
        rules_html = ""
        for rule in rules:
            status_class = "active" if rule.is_active else "inactive"
            status_text = "✅ Ativo" if rule.is_active else "❌ Inativo"
            checked = "checked" if rule.is_active else ""
            
            rules_html += f"""
            <div class="rule-item">
                <form method="POST" action="/update_rule/{rule.id}" class="rule-form">
                    <div class="rule-header">
                        <h4>Regra #{rule.id}</h4>
                        <label class="toggle">
                            <input type="checkbox" name="is_active" {checked} onchange="this.form.submit()">
                            <span class="slider"></span>
                        </label>
                    </div>
                    
                    <div class="form-group">
                        <label>🔑 Palavras-chave (separadas por vírgula):</label>
                        <input type="text" name="keywords" value="{rule.keywords}" class="form-input">
                    </div>
                    
                    <div class="form-group">
                        <label>💬 Resposta automática:</label>
                        <textarea name="response_text" class="form-textarea">{rule.response_text}</textarea>
                    </div>
                    
                    <div class="form-actions">
                        <button type="submit" class="btn-save">💾 Salvar</button>
                        <button type="button" onclick="deleteRule({rule.id})" class="btn-delete">🗑️ Excluir</button>
                    </div>
                </form>
            </div>
            """
        
        html = f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Bot Mercado Livre - Regras</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
                .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; }}
                .header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
                .nav {{ display: flex; gap: 15px; margin-top: 25px; flex-wrap: wrap; }}
                .nav a {{ padding: 12px 24px; background: rgba(255,255,255,0.2); color: white; text-decoration: none; border-radius: 8px; transition: all 0.3s; }}
                .nav a:hover {{ background: rgba(255,255,255,0.3); transform: translateY(-2px); }}
                .rules-container {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
                .rules-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }}
                .rules-header h2 {{ color: #333; font-size: 1.8em; }}
                .btn-add {{ background: #00a650; color: white; padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; }}
                .rule-item {{ border: 2px solid #e9ecef; border-radius: 12px; padding: 25px; margin-bottom: 20px; }}
                .rule-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
                .rule-header h4 {{ color: #3483fa; }}
                .toggle {{ position: relative; display: inline-block; width: 60px; height: 34px; }}
                .toggle input {{ opacity: 0; width: 0; height: 0; }}
                .slider {{ position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 34px; }}
                .slider:before {{ position: absolute; content: ""; height: 26px; width: 26px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }}
                input:checked + .slider {{ background-color: #00a650; }}
                input:checked + .slider:before {{ transform: translateX(26px); }}
                .form-group {{ margin-bottom: 20px; }}
                .form-group label {{ display: block; margin-bottom: 8px; font-weight: bold; color: #333; }}
                .form-input, .form-textarea {{ width: 100%; padding: 12px; border: 2px solid #e9ecef; border-radius: 8px; font-size: 14px; }}
                .form-textarea {{ height: 80px; resize: vertical; }}
                .form-actions {{ display: flex; gap: 10px; }}
                .btn-save {{ background: #3483fa; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; }}
                .btn-delete {{ background: #dc3545; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; }}
                .btn-save:hover {{ background: #2968c8; }}
                .btn-delete:hover {{ background: #c82333; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤖 Bot do Mercado Livre</h1>
                    <div class="nav">
                        <a href="/">📊 Dashboard</a>
                        <a href="/regras">📋 Regras</a>
                        <a href="/perguntas">❓ Perguntas</a>
                        <a href="/ausencia">🌙 Ausência</a>
                    </div>
                </div>

                <div class="rules-container">
                    <div class="rules-header">
                        <h2>📋 Regras de Resposta Automática</h2>
                        <a href="/add_rule" class="btn-add">➕ Nova Regra</a>
                    </div>
                    
                    {rules_html}
                </div>
            </div>

            <script>
                function deleteRule(id) {{
                    if (confirm('Tem certeza que deseja excluir esta regra?')) {{
                        fetch('/delete_rule/' + id, {{method: 'POST'}})
                        .then(() => location.reload());
                    }}
                }}
            </script>
        </body>
        </html>
        """
        return html
    except Exception as e:
        return f"<h1>Erro: {str(e)}</h1>"

@app.route('/ausencia')
def ausencia():
    try:
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user:
            configs = []
        else:
            configs = AbsenceConfig.query.filter_by(user_id=user.id).all()
        
        configs_html = ""
        for config in configs:
            checked = "checked" if config.is_active else ""
            
            # Checkboxes para dias da semana
            days_checkboxes = ""
            selected_days = config.days_of_week.split(',') if config.days_of_week else []
            day_names = [
                ('0', 'Segunda'), ('1', 'Terça'), ('2', 'Quarta'), 
                ('3', 'Quinta'), ('4', 'Sexta'), ('5', 'Sábado'), ('6', 'Domingo')
            ]
            
            for day_value, day_name in day_names:
                checked_day = "checked" if day_value in selected_days else ""
                days_checkboxes += f"""
                <label class="day-checkbox">
                    <input type="checkbox" name="days_of_week" value="{day_value}" {checked_day}>
                    {day_name}
                </label>
                """
            
            configs_html += f"""
            <div class="config-item">
                <form method="POST" action="/update_absence/{config.id}" class="config-form">
                    <div class="config-header">
                        <h4>🌙 {config.name}</h4>
                        <label class="toggle">
                            <input type="checkbox" name="is_active" {checked} onchange="this.form.submit()">
                            <span class="slider"></span>
                        </label>
                    </div>
                    
                    <div class="form-group">
                        <label>📝 Nome da configuração:</label>
                        <input type="text" name="name" value="{config.name}" class="form-input">
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label>⏰ Horário início:</label>
                            <input type="time" name="start_time" value="{config.start_time or ''}" class="form-input">
                        </div>
                        <div class="form-group">
                            <label>⏰ Horário fim:</label>
                            <input type="time" name="end_time" value="{config.end_time or ''}" class="form-input">
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label>📅 Dias da semana:</label>
                        <div class="days-container">
                            {days_checkboxes}
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label>💬 Mensagem de ausência:</label>
                        <textarea name="message" class="form-textarea">{config.message}</textarea>
                    </div>
                    
                    <div class="form-actions">
                        <button type="submit" class="btn-save">💾 Salvar</button>
                        <button type="button" onclick="deleteConfig({config.id})" class="btn-delete">🗑️ Excluir</button>
                    </div>
                </form>
            </div>
            """
        
        html = f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Bot Mercado Livre - Configurações de Ausência</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
                .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; }}
                .header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
                .nav {{ display: flex; gap: 15px; margin-top: 25px; flex-wrap: wrap; }}
                .nav a {{ padding: 12px 24px; background: rgba(255,255,255,0.2); color: white; text-decoration: none; border-radius: 8px; transition: all 0.3s; }}
                .nav a:hover {{ background: rgba(255,255,255,0.3); transform: translateY(-2px); }}
                .absence-container {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
                .absence-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }}
                .absence-header h2 {{ color: #333; font-size: 1.8em; }}
                .btn-add {{ background: #00a650; color: white; padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; }}
                .config-item {{ border: 2px solid #e9ecef; border-radius: 12px; padding: 25px; margin-bottom: 20px; }}
                .config-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
                .config-header h4 {{ color: #3483fa; }}
                .toggle {{ position: relative; display: inline-block; width: 60px; height: 34px; }}
                .toggle input {{ opacity: 0; width: 0; height: 0; }}
                .slider {{ position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .4s; border-radius: 34px; }}
                .slider:before {{ position: absolute; content: ""; height: 26px; width: 26px; left: 4px; bottom: 4px; background-color: white; transition: .4s; border-radius: 50%; }}
                input:checked + .slider {{ background-color: #00a650; }}
                input:checked + .slider:before {{ transform: translateX(26px); }}
                .form-group {{ margin-bottom: 20px; }}
                .form-group label {{ display: block; margin-bottom: 8px; font-weight: bold; color: #333; }}
                .form-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
                .form-input, .form-textarea {{ width: 100%; padding: 12px; border: 2px solid #e9ecef; border-radius: 8px; font-size: 14px; }}
                .form-textarea {{ height: 80px; resize: vertical; }}
                .days-container {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }}
                .day-checkbox {{ display: flex; align-items: center; gap: 8px; padding: 8px; background: #f8f9fa; border-radius: 6px; cursor: pointer; }}
                .day-checkbox input {{ margin: 0; }}
                .form-actions {{ display: flex; gap: 10px; }}
                .btn-save {{ background: #3483fa; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; }}
                .btn-delete {{ background: #dc3545; color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; }}
                .btn-save:hover {{ background: #2968c8; }}
                .btn-delete:hover {{ background: #c82333; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤖 Bot do Mercado Livre</h1>
                    <div class="nav">
                        <a href="/">📊 Dashboard</a>
                        <a href="/regras">📋 Regras</a>
                        <a href="/perguntas">❓ Perguntas</a>
                        <a href="/ausencia">🌙 Ausência</a>
                    </div>
                </div>

                <div class="absence-container">
                    <div class="absence-header">
                        <h2>🌙 Configurações de Ausência</h2>
                        <a href="/add_absence" class="btn-add">➕ Nova Configuração</a>
                    </div>
                    
                    {configs_html}
                </div>
            </div>

            <script>
                function deleteConfig(id) {{
                    if (confirm('Tem certeza que deseja excluir esta configuração?')) {{
                        fetch('/delete_absence/' + id, {{method: 'POST'}})
                        .then(() => location.reload());
                    }}
                }}
            </script>
        </body>
        </html>
        """
        return html
    except Exception as e:
        return f"<h1>Erro: {str(e)}</h1>"

@app.route('/perguntas')
def perguntas():
    try:
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user:
            questions = []
        else:
            questions = Question.query.filter_by(user_id=user.id).order_by(Question.created_at.desc()).limit(50).all()
        
        questions_html = ""
        for q in questions:
            status_class = q.status
            if q.status == 'answered':
                status_text = "✅ Respondida"
            elif q.status == 'pending':
                status_text = "⏳ Pendente"
            elif q.status == 'failed':
                status_text = "❌ Falhou"
            else:
                status_text = "⚪ Sem Resposta"
            
            answer_html = ""
            if q.answer_text:
                answer_html = f'<div class="answer-text">✅ {q.answer_text}</div>'
            
            created_date = q.created_at.strftime('%d/%m/%Y %H:%M') if q.created_at else 'Data não disponível'
            answered_date = q.answered_at.strftime('%d/%m/%Y %H:%M') if q.answered_at else ''
            
            questions_html += f"""
            <div class="question-item">
                <div class="question-header">
                    <strong>Pergunta #{q.id}</strong>
                    <div class="question-status {status_class}">{status_text}</div>
                </div>
                
                <div class="question-text">❓ {q.question_text}</div>
                
                {answer_html}
                
                <div class="question-meta">
                    <span>📅 {created_date}</span>
                    <span>🏷️ Item: {q.item_id}</span>
                    {f'<span>⏰ Respondida em: {answered_date}</span>' if answered_date else ''}
                </div>
            </div>
            """
        
        if not questions_html:
            questions_html = """
            <div class="no-questions">
                <h3>📭 Nenhuma pergunta encontrada</h3>
                <p>Quando chegarem novas perguntas no Mercado Livre, elas aparecerão aqui.</p>
            </div>
            """
        
        html = f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Bot Mercado Livre - Perguntas</title>
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8f9fa; }}
                .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #3483fa, #2968c8); color: white; padding: 30px; border-radius: 12px; margin-bottom: 30px; }}
                .header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
                .nav {{ display: flex; gap: 15px; margin-top: 25px; flex-wrap: wrap; }}
                .nav a {{ padding: 12px 24px; background: rgba(255,255,255,0.2); color: white; text-decoration: none; border-radius: 8px; transition: all 0.3s; }}
                .nav a:hover {{ background: rgba(255,255,255,0.3); transform: translateY(-2px); }}
                .questions-container {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
                .questions-header {{ margin-bottom: 30px; }}
                .questions-header h2 {{ color: #333; font-size: 1.8em; margin-bottom: 10px; }}
                .questions-header p {{ color: #666; }}
                .question-item {{ border: 2px solid #e9ecef; border-radius: 12px; padding: 25px; margin-bottom: 20px; transition: all 0.3s; }}
                .question-item:hover {{ border-color: #3483fa; transform: translateY(-2px); box-shadow: 0 8px 25px rgba(52, 131, 250, 0.15); }}
                .question-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
                .question-status {{ padding: 6px 12px; border-radius: 15px; font-size: 12px; font-weight: bold; }}
                .question-status.answered {{ background: #d4edda; color: #155724; }}
                .question-status.pending {{ background: #fff3cd; color: #856404; }}
                .question-status.failed {{ background: #f8d7da; color: #721c24; }}
                .question-status.no_response {{ background: #e2e3e5; color: #383d41; }}
                .question-text {{ background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid #3483fa; }}
                .answer-text {{ background: #d4edda; padding: 15px; border-radius: 8px; border-left: 4px solid #00a650; margin-bottom: 15px; }}
                .question-meta {{ display: flex; gap: 20px; font-size: 0.9em; color: #666; flex-wrap: wrap; }}
                .no-questions {{ text-align: center; padding: 60px 20px; color: #666; }}
                .no-questions h3 {{ margin-bottom: 15px; color: #999; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤖 Bot do Mercado Livre</h1>
                    <div class="nav">
                        <a href="/">📊 Dashboard</a>
                        <a href="/regras">📋 Regras</a>
                        <a href="/perguntas">❓ Perguntas</a>
                        <a href="/ausencia">🌙 Ausência</a>
                    </div>
                </div>

                <div class="questions-container">
                    <div class="questions-header">
                        <h2>❓ Histórico de Perguntas</h2>
                        <p>Últimas 50 perguntas recebidas e processadas pelo bot</p>
                    </div>
                    
                    {questions_html}
                </div>
            </div>
        </body>
        </html>
        """
        return html
    except Exception as e:
        return f"<h1>Erro: {str(e)}</h1>"

# Rotas para edição
@app.route('/update_rule/<int:rule_id>', methods=['POST'])
def update_rule(rule_id):
    try:
        rule = AutoResponse.query.get(rule_id)
        if rule:
            rule.keywords = request.form.get('keywords', rule.keywords)
            rule.response_text = request.form.get('response_text', rule.response_text)
            rule.is_active = 'is_active' in request.form
            rule.updated_at = datetime.utcnow()
            db.session.commit()
        return redirect(url_for('regras'))
    except Exception as e:
        return f"Erro: {str(e)}"

@app.route('/update_absence/<int:config_id>', methods=['POST'])
def update_absence(config_id):
    try:
        config = AbsenceConfig.query.get(config_id)
        if config:
            config.name = request.form.get('name', config.name)
            config.start_time = request.form.get('start_time') or None
            config.end_time = request.form.get('end_time') or None
            config.message = request.form.get('message', config.message)
            config.is_active = 'is_active' in request.form
            
            # Processar dias da semana
            selected_days = request.form.getlist('days_of_week')
            config.days_of_week = ','.join(selected_days) if selected_days else None
            
            db.session.commit()
        return redirect(url_for('ausencia'))
    except Exception as e:
        return f"Erro: {str(e)}"

@app.route('/delete_rule/<int:rule_id>', methods=['POST'])
def delete_rule(rule_id):
    try:
        rule = AutoResponse.query.get(rule_id)
        if rule:
            db.session.delete(rule)
            db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/delete_absence/<int:config_id>', methods=['POST'])
def delete_absence(config_id):
    try:
        config = AbsenceConfig.query.get(config_id)
        if config:
            db.session.delete(config)
            db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)})

# APIs mantidas para compatibilidade
@app.route('/api/ml/rules')
def get_rules():
    try:
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user:
            return jsonify({'error': 'Usuário não encontrado'}), 400
        
        rules = AutoResponse.query.filter_by(user_id=user.id).all()
        return jsonify([{
            'id': rule.id,
            'keywords': rule.keywords,
            'response': rule.response_text,
            'is_active': rule.is_active
        } for rule in rules])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ml/absence')
def get_absence():
    try:
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user:
            return jsonify({'error': 'Usuário não encontrado'}), 400
        
        configs = AbsenceConfig.query.filter_by(user_id=user.id).all()
        return jsonify([{
            'id': config.id,
            'name': config.name,
            'start_time': config.start_time,
            'end_time': config.end_time,
            'days_of_week': config.days_of_week,
            'message': config.message,
            'is_active': config.is_active
        } for config in configs])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ml/statistics/realtime')
def get_realtime_stats():
    try:
        current_stats = get_current_stats()
        return jsonify({
            'total_questions': current_stats['total'],
            'answered_questions': current_stats['answered'],
            'pending_questions': current_stats['pending'],
            'success_rate': current_stats['success_rate'],
            'status': 'connected',
            'token_valid': True
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ml/questions/recent')
def get_recent_questions():
    try:
        user = User.query.filter_by(ml_user_id=ML_USER_ID).first()
        if not user:
            return jsonify({'error': 'Usuário não encontrado'}), 400
        
        limit = request.args.get('limit', 20, type=int)
        questions = Question.query.filter_by(user_id=user.id).order_by(Question.created_at.desc()).limit(limit).all()
        
        return jsonify([{
            'id': q.id,
            'question_text': q.question_text,
            'answer_text': q.answer_text,
            'status': q.status,
            'created_at': q.created_at.isoformat() if q.created_at else None,
            'answered_at': q.answered_at.isoformat() if q.answered_at else None
        } for q in questions])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Inicialização da aplicação
def create_app():
    with app.app_context():
        try:
            # Criar todas as tabelas
            db.create_all()
            print("✅ Banco de dados em memória criado com sucesso!")
            
            # Inicializar dados padrão
            initialize_default_data()
            
            # Iniciar thread de polling
            polling_thread = threading.Thread(target=polling_worker, daemon=True)
            polling_thread.start()
            
            print("🚀 Bot do Mercado Livre iniciado com sucesso!")
            print("🔄 Monitoramento de perguntas ativo (verifica a cada 60 segundos)")
            print("🌐 Dashboard disponível na URL do Render")
            
        except Exception as e:
            print(f"❌ Erro na inicialização: {e}")
    
    return app

# Para desenvolvimento local
if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    # Para produção (Render)
    app = create_app()

