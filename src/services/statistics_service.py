#!/usr/bin/env python3
"""
Serviço de Estatísticas para calcular métricas em tempo real
"""

from datetime import datetime, date, timedelta
from sqlalchemy import func, and_
from src.models.user import db
from src.models.mercadolivre import (
    MLQuestion, MLAutoResponse, MLResponseQuality, 
    MLAbsenceResponse, MLStatistics, MLLog
)

class StatisticsService:
    @staticmethod
    def get_real_time_stats():
        """Obtém estatísticas em tempo real"""
        try:
            today = date.today()
            
            # Total de perguntas hoje
            total_questions = MLQuestion.query.filter(
                func.date(MLQuestion.date_created) == today
            ).count()
            
            # Perguntas respondidas hoje
            answered_questions = MLQuestion.query.filter(
                and_(
                    func.date(MLQuestion.date_created) == today,
                    MLQuestion.status == 'ANSWERED'
                )
            ).count()
            
            # Perguntas aguardando resposta
            pending_questions = MLQuestion.query.filter(
                MLQuestion.status == 'UNANSWERED'
            ).count()
            
            # Regras ativas
            active_rules = MLAutoResponse.query.filter_by(active=True).count()
            
            # Taxa de sucesso hoje
            success_rate = 0.0
            if total_questions > 0:
                success_rate = (answered_questions / total_questions) * 100
            
            # Tempo médio de resposta hoje
            avg_response_time = db.session.query(
                func.avg(MLResponseQuality.response_time)
            ).filter(
                func.date(MLResponseQuality.created_at) == today
            ).scalar() or 0.0
            
            return {
                'total_questions': total_questions,
                'answered_questions': answered_questions,
                'pending_questions': pending_questions,
                'active_rules': active_rules,
                'success_rate': round(success_rate, 1),
                'avg_response_time': round(avg_response_time, 2),
                'last_updated': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Erro ao calcular estatísticas: {e}")
            return {
                'total_questions': 0,
                'answered_questions': 0,
                'pending_questions': 0,
                'active_rules': 0,
                'success_rate': 0.0,
                'avg_response_time': 0.0,
                'last_updated': datetime.now().isoformat()
            }
    
    @staticmethod
    def get_recent_questions(limit=20):
        """Obtém perguntas recentes com detalhes"""
        try:
            questions = MLQuestion.query.order_by(
                MLQuestion.date_created.desc()
            ).limit(limit).all()
            
            result = []
            for question in questions:
                # Buscar dados de qualidade
                quality = MLResponseQuality.query.filter_by(
                    question_id=question.id
                ).first()
                
                question_data = question.to_dict()
                if quality:
                    question_data.update({
                        'rule_name': quality.rule.name if quality.rule else 'Padrão',
                        'keywords_matched': quality.get_keywords_matched(),
                        'response_time': quality.response_time,
                        'quality_score': quality.quality_score
                    })
                
                result.append(question_data)
            
            return result
            
        except Exception as e:
            print(f"❌ Erro ao obter perguntas recentes: {e}")
            return []
    
    @staticmethod
    def get_quality_metrics():
        """Obtém métricas de qualidade das respostas"""
        try:
            today = date.today()
            
            # Respostas por regra hoje
            rule_stats = db.session.query(
                MLAutoResponse.name,
                func.count(MLResponseQuality.id).label('count'),
                func.avg(MLResponseQuality.response_time).label('avg_time')
            ).join(
                MLResponseQuality, MLAutoResponse.id == MLResponseQuality.rule_id
            ).filter(
                func.date(MLResponseQuality.created_at) == today
            ).group_by(
                MLAutoResponse.name
            ).all()
            
            # Palavras-chave mais utilizadas
            quality_records = MLResponseQuality.query.filter(
                func.date(MLResponseQuality.created_at) == today
            ).all()
            
            keyword_count = {}
            for record in quality_records:
                for keyword in record.get_keywords_matched():
                    keyword_count[keyword] = keyword_count.get(keyword, 0) + 1
            
            # Top 10 palavras-chave
            top_keywords = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)[:10]
            
            return {
                'rule_stats': [
                    {
                        'rule_name': name,
                        'usage_count': count,
                        'avg_response_time': round(avg_time or 0, 2)
                    }
                    for name, count, avg_time in rule_stats
                ],
                'top_keywords': [
                    {'keyword': keyword, 'count': count}
                    for keyword, count in top_keywords
                ],
                'total_responses_today': len(quality_records)
            }
            
        except Exception as e:
            print(f"❌ Erro ao obter métricas de qualidade: {e}")
            return {
                'rule_stats': [],
                'top_keywords': [],
                'total_responses_today': 0
            }
    
    @staticmethod
    def update_daily_statistics():
        """Atualiza estatísticas diárias no banco"""
        try:
            today = date.today()
            
            # Verificar se já existe registro para hoje
            existing = MLStatistics.query.filter_by(date=today).first()
            
            # Calcular estatísticas
            stats = StatisticsService.get_real_time_stats()
            
            if existing:
                # Atualizar registro existente
                existing.total_questions = stats['total_questions']
                existing.answered_questions = stats['answered_questions']
                existing.pending_questions = stats['pending_questions']
                existing.success_rate = stats['success_rate']
                existing.avg_response_time = stats['avg_response_time']
                existing.updated_at = datetime.now()
            else:
                # Criar novo registro
                new_stats = MLStatistics(
                    date=today,
                    total_questions=stats['total_questions'],
                    answered_questions=stats['answered_questions'],
                    pending_questions=stats['pending_questions'],
                    success_rate=stats['success_rate'],
                    avg_response_time=stats['avg_response_time']
                )
                db.session.add(new_stats)
            
            db.session.commit()
            return True
            
        except Exception as e:
            print(f"❌ Erro ao atualizar estatísticas diárias: {e}")
            db.session.rollback()
            return False
    
    @staticmethod
    def get_historical_stats(days=7):
        """Obtém estatísticas históricas"""
        try:
            end_date = date.today()
            start_date = end_date - timedelta(days=days-1)
            
            stats = MLStatistics.query.filter(
                and_(
                    MLStatistics.date >= start_date,
                    MLStatistics.date <= end_date
                )
            ).order_by(MLStatistics.date.asc()).all()
            
            return [stat.to_dict() for stat in stats]
            
        except Exception as e:
            print(f"❌ Erro ao obter estatísticas históricas: {e}")
            return []

