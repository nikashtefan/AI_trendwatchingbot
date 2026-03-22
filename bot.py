import os
import asyncio
import logging
from datetime import time, timezone, timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from db import init_db, add_subscriber, remove_subscriber, get_all_subscribers, subscriber_count
from news import get_weekly_digest

# === Config ===
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# Moscow timezone UTC+3
MSK = timezone(timedelta(hours=3))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# === Commands ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_subscriber(user.id, user.username or "", user.first_name or "")
    count = subscriber_count()
    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Я — бот, который каждую пятницу в 18:00 (МСК) присылает "
        "дайджест самых важных AI-новостей за неделю.\n\n"
        "Топ-5 новостей с кратким описанием на русском + ссылки на источники.\n\n"
        "✅ Ты подписан(а) на рассылку!\n\n"
        "Команды:\n"
        "/digest — получить дайджест прямо сейчас\n"
        "/stop — отписаться\n\n"
        f"Подписчиков: {count}"
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    removed = remove_subscriber(update.effective_user.id)
    if removed:
        await update.message.reply_text(
            "Ты отписан(а) от рассылки. 😔\n"
            "Напиши /start если передумаешь!"
        )
    else:
        await update.message.reply_text("Ты и так не подписан(а). Напиши /start чтобы подписаться.")


async def digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get digest right now (for testing or on-demand)."""
    await update.message.reply_text("⏳ Собираю новости, подожди минутку...")
    text = await get_weekly_digest()
    # Split long messages (Telegram limit 4096 chars)
    if len(text) > 4000:
        parts = split_message(text, 4000)
        for part in parts:
            await update.message.reply_text(part, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = subscriber_count()
    await update.message.reply_text(f"📊 Подписчиков: {count}")


def split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split long text into chunks by double newline."""
    if len(text) <= max_len:
        return [text]
    parts = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > max_len:
            if current:
                parts.append(current.strip())
            current = paragraph
        else:
            current += "\n\n" + paragraph if current else paragraph
    if current:
        parts.append(current.strip())
    return parts


# === Scheduled sending ===

async def send_weekly_digest(app: Application):
    """Send digest to all subscribers."""
    logger.info("Starting weekly digest...")
    text = await get_weekly_digest()
    subscribers = get_all_subscribers()
    logger.info(f"Sending to {len(subscribers)} subscribers")

    sent = 0
    failed = 0
    for user_id in subscribers:
        try:
            if len(text) > 4000:
                parts = split_message(text, 4000)
                for part in parts:
                    await app.bot.send_message(
                        chat_id=user_id, text=part,
                        parse_mode="Markdown", disable_web_page_preview=True,
                    )
            else:
                await app.bot.send_message(
                    chat_id=user_id, text=text,
                    parse_mode="Markdown", disable_web_page_preview=True,
                )
            sent += 1
        except Exception as e:
            logger.warning(f"Failed to send to {user_id}: {e}")
            # Remove blocked/deleted users
            if "Forbidden" in str(e) or "blocked" in str(e).lower():
                remove_subscriber(user_id)
                logger.info(f"Removed blocked user {user_id}")
            failed += 1

    logger.info(f"Digest sent: {sent} ok, {failed} failed")


def main():
    if not BOT_TOKEN:
        print("ERROR: Set BOT_TOKEN environment variable!")
        return

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("digest", digest_now))
    app.add_handler(CommandHandler("stats", stats))

    # Scheduler — every Friday at 18:00 Moscow time (15:00 UTC)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_weekly_digest,
        CronTrigger(day_of_week="fri", hour=15, minute=0),  # 15:00 UTC = 18:00 MSK
        args=[app],
        id="weekly_digest",
        name="Weekly AI Digest",
    )
    scheduler.start()
    logger.info("Scheduler started: every Friday at 18:00 MSK")

    print("Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
