import hashlib
import html as html_lib
import logging
import os
import sqlite3
import unicodedata
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL = "https://www.varzeaalegre.ce.gov.br/processoseletivo.php"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DB_PATH = os.environ.get("MONITOR_DB_PATH", "monitor_state.db")
REQUEST_TIMEOUT = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)


def init_db():
    """Create the state database and migrate databases from earlier versions."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processos (
            uid TEXT PRIMARY KEY, descricao TEXT NOT NULL, numero TEXT, secretaria TEXT,
            data_ultimo_arquivo TEXT, qtd_arquivos TEXT, link TEXT, first_seen TEXT NOT NULL,
            notification_status TEXT NOT NULL DEFAULT 'delivered',
            notification_attempts INTEGER NOT NULL DEFAULT 0, notified_at TEXT,
            last_notification_error TEXT
        )
    """)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(processos)")}
    migrations = {
        "notification_status": "TEXT NOT NULL DEFAULT 'delivered'",
        "notification_attempts": "INTEGER NOT NULL DEFAULT 0",
        "notified_at": "TEXT",
        "last_notification_error": "TEXT",
    }
    for name, definition in migrations.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE processos ADD COLUMN {name} {definition}")
    # Old rows are already-known history. Do not flood users after the migration.
    conn.execute("""
        UPDATE processos SET notified_at = COALESCE(notified_at, first_seen)
        WHERE notification_status = 'delivered' AND notified_at IS NULL
    """)
    conn.commit()
    return conn


def make_uid(descricao, numero, data_ultimo_arquivo, qtd_arquivos):
    # Keep the original identity algorithm so the existing SQLite state remains
    # valid after deployment. This is an identifier, not a security primitive.
    raw = f"{descricao}|{numero}|{data_ultimo_arquivo}|{qtd_arquivos}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def build_session():
    session = requests.Session()
    retries = Retry(total=3, connect=3, read=3, backoff_factor=1,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=frozenset({"GET"}))
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    return session


def fetch_page(session, url):
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return response.text


def normalize(value):
    value = unicodedata.normalize("NFKD", value)
    return "".join(char for char in value if not unicodedata.combining(char)).lower().strip()


def get_column_map(headers):
    col_map = {}
    for index, header in enumerate(headers):
        name = normalize(header)
        if any(term in name for term in ("descricao", "titulo", "nome")):
            col_map.setdefault("descricao", index)
        elif any(term in name for term in ("numero", "edital", "exercicio")):
            col_map.setdefault("numero", index)
        elif any(term in name for term in ("secretaria", "orgao", "setor")):
            col_map.setdefault("secretaria", index)
        elif any(term in name for term in ("quant", "qtd", "qtde")):
            col_map.setdefault("qtd_arquivos", index)
        elif any(term in name for term in ("data", "atualiz", "ultimo")):
            col_map.setdefault("data_ultimo_arquivo", index)
    return col_map


def parse_processos(page_html):
    soup = BeautifulSoup(page_html, "lxml")
    processos = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["th", "td"])]
        col_map = get_column_map(headers)
        # Avoid treating an unrelated layout table as monitored content.
        if "descricao" not in col_map or "data_ultimo_arquivo" not in col_map:
            continue
        for row in rows[1:]:
            cols = row.find_all("td", recursive=False)
            if not cols:
                continue

            def get_col(key):
                index = col_map.get(key)
                return cols[index].get_text(" ", strip=True) if index is not None and index < len(cols) else ""

            descricao = get_col("descricao")
            if not descricao:
                continue
            anchor = row.find("a", href=True)
            processos.append({
                "descricao": descricao,
                "numero": get_col("numero"),
                "secretaria": get_col("secretaria"),
                "qtd_arquivos": get_col("qtd_arquivos"),
                "data_ultimo_arquivo": get_col("data_ultimo_arquivo"),
                "link": urljoin(URL, anchor["href"].strip()) if anchor else URL,
            })
    if not processos:
        raise ValueError("Nenhum processo foi encontrado na tabela esperada.")
    return processos


def get_pagination_urls(page_html):
    soup = BeautifulSoup(page_html, "lxml")
    base_path = urlparse(URL).path
    urls = {URL}
    for anchor in soup.find_all("a", href=True):
        candidate = urljoin(URL, anchor["href"].strip())
        parsed = urlparse(candidate)
        if parsed.path == base_path and "pagina=" in parsed.query:
            urls.add(candidate)
    return sorted(urls)


