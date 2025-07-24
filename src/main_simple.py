import os
import sys
# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, send_from_directory
from flask_cors import CORS
from src.models.user import db
from src.models.mercadolivre import MLCredentials, MLQuestion, MLAutoResponse, MLLog
from src.routes.user import user_bp
from src.routes.mercadolivre import ml_bp

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))

# Configuração
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'asdf#FGSgvasgf$5$WGT')

# Habilitar CORS para todas as rotas
CORS(app)

app.register_blueprint(user_bp, url_prefix='/api')
app.register_blueprint(ml_bp, url_prefix='/api/ml')

# Configuração do banco de dados
database_url = f"sqlite:///{os.path.join(os.path.dirname(__file__), 'database', 'app.db')}"
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Criar diretório do banco se não existir
db_dir = os.path.join(os.path.dirname(__file__), 'database')
if not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

with app.app_context():
    db.create_all()
    
    # Verificar se já existem credenciais
    if MLCredentials.query.count() == 0:
        # Inserir credenciais
        credentials = MLCredentials(
            client_id="5510376630479325",
            client_secret="jlR4As2x8uFY3RTpysLpuPhzC9yM9d35",
            access_token="APP_USR-5510376630479325-072321-31ceebc6a2428e8723948d8e00c75015-180617463",
            user_id="180617463"
        )
        db.session.add(credentials)
        db.session.commit()
        print("✅ Credenciais inicializadas")

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
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
            return "index.html not found", 404

if __name__ == '__main__':
    print("🤖 Bot do Mercado Livre iniciado (modo simples)!")
    
    # Configuração
    port = int(os.environ.get('PORT', 5004))
    
    app.run(host='0.0.0.0', port=port, debug=True)

