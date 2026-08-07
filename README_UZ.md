# Birja Public Monitor

Bu variant Telegram akkauntiga kirmasdan quyidagi ochiq kanallarni kuzatadi:

- `@CorpInfo`
- `@kapdepo`
- `@napp_uz`

Yangi post matni, fayl nomi, kalit so'zlar, kompaniya nomi va birja kodi
tekshiriladi. Mos xabar yoki biriktirilgan hujjat topilsa, shaxsiy Telegram
botingiz sizga bildirishnoma yuboradi.

Gemini AI yangi postlarning mazmuni va ochiq sahifadan yuklab olish mumkin
bo‘lgan rasm/PDFni tahlil qiladi. Har kuni Toshkent vaqti bilan soat 09:00
atrofida oxirgi 3 kunlik umumiy AI hisoboti yuboriladi.

## Eng oson tekin joylashtirish: GitHub Actions

GitHub varianti kanallarni taxminan har 5 daqiqada bir marta tekshiradi. Kod
ochiq (`Public`) repozitoriyda turadi, lekin `BOT_TOKEN` va `ALERT_CHAT_ID`
GitHub Secrets ichida yashirin saqlanadi. `.env` faylini GitHub'ga yuklamang.

### 1. GitHub repozitoriy yarating

1. GitHub'da `New repository` ni bosing.
2. Nomi: `birja-public-monitor`.
3. `Public` ni tanlang va repozitoriyni yarating.
4. Ushbu papkaning ichidagi barcha fayllarni repozitoriyga yuklang. Yashirin
   `.github` papkasi ham albatta yuklanishi kerak.

### 2. Bot ma'lumotlarini Secrets'ga kiriting

Repozitoriy ichida:

`Settings → Secrets and variables → Actions → New repository secret`

Quyidagi uchta secret yarating:

- `BOT_TOKEN` — BotFather bergan token.
- `ALERT_CHAT_ID` — bot xabar yuboradigan shaxsiy chat ID.
- `GEMINI_API_KEY` — Google AI Studio bergan API kalit.

Tokenni hech qachon kod, `.env`, rasm yoki GitHub postiga ochiq yozmang.

### 3. Actions'ni ishga tushiring

1. `Actions` bo'limiga o'ting.
2. `Birja Telegram monitor` workflow'ini oching.
3. `Run workflow` tugmasini bosing.
4. Birinchi ish tugagach, bot “monitor ishga tushdi” xabarini yuboradi.

Keyingi tekshiruvlar avtomatik bajariladi. GitHub Actions yozish huquqi haqida
xato bersa: `Settings → Actions → General → Workflow permissions` ichidan
`Read and write permissions` ni tanlab saqlang.

`Birja 3 kunlik AI hisoboti` workflow’ini `Run workflow` orqali bir marta
qo‘lda ishga tushirib tekshirish mumkin. Keyin u har kuni avtomatik ishlaydi.

### 4. Keyin o'zgartirish kiritish

GitHub ichida quyidagi faylni oching, qalam belgisini bosing, qiymatni
o'zgartiring va `Commit changes` ni bosing:

- `config/keywords.txt` — kalit so'zlar;
- `config/companies.txt` — kompaniya nomi va birja kodlari;
- `config/channels.txt` — kuzatiladigan ochiq kanallar.

O'zgarish keyingi 5 daqiqalik tekshiruvdan boshlab ishlaydi. Monitor o'qigan
oxirgi post raqamlari `data/state.json` fayliga avtomatik commit qilinadi.

> GitHub Actions 45 soniyalik uzluksiz server emas. Bepul scheduled workflow
> uchun eng kichik interval 5 daqiqa va ba'zan GitHub yuklamasi sabab biroz
> kechikishi mumkin.

## Kompyuterda ishlatish (ixtiyoriy)

### 1. Fayllarni joylashtirish

ZIP ichidagi `birja-public-monitor` papkasini Desktop'ga oching.

```powershell
cd "$env:USERPROFILE\Desktop\birja-public-monitor"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. Bot sozlamalarini ko'chirish

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

### 3. Uchala kanalni sinash

```powershell
python public_monitor.py --test
```

Botga uchala kanalning oxirgi post raqami kelishi kerak.

### 4. Kalit so'z va kompaniyalarni sozlash

```powershell
notepad config\keywords.txt
notepad config\companies.txt
```

Har bir qiymat alohida qatorda yoziladi. `#` bilan boshlangan qatorlar izoh.

### 5. Monitorni ishga tushirish

```powershell
python public_monitor.py
```

Birinchi ishga tushganda monitor mavjud oxirgi postlarni boshlang'ich nuqta
sifatida saqlaydi va eski xabarlarni yubormaydi. Keyingi yangi postlar har
45 soniyada tekshiriladi. To'xtatish uchun `Ctrl+C` bosing.

## Hozirgi bosqich chegarasi

Ushbu birinchi versiya post matni, izohi va hujjat nomini tekshiradi. Rasm
ichidagi yozuv va ochiq yuklab olish manzili mavjud PDF Gemini orqali tahlil
qilinadi. Ochiq Telegram sahifasida ayrim katta fayllarning to‘g‘ridan-to‘g‘ri
yuklash manzili ko‘rinmasligi mumkin; bunday holatda AI post matni va fayl nomini
tahlil qiladi, bot esa asl post havolasini yuboradi.
