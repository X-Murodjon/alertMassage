# Birja Public Monitor

Bu variant Telegram akkauntiga kirmasdan quyidagi ochiq kanallarni kuzatadi:

- `@CorpInfo`
- `@kapdepo`
- `@napp_uz`

Yangi post matni, fayl nomi, kalit so'zlar, kompaniya nomi va birja kodi
tekshiriladi. Mos xabar yoki biriktirilgan hujjat topilsa, shaxsiy Telegram
botingiz sizga bildirishnoma yuboradi.

## 1. Fayllarni joylashtirish

ZIP ichidagi `birja-public-monitor` papkasini Desktop'ga oching.

```powershell
cd "$env:USERPROFILE\Desktop\birja-public-monitor"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 2. Bot sozlamalarini ko'chirish

Oldingi loyiha `.env` faylida `BOT_TOKEN` va `ALERT_CHAT_ID` tayyor bo'lsa:

```powershell
Copy-Item "$env:USERPROFILE\Desktop\birja-monitor\.env" ".env"
```

Yoki yangi sozlama yarating:

```powershell
Copy-Item .env.example .env
notepad .env
```

`.env` fayliga faqat quyidagilar kerak:

```dotenv
BOT_TOKEN=BotFather_bergan_token
ALERT_CHAT_ID=bot_chat_id
POLL_SECONDS=45
ALERT_ALL_DOCUMENTS=true
```

`ALERT_CHAT_ID` bo'sh bo'lsa, botga `/start` yuboring va:

```powershell
python bot_setup.py
```

## 3. Uchala kanalni sinash

```powershell
python public_monitor.py --test
```

Botga uchala kanalning oxirgi post raqami kelishi kerak.

## 4. Kalit so'z va kompaniyalarni sozlash

```powershell
notepad config\keywords.txt
notepad config\companies.txt
```

Har bir qiymat alohida qatorda yoziladi. `#` bilan boshlangan qatorlar izoh.

## 5. Monitorni ishga tushirish

```powershell
python public_monitor.py
```

Birinchi ishga tushganda monitor mavjud oxirgi postlarni boshlang'ich nuqta
sifatida saqlaydi va eski xabarlarni yubormaydi. Keyingi yangi postlar har
45 soniyada tekshiriladi. To'xtatish uchun `Ctrl+C` bosing.

## Hozirgi bosqich chegarasi

Ushbu birinchi versiya post matni, izohi va hujjat nomini tekshiradi. Rasm
ichidagi yozuvlarni OCR orqali o'qish, PDF ichki matnini chiqarish va AI xulosasi
keyingi bosqichda qo'shiladi. Ochiq Telegram sahifasida ayrim katta fayllarning
to'g'ridan-to'g'ri yuklash manzili ko'rinmasligi mumkin; bunday holatda bot asl
post havolasini yuboradi.
