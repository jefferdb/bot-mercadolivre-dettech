from flask import Flask, render_template, redirect, request
import requests
import json
import os
from datetime import datetime, timedelta

app = Flask(__name__)

CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI', 'https://seusite.render.com/callback')  # Altere se necessário
TOKEN_FILE = 'tokens.json'

def save_tokens(data):
    with open(TOKEN_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def load_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'r') as f:
            return json.load(f)
    return {}

def refresh_token_if_needed():
    tokens = load_tokens()
    if not tokens:
        return

    expires_at = datetime.fromisoformat(tokens.get('expires_at'))
    if datetime.utcnow() >= expires_at:
        print('🔁 Token expirado, atualizando...')
        refresh_payload = {
            'grant_type': 'refresh_token',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'refresh_token': tokens.get('refresh_token'),
        }
        response = requests.post('https://api.mercadolibre.com/oauth/token', data=refresh_payload)
        if response.status_code == 200:
            new_tokens = response.json()
            new_tokens['expires_at'] = (datetime.utcnow() + timedelta(seconds=new_tokens['expires_in'])).isoformat()
            save_tokens(new_tokens)
            print('✅ Token atualizado com sucesso')
        else:
            print('❌ Erro ao atualizar token:', response.text)

@app.route('/')
def index():
    refresh_token_if_needed()
    tokens = load_tokens()
    return render_template('index.html', tokens=tokens)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return 'Erro: código não fornecido', 400

    payload = {
        'grant_type': 'authorization_code',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'redirect_uri': REDIRECT_URI,
    }

    response = requests.post('https://api.mercadolibre.com/oauth/token', data=payload)
    if response.status_code == 200:
        tokens = response.json()
        tokens['expires_at'] = (datetime.utcnow() + timedelta(seconds=tokens['expires_in'])).isoformat()
        save_tokens(tokens)
        return redirect('/')
    else:
        return f'Erro ao gerar token: {response.text}', 400

if __name__ == '__main__':
    app.run(debug=True)
