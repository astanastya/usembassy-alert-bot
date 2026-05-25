import html
import logging
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_RSS_URL = "https://ua.usembassy.gov/category/alert/feed/"


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    rss_url: str = DEFAULT_RSS_URL
    check_interval_seconds: int = 600
    db_path: str = "data/seen_posts.sqlite3"
    send_existing_on_first_run: bool = False
    notify_on_start: bool = True


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is required")

    interval_raw = os.getenv("CHECK_INTERVAL_SECONDS", "600").strip()
    try:
        interval = int(interval_raw)
    except ValueError as exc:
        raise RuntimeError("CHECK_INTERVAL_SECONDS must be an integer") from exc

    if interval < 300:
        logging.warning("CHECK_INTERVAL_SECONDS is lower than 300. Consider using 300+ seconds to avoid aggressive polling.")

    return Config(
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        rss_url=os.getenv("RSS_URL", DEFAULT_RSS_URL).strip(),
        check_interval_seconds=interval,
        db_path=os.getenv("DB_PATH", "data/seen_posts.sqlite3").strip(),
        send_existing_on_first_run=env_bool("SEND_EXISTING_ON_FIRST_RUN", False),
        notify_on_start=env_bool("NOTIFY_ON_START", True),
    )


def init_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_posts (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            published TEXT,
            first_seen_utc TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def post_id(entry) -> str:
    return (entry.get("id") or entry.get("guid") or entry.get("link") or entry.get("title") or "").strip()


def fetch_entries(rss_url: str):
    # feedparser can fetch by URL directly, but this request keeps headers explicit and errors clearer.
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; EmbassyAlertTelegramBot/1.0; +https://github.com/)"
    }
    response = requests.get(rss_url, headers=headers, timeout=30)
    response.raise_for_status()

    parsed = feedparser.parse(response.content)
    if parsed.bozo:
        logging.warning("RSS feed parsed with warnings: %s", parsed.bozo_exception)

    return parsed.entries


def is_seen(conn: sqlite3.Connection, entry_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM seen_posts WHERE id = ? LIMIT 1", (entry_id,)).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, entry) -> None:
    entry_id = post_id(entry)
    title = entry.get("title", "No title")
    link = entry.get("link", "")
    published = entry.get("published", entry.get("updated", ""))
    conn.execute(
        """
        INSERT OR IGNORE INTO seen_posts (id, title, link, published, first_seen_utc)
        VALUES (?, ?, ?, ?, ?)
        """,
        (entry_id, title, link, published, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def format_message(entry) -> str:
    title = html.escape(entry.get("title", "New alert"))
    link = html.escape(entry.get("link", ""))
    published = html.escape(entry.get("published", entry.get("updated", "")))

    lines = [
        "🚨 <b>Новий допис на U.S. Embassy Ukraine Alerts</b>",
        f"<b>{title}</b>",
    ]

    if published:
        lines.append(f"Дата: {published}")
    if link:
        lines.append(f'<a href="{link}">Відкрити допис</a>')

    return "\n".join(lines)


def send_telegram_message(config: Config, text: str) -> None:
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": config.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    for attempt in range(1, 4):
        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return
        except requests.RequestException:
            logging.exception("Failed to send Telegram message. Attempt %s/3", attempt)
            if attempt == 3:
                raise
            time.sleep(5 * attempt)


def get_new_entries(conn: sqlite3.Connection, entries: Iterable) -> list:
    new_entries = []
    for entry in entries:
        entry_id = post_id(entry)
        if not entry_id:
            continue
        if not is_seen(conn, entry_id):
            new_entries.append(entry)
    return new_entries


def run_once(config: Config, conn: sqlite3.Connection, first_run: bool = False) -> int:
    entries = fetch_entries(config.rss_url)
    new_entries = get_new_entries(conn, entries)

    if first_run and not config.send_existing_on_first_run:
        for entry in entries:
            if post_id(entry):
                mark_seen(conn, entry)
        logging.info("First run: seeded %s existing entries without sending messages", len(entries))
        return 0

    # RSS usually returns newest first. Send oldest first so messages read naturally.
    for entry in reversed(new_entries):
        send_telegram_message(config, format_message(entry))
        mark_seen(conn, entry)
        logging.info("Sent alert: %s", entry.get("title", "No title"))

    return len(new_entries)


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        config = load_config()
        conn = init_db(config.db_path)

        if config.notify_on_start:
            send_telegram_message(
                config,
                "✅ Бот запущено. Перевіряю нові дописи U.S. Embassy Ukraine Alerts.",
            )

        first_run = True
        while True:
            try:
                count = run_once(config, conn, first_run=first_run)
                logging.info("Check completed. New entries: %s", count)
                first_run = False
            except Exception:
                logging.exception("Check failed")

            time.sleep(config.check_interval_seconds)

    except Exception as exc:
        logging.exception("Bot stopped: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
