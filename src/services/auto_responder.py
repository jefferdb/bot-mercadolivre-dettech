import re
from datetime import datetime
from typing import List, Optional, Dict
from src.models.mercadolivre import db, MLQuestion, MLAutoResponse, MLLog
from src.services.mercadolivre_api import MercadoLivreAPI

class AutoResponder:
    """Classe para resposta automática de perguntas"""
    
    def __init__(self):
        self.api = MercadoLivreAPI()
    
    def log_info(self, message: str, data: Dict = None):
        """Log de informação"""
        log = MLLog(level='INFO', message=message)
        if data:
            log.set_data(data)
        db.session.add(log)
        db.session.commit()
        print(f"🤖 {message}")
    
    def log_error(self, message: str, data: Dict = None):
        """Log de erro"""
        log = MLLog(level='ERROR', message=message)
        if data:
            log.set_data(data)
        db.session.add(log)
        db.session.commit()
        print(f"❌ {message}")
    
    def normalize_text(self, text: str) -> str:
        """Normaliza texto para comparação"""
        # Remove acentos, converte para minúsculo, remove pontuação extra
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def find_matching_response(self, question_text: str) -> Optional[MLAutoResponse]:
        """Encontra resposta automática que combina com a pergunta"""
        normalized_question = self.normalize_text(question_text)
        
        # Buscar regras ativas ordenadas por prioridade
        rules = MLAutoResponse.query.filter_by(active=True).order_by(MLAutoResponse.priority.desc()).all()
        
        for rule in rules:
            keywords = rule.get_keywords()
            
            # Verificar se alguma palavra-chave está presente
            for keyword in keywords:
                normalized_keyword = self.normalize_text(keyword)
                
                if normalized_keyword in normalized_question:
                    self.log_info(f"Regra '{rule.name}' ativada por palavra-chave: '{keyword}'", {
                        'rule_id': rule.id,
                        'keyword': keyword,
                        'question': question_text
                    })
                    return rule
        
        return None
    
    def process_unanswered_questions(self) -> Dict[str, int]:
        """Processa perguntas não respondidas"""
        # Primeiro sincronizar perguntas
        synced = self.api.sync_questions()
        
        # Buscar perguntas não respondidas e não processadas
        unanswered = MLQuestion.query.filter_by(
            status='UNANSWERED',
            processed=False
        ).all()
        
        stats = {
            'synced': synced,
            'found': len(unanswered),
            'processed': 0,
            'answered': 0,
            'errors': 0
        }
        
        self.log_info(f"Processando {len(unanswered)} perguntas não respondidas")
        
        for question in unanswered:
            try:
                # Marcar como processada
                question.processed = True
                question.processed_at = datetime.utcnow()
                
                # Buscar resposta automática
                auto_response = self.find_matching_response(question.text)
                
                if auto_response:
                    # Tentar responder
                    success = self.api.answer_question(question.id, auto_response.response_text)
                    
                    if success:
                        # Atualizar pergunta
                        question.status = 'ANSWERED'
                        question.answer_text = auto_response.response_text
                        question.answer_date = datetime.utcnow()
                        
                        stats['answered'] += 1
                        
                        self.log_info(f"Pergunta {question.id} respondida automaticamente", {
                            'question_id': question.id,
                            'rule_name': auto_response.name,
                            'response': auto_response.response_text
                        })
                    else:
                        stats['errors'] += 1
                        self.log_error(f"Falha ao responder pergunta {question.id}")
                else:
                    self.log_info(f"Nenhuma regra encontrada para pergunta {question.id}: '{question.text}'")
                
                stats['processed'] += 1
                
            except Exception as e:
                stats['errors'] += 1
                self.log_error(f"Erro ao processar pergunta {question.id}: {str(e)}")
        
        db.session.commit()
        
        self.log_info(f"Processamento concluído", stats)
        return stats
    
    def create_default_rules(self):
        """Cria regras padrão de resposta automática"""
        default_rules = [
            {
                'name': 'Saudação e Boas-vindas',
                'keywords': ['bom dia', 'boa tarde', 'boa noite', 'olá', 'oi'],
                'response_text': 'Olá! Seja bem-vindo à DETTECH. Como posso ajudá-lo hoje?',
                'priority': 1
            },
            {
                'name': 'Compatibilidade - Numeração Original',
                'keywords': ['compatível', 'serve', 'funciona', 'encaixa', 'modelo', 'ano'],
                'response_text': 'Olá, seja bem-vindo à DETTECH! Para confirmar a compatibilidade, precisamos que informe a numeração original constante na sua peça. Atenciosamente, Jeff - Equipe DETTECH.',
                'priority': 10
            },
            {
                'name': 'Prazo de Entrega',
                'keywords': ['prazo', 'entrega', 'envio', 'demora', 'quando chega', 'correios'],
                'response_text': 'O prazo de entrega varia conforme sua localização. Após a confirmação do pagamento, o produto é enviado em até 2 dias úteis. O prazo dos Correios pode ser consultado no checkout.',
                'priority': 8
            },
            {
                'name': 'Garantia',
                'keywords': ['garantia', 'defeito', 'problema', 'troca', 'devolução'],
                'response_text': 'Todos os nossos produtos possuem garantia de 90 dias contra defeitos de fabricação. Em caso de problemas, entre em contato conosco que resolveremos rapidamente.',
                'priority': 7
            },
            {
                'name': 'Preço e Pagamento',
                'keywords': ['preço', 'valor', 'desconto', 'pagamento', 'parcelamento', 'pix'],
                'response_text': 'O preço está atualizado no anúncio. Aceitamos todas as formas de pagamento do Mercado Livre, incluindo PIX com desconto. Fique à vontade para finalizar sua compra!',
                'priority': 6
            },
            {
                'name': 'Disponibilidade',
                'keywords': ['disponível', 'estoque', 'tem', 'possui', 'vende'],
                'response_text': 'Sim, o produto está disponível em estoque! Pode finalizar sua compra com segurança. Qualquer dúvida, estamos aqui para ajudar.',
                'priority': 5
            },
            {
                'name': 'Instalação e Manual',
                'keywords': ['instalação', 'instalar', 'manual', 'como usar', 'instruções'],
                'response_text': 'O produto acompanha instruções básicas. Caso precise de suporte adicional para instalação, podemos enviar manual detalhado por e-mail após a compra.',
                'priority': 4
            },
            {
                'name': 'Agradecimento',
                'keywords': ['obrigado', 'obrigada', 'valeu', 'muito obrigado'],
                'response_text': 'Por nada! Ficamos felizes em ajudar. Qualquer dúvida, estamos sempre à disposição. Obrigado por escolher a DETTECH!',
                'priority': 2
            }
        ]
        
        created = 0
        for rule_data in default_rules:
            # Verificar se já existe
            existing = MLAutoResponse.query.filter_by(name=rule_data['name']).first()
            
            if not existing:
                rule = MLAutoResponse(
                    name=rule_data['name'],
                    response_text=rule_data['response_text'],
                    priority=rule_data['priority']
                )
                rule.set_keywords(rule_data['keywords'])
                
                db.session.add(rule)
                created += 1
        
        db.session.commit()
        self.log_info(f"Criadas {created} regras padrão de resposta automática")
        return created
    
    def get_statistics(self) -> Dict:
        """Obtém estatísticas do sistema"""
        total_questions = MLQuestion.query.count()
        answered_questions = MLQuestion.query.filter_by(status='ANSWERED').count()
        unanswered_questions = MLQuestion.query.filter_by(status='UNANSWERED').count()
        processed_questions = MLQuestion.query.filter_by(processed=True).count()
        
        active_rules = MLAutoResponse.query.filter_by(active=True).count()
        total_rules = MLAutoResponse.query.count()
        
        return {
            'questions': {
                'total': total_questions,
                'answered': answered_questions,
                'unanswered': unanswered_questions,
                'processed': processed_questions
            },
            'rules': {
                'active': active_rules,
                'total': total_rules
            }
        }

