#!/usr/bin/env python3
"""
Serviço de Polling para verificar novas perguntas automaticamente
"""

import requests
import json
import time
import threading
from datetime import datetime, date, time as dt_time
import sqlite3
import os
import sys

# Importar TokenMonitor do mesmo diretório
from .token_monitor import TokenMonitor

# Importar modelos do banco de dados
from src.models.user import db
from src.models.mercadolivre import (
    MLQuestion, MLAutoResponse, MLResponseQuality, 
    MLAbsenceResponse, MLStatistics, MLLog
)

class PollingService:
    def __init__(self, client_id, client_secret, db_path, initial_token=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.db_path = db_path
        self.is_running = False
        self.polling_thread = None
        self.processed_questions = set()
        
        # Inicializar monitor de tokens
        self.token_monitor = TokenMonitor(db_path)
        
        # Se fornecido token inicial, configurar
        if initial_token:
            self.token_monitor.set_token(initial_token)
        else:
            self.token_monitor.load_token()
        
        # Iniciar monitoramento
        self.token_monitor.start_monitoring()
        
    def get_questions(self):
        """Obtém perguntas não respondidas do Mercado Livre"""
        try:
            # Obter token válido
            access_token = self.token_monitor.get_valid_token()
            if not access_token:
                print("❌ Token não disponível ou expirado")
                return []
            
            url = "https://api.mercadolibre.com/my/received_questions/search"
            headers = {
                'Authorization': f'Bearer {access_token}'
            }
            
            params = {
                'status': 'UNANSWERED',
                'limit': 50,
                'sort': 'date_created',
                'order': 'desc'
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('questions', [])
            else:
                print(f"❌ Erro ao obter perguntas: {response.text}")
                return []
                
        except Exception as e:
            print(f"❌ Erro ao obter perguntas: {e}")
            return []
    
    def answer_question(self, question_id, answer_text):
        """Responde uma pergunta específica"""
        try:
            # Obter token válido
            access_token = self.token_monitor.get_valid_token()
            if not access_token:
                print("❌ Token não disponível ou expirado")
                return False
            
            url = f"https://api.mercadolibre.com/answers"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            data = {
                'question_id': question_id,
                'text': answer_text
            }
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 201:
                print(f"✅ Pergunta {question_id} respondida com sucesso!")
                return True
            else:
                print(f"❌ Erro ao responder pergunta {question_id}: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Erro ao responder pergunta: {e}")
            return False
    
    def get_response_rules(self):
        """Obtém regras de resposta do banco de dados"""
        try:
            import sqlite3
            import json
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, keywords, response_text FROM ml_auto_responses 
                WHERE active = 1 
                ORDER BY priority DESC
            """)
            
            rules = []
            for row in cursor.fetchall():
                rule_id = row[0]
                try:
                    keywords = json.loads(row[1]) if row[1] else []
                except:
                    keywords = []
                response_text = row[2]
                
                rules.append((keywords, response_text, rule_id))
            
            conn.close()
            return rules
            
        except Exception as e:
            print(f"❌ Erro ao obter regras: {e}")
            return []
    
    def check_absence_response(self):
        """Verifica se deve usar resposta de ausência baseada no horário atual"""
        try:
            import sqlite3
            from datetime import datetime, time as dt_time
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Buscar configurações de ausência ativas
            cursor.execute("""
                SELECT id, name, message, start_time, end_time, weekdays_only
                FROM ml_absence_responses 
                WHERE active = 1
                ORDER BY id
            """)
            
            now = datetime.now()
            current_time = now.time()
            current_weekday = now.weekday()  # 0=Monday, 6=Sunday
            is_weekend = current_weekday >= 5  # Saturday=5, Sunday=6
            
            for row in cursor.fetchall():
                absence_id, name, message, start_time_str, end_time_str, weekdays_only = row
                
                # Parse dos horários
                start_time = dt_time.fromisoformat(start_time_str)
                end_time = dt_time.fromisoformat(end_time_str)
                
                # Verificar se é final de semana e a regra é só para dias úteis
                if weekdays_only and is_weekend:
                    print(f"🌙 Usando resposta de ausência: '{name}' (Final de semana)")
                    conn.close()
                    return message, name
                
                # Verificar horário (considerando que pode ser overnight)
                if start_time > end_time:  # Overnight (ex: 18:01 - 08:59)
                    if current_time >= start_time or current_time <= end_time:
                        print(f"🌙 Usando resposta de ausência: '{name}' (Fora do horário: {start_time_str}-{end_time_str})")
                        conn.close()
                        return message, name
                else:  # Same day (ex: 09:00 - 18:00)
                    if start_time <= current_time <= end_time:
                        print(f"🌙 Usando resposta de ausência: '{name}' (Durante horário: {start_time_str}-{end_time_str})")
                        conn.close()
                        return message, name
            
            conn.close()
            return None, None
            
        except Exception as e:
            print(f"❌ Erro ao verificar ausência: {e}")
            return None, None

    def process_question(self, question):
        """Processa uma pergunta e gera resposta automática"""
        
        # PRIORIDADE 1: Verificar regras de ausência PRIMEIRO
        absence_response, absence_name = self.check_absence_response()
        if absence_response:
            print(f"🌙 Aplicando regra de ausência: {absence_name}")
            return absence_response, None, [], "absence"
        
        # PRIORIDADE 2: Verificar regras ativas de resposta automática
        question_text = question['text'].lower()
        rules = self.get_response_rules()
        
        # Se não há regras ativas, não responder
        if not rules:
            print("ℹ️ Nenhuma regra ativa encontrada - não respondendo")
            return None, None, [], "no_rules"
        
        matched_rule_id = None
        matched_keywords = []
        response_text = None
        
        # Verifica cada regra ativa
        for keywords_list, rule_response, rule_id in rules:
            for keyword in keywords_list:
                if keyword.lower() in question_text:
                    matched_keywords.append(keyword)
                    matched_rule_id = rule_id
                    response_text = rule_response
                    print(f"🎯 Regra encontrada (ID: {rule_id}) por palavra-chave: '{keyword}'")
                    break
            
            if response_text:
                break
        
        # PRIORIDADE 3: Se há regras ativas mas nenhuma combinou, não responder
        if not response_text:
            print("ℹ️ Nenhuma palavra-chave encontrada nas regras ativas - não respondendo")
            return None, None, [], "no_match"
        
        return response_text, matched_rule_id, matched_keywords, "rule_match"
    
    def log_activity(self, question_id, question_text, response_text, success, rule_id=None, keywords_matched=None, response_time=None, response_type=None):
        """Registra a atividade no banco de dados"""
        try:
            import sqlite3
            import json
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Determinar se deve salvar a resposta no banco
            # Salva se há uma resposta real (não apenas descrição de erro)
            should_save_response = response_text and not response_text.startswith("Não respondida:")
            
            # Registrar pergunta
            cursor.execute("""
                INSERT OR REPLACE INTO ml_questions 
                (id, item_id, seller_id, from_user_id, text, status, date_created, answer_text, answer_date, processed, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                question_id,
                "",  # item_id será preenchido depois
                0,   # seller_id será preenchido depois  
                0,   # from_user_id será preenchido depois
                question_text,
                "ANSWERED" if should_save_response else "UNANSWERED",
                datetime.now().isoformat(),
                response_text if should_save_response else None,
                datetime.now().isoformat() if should_save_response else None,
                1,   # processed = True
                datetime.now().isoformat()
            ))
            
            # Registrar qualidade da resposta
            if keywords_matched:
                keywords_json = json.dumps(keywords_matched, ensure_ascii=False)
            else:
                keywords_json = None
                
            cursor.execute("""
                INSERT INTO ml_response_quality 
                (question_id, rule_id, question_text, response_text, keywords_matched, response_time, success, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                question_id,
                rule_id,
                question_text,
                response_text if should_save_response else None,
                keywords_json,
                response_time,
                1 if should_save_response else 0,
                datetime.now().isoformat()
            ))
            
            # Registrar log
            log_data = {
                'question_id': question_id,
                'rule_id': rule_id,
                'keywords_matched': keywords_matched,
                'response_time': response_time,
                'response_type': response_type,
                'api_success': success,
                'response_saved': should_save_response
            }
            
            cursor.execute("""
                INSERT INTO ml_logs (level, message, data, created_at)
                VALUES (?, ?, ?, ?)
            """, (
                "INFO" if should_save_response else "WARNING",
                f"Pergunta {question_id} {'respondida' if should_save_response else 'processada sem resposta'}",
                json.dumps(log_data, ensure_ascii=False, default=str),
                datetime.now().isoformat()
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"❌ Erro ao registrar log: {e}")
            try:
                conn.close()
            except:
                pass
    
    def polling_loop(self):
        """Loop principal de polling"""
        print("🔄 Iniciando polling automático...")
        
        while self.is_running:
            try:
                questions = self.get_questions()
                
                for question in questions:
                    question_id = question['id']
                    
                    # Verifica se já processamos esta pergunta
                    if question_id not in self.processed_questions:
                        print(f"\n📩 Nova pergunta encontrada:")
                        print(f"ID: {question_id}")
                        print(f"Texto: {question['text']}")
                        print(f"De: {question.get('from', {}).get('id', 'Desconhecido')}")
                        
                        # Medir tempo de resposta
                        start_time = time.time()
                        
                        # Gera resposta automática
                        result = self.process_question(question)
                        response, rule_id, keywords_matched, response_type = result
                        
                        # Calcular tempo de resposta
                        response_time = time.time() - start_time
                        
                        # Só responder se há uma resposta válida
                        if response:
                            print(f"🤖 Resposta gerada ({response_type}): {response}")
                            
                            # Envia resposta
                            success = self.answer_question(question_id, response)
                            
                            # Registra log completo (sempre salva a resposta no banco)
                            self.log_activity(
                                question_id, 
                                question['text'], 
                                response, 
                                success,
                                rule_id,
                                keywords_matched,
                                response_time,
                                response_type
                            )
                            
                            if success:
                                self.processed_questions.add(question_id)
                                print(f"✅ Pergunta processada com sucesso!")
                            else:
                                print(f"⚠️ Resposta salva no banco, mas falha no envio para API")
                        else:
                            print(f"ℹ️ Pergunta não respondida ({response_type}) - sem regras aplicáveis")
                            
                            # Registra que a pergunta foi processada mas não respondida
                            self.log_activity(
                                question_id, 
                                question['text'], 
                                f"Não respondida: {response_type}", 
                                False,
                                None,
                                [],
                                response_time,
                                response_type
                            )
                        
                        # Marcar como processada para não tentar novamente
                        self.processed_questions.add(question_id)
                
                if questions:
                    print(f"✅ Verificação concluída - {len(questions)} perguntas encontradas")
                else:
                    print("ℹ️ Nenhuma pergunta nova encontrada")
                
                # Aguarda 60 segundos antes da próxima verificação
                time.sleep(60)
                
            except Exception as e:
                print(f"❌ Erro no polling: {e}")
                time.sleep(30)  # Aguarda menos tempo em caso de erro
    
    def start(self):
        """Inicia o serviço de polling"""
        if not self.is_running:
            self.is_running = True
            self.polling_thread = threading.Thread(target=self.polling_loop, daemon=True)
            self.polling_thread.start()
            print("🚀 Serviço de polling iniciado!")
            return True
        return False
    
    def stop(self):
        """Para o serviço de polling"""
        if self.is_running:
            self.is_running = False
            if self.polling_thread:
                self.polling_thread.join(timeout=5)
            print("🛑 Serviço de polling parado!")
            return True
        return False
    
    def is_active(self):
        """Verifica se o polling está ativo"""
        return self.is_running and self.polling_thread and self.polling_thread.is_alive()
    
    def get_status(self):
        """Retorna status do serviço"""
        token_status = self.token_monitor.get_status()
        notifications = self.token_monitor.get_notifications(5)
        
        return {
            'polling_active': self.is_active(),
            'processed_questions': len(self.processed_questions),
            'last_check': datetime.now().isoformat(),
            'token_status': token_status,
            'recent_notifications': notifications
        }




