# E-IMZO integratsiyasi

Manba: rasmiy hujjat <https://github.com/qo0p/e-imzo-doc> (2.2-bo'lim — E-IMZO-SERVER REST API).

## Nima qiladi

| Imkoniyat | Endpoint | Natija |
|---|---|---|
| E-IMZO bilan kirish / ro'yxatdan o'tish | `GET /auth/eimzo/challenge` → `POST /auth/eimzo` | Tasdiqlangan shaxs (JShShIR) bilan akkaunt, TOTP so'ralmaydi (kalit + parol = 2 omil) |
| Telefon akkauntiga E-IMZO bog'lash | `POST /auth/eimzo/link` | Akkaunt «shaxsi tasdiqlangan» bo'ladi |
| Shartnomani imzolash | `GET /contracts/{id}/approve/eimzo` → `POST /contracts/{id}/approve` (`method: "eimzo"`) | Malakali elektron imzo, vaqt tamg'asi bilan |
| Barcha imzolar bitta faylda | `GET /contracts/{id}/versions/{n}/signature.p7s` | Ikkala tomon imzosi birlashtirilgan PKCS#7 |

## Kerakli infratuzilma

1. **E-IMZO-SERVER** — rasmiy server komponenti. Hujjatga ko'ra u faqat litsenziya asosida, ishlab chiquvchilar kanali orqali tarqatiladi; uchinchi tomon yig'malaridan foydalanmang. Sertifikat holatini tekshirish uchun VPN kaliti kerak (`vpn.e-imzo.uz`, test uchun `testvpn.e-imzo.uz`).
2. **API-kalit** — har bir production domen uchun alohida beriladi (IP-manzilli sayt uchun berilmaydi). Lokal ishlab chiqishda hujjatdagi `localhost` / `127.0.0.1` kalitlari ishlatiladi; test domeni uchun E-IMZO ilovasida «Режим разработчика» yoqiladi.
3. Foydalanuvchi kompyuterida **E-IMZO ilovasi** o'rnatilgan bo'lishi kerak.

Backend sozlamalari (`services/api/.env`):

```env
EIMZO_SERVER_URL=http://127.0.0.1:8080   # E-IMZO-SERVER (ichki tarmoq)
EIMZO_SITE_HOST=lexlab.uz                # bizning domen — Host sarlavhasida yuboriladi
EIMZO_REQUIRE_TIMESTAMP=true             # imzoga ishonchli vaqt tamg'asi majburiy
```

> ⚠️ `/backend/*` yo'llari **faqat** bizning API'ga ochiq bo'lishi kerak (hujjat talabi). Nginx'da tashqariga faqat
> `/frontend/*` chiqarilishi mumkin; bizda frontend hammasini API orqali chaqiradi, shuning uchun E-IMZO-SERVER'ni
> umuman tashqariga ochmaslik eng xavfsiz yo'l.

## Frontend: kirish

Hujjatdagi `e-imzo-client.js` (`EIMZOClient`) va `e-imzo-init.js` (`AppLoad`) fayllaridan foydalaniladi.

```js
// 1) challenge
const { challenge } = await api.get("/api/v1/auth/eimzo/challenge");

// 2) foydalanuvchi kalitini tanlaydi -> yuklash -> challenge'ni imzolash (parolni E-IMZO ilovasi so'raydi)
EIMZOClient.loadKey(selectedKey, (keyId) => {
  EIMZOClient.createPkcs7(keyId, challenge, null, async (pkcs7) => {
    // 3) backend tekshiradi (challenge bir martalik, ~120 s amal qiladi)
    const tokens = await api.post("/api/v1/auth/eimzo", { pkcs7, consent: true });
  }, onError);
}, onError);
```

## Frontend: shartnomani imzolash

