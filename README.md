# LexLab — Shartnoma platformasi

«Huquqiy xizmat platformasi — Dasturiy struktura» hujjati asosida qurilgan modulli monolit.
Platforma faqat **shartnoma** yo'nalishiga qaratilgan: «Shartnoma tuz», «Shartnomani tekshir» va ularni bog'lovchi
qatlamlar (tasdiqlash, majburiyat va eslatmalar, yurist arxivi). «Mening yo'riqnomam» moduli olib tashlangan.
Backend (`services/api`): 132 ta API operatsiyasi, 112 avtomatik test; web ilova — `apps/web`.
Hujjatlar xeshi Polygon blokcheyniga Merkle ildizi orqali qayd etiladi — [docs/blockchain.md](docs/blockchain.md).

```
lexlab-platform/
├── apps/web/                # web ilova (HTML/CSS/JS dizayn); backend uni http://localhost:8000/ da beradi
├── services/api/            # FastAPI backend (modulli monolit)
│   ├── app/
│   │   ├── core/            # config, xatoliklar, JWT, AES-256-GCM, RBAC, rate-limit, xavfsiz formula, kalendar
│   │   ├── db/              # SQLAlchemy 2 (async), shifrlangan ustun turlari, sessiya
│   │   ├── integrations/    # SMS (Eskiz), OneID, E-IMZO, Telegram
│   │   ├── ai/              # LLM (lokal Qwen / DeepSeek), PII maskalash, promptlar, shablon bilan solishtirish
│   │   ├── workers/         # ARQ worker, scheduler (har daqiqa), fon navbati
│   │   └── modules/
│   │       ├── auth/            # telefon+OTP, E-IMZO, OneID, TOTP 2FA, refresh-token rotatsiyasi
│   │       ├── users/           # profil, kompaniya va xodimlar, admin, yurist litsenziyasi
│   │       ├── calc/            # BHM, muddat (ish/taqvim kunlari), neustoyka, bayramlar kalendari
│   │       ├── contracts/       # «Shartnoma tuz»: savolnoma, generator (DOCX/PDF), versiyalar, tomonlar
│   │       ├── rules/           # Rule Engine (JSON qoidalar, testlar, 4-ko'z tasdiq)
│   │       ├── moderation/      # noto'g'ri xulosa haqida shikoyatlar, muharrir vazifalari
│   │       ├── scan/            # «Shartnomani tekshir»: OCR → segmentatsiya → tasnif → hisobot
│   │       ├── approvals/       # SMS-OTP / E-IMZO imzo (vaqt tamg'asi, .p7s konteyner), SHA-256
│   │       ├── obligations/     # majburiyat/huquqlar, RRULE, dashboard
│   │       ├── reminders/       # 6/3/2/1/0 kunlik eslatmalar, dispatcher, retry + zaxira kanal
│   │       ├── cases/           # yurist arxivi, timeline, dalillar to'plami (ZIP)
│   │       ├── files/           # shifrlangan fayl saqlash (local / S3-MinIO)
│   │       ├── notifications/   # in-app, SMS, Telegram (push/email — adapter tayyor)
│   │       ├── audit/           # append-only, hash-zanjirli audit log
│   │       └── anchoring/       # blokcheyn qaydi: Merkle partiyalar, relayer (gasless), isbot paketlari
│   ├── alembic/             # migratsiyalar (Postgres'da audit uchun trigger)
│   └── tests/               # 112 ta test (E-IMZO emulyatori, xotiradagi EVM, soxta LLM — haqiqiy AI chaqirilmaydi)
├── packages/legal-content/  # shartnoma turlari, qoidalar, bandlar kutubxonasi, BHM/bayramlar (JSON)
├── packages/contracts/      # LexLabAnchor.sol (Solidity) + kompilyatsiya qilingan ABI/bytecode
├── packages/web-sdk/        # lexlab-api.js — web ilova uchun JS klient (/sdk/lexlab-api.js)
├── scripts/                 # sync-frontend.ps1 — dizayn papkasidan apps/web ga nusxa
├── docs/                    # eimzo.md, blockchain.md, FRONTEND_GEMINI.md (frontend ↔ API xaritasi)
└── infra/                   # docker-compose (Postgres+pgvector, Redis, MinIO, API, worker)
```

