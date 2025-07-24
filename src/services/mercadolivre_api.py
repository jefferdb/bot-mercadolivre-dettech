import requests
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from src.models.mercadolivre import db, MLCredentials, MLQuestion, MLLog

class MercadoLivreAPI:
    """Classe para integração com API do Mercado Livre"""
    
    BASE_URL = "https://api.mercadolibre.com"
    
    def __init__(self):
        self.credentials = None
        self.load_credentials()
    
    def load_credentials(self):
        """Carrega credenciais do banco de dados"""
        self.credentials = MLCredentials.query.first()
        if not self.credentials:
            self.log_error("Credenciais não encontradas no banco de dados")
    
    def log_info(self, message: str, data: Dict = None):
        """Log de informação"""
        log = MLLog(level='INFO', message=message)
        if data:
            log.set_data(data)
        db.session.add(log)
        db.session.commit()
        print(f"ℹ️  {message}")
    
    def log_warning(self, message: str, data: Dict = None):
        """Log de aviso"""
        log = MLLog(level='WARNING', message=message)
        if data:
            log.set_data(data)
        db.session.add(log)
        db.session.commit()
        print(f"⚠️  {message}")
    
    def log_error(self, message: str, data: Dict = None):
        """Log de erro"""
        log = MLLog(level='ERROR', message=message)
        if data:
            log.set_data(data)
        db.session.add(log)
        db.session.commit()
        print(f"❌ {message}")
    
    def make_request(self, endpoint: str, method: str = "GET", data: Dict = None, params: Dict = None) -> Optional[Dict]:
        """Faz requisição à API do Mercado Livre"""
        if not self.credentials or not self.credentials.access_token:
            self.log_error("Token de acesso não disponível")
            return None
        
        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            'Authorization': f'Bearer {self.credentials.access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=data, params=params)
            elif method == "PUT":
                response = requests.put(url, headers=headers, json=data, params=params)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:
                self.log_warning("Token expirado, tentando renovar")
                if self.refresh_token():
                    # Tentar novamente com token renovado
                    return self.make_request(endpoint, method, data, params)
                else:
                    self.log_error("Falha ao renovar token")
                    return None
            else:
                self.log_error(f"Erro na API: {response.status_code}", {
                    'endpoint': endpoint,
                    'method': method,
                    'response': response.text
                })
                return None
                
        except Exception as e:
            self.log_error(f"Erro na requisição: {str(e)}", {
                'endpoint': endpoint,
                'method': method,
                'error': str(e)
            })
            return None
    
    def refresh_token(self) -> bool:
        """Renova o token de acesso"""
        if not self.credentials or not self.credentials.refresh_token:
            return False
        
        url = f"{self.BASE_URL}/oauth/token"
        data = {
            'grant_type': 'refresh_token',
            'client_id': self.credentials.client_id,
            'client_secret': self.credentials.client_secret,
            'refresh_token': self.credentials.refresh_token
        }
        
        try:
            response = requests.post(url, data=data)
            if response.status_code == 200:
                token_data = response.json()
                
                # Atualizar credenciais
                self.credentials.access_token = token_data.get('access_token')
                self.credentials.refresh_token = token_data.get('refresh_token')
                self.credentials.expires_at = datetime.utcnow() + timedelta(seconds=token_data.get('expires_in', 21600))
                self.credentials.updated_at = datetime.utcnow()
                
                db.session.commit()
                self.log_info("Token renovado com sucesso")
                return True
            else:
                self.log_error(f"Falha ao renovar token: {response.status_code}")
                return False
                
        except Exception as e:
            self.log_error(f"Erro ao renovar token: {str(e)}")
            return False
    
    def get_user_info(self) -> Optional[Dict]:
        """Obtém informações do usuário"""
        return self.make_request("/users/me")
    
    def get_questions(self, status: str = None, limit: int = 50, offset: int = 0) -> Optional[Dict]:
        """Obtém perguntas recebidas"""
        params = {
            'limit': limit,
            'offset': offset
        }
        
        if status:
            params['status'] = status
        
        return self.make_request("/my/received_questions/search", params=params)
    
    def get_unanswered_questions(self) -> List[Dict]:
        """Obtém perguntas não respondidas (para teste, busca todas)"""
        # Para teste, buscar todas as perguntas (incluindo respondidas)
        result = self.get_questions(limit=50)
        if result and 'results' in result:
            # Filtrar apenas não respondidas se necessário
            questions = result['results']
            # Para teste: retornar todas, depois filtrar apenas UNANSWERED
            return [q for q in questions if q.get('status') == 'UNANSWERED'] or questions[:5]  # Para teste
        return []
    
    def answer_question(self, question_id: int, answer_text: str) -> bool:
        """Responde uma pergunta"""
        data = {
            'question_id': question_id,
            'text': answer_text
        }
        
        result = self.make_request(f"/answers", method="POST", data=data)
        
        if result:
            self.log_info(f"Pergunta {question_id} respondida com sucesso")
            return True
        else:
            self.log_error(f"Falha ao responder pergunta {question_id}")
            return False
    
    def sync_questions(self) -> int:
        """Sincroniza perguntas do ML com banco local"""
        questions_data = self.get_questions(limit=100)
        
        if not questions_data or 'results' not in questions_data:
            self.log_warning("Nenhuma pergunta encontrada para sincronizar")
            return 0
        
        synced_count = 0
        
        for q_data in questions_data['results']:
            try:
                # Verificar se pergunta já existe
                existing = MLQuestion.query.filter_by(id=q_data['id']).first()
                
                if not existing:
                    # Criar nova pergunta
                    question = MLQuestion(
                        id=q_data['id'],
                        item_id=q_data['item_id'],
                        seller_id=q_data['seller_id'],
                        from_user_id=q_data['from']['id'],
                        text=q_data['text'],
                        status=q_data['status'],
                        date_created=datetime.fromisoformat(q_data['date_created'].replace('Z', '+00:00'))
                    )
                    
                    # Se tem resposta, adicionar
                    if 'answer' in q_data and q_data['answer']:
                        question.answer_text = q_data['answer']['text']
                        question.answer_date = datetime.fromisoformat(q_data['answer']['date_created'].replace('Z', '+00:00'))
                    
                    db.session.add(question)
                    synced_count += 1
                else:
                    # Atualizar status se mudou
                    if existing.status != q_data['status']:
                        existing.status = q_data['status']
                        
                        # Atualizar resposta se foi adicionada
                        if 'answer' in q_data and q_data['answer'] and not existing.answer_text:
                            existing.answer_text = q_data['answer']['text']
                            existing.answer_date = datetime.fromisoformat(q_data['answer']['date_created'].replace('Z', '+00:00'))
                        
                        synced_count += 1
                
            except Exception as e:
                self.log_error(f"Erro ao sincronizar pergunta {q_data.get('id')}: {str(e)}")
        
        db.session.commit()
        self.log_info(f"Sincronizadas {synced_count} perguntas")
        return synced_count
    
    def test_connection(self) -> Dict[str, Any]:
        """Testa conexão com a API"""
        user_info = self.get_user_info()
        
        if user_info:
            return {
                'success': True,
                'user_id': user_info.get('id'),
                'nickname': user_info.get('nickname'),
                'email': user_info.get('email')
            }
        else:
            return {
                'success': False,
                'error': 'Falha ao conectar com a API'
            }