```js
// 1) imzolanadigan hujjat (backend tayyorlaydi — o'zingiz yasamang)
const p = await api.get(`/api/v1/contracts/${id}/approve/eimzo`);
// p = { document_b64, document_sha256, content_sha256, version, detached: false }

// 2) attached PKCS#7; hujjat allaqachon Base64 -> isDataBase64Encoded = true
EIMZOClient.createPkcs7(keyId, p.document_b64, null, async (pkcs7) => {
  const r = await api.post(`/api/v1/contracts/${id}/approve`, {
    method: "eimzo", pkcs7, sha256: p.content_sha256,
  });
  // r.legal_strength === "qualified_signature"
}, onError, /* detached */ false, /* isDataBase64Encoded */ true);
```

Vaqt tamg'asini frontend qo'shmaydi — backend `/frontend/timestamp/pkcs7` orqali o'zi qo'shadi.

## Backend nimani tekshiradi

1. **Imzo va sertifikat** — E-IMZO-SERVER: imzo, sertifikat zanjiri, bekor qilinmaganligi (OCSP), imzolangan
   vaqtda amal qilganligi, vaqt tamg'asi.
2. **Nima imzolangan** — imzolangan baytlar aynan shu shartnoma versiyasining hujjatiga teng
   (`contract_id`, `version`, kontentning SHA-256 xeshi). Boshqa versiya yoki o'zgartirilgan hujjat rad etiladi.
3. **Kim imzolagan** — sertifikatdagi JShShIR (`1.2.860.3.16.1.2`) akkauntning tasdiqlangan shaxsiga teng bo'lishi
   kerak. Kompaniya nomidan imzolanganda yuridik STIR (`1.2.860.3.16.1.1`) kompaniya STIR'iga teng bo'lishi kerak.
4. **Akkauntni egallab olishdan himoya** — profilda qo'lda yozilgan JShShIR hech qachon E-IMZO bilan bog'lash
   uchun ishlatilmaydi; faqat OneID yoki E-IMZO imzosi orqali isbotlangan JShShIR (`users.verified_pinfl_hash`).

Imzolangan PKCS#7 (ichida sertifikat — shaxsiy ma'lumot) shifrlangan fayl sifatida saqlanadi; tasdiq yozuvida
faqat qisqacha ma'lumot (F.I.Sh., maskalangan JShShIR, sertifikat seriyasi, imzo va vaqt tamg'asi vaqti) qoladi.

## Xato kodlari (E-IMZO-SERVER `status` → API `error.code`)

| status | code | Ma'nosi |
|---|---|---|
| -1 | `eimzo_status_check_failed` (503) | Sertifikat holatini tekshirib bo'lmadi (ko'pincha VPN) |
| -5 | `eimzo_time_window` | Imzo vaqti ruxsat etilgan oraliqdan tashqarida |
| -10 | `eimzo_signature_invalid` | Imzo yaroqsiz |
| -11 | `eimzo_certificate_invalid` | Sertifikat yaroqsiz / bekor qilingan |
| -12 | `eimzo_certificate_expired` | Imzo vaqtida sertifikat amal qilmagan |
| -20 | `eimzo_challenge_expired` (login) | Challenge topilmadi yoki muddati o'tgan |
| -21…-23 | `eimzo_tsa_*` | Vaqt tamg'asi muammosi |
| -24, -25 | `eimzo_policy_not_allowed`, `eimzo_ca_not_allowed` | Sertifikat turi / CA ruxsat etilmagan |

Bizning qo'shimcha tekshiruvlarimiz: `eimzo_document_mismatch`, `eimzo_signer_mismatch`,
`eimzo_company_mismatch`, `eimzo_timestamp_invalid`, `identity_taken`, `identity_mismatch`.

## Testlar

`services/api/tests/fake_eimzo.py` — E-IMZO-SERVER emulyatori (hujjatdagi JSON tuzilmalari bilan);
`tests/test_api_eimzo.py` — kirish, bog'lash, akkauntni egallab olishga urinish, ikki tomonlama imzo,
kompaniya kaliti va boshqa holatlar.
