from __future__ import annotations

import feedparser
import httpx
import json
import os
import re
from datetime import datetime, timedelta, timezone

# === ProxyAPI (OpenAI-compatible) ===
PROXY_API_KEY = os.environ.get("PROXY_API_KEY", "")
PROXY_API_BASE = os.environ.get("PROXY_API_BASE", "https://api.proxyapi.ru/openai/v1")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")

# === RSS Sources ===
RSS_FEEDS = [
    ("OpenAI Blog", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("Google AI", "https://blog.google/technology/ai/rss/"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("Ars Technica AI", "https://arstechnica.com/ai/feed/"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("Import AI", "https://importai.substack.com/feed"),
    ("Last Week in AI", "https://lastweekin.ai/feed"),
]


def fetch_articles(days: int = 7) -> list[dict]:
    """Fetch articles from all RSS feeds published in the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    articles = []

    for source_name, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                # Parse published date
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

                if published and published < cutoff:
                    continue

                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", "").strip()
                # Clean HTML tags from summary
                if summary:
                    summary = re.sub(r"<[^>]+>", "", summary)[:500]

                if title:
                    articles.append(
                        {
                            "source": source_name,
                            "title": title,
                            "link": link,
                            "summary": summary,
                            "published": published.isoformat() if published else "",
                        }
                    )
        except Exception as e:
            print(f"[RSS] Error fetching {source_name}: {e}")

    return articles


def build_digest_prompt(articles: list[dict]) -> str:
    """Build a prompt for the AI to create a weekly digest."""
    articles_text = ""
    for i, a in enumerate(articles, 1):
        articles_text += (
            f"{i}. [{a['source']}] {a['title']}\n"
            f"   Ссылка: {a['link']}\n"
            f"   Описание: {a['summary'][:200]}\n\n"
        )

    prompt = f"""Ты — дружелюбный редактор еженедельного AI-дайджеста для широкой аудитории. Твои читатели — маркетологи, предприниматели, менеджеры и все, кто хочет использовать AI в работе. Они НЕ разработчики.

Из списка статей ниже выбери ТОП-5 самых полезных и интересных новостей за неделю.

🎯 Критерии отбора (ВАЖНО — приоритет именно такой):
1. Новые AI-инструменты и сервисы, которые можно сразу попробовать (например, новый чат-бот, генератор картинок, помощник для текстов)
2. Обновления популярных сервисов (ChatGPT, Claude, Gemini, Midjourney и т.д.), которые меняют пользовательский опыт
3. Новости о том, как компании используют AI — вдохновляющие кейсы
4. Важные события в мире AI, которые влияют на всех (регуляция, доступность, безопасность)

❌ НЕ бери:
- Чисто технические статьи про архитектуру моделей, бенчмарки, код
- Научные исследования без практического применения
- Новости только для разработчиков (API, SDK, фреймворки)

✍️ Стиль написания:
- Пиши простым, живым языком — как будто рассказываешь другу
- Никаких технических терминов (если нужен термин — объясни в скобках)
- В каждой новости обязательно скажи: "Что это значит для тебя" или "Как это можно использовать"
- Используй эмодзи для настроения, но без перебора

Формат ответа — строго такой:

🔥 **1. Заголовок**
Описание простым языком. Что случилось и почему тебе это полезно.
👉 Как попробовать / что с этим делать
🔗 ссылка

✨ **2. Заголовок**
Описание простым языком.
👉 Практическая польза
🔗 ссылка

🚀 **3. Заголовок**
...

💡 **4. Заголовок**
...

⚡ **5. Заголовок**
...

В самом конце напиши:
"Было полезно? Перешли другу, который тоже хочет быть в теме! 💬"

Вот список статей за неделю ({len(articles)} шт.):

{articles_text}"""

    return prompt


async def generate_digest(articles: list[dict]) -> str | None:
    """Call ProxyAPI (OpenAI-compatible) to generate the digest."""
    if not PROXY_API_KEY:
        print("[AI] PROXY_API_KEY not set")
        return None

    if not articles:
        return None

    prompt = build_digest_prompt(articles)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{PROXY_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {PROXY_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": AI_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Ты — дружелюбный AI-редактор, который пишет понятные дайджесты на русском языке для широкой аудитории. Твой стиль — живой, без занудства, с практической пользой. Пишешь так, как будто рассказываешь новости другу за кофе.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2000,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[AI] Error generating digest: {e}")
        return None


async def get_weekly_digest() -> str:
    """Main function: fetch articles → generate digest."""
    print("[Digest] Fetching articles...")
    articles = fetch_articles(days=7)
    print(f"[Digest] Found {len(articles)} articles")

    if not articles:
        return "На этой неделе не удалось собрать новости. Попробуем на следующей! 🤷"

    digest = await generate_digest(articles)

    if not digest:
        # Fallback: just list top articles without AI summary
        digest = "📰 *AI-дайджест недели*\n\n"
        for a in articles[:5]:
            digest += f"• *{a['title']}*\n  [{a['source']}]({a['link']})\n\n"
        digest += "Хорошей недели! 🤖"

    return f"📰 *AI-новости недели — что попробовать прямо сейчас*\n\n{digest}"
