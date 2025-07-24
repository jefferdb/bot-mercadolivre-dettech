"""
Bot do Mercado Livre - Versão Railway
Versão básica sem IA, otimizada para PostgreSQL
"""

import os
import sys
import threading
from datetime import datetime
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS

# Adicionar diretório src ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Importar módulos do bot
from models.user import db
from models.mercadolivre import MLCredentials, MLQuestion, MLAutoResponse, MLLog
from routes.user import user_bp
from routes.mercadolivre import ml_bp
from services.polling_service import PollingService

# Configurar Flask
app = Flask(__name__, static_folder='src/static')

# Configuração para Railway
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dettech_bot_railway_2024')

# Habilitar CORS
CORS(app, origins="*")

# Registrar blueprints
app.register_blueprint(user_bp, url_prefix='/api')
app.register_blueprint(ml_bp, url_prefix='/api/ml')

# Configuração do banco PostgreSQL para Railway
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # PostgreSQL no Railway
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    # Fallback para desenvolvimento local
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///src/database/app.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializar banco
db.init_app(app)

# Variável global para polling service
polling_service = None

def initialize_database():
    """Inicializar banco de dados"""
    with app.app_context():
        try:
            # Criar todas as tabelas
            db.create_all()
            
            # Verificar se já existem credenciais
            if MLCredentials.query.count() == 0:
                print("📝 Inicializando credenciais padrão...")
                credentials = MLCredentials(
                    client_id=os.environ.get('ML_CLIENT_ID', "5510376630479325"),
                    client_secret=os.environ.get('ML_CLIENT_SECRET', "jlR4As2x8uFY3RTpysLpuPhzC9yM9d35"),
                    access_token=os.environ.get('ML_ACCESS_TOKEN', "APP_USR-5510376630479325-072321-31ceebc6a2428e8723948d8e00c75015-180617463"),
                    user_id=os.environ.get('ML_USER_ID', "180617463")
                )
                db.session.add(credentials)
                db.session.commit()
                print("✅ Credenciais inicializadas")
            
            # Restaurar regras se não existirem
            restore_default_rules()
            
            print("✅ Banco de dados inicializado")
            
        except Exception as e:
            print(f"❌ Erro ao inicializar banco: {e}")

def restore_default_rules():
    """Restaurar regras padrão se não existirem"""
    try:
        if MLAutoResponse.query.count() > 0:
            print("⚠️ Regras já existem - pulando restauração")
            return
        
        print("🤖 Restaurando regras padrão...")
        
        # Regras básicas
        default_rules = [
            {
                "name": "Saudação e Boas-vindas",
                "keywords": '["olá", "oi", "bom dia", "boa tarde", "boa noite", "tudo bem"]',
                "response": "Olá! Seja muito bem-vindo à DETTECH! Estamos aqui para ajudá-lo com peças automotivas de qualidade. Como posso auxiliá-lo hoje? Atenciosamente, Jeff - Equipe DETTECH.",
                "priority": 1,
                "active": True
            },
            {
                "name": "Compatibilidade - Numeração Original",
                "keywords": '["compatível", "serve", "funciona", "encaixa", "modelo", "ano"]',
                "response": "Olá, seja bem-vindo à DETTECH! Para confirmar a compatibilidade, precisamos que informe a numeração original constante na sua peça. Atenciosamente, Jeff - Equipe DETTECH.",
                "priority": 10,
                "active": True
            },
            {
                "name": "Prazo de Entrega",
                "keywords": '["prazo", "entrega", "demora", "quando chega", "tempo", "dias"]',
                "response": "O prazo de entrega varia conforme sua localização. Após a confirmação do pagamento, o envio é realizado em até 1 dia útil. O prazo de entrega pelos Correios é de 3 a 10 dias úteis. Atenciosamente, Jeff - Equipe DETTECH.",
                "priority": 8,
                "active": True
            },
            {
                "name": "Garantia",
                "keywords": '["garantia", "defeito", "problema", "troca", "devolução"]',
                "response": "Todos os nossos produtos possuem garantia de 90 dias contra defeitos de fabricação. Em caso de problemas, entre em contato conosco que resolveremos rapidamente. Atenciosamente, Jeff - Equipe DETTECH.",
                "priority": 9,
                "active": True
            },
            {
                "name": "Preço e Pagamento",
                "keywords": '["preço", "valor", "custa", "pagamento", "desconto", "parcelamento"]',
                "response": "O preço está anunciado no produto. Aceitamos PIX (com desconto), cartão de crédito e débito. Para PIX, oferecemos desconto especial. Atenciosamente, Jeff - Equipe DETTECH.",
                "priority": 7,
                "active": True
            }
        ]
        
        for rule_data in default_rules:
            rule = MLAutoResponse(
                name=rule_data["name"],
                keywords=rule_data["keywords"],
                response=rule_data["response"],
                priority=rule_data["priority"],
                active=rule_data["active"],
                created_at=datetime.now()
            )
            db.session.add(rule)
        
        db.session.commit()
        print(f"✅ {len(default_rules)} regras restauradas!")
        
    except Exception as e:
        print(f"❌ Erro ao restaurar regras: {e}")

def start_polling_service():
    """Iniciar serviço de polling"""
    global polling_service
    
    try:
        # Obter credenciais das variáveis de ambiente
        CLIENT_ID = os.environ.get('ML_CLIENT_ID', "5510376630479325")
        CLIENT_SECRET = os.environ.get('ML_CLIENT_SECRET', "jlR4As2x8uFY3RTpysLpuPhzC9yM9d35")
        INITIAL_TOKEN = os.environ.get('ML_ACCESS_TOKEN', "APP_USR-5510376630479325-072321-31ceebc6a2428e8723948d8e00c75015-180617463")
        
        # Inicializar serviço de polling
        polling_service = PollingService(CLIENT_ID, CLIENT_SECRET, None, INITIAL_TOKEN)
        polling_service.start()
        
        print("🤖 Bot do Mercado Livre iniciado!")
        print("🔄 Verificando novas perguntas a cada 60 segundos")
        print("🔑 Token será renovado automaticamente a cada 6 horas")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao iniciar polling: {e}")
        return False

# Rotas principais
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    """Servir arquivos estáticos"""
    static_folder_path = app.static_folder
    if static_folder_path is None:
        return "Static folder not configured", 404

    if path != "" and os.path.exists(os.path.join(static_folder_path, path)):
        return send_from_directory(static_folder_path, path)
    else:
        index_path = os.path.join(static_folder_path, 'index.html')
        if os.path.exists(index_path):
            return send_from_directory(static_folder_path, 'index.html')
        else:
            return "Dashboard não encontrado", 404

@app.route('/api/health')
def health_check():
    """Health check para Railway"""
    try:
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'database': 'connected' if db else 'disconnected',
            'polling': 'active' if polling_service and polling_service.is_running else 'inactive',
            'version': 'Railway Basic v1.0'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

# Inicialização
def initialize_app():
    """Inicializar aplicação"""
    print("🚀 Iniciando Bot do Mercado Livre para Railway...")
    
    # Inicializar banco de dados
    initialize_database()
    
    # Iniciar serviços em thread separada (para não bloquear o startup)
    def start_services():
        import time
        time.sleep(5)  # Aguardar app estar pronta
        start_polling_service()
    
    service_thread = threading.Thread(target=start_services, daemon=True)
    service_thread.start()
    
    print("✅ Bot inicializado com sucesso!")

# Inicializar quando importado
initialize_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

