import os
import logging
from datetime import timezone, timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from db import init_db, add_subscriber, remove_subscriber, get_all_subscribers, subscriber_count
from news import get_weekly_digest

# === Config ===
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MSK = timezone(timedelta(hours=3))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# === Send digest to one user ===

async def send_digest_to_chat(bot, chat_id: int, news_items: list[dict]):
    """Send digest as a series of messages with photos."""
    # Header
    await bot.send_message(
        chat_id=chat_id,
        text="📰 *AI-новости недели — что попробовать прямо сейчас*",
        parse_mode="Markdown",
    )

    for item in news_items:
        # Last item is outro
        if "outro" in item:
            await bot.send_message(chat_id=chat_id, text=item["outro"])
            continue

        emoji = item.get("emoji", "📌")
        title = item.get("title", "")
        text = item.get("text", "")
        link = item.get("link", "")
        image_url = item.get("image_url", "")

        caption = f"{emoji} *{title}*\n\n{text}"
        if link:
            caption += f"\n\n🔗 [Читать подробнее]({link})"

        # Telegram caption limit is 1024 chars
        if len(caption) > 1024:
            caption = caption[:1020] + "..."

        if image_url:
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=image_url,
                    caption=caption,
                    parse_mode="Markdown",
                )
                continue
            except Exception as e:
                logger.warning(f"Failed to send photo {image_url[:50]}: {e}")
                # Fall through to text-only

        # Text-only fallback
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )


# === Commands ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_subscriber(user.id, user.username or "", user.first_name or "")
    count = subscriber_count()
    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Я — бот, который каждую пятницу в 18:00 (МСК) присылает "
        "топ-5 AI-новостей за неделю 🤖\n\n"
        "Простым языком, с картинками и ссылками.\n"
        "Никакого техно-жаргона — только то, что реально можно попробовать.\n\n"
        "✅ Ты подписан(а) на рассылку!\n\n"
        "/digest — получить дайджест прямо сейчас\n"
        "/stop — отписаться\n\n"
        f"Нас уже: {count} 🙌"
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    removed = remove_subscriber(update.effective_user.id)
    if removed:
        await update.message.reply_text(
            "Ты отписан(а) от рассылки 😔\n"
            "Напиши /start если передумаешь!"
        )
    else:
        await update.message.reply_text("Ты и так не подписан(а). Напиши /start чтобы подписаться.")


async def digest_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get digest right now (for testing or on-demand)."""
    await update.message.reply_text("⏳ Собираю свежие новости, подожди минутку...")
    news_items = await get_weekly_digest()
    await send_digest_to_chat(context.bot, update.effective_chat.id, news_items)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = subscriber_count()
    await update.message.reply_text(f"📊 Подписчиков: {count}")


# === Scheduled sending ===

async def send_weekly_digest(app: Application):
    """Send digest to all subscribers."""
    logger.info("Starting weekly digest...")
    news_items = await get_weekly_digest()
    subscribers = get_all_subscribers()
    logger.info(f"Sending to {len(subscribers)} subscribers")

    sent = 0
    failed = 0
    for user_id in subscribers:
        try:
            await send_digest_to_chat(app.bot, user_id, news_items)
            sent += 1
        except Exception as e:
            logger.warning(f"Failed to send to {user_id}: {e}")
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("digest", digest_now))
    app.add_handler(CommandHandler("stats", stats))

    # Scheduler — every Friday at 18:00 Moscow time (15:00 UTC)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_weekly_digest,
        CronTrigger(day_of_week="fri", hour=15, minute=0),
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
