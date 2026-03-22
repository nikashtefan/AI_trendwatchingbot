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

    prompt = f"""Ты — редактор еженедельного AI-дайджеста. Из списка статей ниже выбери ТОП-5 самых важных и интересных новостей за неделю.

Критерии отбора:
- Крупные релизы моделей, продуктов, API
- Важные исследования и прорывы
- Значимые бизнес-решения (сделки, партнёрства, регуляция)
- Практические инструменты и обновления

Для каждой новости напиши:
1. Заголовок на русском (краткий, цепляющий)
2. Краткое описание на русском (2-3 предложения, суть + почему это важно)
3. Ссылка на источник

Формат ответа — строго такой:

**1. Заголовок**
Описание описание описание.
🔗 ссылка

**2. Заголовок**
Описание описание описание.
🔗 ссылка

...и так далее до 5.

В конце добавь одну строку:
"Хорошей недели! 🤖"

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
                            "content": "Ты — AI-редактор, который пишет краткие и информативные дайджесты на русском языке.",
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

    return f"📰 *AI-дайджест недели*\n\n{digest}"
