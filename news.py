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


async def fetch_og_image(url: str) -> str:
    """Fetch og:image from a webpage URL."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            # Search for og:image meta tag
            match = re.search(
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                resp.text,
            )
            if not match:
                # Try reverse order (content before property)
                match = re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
                    resp.text,
                )
            if match:
                return match.group(1)
    except Exception as e:
        print(f"[OG] Error fetching {url}: {e}")
    return ""


def fetch_articles(days: int = 7) -> list[dict]:
    """Fetch articles from all RSS feeds published in the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    articles = []

    for source_name, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
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
1. Новые AI-инструменты и сервисы, которые можно сразу попробовать
2. Обновления популярных сервисов (ChatGPT, Claude, Gemini, Midjourney и т.д.)
3. Новости о том, как компании используют AI — вдохновляющие кейсы
4. Важные события в мире AI, которые влияют на всех

❌ НЕ бери:
- Чисто технические статьи про архитектуру моделей, бенчмарки, код
- Научные исследования без практического применения
- Новости только для разработчиков (API, SDK, фреймворки)

✍️ Стиль написания:
- Пиши простым, живым языком — как будто рассказываешь другу
- Никаких технических терминов (если нужен термин — объясни в скобках)
- В каждой новости скажи: что это значит для обычного человека

⚠️ ОТВЕТ СТРОГО В ФОРМАТЕ JSON (никакого другого текста, только JSON):
{{
  "news": [
    {{
      "emoji": "🔥",
      "title": "Заголовок на русском",
      "text": "Описание простым языком. Что случилось и почему это полезно. Как попробовать.",
      "link": "https://..."
    }},
    {{
      "emoji": "✨",
      "title": "...",
      "text": "...",
      "link": "..."
    }}
  ],
  "outro": "Было полезно? Перешли другу, который тоже хочет быть в теме! 💬"
}}

Используй разные эмодзи для каждой новости: 🔥 ✨ 🚀 💡 ⚡

Вот список статей за неделю ({len(articles)} шт.):

{articles_text}"""

    return prompt


async def generate_digest(articles: list[dict]) -> list[dict] | None:
    """Call ProxyAPI to generate digest. Returns list of news items."""
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
                            "content": "Ты — дружелюбный AI-редактор. Отвечай ТОЛЬКО валидным JSON, без markdown-обёрток.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2000,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # Strip markdown code block if present
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)

            parsed = json.loads(content)
            return parsed
    except Exception as e:
        print(f"[AI] Error generating digest: {e}")
        return None


async def get_weekly_digest() -> list[dict]:
    """Main function: fetch articles → generate digest with images.

    Returns list of dicts: [{"emoji", "title", "text", "link", "image_url"}, ...]
    If AI fails, returns fallback list.
    """
    print("[Digest] Fetching articles...")
    articles = fetch_articles(days=7)
    print(f"[Digest] Found {len(articles)} articles")

    if not articles:
        return [{"emoji": "🤷", "title": "Нет новостей", "text": "На этой неделе не удалось собрать новости. Попробуем на следующей!", "link": "", "image_url": ""}]

    result = await generate_digest(articles)

    if result and "news" in result:
        news_items = result["news"][:5]
    else:
        # Fallback without AI
        news_items = []
        emojis = ["🔥", "✨", "🚀", "💡", "⚡"]
        for i, a in enumerate(articles[:5]):
            news_items.append({
                "emoji": emojis[i],
                "title": a["title"],
                "text": a["summary"][:200] if a["summary"] else "",
                "link": a["link"],
            })

    # Fetch og:image for each news item
    for item in news_items:
        link = item.get("link", "")
        if link:
            image_url = await fetch_og_image(link)
            item["image_url"] = image_url
            print(f"[OG] {link[:50]} -> {'found' if image_url else 'no image'}")
        else:
            item["image_url"] = ""

    # Add outro
    outro = "Было полезно? Перешли другу, который тоже хочет быть в теме! 💬"
    if result and "outro" in result:
        outro = result["outro"]

    # Append outro as last item
    news_items.append({"outro": outro})

    return news_items
