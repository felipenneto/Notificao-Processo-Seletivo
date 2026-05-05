# Notificador de Processos Seletivos

Sistema simples em Python para monitorar publicações e atualizações na página de Processos Seletivos de prefeituras e enviar alertas via Telegram.

## Objetivo

O projeto verifica periodicamente a página de processos seletivos da prefeitura e identifica novos itens ou alterações relevantes nos processos já publicados.

Quando uma novidade é detectada, o sistema envia uma mensagem para um chat do Telegram configurado pelo usuário.

## Funcionalidades

- Monitoramento da página de processos seletivos da prefeitura
- Identificação de novas publicações
- Identificação de atualizações em processos existentes
- Envio de alertas via Telegram
- Armazenamento local do histórico em SQLite
- Execução manual ou agendada via cron

## Tecnologias utilizadas

- Python 3
- Requests
- BeautifulSoup
- lxml
- SQLite
- Telegram Bot API

## Estrutura do projeto

```text
.
├── main.py
├── requirements.txt
├── README.md
├── .gitignore
└── .env.example