def fetch_all_processos():
    with build_session() as session:
        first_html = fetch_page(session, URL)
        page_urls = get_pagination_urls(first_html)
        processos = parse_processos(first_html)
        for page_url in page_urls:
            if page_url != URL:
                processos.extend(parse_processos(fetch_page(session, page_url)))

    unique = {}
    for processo in processos:
        uid = make_uid(processo["descricao"], processo["numero"], processo["data_ultimo_arquivo"], processo["qtd_arquivos"])
        unique[uid] = processo
    logger.info("Páginas consultadas: %s | Itens encontrados: %s", len(page_urls), len(unique))
    return list(unique.values())


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configurados.")
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False},
        timeout=15,
    )
    response.raise_for_status()


def format_message(processo):
    def escape(value):
        return html_lib.escape(value or "—")
    return (
        "🚨 <b>Nova atualização em processo seletivo</b>\n\n"
        f"<b>Título:</b>\n{escape(processo['descricao'])}\n\n"
        f"<b>Número:</b>\n{escape(processo['numero'])}\n\n"
        f"<b>Secretaria:</b>\n{escape(processo['secretaria'])}\n\n"
        f"<b>Data do último arquivo:</b>\n{escape(processo['data_ultimo_arquivo'])}\n\n"
        f"<b>Quantidade de arquivos:</b>\n{escape(processo['qtd_arquivos'])}\n\n"
        f"<b>Link:</b>\n{escape(processo['link'] or URL)}"
    )


def save_pending(conn, processo, is_first_run):
    uid = make_uid(processo["descricao"], processo["numero"], processo["data_ultimo_arquivo"], processo["qtd_arquivos"])
    status = "ignored" if is_first_run else "pending"
    conn.execute("""
        INSERT OR IGNORE INTO processos
            (uid, descricao, numero, secretaria, data_ultimo_arquivo, qtd_arquivos, link, first_seen, notification_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (uid, processo["descricao"], processo["numero"], processo["secretaria"], processo["data_ultimo_arquivo"],
            processo["qtd_arquivos"], processo["link"], datetime.now().isoformat(), status))
    return conn.execute("SELECT changes()").fetchone()[0] == 1


def deliver_pending(conn):
    pending = conn.execute("SELECT * FROM processos WHERE notification_status = 'pending' ORDER BY first_seen").fetchall()
    sent = 0
    for row in pending:
        processo = dict(row)
        try:
            send_telegram(format_message(processo))
        except Exception as error:
            logger.error("Falha ao enviar Telegram para '%s': %s", processo["descricao"], error)
            conn.execute("""
                UPDATE processos SET notification_attempts = notification_attempts + 1, last_notification_error = ?
                WHERE uid = ?
            """, (str(error), processo["uid"]))
        else:
            sent += 1
            conn.execute("""
                UPDATE processos SET notification_status = 'delivered', notification_attempts = notification_attempts + 1,
                    notified_at = ?, last_notification_error = NULL WHERE uid = ?
            """, (datetime.now().isoformat(), processo["uid"]))
            logger.info("Notificação enviada: %s", processo["descricao"])
        conn.commit()
    return len(pending), sent


def main():
    logger.info("=" * 50)
    logger.info("Verificação iniciada em: %s", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    logger.info("URL monitorada: %s", URL)
    try:
        processos = fetch_all_processos()
    except Exception as error:
        logger.error("Falha na coleta; estado não foi alterado: %s", error)
        return

    conn = init_db()
    try:
        is_first_run = conn.execute("SELECT COUNT(*) FROM processos").fetchone()[0] == 0
        if is_first_run:
            logger.info("Primeira execução: salvando estado inicial sem enviar alertas.")
        novidades = sum(save_pending(conn, processo, is_first_run) for processo in processos)
        conn.commit()
        pending, sent = deliver_pending(conn)
        logger.info("Novidades detectadas: %s", 0 if is_first_run else novidades)
        logger.info("Notificações pendentes processadas: %s | enviadas: %s", pending, sent)
    finally:
        conn.close()
    logger.info("Verificação concluída em: %s", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    logger.info("=" * 50)


def test_telegram():
    logger.info("Modo de teste: enviando mensagem de verificação ao Telegram...")
    try:
        send_telegram("✅ Monitoramento de editais configurado com sucesso.")
    except Exception as error:
        logger.error("Erro ao enviar mensagem de teste: %s", error)
    else:
        logger.info("Mensagem de teste enviada com sucesso!")


if __name__ == "__main__":
    import sys
    test_telegram() if len(sys.argv) > 1 and sys.argv[1] == "--test-telegram" else main()
