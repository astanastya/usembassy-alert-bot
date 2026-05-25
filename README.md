# Telegram bot для U.S. Embassy Ukraine Alerts

Бот перевіряє RSS-стрічку сторінки `https://ua.usembassy.gov/category/alert/` і надсилає Telegram-повідомлення, коли зʼявляється новий допис.

За замовчуванням використовується RSS:

```text
https://ua.usembassy.gov/category/alert/feed/
```

## 1. Створи Telegram bot

1. Відкрий Telegram.
2. Знайди `@BotFather`.
3. Виконай команду `/newbot`.
4. Скопіюй token.

## 2. Отримай chat_id

1. Напиши своєму новому боту будь-яке повідомлення, наприклад `test`.
2. Відкрий у браузері:

```text
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

3. Знайди `message.chat.id` і скопіюй це число.

## 3. Налаштуй .env

Скопіюй приклад:

```bash
cp .env.example .env
```

Відкрий `.env` і заповни:

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## 4. Запуск через Docker

```bash
docker compose up -d --build
```

Переглянути логи:

```bash
docker logs -f usembassy-alert-bot
```

Зупинити:

```bash
docker compose down
```

## 5. Запуск без Docker

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.bot
```

## Важливі налаштування

```text
CHECK_INTERVAL_SECONDS=600
SEND_EXISTING_ON_FIRST_RUN=false
NOTIFY_ON_START=true
```

`SEND_EXISTING_ON_FIRST_RUN=false` означає, що при першому запуску бот просто запамʼятає старі дописи й не буде спамити ними. Повідомлення прийдуть тільки для нових дописів після запуску.

Якщо хочеш перевірити, що повідомлення реально приходять, тимчасово постав:

```text
SEND_EXISTING_ON_FIRST_RUN=true
```

Після тесту поверни назад `false`.
