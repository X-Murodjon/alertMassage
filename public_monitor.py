from __future__ import annotations

import argparse
import asyncio
import base64
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from common import (
    DATA_DIR,
    STATE_FILE,
    load_bot_settings,
    normalize_channel,
    read_config_lines,
)


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)
IMAGE_URL_PATTERN = re.compile(r"background-image\s*:\s*url\(['\"]?([^'\")]+)")
APOSTROPHE_PATTERN = re.compile(r"['’‘ʻ`]")
WHITESPACE_PATTERN = re.compile(r"\s+")
MAX_MEDIA_BYTES = 15 * 1024 * 1024
MAX_DIGEST_POSTS = 150


@dataclass(frozen=True)
class PublicPost:
    channel: str
    message_id: int
    text: str
    file_names: tuple[str, ...]
    document_links: tuple[str, ...]
    image_links: tuple[str, ...]
    published_at: str | None

    @property
    def post_url(self) -> str:
        return f"https://t.me/{self.channel}/{self.message_id}"

    @property
    def searchable_text(self) -> str:
        return "\n".join([self.text, *self.file_names]).strip()


@dataclass(frozen=True)
class MatchResult:
    keywords: tuple[str, ...]
    companies: tuple[str, ...]

    @property
    def matched(self) -> bool:
        return bool(self.keywords or self.companies)


@dataclass(frozen=True)
class AiAnalysis:
    relevant: bool
    importance: int
    sentiment: str
    company_or_code: str
    event: str
    summary: str
    market_impact: str
    risks: str


def parse_public_page(channel: str, page_html: str) -> list[PublicPost]:
    soup = BeautifulSoup(page_html, "html.parser")
    posts: list[PublicPost] = []

    for message in soup.select(".tgme_widget_message[data-post]"):
        data_post = str(message.get("data-post", ""))
        try:
            _, raw_id = data_post.rsplit("/", 1)
            message_id = int(raw_id)
        except (ValueError, TypeError):
            continue

        text_parts: list[str] = []
        for selector in (".tgme_widget_message_text", ".tgme_widget_message_caption"):
            for node in message.select(selector):
                value = node.get_text(" ", strip=True)
                if value and value not in text_parts:
                    text_parts.append(value)

        file_names: list[str] = []
        for selector in (
            ".tgme_widget_message_document_title",
            ".tgme_widget_message_document_extra",
        ):
            for node in message.select(selector):
                value = node.get_text(" ", strip=True)
                if value and value not in file_names:
                    file_names.append(value)

        document_links: list[str] = []
        for node in message.select("a.tgme_widget_message_document_wrap[href]"):
            href = urljoin("https://t.me", str(node.get("href", "")))
            if href and href not in document_links:
                document_links.append(href)

        image_links: list[str] = []
        for node in message.select(".tgme_widget_message_photo_wrap"):
            style = str(node.get("style", ""))
            match = IMAGE_URL_PATTERN.search(style)
            if match and match.group(1) not in image_links:
                image_links.append(match.group(1))

        time_node = message.select_one("time[datetime]")
        published_at = str(time_node.get("datetime")) if time_node else None

        posts.append(
            PublicPost(
                channel=channel,
                message_id=message_id,
                text="\n".join(text_parts),
                file_names=tuple(file_names),
                document_links=tuple(document_links),
                image_links=tuple(image_links),
                published_at=published_at,
            )
        )

    return sorted(posts, key=lambda item: item.message_id)


def normalize_search_text(value: str) -> str:
    normalized = value.casefold()
    normalized = APOSTROPHE_PATTERN.sub("'", normalized)
    return WHITESPACE_PATTERN.sub(" ", normalized).strip()


def find_matches(text: str, keywords: list[str], companies: list[str]) -> MatchResult:
    normalized_text = normalize_search_text(text)
    matched_keywords = tuple(
        item for item in keywords if normalize_search_text(item) in normalized_text
    )
    matched_companies = tuple(
        item for item in companies if normalize_search_text(item) in normalized_text
    )
    return MatchResult(matched_keywords, matched_companies)


