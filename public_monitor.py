from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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


def find_matches(text: str, keywords: list[str], companies: list[str]) -> MatchResult:
    folded = text.casefold()
    matched_keywords = tuple(item for item in keywords if item.casefold() in folded)
    matched_companies = tuple(item for item in companies if item.casefold() in folded)
    return MatchResult(matched_keywords, matched_companies)


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


async def send_bot_message(
    http: httpx.AsyncClient,
    bot_token: str,
    chat_id: str,
    text: str,
) -> None:
    response = await http.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
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
) -> None:
    lines = [
        "🚨 <b>Muhim ochiq kanal xabari</b>",
        f"📢 Kanal: <b>@{html.escape(post.channel)}</b>",
    ]
    if result.companies:
        lines.append("🏢 Kompaniya/kod: " + html.escape(", ".join(result.companies)))
    if result.keywords:
        lines.append("🔎 Kalit so‘z: " + html.escape(", ".join(result.keywords)))
    if document_only:
        lines.append("📄 Hujjat biriktirilgan post")
    if post.file_names:
        lines.append("📎 Fayl: " + html.escape(", ".join(post.file_names)))

    preview = post.text.strip()
    if len(preview) > 2400:
        preview = preview[:2400].rstrip() + "…"
    if preview:
        lines.append("\n" + html.escape(preview))
    lines.append(f'\n<a href="{html.escape(post.post_url)}">Asl postni ochish</a>')

    await send_bot_message(http, bot_token, chat_id, "\n".join(lines))


async def fetch_posts(http: httpx.AsyncClient, channel: str) -> list[PublicPost]:
    response = await http.get(f"https://t.me/s/{channel}")
    response.raise_for_status()
    posts = parse_public_page(channel, response.text)
    if not posts:
        raise RuntimeError(f"@{channel} sahifasidan postlar topilmadi.")
    return posts


def log(message: str) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {message}")


async def check_channels(test_mode: bool = False) -> None:
    settings = load_bot_settings(require_chat_id=True)
    channels = [normalize_channel(value) for value in read_config_lines("channels.txt")]
    channels = [value for value in channels if value]
    keywords = read_config_lines("keywords.txt")
    companies = read_config_lines("companies.txt")
    if not channels:
        raise RuntimeError("config/channels.txt fayli bo'sh.")

    state = load_state()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "uz,ru;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    }
    timeout = httpx.Timeout(30)

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
            await send_bot_message(
                http,
                str(settings["bot_token"]),
                str(settings["alert_chat_id"]),
                "<b>Ochiq kanal testi</b>\n" + "\n".join(summaries),
            )
            print("✅ Uchala kanal o'qildi va botga test natijasi yuborildi.")
            return

        first_run = not bool(state)
        while True:
            for channel in channels:
                try:
                    posts = await fetch_posts(http, channel)
                    newest_id = posts[-1].message_id
                    previous_id = state.get(channel)

                    if previous_id is None:
                        state[channel] = newest_id
                        save_state(state)
                        log(f"@{channel}: boshlang'ich post #{newest_id}")
                        continue

                    for post in (item for item in posts if item.message_id > previous_id):
                        result = find_matches(post.searchable_text, keywords, companies)
                        document_only = bool(post.document_links) and bool(
                            settings["alert_all_documents"]
                        )
                        if result.matched or document_only:
                            await send_post_alert(
                                http,
                                str(settings["bot_token"]),
                                str(settings["alert_chat_id"]),
                                post,
                                result,
                                document_only and not result.matched,
                            )
                            log(f"@{channel} #{post.message_id}: bildirishnoma yuborildi")
                        else:
                            log(f"@{channel} #{post.message_id}: mos kelmadi")

                    state[channel] = max(previous_id, newest_id)
                    save_state(state)
                except Exception as exc:
                    log(f"@{channel}: xatolik — {exc}")

            if first_run:
                await send_bot_message(
                    http,
                    str(settings["bot_token"]),
                    str(settings["alert_chat_id"]),
                    "✅ <b>Birja Public Monitor ishga tushdi</b>\n"
                    "@CorpInfo, @kapdepo va @napp_uz kanallari kuzatilmoqda.",
                )
                first_run = False

            await asyncio.sleep(int(settings["poll_seconds"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ochiq Telegram kanallari monitori")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Kanallar ochilishini tekshiradi va botga test xabari yuboradi.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    try:
        asyncio.run(check_channels(test_mode=arguments.test))
    except KeyboardInterrupt:
        print("\nMonitor to'xtatildi.")
    except Exception as exc:
        print(f"\n❌ Xatolik: {exc}")
