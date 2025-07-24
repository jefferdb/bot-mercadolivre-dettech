"""
Script para restaurar todas as regras e configurações
Executa automaticamente no deploy Railway
"""

import os
import sys
import json
from datetime import datetime

# Adicionar src ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def restore_all_rules():
    """Restaurar todas as regras no banco"""
    try:
        from models.user import db
        from models.mercadolivre import MLAutoResponse, MLAbsenceResponse
        from flask import Flask
        
        # Configurar Flask temporariamente
        app = Flask(__name__)
        
        # Configuração do banco
        DATABASE_URL = os.environ.get('DATABASE_URL')
        if DATABASE_URL:
            if DATABASE_URL.startswith('postgres://'):
                DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
            app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
        else:
            app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///temp.db'
        
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        
        with app.app_context():
            # Todas as regras
            rules_data = [
                {
                    "name": "Saudação e Boas-vindas",
                    "keywords": ["olá", "oi", "bom dia", "boa tarde", "boa noite", "tudo bem"],
                    "response": "Olá! Seja muito bem-vindo à DETTECH! Estamos aqui para ajudá-lo com peças automotivas de qualidade. Como posso auxiliá-lo hoje? Atenciosamente, Jeff - Equipe DETTECH.",
                    "priority": 1,
                    "active": True
                },
                {
                    "name": "Compatibilidade - Numeração Original",
                    "keywords": ["compatível", "serve", "funciona", "encaixa", "modelo", "ano"],
                    "response": "Olá, seja bem-vindo à DETTECH! Para confirmar a compatibilidade, precisamos que informe a numeração original constante na sua peça. Atenciosamente, Jeff - Equipe DETTECH.",
                    "priority": 10,
                    "active": True
                },
                {
                    "name": "Prazo de Entrega",
                    "keywords": ["prazo", "entrega", "demora", "quando chega", "tempo", "dias"],
                    "response": "O prazo de entrega varia conforme sua localização. Após a confirmação do pagamento, o envio é realizado em até 1 dia útil. O prazo de entrega pelos Correios é de 3 a 10 dias úteis. Atenciosamente, Jeff - Equipe DETTECH.",
                    "priority": 8,
                    "active": True
                },
                {
                    "name": "Garantia",
                    "keywords": ["garantia", "defeito", "problema", "troca", "devolução"],
                    "response": "Todos os nossos produtos possuem garantia de 90 dias contra defeitos de fabricação. Em caso de problemas, entre em contato conosco que resolveremos rapidamente. Atenciosamente, Jeff - Equipe DETTECH.",
                    "priority": 9,
                    "active": True
                },
                {
                    "name": "Preço e Pagamento",
                    "keywords": ["preço", "valor", "custa", "pagamento", "desconto", "parcelamento"],
                    "response": "O preço está anunciado no produto. Aceitamos PIX (com desconto), cartão de crédito e débito. Para PIX, oferecemos desconto especial. Atenciosamente, Jeff - Equipe DETTECH.",
                    "priority": 7,
                    "active": True
                },
                {
                    "name": "Disponibilidade",
                    "keywords": ["disponível", "estoque", "tem", "pronta entrega"],
                    "response": "Sim, temos o produto em estoque e pronta entrega! Pode finalizar sua compra que enviaremos rapidamente. Atenciosamente, Jeff - Equipe DETTECH.",
                    "priority": 6,
                    "active": True
                },
                {
                    "name": "Instalação e Manual",
                    "keywords": ["instalar", "instalação", "como", "manual", "instruções"],
                    "response": "O produto vem com instruções básicas. Para instalação profissional, recomendamos procurar um técnico especializado. Estamos disponíveis para esclarecer dúvidas técnicas. Atenciosamente, Jeff - Equipe DETTECH.",
                    "priority": 5,
                    "active": True
                },
                {
                    "name": "Agradecimento",
                    "keywords": ["obrigado", "obrigada", "valeu", "agradeço"],
                    "response": "Por nada! Ficamos felizes em ajudar. A DETTECH está sempre à disposição para oferecer as melhores peças e atendimento. Volte sempre! Atenciosamente, Jeff - Equipe DETTECH.",
                    "priority": 2,
                    "active": True
                },
                {
                    "name": "Estoque",
                    "keywords": ["quantos", "quantidade", "unidades", "peças"],
                    "response": "Temos boa quantidade em estoque. Caso precise de grandes quantidades, consulte-nos para condições especiais. Atenciosamente, Jeff - Equipe DETTECH.",
                    "priority": 4,
                    "active": True
                },
                {
                    "name": "Medidas e Especificações",
                    "keywords": ["medida", "tamanho", "dimensão", "especificação", "ficha técnica"],
                    "response": "As especificações técnicas estão descritas no anúncio. Para informações mais detalhadas ou medidas específicas, informe o modelo do seu veículo que te auxiliaremos. Atenciosamente, Jeff - Equipe DETTECH.",
                    "priority": 3,
                    "active": True
                }
            ]
            
            print("🤖 Restaurando regras de resposta...")
            rules_created = 0
            
            for rule_data in rules_data:
                # Verificar se já existe
                existing = MLAutoResponse.query.filter_by(name=rule_data["name"]).first()
                if existing:
                    print(f"   ⚠️ Regra '{rule_data['name']}' já existe")
                    continue
                
                # Criar nova regra
                rule = MLAutoResponse(
                    name=rule_data["name"],
                    keywords=json.dumps(rule_data["keywords"], ensure_ascii=False),
                    response=rule_data["response"],
                    priority=rule_data["priority"],
                    active=rule_data["active"],
                    created_at=datetime.now()
                )
                
                db.session.add(rule)
                rules_created += 1
                print(f"   ✅ Regra '{rule_data['name']}' criada")
            
            # Configurações de ausência
            absence_data = [
                {
                    "name": "Fora do Horário Comercial",
                    "message": "Olá! Obrigado pelo seu contato. No momento estamos fora do horário de atendimento (09:00 às 18:00). Retornaremos sua mensagem no próximo dia útil. Atenciosamente, Jeff - Equipe DETTECH.",
                    "start_time": "18:01",
                    "end_time": "08:59",
                    "weekdays_only": False,
                    "active": True
                },
                {
                    "name": "Final de Semana",
                    "message": "Olá! Obrigado pelo seu contato. Nosso atendimento funciona de segunda a sexta-feira, das 09:00 às 18:00. Retornaremos sua mensagem no próximo dia útil. Atenciosamente, Jeff - Equipe DETTECH.",
                    "start_time": "00:00",
                    "end_time": "23:59",
                    "weekdays_only": True,
                    "active": True
                }
            ]
            
            print("🌙 Restaurando configurações de ausência...")
            absence_created = 0
            
            for absence in absence_data:
                # Verificar se já existe
                existing = MLAbsenceResponse.query.filter_by(name=absence["name"]).first()
                if existing:
                    print(f"   ⚠️ Configuração '{absence['name']}' já existe")
                    continue
                
                # Criar nova configuração
                config = MLAbsenceResponse(
                    name=absence["name"],
                    message=absence["message"],
                    start_time=absence["start_time"],
                    end_time=absence["end_time"],
                    weekdays_only=absence["weekdays_only"],
                    active=absence["active"],
                    created_at=datetime.now()
                )
                
                db.session.add(config)
                absence_created += 1
                print(f"   ✅ Configuração '{absence['name']}' criada")
            
            # Salvar tudo
            db.session.commit()
            
            print(f"✅ Restauração concluída!")
            print(f"   📋 {rules_created} regras criadas")
            print(f"   🌙 {absence_created} configurações de ausência criadas")
            
            return True
            
    except Exception as e:
        print(f"❌ Erro na restauração: {e}")
        return False

if __name__ == "__main__":
    success = restore_all_rules()
    if success:
        print("🎉 Todas as configurações foram restauradas!")
    else:
        print("❌ Erro na restauração das configurações")