def parse_ai_analysis(raw_text: str) -> AiAnalysis:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    data = json.loads(cleaned)
    importance = max(0, min(100, int(data.get("importance", 0))))
    relevant_value = data.get("relevant", False)
    if isinstance(relevant_value, str):
        relevant = relevant_value.strip().casefold() in {"true", "1", "yes", "ha"}
    else:
        relevant = bool(relevant_value)

    def value(name: str, default: str = "Ko‘rsatilmagan") -> str:
        result = str(data.get(name, "")).strip()
        return result or default

    return AiAnalysis(
        relevant=relevant,
        importance=importance,
        sentiment=value("sentiment", "Neytral"),
        company_or_code=value("company_or_code"),
        event=value("event"),
        summary=value("summary"),
        market_impact=value("market_impact"),
        risks=value("risks"),
    )


def load_state() -> dict[str, int]:
    if not STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {str(key): int(value) for key, value in raw.items()}
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, int]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    temporary = Path(str(STATE_FILE) + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(STATE_FILE)


def published_datetime(post: PublicPost) -> datetime | None:
    if not post.published_at:
        return None
    try:
        parsed = datetime.fromisoformat(post.published_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


async def send_bot_message(
    http: httpx.AsyncClient,
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None = "HTML",
) -> None:
    data: dict[str, str | bool] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        data["parse_mode"] = parse_mode
    response = await http.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=data,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Bot bildirishnomani yubora olmadi.")


async def send_post_alert(
    http: httpx.AsyncClient,
    bot_token: str,
    chat_id: str,
    post: PublicPost,
    result: MatchResult,
    document_only: bool,
    analysis: AiAnalysis | None,
) -> None:
    def shortened(value: str, limit: int) -> str:
        return value if len(value) <= limit else value[:limit].rstrip() + "…"

    lines = [
        "🚨 <b>Muhim ochiq kanal xabari</b>",
        f"📢 Kanal: <b>@{html.escape(post.channel)}</b>",
    ]
    if analysis:
        lines.extend(
            [
                f"⭐ Muhimlik: <b>{analysis.importance}/100</b>",
                f"📈 Ta’siri: <b>{html.escape(analysis.sentiment)}</b>",
                f"🏢 Kompaniya/kod: {html.escape(analysis.company_or_code)}",
                f"📰 Voqea: {html.escape(analysis.event)}",
                "\n<b>AI xulosasi:</b>\n"
                + html.escape(shortened(analysis.summary, 750)),
                "\n<b>Bozorga ehtimoliy ta’siri:</b>\n"
                + html.escape(shortened(analysis.market_impact, 550)),
                "\n<b>Xavf va tekshiriladigan jihatlar:</b>\n"
                + html.escape(shortened(analysis.risks, 550)),
            ]
        )
    else:
        if result.companies:
            lines.append("🏢 Kompaniya/kod: " + html.escape(", ".join(result.companies)))
        if result.keywords:
            lines.append("🔎 Kalit so‘z: " + html.escape(", ".join(result.keywords)))
        preview = post.text.strip()
        if len(preview) > 1400:
            preview = preview[:1400].rstrip() + "…"
        if preview:
            lines.append("\n" + html.escape(preview))

    if document_only:
        lines.append("📄 Hujjat biriktirilgan post")
    if post.file_names:
        lines.append("📎 Fayl: " + html.escape(", ".join(post.file_names)))
    lines.append(f'\n<a href="{html.escape(post.post_url)}">Asl postni ochish</a>')
    lines.append("\n<i>AI xulosasi investitsiya tavsiyasi emas.</i>")

    await send_bot_message(http, bot_token, chat_id, "\n".join(lines))


async def fetch_posts_page(
    http: httpx.AsyncClient,
    channel: str,
    before_id: int | None = None,
) -> list[PublicPost]:
    params = {"before": str(before_id)} if before_id is not None else None
    response = await http.get(f"https://t.me/s/{channel}", params=params)
    response.raise_for_status()
    posts = parse_public_page(channel, response.text)
    if not posts:
        raise RuntimeError(f"@{channel} sahifasidan postlar topilmadi.")
    return posts


async def fetch_posts(http: httpx.AsyncClient, channel: str) -> list[PublicPost]:
    return await fetch_posts_page(http, channel)


async def fetch_recent_posts(
    http: httpx.AsyncClient,
    channel: str,
    since: datetime,
) -> list[PublicPost]:
    collected: dict[int, PublicPost] = {}
    before_id: int | None = None
    previous_oldest: int | None = None

    for _ in range(20):
        posts = await fetch_posts_page(http, channel, before_id)
        for post in posts:
            when = published_datetime(post)
            if when is not None and when >= since:
                collected[post.message_id] = post

        dated = [published_datetime(post) for post in posts]
        dated = [item for item in dated if item is not None]
        if dated and min(dated) < since:
            break

        oldest_id = min(post.message_id for post in posts)
        if oldest_id == previous_oldest:
            break
        previous_oldest = oldest_id
        before_id = oldest_id

    return sorted(collected.values(), key=lambda item: item.message_id)


def extract_gemini_text(payload: dict[str, Any]) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
        text_parts = [str(part.get("text", "")) for part in parts if part.get("text")]
        result = "\n".join(text_parts).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini javobini o‘qib bo‘lmadi.") from exc
    if not result:
        raise RuntimeError("Gemini bo‘sh javob qaytardi.")
    return result


async def gemini_generate(
    http: httpx.AsyncClient,
    api_key: str,
    model: str,
    prompt: str,
    media_parts: list[dict[str, Any]] | None = None,
    json_output: bool = False,
    max_output_tokens: int = 1400,
) -> str:
    parts: list[dict[str, Any]] = [*(media_parts or []), {"text": prompt}]
    generation_config: dict[str, Any] = {
        "temperature": 0.2,
        "maxOutputTokens": max_output_tokens,
    }
    if json_output:
        generation_config["responseMimeType"] = "application/json"
    response = await http.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        },
    )
    response.raise_for_status()
    return extract_gemini_text(response.json())


