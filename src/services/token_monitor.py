#!/usr/bin/env python3
"""
Sistema de Monitoramento de Token sem Refresh Token
Monitora expiração e notifica quando precisa renovar manualmente
"""

import requests
import json
import time
import threading
from datetime import datetime, timedelta
import sqlite3
import os

class TokenMonitor:
    def __init__(self, db_path):
        self.db_path = db_path
        self.access_token = None
        self.expires_at = None
        self.is_running = False
        self.monitor_thread = None
        self.last_warning = None
        
        # Inicializar banco de dados
        self.init_database()
    
    def init_database(self):
        """Inicializa tabela para armazenar tokens"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS token_monitor (
                    id INTEGER PRIMARY KEY,
                    access_token TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Criar tabela de notificações
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS token_notifications (
                    id INTEGER PRIMARY KEY,
                    message TEXT NOT NULL,
                    level TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            conn.close()
            print("✅ Banco de dados de monitoramento inicializado")
            
        except Exception as e:
            print(f"❌ Erro ao inicializar banco: {e}")
    
    def set_token(self, access_token, expires_in=21600):
        """Define token atual com tempo de expiração"""
        try:
            expires_at = datetime.now() + timedelta(seconds=expires_in)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Remove tokens antigos
            cursor.execute("DELETE FROM token_monitor")
            
            # Insere novo token
            cursor.execute("""
                INSERT INTO token_monitor (access_token, expires_at)
                VALUES (?, ?)
            """, (access_token, expires_at.isoformat()))
            
            conn.commit()
            conn.close()
            
            # Atualiza variáveis da classe
            self.access_token = access_token
            self.expires_at = expires_at
            
            print(f"✅ Token configurado - Expira em: {expires_at}")
            return True
            
        except Exception as e:
            print(f"❌ Erro ao configurar token: {e}")
            return False
    
    def load_token(self):
        """Carrega token salvo do banco de dados"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT access_token, expires_at 
                FROM token_monitor 
                ORDER BY created_at DESC 
                LIMIT 1
            """)
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                access_token, expires_at_str = result
                expires_at = datetime.fromisoformat(expires_at_str)
                
                self.access_token = access_token
                self.expires_at = expires_at
                
                print(f"✅ Token carregado - Expira em: {expires_at}")
                return True
            else:
                print("ℹ️ Nenhum token salvo encontrado")
            
            return False
            
        except Exception as e:
            print(f"❌ Erro ao carregar token: {e}")
            return False
    
    def is_token_valid(self):
        """Verifica se o token ainda é válido"""
        if not self.expires_at:
            return False
        
        return datetime.now() < self.expires_at
    
    def time_until_expiry(self):
        """Retorna tempo até expiração"""
        if not self.expires_at:
            return None
        
        delta = self.expires_at - datetime.now()
        return delta if delta.total_seconds() > 0 else timedelta(0)
    
    def needs_renewal(self):
        """Verifica se precisa renovar (menos de 30 minutos)"""
        time_left = self.time_until_expiry()
        if not time_left:
            return True
        
        return time_left.total_seconds() < 1800  # 30 minutos
    
    def add_notification(self, message, level="INFO"):
        """Adiciona notificação ao banco"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO token_notifications (message, level)
                VALUES (?, ?)
            """, (message, level))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"❌ Erro ao adicionar notificação: {e}")
    
    def test_token(self):
        """Testa se o token ainda funciona"""
        if not self.access_token:
            return False
        
        try:
            url = "https://api.mercadolibre.com/users/me"
            headers = {'Authorization': f'Bearer {self.access_token}'}
            
            response = requests.get(url, headers=headers)
            return response.status_code == 200
            
        except Exception as e:
            print(f"❌ Erro ao testar token: {e}")
            return False
    
    def monitor_loop(self):
        """Loop de monitoramento em background"""
        print("🔍 Iniciando monitoramento de token...")
        
        while self.is_running:
            try:
                if not self.is_token_valid():
                    message = "🚨 TOKEN EXPIRADO! Renovação manual necessária."
                    print(message)
                    self.add_notification(message, "CRITICAL")
                    
                elif self.needs_renewal():
                    time_left = self.time_until_expiry()
                    minutes_left = int(time_left.total_seconds() / 60)
                    
                    # Evita spam de notificações
                    now = datetime.now()
                    if not self.last_warning or (now - self.last_warning).total_seconds() > 600:  # 10 min
                        message = f"⚠️ Token expira em {minutes_left} minutos. Renovação recomendada."
                        print(message)
                        self.add_notification(message, "WARNING")
                        self.last_warning = now
                
                # Testa token a cada verificação
                if not self.test_token():
                    message = "❌ Token inválido ou expirado. Renovação necessária."
                    print(message)
                    self.add_notification(message, "ERROR")
                
                # Aguarda 5 minutos antes da próxima verificação
                time.sleep(300)
                
            except Exception as e:
                print(f"❌ Erro no monitoramento: {e}")
                time.sleep(60)
    
    def start_monitoring(self):
        """Inicia monitoramento em background"""
        if not self.is_running:
            self.is_running = True
            self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
            self.monitor_thread.start()
            print("🚀 Monitoramento de token iniciado!")
            return True
        return False
    
    def stop_monitoring(self):
        """Para monitoramento"""
        if self.is_running:
            self.is_running = False
            if self.monitor_thread:
                self.monitor_thread.join(timeout=5)
            print("🛑 Monitoramento de token parado!")
            return True
        return False
    
    def get_valid_token(self):
        """Retorna token se válido, None se expirado"""
        if self.is_token_valid() and self.test_token():
            return self.access_token
        else:
            print("❌ Token inválido ou expirado")
            return None
    
    def get_status(self):
        """Retorna status do monitor"""
        time_left = self.time_until_expiry()
        
        return {
            'has_token': bool(self.access_token),
            'is_valid': self.is_token_valid(),
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'time_until_expiry': str(time_left) if time_left else None,
            'needs_renewal': self.needs_renewal(),
            'monitoring_active': self.is_running,
            'token_works': self.test_token() if self.access_token else False
        }
    
    def get_notifications(self, limit=10):
        """Obtém notificações recentes"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT message, level, created_at 
                FROM token_notifications 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (limit,))
            
            notifications = cursor.fetchall()
            conn.close()
            
            return [
                {
                    'message': msg,
                    'level': level,
                    'created_at': created_at
                }
                for msg, level, created_at in notifications
            ]
            
        except Exception as e:
            print(f"❌ Erro ao obter notificações: {e}")
            return []

def test_token_monitor():
    """Função de teste do monitor de tokens"""
    print("🧪 TESTANDO MONITOR DE TOKENS")
    print("=" * 50)
    
    # Configurações
    DB_PATH = "/home/ubuntu/mercadolivre_bot/src/database/app.db"
    CURRENT_TOKEN = "APP_USR-5510376630479325-072321-31ceebc6a2428e8723948d8e00c75015-180617463"
    
    # Criar monitor
    token_monitor = TokenMonitor(DB_PATH)
    
    # Configurar token atual
    token_monitor.set_token(CURRENT_TOKEN)
    
    # Mostrar status
    status = token_monitor.get_status()
    print(f"📊 Status do Token Monitor:")
    for key, value in status.items():
        print(f"   {key}: {value}")
    
    # Iniciar monitoramento
    token_monitor.start_monitoring()
    
    print(f"\n✅ Token Monitor configurado e funcionando!")
    print(f"🔍 Monitoramento ativo")
    print(f"⚠️ Notificações serão geradas quando o token estiver próximo da expiração")
    
    return token_monitor

if __name__ == "__main__":
    test_token_monitor()

