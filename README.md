# Notificador de Processos Seletivos

Sistema em Python para monitorar publicações e atualizações na página de Processos Seletivos de prefeituras e enviar alertas via Telegram.

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
```

Arquivos gerados em produção, mas não versionados:

```text
.env
monitor_state.db
monitor.log
venv/
__pycache__/
```

## Variáveis de ambiente

Crie um arquivo `.env` com base no `.env.example`:

```env
TELEGRAM_BOT_TOKEN=seu_token_do_bot
TELEGRAM_CHAT_ID=seu_chat_id
```

## Instalação

Clone o repositório:

```bash
git clone https://github.com/SEU-USUARIO/NOME-DO-REPOSITORIO.git
cd NOME-DO-REPOSITORIO
```

Crie o ambiente virtual:

```bash
python3 -m venv venv
source venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

## Teste do Telegram

Para testar se o bot está enviando mensagens corretamente:

```bash
set -a
source .env
set +a
python main.py --test-telegram
```

## Execução manual

Para rodar uma verificação:

```bash
set -a
source .env
set +a
python main.py
```

Na primeira execução, o sistema salva o estado inicial dos processos encontrados e não envia alertas.

A partir das próximas execuções, ele notifica apenas quando detectar novidade ou atualização.

## Agendamento com cron

Exemplo para rodar a cada 1 hora:

```bash
0 * * * * cd /opt/notificador-editais && set -a && . ./.env && set +a && /opt/notificador-editais/venv/bin/python /opt/notificador-editais/main.py >> /opt/notificador-editais/monitor.log 2>&1
```

Para editar o cron:

```bash
crontab -e
```

Para listar os agendamentos ativos:

```bash
crontab -l
```

## Logs

Para acompanhar os logs:

```bash
tail -f /opt/notificador-editais/monitor.log
```

Para visualizar as últimas linhas:

```bash
tail -n 50 /opt/notificador-editais/monitor.log
```

Para limpar o log manualmente:

```bash
truncate -s 0 /opt/notificador-editais/monitor.log
```

## Segurança

Nunca envie o arquivo `.env` para o GitHub, mesmo em repositórios privados.

Esse arquivo contém dados sensíveis, como o token do bot do Telegram.

Use o `.env.example` apenas como modelo.

## Observações

- O sistema não fica rodando continuamente.
- A execução é feita de forma agendada pelo cron.
- O consumo de RAM é baixo, pois o script roda, verifica a página e encerra.
- O banco `monitor_state.db` é criado automaticamente na primeira execução.
