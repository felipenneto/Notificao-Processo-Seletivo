import os
import sqlite3
import hashlib
import requests
import logging
from datetime import datetime
from bs4 import BeautifulSoup

URL = "https://www.varzeaalegre.ce.gov.br/processoseletivo.php"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DB_PATH = "monitor_state.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS processos (
            uid TEXT PRIMARY KEY,
            descricao TEXT,
            numero TEXT,
            secretaria TEXT,
            data_ultimo_arquivo TEXT,
            qtd_arquivos TEXT,
            link TEXT,
            first_seen TEXT
        )
    """
    )
    conn.commit()
    return conn


def make_uid(descricao, numero, data_ultimo_arquivo, qtd_arquivos):
    raw = f"{descricao}|{numero}|{data_ultimo_arquivo}|{qtd_arquivos}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def fetch_page():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    resp = requests.get(URL, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


def parse_processos(html):
    soup = BeautifulSoup(html, "lxml")
    processos = []

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header_row = rows[0]
        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

        if not headers:
            continue

        col_map = {}
        for idx, h in enumerate(headers):
            if any(k in h for k in ["descri", "processo", "título", "titulo", "nome"]):
                col_map.setdefault("descricao", idx)
            elif any(k in h for k in ["edital", "número", "numero", "nº", "n°"]):
                col_map.setdefault("numero", idx)
            elif any(k in h for k in ["secretaria", "órgão", "orgao", "setor"]):
                col_map.setdefault("secretaria", idx)
            elif any(k in h for k in ["arquivo", "qtd", "quant", "qtde"]):
                col_map.setdefault("qtd_arquivos", idx)
            elif any(k in h for k in ["data", "atualiz", "última", "ultima"]):
                col_map.setdefault("data_ultimo_arquivo", idx)

        if not col_map:
            col_indices = list(range(len(headers)))
            col_map = {
                "descricao": col_indices[0] if len(col_indices) > 0 else 0,
                "numero": col_indices[1] if len(col_indices) > 1 else 1,
                "secretaria": col_indices[2] if len(col_indices) > 2 else 2,
                "qtd_arquivos": col_indices[3] if len(col_indices) > 3 else 3,
                "data_ultimo_arquivo": col_indices[4] if len(col_indices) > 4 else 4,
            }

        for row in rows[1:]:
            cols = row.find_all("td")
            if not cols:
                continue

            def get_col(key, fallback=""):
                idx = col_map.get(key)
                if idx is not None and idx < len(cols):
                    return cols[idx].get_text(strip=True)
                return fallback

            descricao = get_col("descricao")
            if not descricao:
                continue

            numero = get_col("numero")
            secretaria = get_col("secretaria")
            qtd_arquivos = get_col("qtd_arquivos")
            data_ultimo_arquivo = get_col("data_ultimo_arquivo")

            link = ""
            for col in cols:
                a = col.find("a", href=True)
                if a:
                    href = a["href"].strip()
                    if href.startswith("http"):
                        link = href
                    elif href and href != "#":
                        base = "https://www.varzeaalegre.ce.gov.br"
                        link = base + "/" + href.lstrip("/")
                    break

            processos.append(
                {
                    "descricao": descricao,
                    "numero": numero,
                    "secretaria": secretaria,
                    "qtd_arquivos": qtd_arquivos,
                    "data_ultimo_arquivo": data_ultimo_arquivo,
                    "link": link,
                }
            )

    if not processos:
        logger.warning(
            "Nenhum item encontrado via tabela. Tentando busca genérica por links..."
        )
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if text and len(text) > 10:
                href = a["href"].strip()
                if href.startswith("http"):
                    link = href
                elif href and href != "#":
                    link = "https://www.varzeaalegre.ce.gov.br/" + href.lstrip("/")
                else:
                    link = URL
                processos.append(
                    {
                        "descricao": text,
                        "numero": "",
                        "secretaria": "",
                        "qtd_arquivos": "",
                        "data_ultimo_arquivo": "",
                        "link": link,
                    }
                )

    return processos


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configurados.")
        return False
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(api_url, json=payload, timeout=15)
    resp.raise_for_status()
    return True


def format_message(processo):
    link = processo["link"] or URL
    return (
        "🚨 <b>Nova atualização em processo seletivo</b>\n\n"
        f"<b>Título:</b>\n{processo['descricao']}\n\n"
        f"<b>Número:</b>\n{processo['numero'] or '—'}\n\n"
        f"<b>Secretaria:</b>\n{processo['secretaria'] or '—'}\n\n"
        f"<b>Data do último arquivo:</b>\n{processo['data_ultimo_arquivo'] or '—'}\n\n"
        f"<b>Quantidade de arquivos:</b>\n{processo['qtd_arquivos'] or '—'}\n\n"
        f"<b>Link:</b>\n{link}"
    )


def main():
    logger.info("=" * 50)
    logger.info(f"Verificação iniciada em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    logger.info(f"URL monitorada: {URL}")

    conn = init_db()
    c = conn.cursor()

    try:
        html = fetch_page()
    except Exception as e:
        logger.error(f"Erro ao acessar a página: {e}")
        conn.close()
        return

    try:
        processos = parse_processos(html)
    except Exception as e:
        logger.error(f"Erro ao fazer parsing da página: {e}")
        conn.close()
        return

    logger.info(f"Itens encontrados na página: {len(processos)}")

    c.execute("SELECT COUNT(*) FROM processos")
    total_saved = c.fetchone()[0]
    is_first_run = total_saved == 0

    if is_first_run:
        logger.info("Primeira execução — salvando estado inicial sem enviar alertas.")

    novidades = 0
    notificacoes_enviadas = 0

    for processo in processos:
        uid = make_uid(
            processo["descricao"],
            processo["numero"],
            processo["data_ultimo_arquivo"],
            processo["qtd_arquivos"],
        )

        c.execute("SELECT uid FROM processos WHERE uid = ?", (uid,))
        exists = c.fetchone()

        if not exists:
            now = datetime.now().isoformat()
            c.execute(
                """
                INSERT INTO processos
                    (uid, descricao, numero, secretaria, data_ultimo_arquivo, qtd_arquivos, link, first_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    uid,
                    processo["descricao"],
                    processo["numero"],
                    processo["secretaria"],
                    processo["data_ultimo_arquivo"],
                    processo["qtd_arquivos"],
                    processo["link"],
                    now,
                ),
            )
            conn.commit()

            if not is_first_run:
                novidades += 1
                logger.info(
                    f"Novidade detectada: {processo['descricao']} | "
                    f"Número: {processo['numero']} | "
                    f"Data: {processo['data_ultimo_arquivo']}"
                )
                try:
                    msg = format_message(processo)
                    sent = send_telegram(msg)
                    if sent:
                        notificacoes_enviadas += 1
                        logger.info(
                            f"Notificação enviada com sucesso para: {processo['descricao']}"
                        )
                except Exception as e:
                    logger.error(f"Erro ao enviar notificação Telegram: {e}")

    conn.close()

    logger.info(f"Novidades detectadas: {novidades}")
    logger.info(f"Notificações enviadas com sucesso: {notificacoes_enviadas}")
    logger.info(f"Verificação concluída em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    logger.info("=" * 50)


def test_telegram():
    logger.info("Modo de teste — enviando mensagem de verificação ao Telegram...")
    try:
        sent = send_telegram("✅ Monitoramento de editais configurado com sucesso.")
        if sent:
            logger.info("Mensagem de teste enviada com sucesso!")
        else:
            logger.error("Falha ao enviar mensagem de teste.")
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem de teste: {e}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--test-telegram":
        test_telegram()
    else:
        main()
