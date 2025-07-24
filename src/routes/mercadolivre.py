from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from src.models.user import db
from src.models.mercadolivre import (
    MLCredentials, MLQuestion, MLAutoResponse, MLLog,
    MLResponseQuality, MLAbsenceResponse, MLStatistics
)
from src.services.mercadolivre_api import MercadoLivreAPI
from src.services.auto_responder import AutoResponder

# Importar novos serviços
try:
    from src.services.statistics_service import StatisticsService
except ImportError:
    StatisticsService = None

ml_bp = Blueprint('mercadolivre', __name__)

@ml_bp.route('/status', methods=['GET'])
def get_status():
    """Obtém status do sistema"""
    try:
        api = MercadoLivreAPI()
        responder = AutoResponder()
        
        # Testar conexão
        connection_test = api.test_connection()
        
        # Obter estatísticas
        stats = responder.get_statistics()
        
        # Verificar credenciais
        credentials = MLCredentials.query.first()
        has_credentials = bool(credentials and credentials.access_token)
        
        return jsonify({
            'success': True,
            'connection': connection_test,
            'statistics': stats,
            'has_credentials': has_credentials,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/credentials', methods=['GET'])
def get_credentials():
    """Obtém credenciais (sem dados sensíveis)"""
    try:
        credentials = MLCredentials.query.first()
        
        if credentials:
            return jsonify({
                'success': True,
                'credentials': credentials.to_dict()
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Credenciais não encontradas'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/credentials', methods=['POST'])
def save_credentials():
    """Salva ou atualiza credenciais"""
    try:
        data = request.get_json()
        
        required_fields = ['client_id', 'client_secret', 'access_token']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Campo obrigatório: {field}'
                }), 400
        
        # Buscar credenciais existentes
        credentials = MLCredentials.query.first()
        
        if not credentials:
            credentials = MLCredentials()
            db.session.add(credentials)
        
        # Atualizar dados
        credentials.client_id = data['client_id']
        credentials.client_secret = data['client_secret']
        credentials.access_token = data['access_token']
        credentials.refresh_token = data.get('refresh_token')
        credentials.user_id = data.get('user_id')
        
        # Calcular expiração (6 horas padrão)
        expires_in = data.get('expires_in', 21600)
        credentials.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Credenciais salvas com sucesso',
            'credentials': credentials.to_dict()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/sync', methods=['POST'])
def sync_questions():
    """Sincroniza perguntas do Mercado Livre"""
    try:
        api = MercadoLivreAPI()
        synced_count = api.sync_questions()
        
        return jsonify({
            'success': True,
            'synced_count': synced_count,
            'message': f'Sincronizadas {synced_count} perguntas'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/questions', methods=['GET'])
def get_questions():
    """Obtém perguntas do banco local"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status = request.args.get('status')
        
        query = MLQuestion.query
        
        if status:
            query = query.filter_by(status=status)
        
        questions = query.order_by(MLQuestion.date_created.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'questions': [q.to_dict() for q in questions.items],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': questions.total,
                'pages': questions.pages
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/auto-responses', methods=['GET'])
def get_auto_responses():
    """Obtém regras de resposta automática"""
    try:
        rules = MLAutoResponse.query.order_by(MLAutoResponse.priority.desc()).all()
        
        return jsonify({
            'success': True,
            'rules': [rule.to_dict() for rule in rules]
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/auto-responses', methods=['POST'])
def create_auto_response():
    """Cria nova regra de resposta automática"""
    try:
        data = request.get_json()
        
        required_fields = ['name', 'keywords', 'response_text']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Campo obrigatório: {field}'
                }), 400
        
        rule = MLAutoResponse(
            name=data['name'],
            response_text=data['response_text'],
            priority=data.get('priority', 0),
            active=data.get('active', True)
        )
        rule.set_keywords(data['keywords'])
        
        db.session.add(rule)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Regra criada com sucesso',
            'rule': rule.to_dict()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/auto-responses/<int:rule_id>', methods=['PUT'])
def update_auto_response(rule_id):
    """Atualiza regra de resposta automática"""
    try:
        rule = MLAutoResponse.query.get_or_404(rule_id)
        data = request.get_json()
        
        if 'name' in data:
            rule.name = data['name']
        if 'keywords' in data:
            rule.set_keywords(data['keywords'])
        if 'response_text' in data:
            rule.response_text = data['response_text']
        if 'priority' in data:
            rule.priority = data['priority']
        if 'active' in data:
            rule.active = data['active']
        
        rule.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Regra atualizada com sucesso',
            'rule': rule.to_dict()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/auto-responses/<int:rule_id>', methods=['DELETE'])
def delete_auto_response(rule_id):
    """Remove regra de resposta automática"""
    try:
        rule = MLAutoResponse.query.get_or_404(rule_id)
        
        db.session.delete(rule)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Regra removida com sucesso'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/process', methods=['POST'])
def process_questions():
    """Processa perguntas não respondidas"""
    try:
        responder = AutoResponder()
        stats = responder.process_unanswered_questions()
        
        return jsonify({
            'success': True,
            'statistics': stats,
            'message': f'Processadas {stats["processed"]} perguntas, {stats["answered"]} respondidas automaticamente'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/setup-defaults', methods=['POST'])
def setup_defaults():
    """Configura regras padrão e credenciais"""
    try:
        responder = AutoResponder()
        
        # Criar regras padrão
        rules_created = responder.create_default_rules()
        
        # Configurar credenciais padrão se não existirem
        credentials = MLCredentials.query.first()
        if not credentials:
            credentials = MLCredentials(
                client_id='5510376630479325',
                client_secret='jlR4As2x8uFY3RTpysLpuPhzC9yM9d35',
                access_token='APP_USR-5510376630479325-072321-31ceebc6a2428e8723948d8e00c75015-180617463',
                user_id='180617463',
                expires_at=datetime.utcnow() + timedelta(hours=6)
            )
            db.session.add(credentials)
            db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Configuração inicial concluída. {rules_created} regras criadas.',
            'rules_created': rules_created
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/logs', methods=['GET'])
def get_logs():
    """Obtém logs do sistema"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        level = request.args.get('level')
        
        query = MLLog.query
        
        if level:
            query = query.filter_by(level=level.upper())
        
        logs = query.order_by(MLLog.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'logs': [log.to_dict() for log in logs.items],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': logs.total,
                'pages': logs.pages
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/webhook', methods=['POST'])
def webhook_receiver():
    """Recebe notificações do Mercado Livre"""
    try:
        data = request.get_json()
        
        # Log da notificação recebida
        log = MLLog(
            level='INFO',
            message='Webhook recebido do Mercado Livre'
        )
        log.set_data(data)
        db.session.add(log)
        db.session.commit()
        
        # Processar notificação se for de mensagem ou pergunta
        if data.get('topic') in ['messages', 'questions']:
            # Sincronizar perguntas após receber notificação
            api = MercadoLivreAPI()
            api.sync_questions()
            
            # Processar automaticamente
            responder = AutoResponder()
            responder.process_unanswered_questions()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ml_bp.route('/statistics/realtime', methods=['GET'])
def get_realtime_statistics():
    """Obtém estatísticas em tempo real"""
    try:
        import sqlite3
        db_path = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Contar regras ativas
        cursor.execute("SELECT COUNT(*) FROM ml_auto_responses WHERE active = 1")
        result = cursor.fetchone()
        active_rules = result[0] if result else 0
        
        # Contar perguntas totais (todas as perguntas)
        cursor.execute("SELECT COUNT(*) FROM ml_questions")
        result = cursor.fetchone()
        total_questions = result[0] if result else 0
        
        # Contar respondidas (perguntas processadas com resposta OU status ANSWERED)
        cursor.execute("""
            SELECT COUNT(*) FROM ml_questions 
            WHERE (processed = 1 AND answer_text IS NOT NULL AND answer_text != '') 
               OR status = 'ANSWERED'
        """)
        result = cursor.fetchone()
        answered_questions = result[0] if result else 0
        
        # Contar aguardando (perguntas não processadas OU sem resposta)
        cursor.execute("""
            SELECT COUNT(*) FROM ml_questions 
            WHERE (processed = 0 OR answer_text IS NULL OR answer_text = '') 
              AND status != 'ANSWERED'
        """)
        result = cursor.fetchone()
        pending_questions = result[0] if result else 0
        
        # Verificar consistência (total deve ser igual a respondidas + aguardando)
        calculated_total = answered_questions + pending_questions
        if calculated_total != total_questions:
            # Se há inconsistência, recalcular aguardando
            pending_questions = total_questions - answered_questions
            if pending_questions < 0:
                pending_questions = 0
        
        conn.close()
        
        success_rate = (answered_questions / total_questions * 100) if total_questions > 0 else 0
        
        return jsonify({
            'success': True,
            'statistics': {
                'total_questions': total_questions,
                'answered_questions': answered_questions,
                'pending_questions': pending_questions,
                'active_rules': active_rules,
                'success_rate': round(success_rate, 1),
                'avg_response_time': 0.0,
                'last_updated': datetime.now().isoformat()
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/rules', methods=['GET'])
def get_auto_response_rules():
    """Obtém todas as regras de resposta automática"""
    try:
        import sqlite3
        import json
        db_path = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, keywords, response_text, active, priority, created_at, updated_at
            FROM ml_auto_responses 
            ORDER BY priority DESC
        """)
        
        rules = []
        for row in cursor.fetchall():
            try:
                keywords = json.loads(row[2]) if row[2] else []
            except:
                keywords = []
            
            rules.append({
                'id': row[0],
                'name': row[1],
                'keywords': keywords,
                'response_text': row[3],
                'active': bool(row[4]),
                'priority': row[5],
                'created_at': row[6],
                'updated_at': row[7]
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'rules': rules
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/rules', methods=['POST'])
def create_auto_response_rule():
    """Cria nova regra de resposta automática"""
    try:
        import sqlite3
        import json
        
        data = request.get_json()
        
        db_path = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        keywords_json = json.dumps(data['keywords'], ensure_ascii=False)
        
        cursor.execute("""
            INSERT INTO ml_auto_responses (name, keywords, response_text, priority, active)
            VALUES (?, ?, ?, ?, ?)
        """, (
            data['name'],
            keywords_json,
            data['response_text'],
            data.get('priority', 0),
            1 if data.get('active', True) else 0
        ))
        
        rule_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'rule': {
                'id': rule_id,
                'name': data['name'],
                'keywords': data['keywords'],
                'response_text': data['response_text'],
                'priority': data.get('priority', 0),
                'active': data.get('active', True)
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/rules/<int:rule_id>', methods=['PUT'])
def update_auto_response_rule(rule_id):
    """Atualiza regra de resposta automática"""
    try:
        import sqlite3
        import json
        
        data = request.get_json()
        
        db_path = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        keywords_json = json.dumps(data['keywords'], ensure_ascii=False)
        
        cursor.execute("""
            UPDATE ml_auto_responses 
            SET name = ?, keywords = ?, response_text = ?, priority = ?, active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            data['name'],
            keywords_json,
            data['response_text'],
            data.get('priority', 0),
            1 if data.get('active', True) else 0,
            rule_id
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'rule': {
                'id': rule_id,
                'name': data['name'],
                'keywords': data['keywords'],
                'response_text': data['response_text'],
                'priority': data.get('priority', 0),
                'active': data.get('active', True)
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/rules/<int:rule_id>', methods=['DELETE'])
def delete_auto_response_rule(rule_id):
    """Remove regra de resposta automática"""
    try:
        import sqlite3
        
        db_path = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM ml_auto_responses WHERE id = ?", (rule_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Regra removida com sucesso'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/absence', methods=['GET'])
def get_absence_responses():
    """Obtém configurações de resposta de ausência"""
    try:
        import sqlite3
        
        db_path = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, message, active, start_time, end_time, weekdays_only, timezone, created_at, updated_at
            FROM ml_absence_responses
        """)
        
        responses = []
        for row in cursor.fetchall():
            responses.append({
                'id': row[0],
                'name': row[1],
                'message': row[2],
                'active': bool(row[3]),
                'start_time': row[4],
                'end_time': row[5],
                'weekdays_only': bool(row[6]),
                'timezone': row[7],
                'created_at': row[8],
                'updated_at': row[9]
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'absence_responses': responses
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/absence', methods=['POST'])
def create_absence_response():
    """Cria nova configuração de resposta de ausência"""
    try:
        import sqlite3
        
        data = request.get_json()
        
        db_path = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO ml_absence_responses (name, message, active, start_time, end_time, weekdays_only, timezone)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data['name'],
            data['message'],
            1 if data.get('active', False) else 0,
            data['start_time'],
            data['end_time'],
            1 if data.get('weekdays_only', True) else 0,
            data.get('timezone', 'America/Sao_Paulo')
        ))
        
        response_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'absence_response': {
                'id': response_id,
                'name': data['name'],
                'message': data['message'],
                'active': data.get('active', False),
                'start_time': data['start_time'],
                'end_time': data['end_time'],
                'weekdays_only': data.get('weekdays_only', True),
                'timezone': data.get('timezone', 'America/Sao_Paulo')
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/absence/<int:response_id>', methods=['PUT'])
def update_absence_response(response_id):
    """Atualiza configuração de resposta de ausência"""
    try:
        import sqlite3
        
        data = request.get_json()
        
        db_path = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE ml_absence_responses 
            SET name = ?, message = ?, active = ?, start_time = ?, end_time = ?, weekdays_only = ?, timezone = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            data['name'],
            data['message'],
            1 if data.get('active', False) else 0,
            data['start_time'],
            data['end_time'],
            1 if data.get('weekdays_only', True) else 0,
            data.get('timezone', 'America/Sao_Paulo'),
            response_id
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'absence_response': {
                'id': response_id,
                'name': data['name'],
                'message': data['message'],
                'active': data.get('active', False),
                'start_time': data['start_time'],
                'end_time': data['end_time'],
                'weekdays_only': data.get('weekdays_only', True),
                'timezone': data.get('timezone', 'America/Sao_Paulo')
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/absence/<int:response_id>', methods=['DELETE'])
def delete_absence_response(response_id):
    """Remove configuração de resposta de ausência"""
    try:
        import sqlite3
        
        db_path = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM ml_absence_responses WHERE id = ?", (response_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Configuração de ausência removida com sucesso'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/questions/recent', methods=['GET'])
def get_recent_questions():
    """Obtém perguntas recentes com detalhes"""
    try:
        import sqlite3
        
        limit = request.args.get('limit', 20, type=int)
        
        db_path = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, text, answer_text, status, date_created, answer_date, processed
            FROM ml_questions 
            ORDER BY date_created DESC 
            LIMIT ?
        """, (limit,))
        
        questions = []
        for row in cursor.fetchall():
            questions.append({
                'id': row[0],
                'text': row[1],
                'answer_text': row[2],
                'status': row[3],
                'date_created': row[4],
                'answer_date': row[5],
                'processed': bool(row[6]),
                'rule_name': 'Automática',
                'keywords_matched': [],
                'response_time': 0.0
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'questions': questions
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@ml_bp.route('/statistics/quality', methods=['GET'])
def get_quality_metrics():
    """Obtém métricas de qualidade das respostas"""
    try:
        return jsonify({
            'success': True,
            'metrics': {
                'rule_stats': [],
                'top_keywords': [],
                'total_responses_today': 0
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@ml_bp.route('/questions/reset', methods=['DELETE'])
def reset_questions():
    """Reseta apenas os dados de perguntas mantendo configurações"""
    try:
        import sqlite3
        import os
        
        db_path = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')
        
        if not os.path.exists(db_path):
            return jsonify({
                'success': False,
                'error': 'Banco de dados não encontrado'
            }), 404
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Contar dados antes da limpeza
        cursor.execute("SELECT COUNT(*) FROM ml_questions")
        questions_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM ml_logs")
        logs_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM ml_response_quality")
        quality_count = cursor.fetchone()[0]
        
        # Limpar apenas dados de perguntas e atividades
        cursor.execute("DELETE FROM ml_questions")
        cursor.execute("DELETE FROM ml_logs")
        cursor.execute("DELETE FROM ml_response_quality")
        
        # Limpar estatísticas se existir a tabela
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ml_statistics'")
        if cursor.fetchone():
            cursor.execute("DELETE FROM ml_statistics")
        
        # Commit das alterações
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Dashboard resetado com sucesso',
            'removed': {
                'questions': questions_count,
                'logs': logs_count,
                'quality_records': quality_count
            },
            'preserved': {
                'rules': 'Mantidas',
                'absence_config': 'Mantidas',
                'credentials': 'Mantidas'
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erro ao resetar dashboard: {str(e)}'
        }), 500