async def load_post_media(
    http: httpx.AsyncClient,
    post: PublicPost,
) -> list[dict[str, Any]]:
    candidates = [*post.image_links, *post.document_links]
    for link in candidates:
        try:
            response = await http.get(link)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            if content_type not in {
                "image/jpeg",
                "image/png",
                "image/webp",
                "image/heic",
                "image/heif",
                "application/pdf",
            }:
                continue
            if not response.content or len(response.content) > MAX_MEDIA_BYTES:
                continue
            return [
                {
                    "inline_data": {
                        "mime_type": content_type,
                        "data": base64.b64encode(response.content).decode("ascii"),
                    }
                }
            ]
        except Exception:
            continue
    return []


async def analyze_post(
    http: httpx.AsyncClient,
    post: PublicPost,
    result: MatchResult,
    api_key: str,
    model: str,
) -> AiAnalysis:
    media_parts = await load_post_media(http, post)
    prompt = f"""
Siz O‘zbekiston kapital bozori bo‘yicha ehtiyotkor tahlilchisiz.
Quyidagi ochiq Telegram postini tahlil qiling. Yangilik kompaniya, qimmatli
qog‘oz, dividend, korporativ harakat, litsenziya, tartibga solish, moliyaviy
hisobot yoki investor qaroriga ta’sir qilsa relevant=true bo‘lsin.
Taxminni fakt sifatida ko‘rsatmang. Faqat o‘zbek tilida yozing.

Kanal: @{post.channel}
Sana: {post.published_at or "ko‘rsatilmagan"}
Post: {post.text or "matn yo‘q"}
Fayllar: {", ".join(post.file_names) or "yo‘q"}
Topilgan kalit so‘zlar: {", ".join(result.keywords) or "yo‘q"}
Topilgan kompaniyalar/kodlar: {", ".join(result.companies) or "yo‘q"}
Havola: {post.post_url}

Faqat quyidagi JSON formatida javob bering:
{{
  "relevant": true,
  "importance": 0,
  "sentiment": "Ijobiy, Salbiy yoki Neytral",
  "company_or_code": "kompaniya yoki birja kodi",
  "event": "qisqa voqea nomi",
  "summary": "2-4 gaplik aniq xulosa",
  "market_impact": "bozorga ehtimoliy ta’sir",
  "risks": "xavf va alohida tekshiriladigan jihatlar"
}}
""".strip()
    raw = await gemini_generate(
        http,
        api_key,
        model,
        prompt,
        media_parts=media_parts,
        json_output=True,
        max_output_tokens=900,
    )
    return parse_ai_analysis(raw)


