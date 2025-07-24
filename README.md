# 🤖 Bot Mercado Livre - DETTECH

Bot automatizado para responder perguntas no Mercado Livre usando regras personalizadas.

## 🚀 Deploy no Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/your-template-id)

## ✨ Funcionalidades

- ✅ **Respostas automáticas** baseadas em palavras-chave
- ✅ **Dashboard web** para gerenciamento
- ✅ **Configurações de ausência** (horário comercial)
- ✅ **Monitoramento em tempo real**
- ✅ **16 regras pré-configuradas**
- ✅ **Interface amigável**

## 🔧 Configuração

### Variáveis de Ambiente Necessárias:

```env
ML_CLIENT_ID=seu_client_id
ML_CLIENT_SECRET=seu_client_secret
ML_ACCESS_TOKEN=seu_access_token
ML_USER_ID=seu_user_id
```

### Como obter as credenciais:

1. Acesse [Mercado Livre Developers](https://developers.mercadolivre.com.br/)
2. Crie uma aplicação
3. Obtenha as credenciais necessárias

## 📋 Regras Pré-configuradas

1. **Saudação e Boas-vindas**
2. **Compatibilidade - Numeração Original**
3. **Prazo de Entrega**
4. **Garantia**
5. **Preço e Pagamento**
6. **Disponibilidade**
7. **Instalação e Manual**
8. **Agradecimento**
9. **Estoque**
10. **Medidas e Especificações**

## 🌙 Configurações de Ausência

- **Fora do Horário Comercial** (18:01 - 08:59)
- **Final de Semana** (Sábado e Domingo)

## 🎯 Como Usar

1. **Faça o deploy** no Railway
2. **Configure as variáveis** de ambiente
3. **Acesse o dashboard** na URL gerada
4. **Personalize as regras** conforme necessário

## 📊 Dashboard

O dashboard permite:
- Ver estatísticas em tempo real
- Gerenciar regras de resposta
- Configurar horários de ausência
- Monitorar perguntas e respostas

## 🔄 Funcionamento

1. Bot verifica novas perguntas a cada 60 segundos
2. Analisa palavras-chave nas perguntas
3. Responde automaticamente baseado nas regras
4. Registra todas as interações no dashboard

## 🛠️ Tecnologias

- **Python 3.11**
- **Flask** (Framework web)
- **PostgreSQL** (Banco de dados)
- **SQLAlchemy** (ORM)
- **Gunicorn** (Servidor web)

## 📞 Suporte

Bot desenvolvido para **DETTECH** - Especialista em peças automotivas.

---

**Versão:** Railway Basic v1.0  
**Última atualização:** 2024

