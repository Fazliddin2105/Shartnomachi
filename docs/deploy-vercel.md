# Vercel'ga joylash (hakaton demosi)

Demo: https://lexlab-platform.vercel.app — API, web ilova va SDK bitta Python funksiyada (`api/index.py`).

## Tarkib

| Fayl | Vazifasi |
|---|---|
| `api/index.py` | Vercel kirish nuqtasi: `services/api` ni import qiladi, muhitni sozlaydi |
| `vercel.json` | barcha so'rovlar `api/index` ga; `fra1` (Frankfurt) hududi; 60 s limit |
| `requirements.txt` (ildizda) | faqat ishlash uchun kerakli kutubxonalar (web3/boto3/redis yo'q) |
| `.vercelignore` | `.venv`, testlar, `.env`, `apps/web/server.py` va boshqalar yuklanmaydi |
| `scripts/vercel_setup.py` | loyihani yaratish/ulash + muhit o'zgaruvchilari (qiymatlar chiqarilmaydi) |
| `scripts/vercel_migrate.py` | Neon bazasida migratsiya + seed (yurist demo akkaunti) |
| `scripts/build_vercel_db.py` | `services/api/.env.vercel` (JWT/shifrlash kaliti) va zaxira SQLite snapshot |

## Baza va fayllar

- **Baza:** Neon Postgres (Vercel Marketplace, bepul `free_v3`, `fra1`). Vercel `DATABASE_URL_UNPOOLED` ni beradi, `Settings` uni `postgresql+asyncpg://…?ssl=require` ga o'tkazadi. Har bir server nusxasi 2+3 ulanish ishlatadi.
- **Fayllar** `/tmp` da saqlanadi (vaqtinchalik). Yo'qolsa, imzolangan DOCX shartnomaning saqlangan matnidan qayta yasaladi. Prod uchun `STORAGE_BACKEND=s3`.
- **Fon vazifalari** (skaner, AI) `INLINE_JOBS=true` bilan so'rov ichida bajariladi. Eslatma yuboruvchi sikl (`SCHEDULER_MODE=off`) serverlessda ishlamaydi; prod'da alohida worker kerak.

## Demo xavfsizligi (faqat test ma'lumotlari!)

- `ENVIRONMENT=dev`, kirish kodi **111111** ochiq — havolani bilgan har kim istalgan raqam bilan kiradi.
- Admin, muharrir va moderator demo akkauntlari **yaratilmagan**. Faqat yurist bor: `+998900000004`.
- AI DeepSeek orqali ishlaydi, kalit Vercel'da shifrlangan holda saqlanadi. Shaxsiy ma'lumotlar yuborishdan oldin maskalanadi.
- Shaxsiy ma'lumotlarni lokalizatsiya qilish talabi sababli haqiqiy foydalanuvchilar uchun server O'zbekistonda bo'lishi kerak. Hakatondan keyin ko'chiring: Postgres + S3 + lokal LLM (Qwen) + SMS shlyuz + `ENVIRONMENT=prod`.

## Qayta deploy

```powershell
# kod o'zgargach (dizayn papkasidan nusxa + deploy)
.\scripts\sync-frontend.ps1
npx vercel deploy --prod --yes --token <VERCEL_TOKEN>
# migratsiya qo'shilgan bo'lsa
services\api\.venv\Scripts\python scripts\vercel_migrate.py <token-fayli>
```