async def send_digest(
    http: httpx.AsyncClient,
    bot_token: str,
    chat_id: str,
    channels: list[str],
    days: int,
    api_key: str,
    model: str,
) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts: list[PublicPost] = []
    for channel in channels:
        posts = await fetch_recent_posts(http, channel, since)
        all_posts.extend(posts)
        log(f"@{channel}: {days} kun ichida {len(posts)} ta post")

    all_posts.sort(key=lambda post: published_datetime(post) or since)
    if not all_posts:
        await send_bot_message(
            http,
            bot_token,
            chat_id,
            f"📊 Oxirgi {days} kunda kuzatilgan kanallarda post topilmadi.",
            parse_mode=None,
        )
        return

    selected = all_posts[-MAX_DIGEST_POSTS:]
    entries: list[str] = []
    for post in selected:
        text = post.text.strip().replace("\n", " ")
        if len(text) > 700:
            text = text[:700].rstrip() + "…"
        entries.append(
            "\n".join(
                [
                    f"KANAL: @{post.channel}",
                    f"SANA: {post.published_at or 'ko‘rsatilmagan'}",
                    f"MATN: {text or 'matn yo‘q'}",
                    f"FAYL: {', '.join(post.file_names) or 'yo‘q'}",
                    f"HAVOLA: {post.post_url}",
                ]
            )
        )

    prompt = f"""
Siz O‘zbekiston kapital bozori bo‘yicha ehtiyotkor tahlilchisiz. Quyida
@CorpInfo, @kapdepo va @napp_uz kanallarining oxirgi {days} kunlik postlari bor.

O‘zbek tilida, 3500 belgidan oshmaydigan umumiy hisobot yozing:
1. Eng muhim 5 ta voqea va har birining manba havolasi.
2. Qaysi kompaniya yoki birja kodlariga e’tibor kerak.
3. Ijobiy, salbiy va neytral tendensiyalar.
4. Investor alohida tekshirishi kerak bo‘lgan xavflar.
5. Juda qisqa yakun.

Taxminlarni fakt sifatida yozmang va oxirida “AI tahlili investitsiya tavsiyasi
emas” deb ko‘rsating.

POSTLAR:
{"\n\n---\n\n".join(entries)}
""".strip()
    report = await gemini_generate(
        http,
        api_key,
        model,
        prompt,
        max_output_tokens=1500,
    )
    message = f"📊 OXIRGI {days} KUNLIK AI HISOBOT\n\n{report}"
    if len(message) > 4000:
        message = message[:3950].rstrip() + "\n…"
    await send_bot_message(http, bot_token, chat_id, message, parse_mode=None)


def log(message: str) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}")


