from __future__ import annotations

import asyncio

import httpx
from dotenv import set_key

from common import ENV_FILE, load_bot_settings


async def main() -> None:
    settings = load_bot_settings(require_chat_id=False)
    token = str(settings["bot_token"])

    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get(f"https://api.telegram.org/bot{token}/getUpdates")
        response.raise_for_status()
        payload = response.json()

        if not payload.get("ok"):
            raise RuntimeError("Bot token tekshiruvidan o'tmadi.")

        chat_id: str | None = None
        for update in reversed(payload.get("result", [])):
            message = update.get("message") or update.get("edited_message")
            if not message:
                continue
            chat = message.get("chat", {})
            if chat.get("type") == "private" and chat.get("id"):
                chat_id = str(chat["id"])
                break

        if not chat_id:
            raise RuntimeError(
                "Bot bilan shaxsiy chat topilmadi. Botga /start yuboring va "
                "python bot_setup.py ni qayta bajaring."
            )

        set_key(str(ENV_FILE), "ALERT_CHAT_ID", chat_id)
        test = await http.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": "✅ Ochiq kanallar monitori botga muvaffaqiyatli ulandi.",
            },
        )
        test.raise_for_status()
        if not test.json().get("ok"):
            raise RuntimeError("Bot sinov xabarini yubora olmadi.")

    print("✅ ALERT_CHAT_ID saqlandi va bot sinov xabarini yubordi.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nJarayon to'xtatildi.")
    except Exception as exc:
        print(f"\n❌ Xatolik: {exc}")
