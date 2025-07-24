from .user import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID
import uuid
import json

class MLCredentials(db.Model):
    """Modelo para armazenar credenciais do Mercado Livre"""
    __tablename__ = 'ml_credentials'
    
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(50), nullable=False)
    client_secret = db.Column(db.String(100), nullable=False)
    access_token = db.Column(db.Text, nullable=True)
    refresh_token = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.String(50), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'client_id': self.client_id,
            'user_id': self.user_id,
            'has_token': bool(self.access_token),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class MLQuestion(db.Model):
    """Modelo para armazenar perguntas do Mercado Livre"""
    __tablename__ = 'ml_questions'
    
    id = db.Column(db.BigInteger, primary_key=True)  # ID da pergunta no ML
    item_id = db.Column(db.String(50), nullable=False)
    seller_id = db.Column(db.BigInteger, nullable=False)
    from_user_id = db.Column(db.BigInteger, nullable=False)
    text = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False)  # ANSWERED, UNANSWERED, etc.
    date_created = db.Column(db.DateTime, nullable=False)
    answer_text = db.Column(db.Text, nullable=True)
    answer_date = db.Column(db.DateTime, nullable=True)
    processed = db.Column(db.Boolean, default=False)
    processed_at = db.Column(db.DateTime, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'item_id': self.item_id,
            'seller_id': self.seller_id,
            'from_user_id': self.from_user_id,
            'text': self.text,
            'status': self.status,
            'date_created': self.date_created.isoformat(),
            'answer_text': self.answer_text,
            'answer_date': self.answer_date.isoformat() if self.answer_date else None,
            'processed': self.processed,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None
        }

class MLAutoResponse(db.Model):
    """Modelo para regras de resposta automática"""
    __tablename__ = 'ml_auto_responses'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    keywords = db.Column(db.Text, nullable=False)  # JSON array de palavras-chave
    response_text = db.Column(db.Text, nullable=False)
    active = db.Column(db.Boolean, default=True)
    priority = db.Column(db.Integer, default=0)  # Maior prioridade = processado primeiro
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def get_keywords(self):
        """Retorna lista de palavras-chave"""
        try:
            return json.loads(self.keywords)
        except:
            return []
    
    def set_keywords(self, keywords_list):
        """Define lista de palavras-chave"""
        self.keywords = json.dumps(keywords_list, ensure_ascii=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'keywords': self.get_keywords(),
            'response_text': self.response_text,
            'active': self.active,
            'priority': self.priority,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class MLLog(db.Model):
    """Modelo para logs do sistema"""
    __tablename__ = 'ml_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(10), nullable=False)  # INFO, WARNING, ERROR
    message = db.Column(db.Text, nullable=False)
    data = db.Column(db.Text, nullable=True)  # JSON data adicional
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_data(self, data_dict):
        """Define dados adicionais como JSON"""
        if data_dict:
            self.data = json.dumps(data_dict, ensure_ascii=False, default=str)
    
    def get_data(self):
        """Retorna dados adicionais como dict"""
        try:
            return json.loads(self.data) if self.data else {}
        except:
            return {}
    
    def to_dict(self):
        return {
            'id': self.id,
            'level': self.level,
            'message': self.message,
            'data': self.get_data(),
            'created_at': self.created_at.isoformat()
        }


class MLResponseQuality(db.Model):
    """Modelo para monitoramento de qualidade das respostas"""
    __tablename__ = 'ml_response_quality'
    
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.BigInteger, nullable=False)
    rule_id = db.Column(db.Integer, db.ForeignKey('ml_auto_responses.id'), nullable=True)
    question_text = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text, nullable=False)
    keywords_matched = db.Column(db.Text, nullable=True)  # JSON array
    response_time = db.Column(db.Float, nullable=True)  # Tempo de resposta em segundos
    success = db.Column(db.Boolean, nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    quality_score = db.Column(db.Integer, nullable=True)  # 1-5 score
    feedback = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relacionamento
    rule = db.relationship('MLAutoResponse', backref='quality_logs')
    
    def set_keywords_matched(self, keywords_list):
        """Define palavras-chave que fizeram match"""
        self.keywords_matched = json.dumps(keywords_list, ensure_ascii=False)
    
    def get_keywords_matched(self):
        """Retorna palavras-chave que fizeram match"""
        try:
            return json.loads(self.keywords_matched) if self.keywords_matched else []
        except:
            return []
    
    def to_dict(self):
        return {
            'id': self.id,
            'question_id': self.question_id,
            'rule_id': self.rule_id,
            'question_text': self.question_text,
            'response_text': self.response_text,
            'keywords_matched': self.get_keywords_matched(),
            'response_time': self.response_time,
            'success': self.success,
            'error_message': self.error_message,
            'quality_score': self.quality_score,
            'feedback': self.feedback,
            'created_at': self.created_at.isoformat(),
            'rule_name': self.rule.name if self.rule else None
        }

class MLAbsenceResponse(db.Model):
    """Modelo para configuração de respostas de ausência"""
    __tablename__ = 'ml_absence_responses'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    active = db.Column(db.Boolean, default=False)
    start_time = db.Column(db.Time, nullable=False)  # Início do horário comercial
    end_time = db.Column(db.Time, nullable=False)    # Fim do horário comercial
    weekdays_only = db.Column(db.Boolean, default=True)  # Apenas dias úteis
    timezone = db.Column(db.String(50), default='America/Sao_Paulo')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'message': self.message,
            'active': self.active,
            'start_time': self.start_time.strftime('%H:%M') if self.start_time else None,
            'end_time': self.end_time.strftime('%H:%M') if self.end_time else None,
            'weekdays_only': self.weekdays_only,
            'timezone': self.timezone,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class MLStatistics(db.Model):
    """Modelo para estatísticas do sistema"""
    __tablename__ = 'ml_statistics'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    total_questions = db.Column(db.Integer, default=0)
    answered_questions = db.Column(db.Integer, default=0)
    pending_questions = db.Column(db.Integer, default=0)
    auto_responses = db.Column(db.Integer, default=0)
    manual_responses = db.Column(db.Integer, default=0)
    avg_response_time = db.Column(db.Float, default=0.0)
    success_rate = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'total_questions': self.total_questions,
            'answered_questions': self.answered_questions,
            'pending_questions': self.pending_questions,
            'auto_responses': self.auto_responses,
            'manual_responses': self.manual_responses,
            'avg_response_time': self.avg_response_time,
            'success_rate': self.success_rate,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