async def check_channels(
    test_mode: bool = False,
    once_mode: bool = False,
    digest_days: int | None = None,
) -> None:
    settings = load_bot_settings(require_chat_id=True)
    channels = [normalize_channel(value) for value in read_config_lines("channels.txt")]
    channels = [value for value in channels if value]
    keywords = read_config_lines("keywords.txt")
    companies = read_config_lines("companies.txt")
    if not channels:
        raise RuntimeError("config/channels.txt fayli bo‘sh.")

    ai_enabled = bool(settings["ai_enabled"])
    api_key = str(settings["gemini_api_key"])
    model = str(settings["gemini_model"])
    if ai_enabled and not api_key:
        raise RuntimeError("GEMINI_API_KEY kiritilmagan.")

    state = load_state()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "uz,ru;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    }
    timeout = httpx.Timeout(60)

    async with httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
    ) as http:
        if test_mode:
            summaries: list[str] = []
            for channel in channels:
                posts = await fetch_posts(http, channel)
                latest = posts[-1]
                summaries.append(
                    f"✅ @{html.escape(channel)}: oxirgi post #{latest.message_id}"
                )
            summaries.append(f"✅ Gemini AI: {'yoqilgan' if ai_enabled else 'o‘chirilgan'}")
            await send_bot_message(
                http,
                str(settings["bot_token"]),
                str(settings["alert_chat_id"]),
                "<b>Ochiq kanal testi</b>\n" + "\n".join(summaries),
            )
            print("✅ Kanallar o‘qildi va botga test natijasi yuborildi.")
            return

        if digest_days is not None:
            await send_digest(
                http,
                str(settings["bot_token"]),
                str(settings["alert_chat_id"]),
                channels,
                digest_days,
                api_key,
                model,
            )
            log("3 kunlik AI hisoboti yuborildi.")
            return

        first_run = not bool(state)
        while True:
            cycle_errors: list[str] = []
            for channel in channels:
                try:
                    posts = await fetch_posts(http, channel)
                    newest_id = posts[-1].message_id
                    previous_id = state.get(channel)

                    if previous_id is None:
                        state[channel] = newest_id
                        save_state(state)
                        log(f"@{channel}: boshlang‘ich post #{newest_id}")
                        continue

                    for post in (item for item in posts if item.message_id > previous_id):
                        result = find_matches(post.searchable_text, keywords, companies)
                        document_only = bool(post.document_links) and bool(
                            settings["alert_all_documents"]
                        )
                        analysis: AiAnalysis | None = None
                        if ai_enabled:
                            try:
                                analysis = await analyze_post(
                                    http, post, result, api_key, model
                                )
                            except Exception as exc:
                                log(f"@{channel} #{post.message_id}: AI xatosi — {exc}")

                        if (analysis and analysis.relevant) or result.matched or document_only:
                            await send_post_alert(
                                http,
                                str(settings["bot_token"]),
                                str(settings["alert_chat_id"]),
                                post,
                                result,
                                document_only and not result.matched,
                                analysis,
                            )
                            log(f"@{channel} #{post.message_id}: bildirishnoma yuborildi")
                        else:
                            log(f"@{channel} #{post.message_id}: muhim emas")

                    state[channel] = max(previous_id, newest_id)
                    save_state(state)
                except Exception as exc:
                    log(f"@{channel}: xatolik — {exc}")
                    cycle_errors.append(f"@{channel}: {exc}")

            if first_run and not cycle_errors:
                await send_bot_message(
                    http,
                    str(settings["bot_token"]),
                    str(settings["alert_chat_id"]),
                    "✅ <b>Birja Public Monitor ishga tushdi</b>\n"
                    "@CorpInfo, @kapdepo va @napp_uz kanallari kuzatilmoqda.\n"
                    "🤖 Gemini AI tahlili yoqilgan.",
                )
                first_run = False

            if once_mode:
                if cycle_errors:
                    raise RuntimeError(
                        "Ayrim kanallar tekshirilmadi: " + " | ".join(cycle_errors)
                    )
                log("Bir martalik tekshiruv tugadi.")
                return

            await asyncio.sleep(int(settings["poll_seconds"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ochiq Telegram kanallari monitori")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Kanallar ochilishini tekshiradi va botga test xabari yuboradi.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Kanallarni bir marta tekshiradi va dasturni yopadi.",
    )
    parser.add_argument(
        "--digest-days",
        type=int,
        metavar="N",
        help="Oxirgi N kunlik AI hisobotini botga yuboradi.",
    )
    arguments = parser.parse_args()
    if arguments.digest_days is not None and not 1 <= arguments.digest_days <= 14:
        parser.error("--digest-days 1 dan 14 gacha bo‘lishi kerak.")
    return arguments


if __name__ == "__main__":
    arguments = parse_args()
    try:
        asyncio.run(
            check_channels(
                test_mode=arguments.test,
                once_mode=arguments.once,
                digest_days=arguments.digest_days,
            )
        )
    except KeyboardInterrupt:
        print("\nMonitor to‘xtatildi.")
    except Exception as exc:
        print(f"\n❌ Xatolik: {exc}")
        raise SystemExit(1)