## Tez ishga tushirish (Windows, Docker shart emas)

```powershell
cd services\api
.\run_dev.ps1          # venv, migratsiya, seed (+dev foydalanuvchilar), server :8000
```

- Swagger: http://localhost:8000/docs
- Dev rejimida SMS konsolga chiqadi, OTP kodi `.env` dagi `OTP_DEV_FIXED_CODE` (standart `111111`).
- Dev foydalanuvchilar: `+998900000001` admin, `…02`/`…03` muharrirlar, `…04` yurist, `…05` moderator.
  Admin va muharrirlar uchun TOTP 2FA majburiy (`/auth/2fa/setup` → `/auth/2fa/enable`).

Testlar va tekshiruvlar:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\ruff check app tests
```

Prod-ga o'xshash muhit (Docker bilan): `docker compose -f infra/docker-compose.yml up --build`
(`JWT_SECRET` va `MASTER_ENCRYPTION_KEY` muhit o'zgaruvchilari majburiy).

## Asosiy oqimlar

**Shartnoma tuz:** `POST /contracts` → `PATCH /contracts/{id}/answers` (har saqlashda real vaqt
tekshiruvi: 🔴/🟡/🔵, qonun havolasi, tuzatish taklifi, shakl talabi) → `POST /generate`
(qizil band bo'lsa bloklanadi yoki `acknowledge_red`) → `POST /invite` (taklif kodi faqat SMS orqali)
→ `POST /approve/otp` + `POST /approve` (foydalanuvchi ko'rgan SHA-256 bilan) → hamma tomon tasdiqlasa
shartnoma **faol**, shablon bo'yicha majburiyatlar va eslatmalar avtomatik yaratiladi.

**Shartnomani tekshir:** `POST /scans` (PDF/rasm/DOCX/TXT, fonda) yoki `POST /scans/text` →
`GET /scans/{id}/report`: umumiy xavf, qizil/qaltis bandlar, majburiyatlar, huquqlar,
yetishmayotgan elementlar, «Rozimisiz?» kartalari. OCR ishonchi past bo'lsa — `needs_review`,
foydalanuvchi matnni `PUT /scans/{id}/text` bilan tasdiqlaydi.

**Ikki tomon:** A tomon `POST /contracts/{id}/invite` bilan B ni telefon raqami bo'yicha taklif qiladi;
B o'sha raqam bilan (SMS-kod) kirib `GET /contracts/invitations` da taklifni ko'radi, matnni qo'shilishdan oldin o'qiydi
(`/invitations/{party_id}/preview`), qabul qiladi yoki rad etadi. Har bosqichda ikkala tomonga bildirishnoma boradi.
Kelishuv: har tomon faqat o'z ma'lumotini (`party_a.*` / `party_b.*`) tahrirlaydi, umumiy shartlarni ikkalasi;
norozilik va qarshi taklif (`/objections`, qabul/rad/qaytarib olish), har o'zgarish oldingi roziliklarni bekor qiladi.
Ikkala tomon bir xil shartlarga `/agree` bersa, umumiy shartnoma avtomatik yaratiladi; qonunga zid shart bo'lsa — yaratilmaydi.
Hammasi imzolagach shartnoma har bir tomonning shaxsiy arxiviga (`/archive`) saqlanadi; `GET /contracts/{id}/negotiation`
ekranga kerakli hamma narsani (keyingi qadam, maydon egalari, ogohlantirishlar) beradi.

**Shablonlar:** shartnoma turlari `packages/legal-content/contract_types/*.json`. Manba `source.kind` bilan belgilanadi:
`lexuz` — lex.uz'dagi rasmiy namunaviy shakl (mehnat shartnomasi), `organization` — tashkilotning o'z shabloni
(noturar joy ijarasi, jismoniy shaxslar ijarasi, notarial qarz). Matn so'zma-so'z, `[..]` o'rinlari savolnoma maydonlari.

**AI:** `LLM_*` sozlamalari (OpenAI-mos API): lokal Qwen (Ollama/vLLM) yoki dev uchun DeepSeek.
AI shartnomani rasmiy/tashkilot shabloni bilan band-bandi solishtiradi, xavfli bandlar va kimning foydasiga ekanini
tushuntiradi, majburiyatlarni ajratadi, «vaziyatingizni yozing» yordamchisi (`POST /assistant/situation`).
Tashqi modelga yuborishdan oldin shaxsiy ma'lumotlar maskalanadi; prod'da faqat lokal model (config bloklaydi).
Qonunga zid degan yakuniy hukmni faqat qoidalar tizimi beradi.

**Web ilova:** `apps/web` — dizayn; `/sdk/lexlab-api.js` — API klienti (tokenlar, ikki tomon sessiyasi,
o'zbekcha xatolar). Ekran elementlari ↔ endpointlar xaritasi: [docs/FRONTEND_GEMINI.md](docs/FRONTEND_GEMINI.md).
`.env` da `FRONTEND_DIR=../../apps/web` bo'lsa, backend saytni http://localhost:8000/ da beradi.

## Xavfsizlik (spec §10)

- AES-256-GCM envelope shifrlash: har fayl o'z kaliti bilan, kalit master-KEK bilan o'ralgan;
  JShShIR, pasport, manzil, shartnoma matni va savolnoma javoblari DB'da shifrlangan.
- RBAC + qator darajasidagi ruxsat (begona foydalanuvchi shartnoma mavjudligini ham bilmaydi — 404).
- Audit log: append-only (Postgres trigger) + SHA-256 hash-zanjir, `GET /admin/audit/verify`.
- Blokcheyn: zanjirga faqat Merkle ildizi chiqadi; shaxs tuzli commitment bilan ifodalanadi (JShShIR xeshi emas),
  ma'lumotlar O'zbekistondan chiqmaydi — [docs/blockchain.md](docs/blockchain.md).
- E-IMZO: imzolangan hujjat va imzolovchi (JShShIR/STIR) backendda tekshiriladi, vaqt tamg'asi majburiy — [docs/eimzo.md](docs/eimzo.md).
- OTP: HMAC bilan saqlanadi, amalga bog'langan (login kodi bilan shartnoma imzolab bo'lmaydi), urinish/limit.
- Refresh token rotatsiyasi va qayta ishlatilganda butun sessiya oilasini bekor qilish.
- Muharrir/admin uchun majburiy TOTP; qoidalar uchun «4 ko'z» tasdiq.
- Fayl turi magic-bytes bo'yicha tekshiriladi; formulalar sandbox'da (eval yo'q); shablonlar Jinja2 sandbox.
- AI'ga yuborishdan oldin PII maskalanadi; AI faqat izohlaydi — yakuniy hukm qoidaga asoslanadi.

## Muhim: huquqiy kontent

`packages/legal-content` dagi qoidalar, shartnoma shablonlari, BHM va bayram sanalari —
**namunaviy (demo)**. Dev rejimida ular avtomatik tasdiqlangan holda yuklanadi (`meta.demo=true`),
staging/prod'da esa qoralama sifatida yuklanib, huquqiy ekspert tasdig'idan o'tishi kerak.
`(tekshirilsin)` belgisi bor qiymatlarni rasmiy manba (Lex.uz) bilan solishtiring.

## Keyingi qadamlar

1. E-IMZO-SERVER'ni o'rnatish va domen API-kalitini olish (integratsiya tayyor — [docs/eimzo.md](docs/eimzo.md)); OneID kalitlari.
2. Push (FCM/APNs) va email kanallari; to'lovlar (Payme/Click/Uzum).
3. Blokcheyn: relayer hamyonini to'ldirish va `LexLabAnchor` ni Polygon Amoy'ga deploy qilish
   (`python -m app.modules.anchoring.deploy`); mainnet'ga o'tishda kalitni HSM/secret manager'da saqlash.
4. RAG: pgvector bilan semantik qidiruv + mahalliy LLM provayderi (`app/ai/llm.py`).
5. Skaner hisobotini PDF ko'rinishida yuklab olish (hozir DOCX); rus tilidagi shablonlar (`template_ru`).
6. Lex.uz o'zgarishlarini avtomatik kuzatish (hozir `POST /cms/rules/law-changed` hook bor).
7. Shartnoma turlari va shablonlari uchun CMS endpointlari (hozir JSON + seed orqali; qoidalar CMS'i tayyor).
8. Web ilovani SDK orqali to'liq ulash (`docs/FRONTEND_GEMINI.md`); `apps/admin`.
