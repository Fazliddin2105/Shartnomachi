# Blokcheyn qaydi (anchoring)

## Qisqacha

Shartnoma, pasport ma'lumotlari va yurist dalillari **O'zbekistondagi serverda, shifrlangan holda** qoladi.
Blokcheynga faqat **Merkle ildizi** — ko'plab hujjatlar xeshlaridan hisoblangan bitta 32 baytlik qiymat — yoziladi.
Foydalanuvchi kripto-hamyon ko'rmaydi: «Tasdiqlash» tugmasini bosadi, qolganini backend (relayer) bajaradi.

| Qatlam | Qayerda | Nima |
|---|---|---|
| Hujjat, pasport, rasm, PKCS#7 | Lokal server (AES-256-GCM) | To'liq ma'lumot |
| Barg (leaf) | Lokal DB | Hujjat SHA-256, **tuzli** shaxs commitment'i, vaqt |
| Merkle ildizi | **Polygon (Amoy testnet)** | 32 bayt, ma'nosiz tasodifiy ko'rinadi |

## Nega to'g'ridan-to'g'ri JShShIR yoki uning xeshi emas

JShShIR 14 xonali va tuzilmasi ma'lum. Shu sababli `SHA-256(JShShIR)` ni oddiy kompyuterda ham hamma variantlarni
sinab chiqib tiklash mumkin. Ochiq blokcheynga bunday xeshni yozish shaxsiy ma'lumotni oshkor qilish bilan barobar va
uni hech qachon o'chirib bo'lmaydi. Shuning uchun:

1. Shaxs **tuzli commitment** bilan ifodalanadi: `sha256(tuz ‖ {pinfl, eri_sertifikat_seriyasi, user_id})`.
   Tuz faqat serverimizda shifrlangan holda turadi va faqat shaxsning o'ziga (yoki sud so'rovi bilan) beriladi.
2. Barg ham zanjirga chiqmaydi — u Merkle daraxtiga kiradi, zanjirda faqat ildiz bo'ladi.

## Qanday ishlaydi

```
Tasdiqlash / dalil yuklash ──► barg (DB) ──► har daqiqa: Merkle daraxti ──► relayer tx ──► LexLabAnchor.anchor(root)
                                                                    (bitta tx = yuzlab hujjat)        │
Isbot paketi: barg + Merkle yo'li + tx hash  ◄────────────────── N ta tasdiqdan keyin «confirmed» ◄──┘
```

Qaysi hodisalar qayd etiladi:

| Hodisa | Barg tarkibi |
|---|---|
| Shartnoma barcha tomonlarca imzolandi | `contract_id`, versiya, kontent SHA-256, har bir imzolovchi uchun commitment + usul (OTP / E-IMZO) + vaqt + PKCS#7 xeshi |
| Yurist dalil fayli yukladi | fayl SHA-256, turi, qayd vaqti |
| Audit log boshi | oxirgi audit yozuvining xeshi — butun audit zanjiri ochiq qaydga bog'lanadi |

**Smart kontrakt:** `packages/contracts/LexLabAnchor.sol`.
- Faqat relayer yoza oladi.
- Bir ildizni ikki marta yozib bo'lmaydi.
- `anchoredAt(root)` ildiz qayd etilgan blok vaqtini qaytaradi.
- Kompilyatsiya qilingan ABI/bytecode `build/` papkasida saqlanadi (serverda Solidity kompilyatori kerak emas).

**Merkle daraxti:** SHA-256, RFC 6962 uslubidagi domen ajratish (`0x00` barg, `0x01` ichki tugun).
Juft bo'lmagan tugun o'zgarishsiz yuqoriga ko'tariladi, ya'ni nusxalanmaydi (CVE-2012-2459 kabi muammo yo'q).

**Ishonchlilik:**
- RPC uzilsa, partiya 5 martagacha qayta yuboriladi.
- `AlreadyAnchored` javobi «tasdiqlangan» deb qabul qilinadi.
- `NotRelayer` — konfiguratsiya xatosi, shuning uchun darhol `failed` holatiga o'tadi.
- Blokcheyn xatosi eslatmalar va boshqa scheduler ishlariga ta'sir qilmaydi.

## API

| Endpoint | Kim | Natija |
|---|---|---|
| `GET /contracts/{id}/versions/{n}/anchor` | Shartnoma tomonlari | Isbot paketi + **faqat o'zingizning** commitment ochqichingiz |
| `GET /cases/{id}/attachments/{aid}/anchor` | Yurist | Dalil faylining isboti |
| `GET /cases/{id}/export` | Yurist | Dalillar to'plami — har fayl yonida blokcheyn isboti |
| `POST /anchors/verify` | **Har kim** (hisobsiz, masalan sud) | Merkle hisobi + zanjirdagi `anchoredAt` tekshiruvi |
| `GET /admin/anchors` | Admin | Partiyalar holati |

Mustaqil tekshirish uchun platformaga ishonish shart emas:
1. Hujjatni SHA-256 qiling va paketdagi `content_sha256` / `file_sha256` bilan solishtiring.
2. Paketdagi Merkle yo'li bo'yicha ildizni qayta hisoblang.
3. Polygonscan'da `anchoredAt(root)` ni chaqiring yoki tranzaksiyani oching.

## Ishga tushirish (Polygon Amoy testnet)

```powershell
cd services\api
.\.venv\Scripts\python -m app.modules.anchoring.deploy --new-key   # relayer hamyoni
# manzilni Polygon Amoy faucet orqali test POL bilan to'ldiring
# .env: ANCHOR_BACKEND=evm, EVM_RPC_URL=https://rpc-amoy.polygon.technology, EVM_CHAIN_ID=80002, RELAYER_PRIVATE_KEY=...
.\.venv\Scripts\python -m app.modules.anchoring.deploy             # -> ANCHOR_CONTRACT_ADDRESS=0x...
```

Kontraktni o'zgartirsangiz: `python packages/contracts/build.py` (py-solc-x kerak).

**Hyperledger Fabric:** `AnchorChain` interfeysi (`submit`, `receipt`, `anchored_at`) Fabric chaincode uchun ham
amalga oshirilishi mumkin. MVP uchun Polygon tanlandi: yopiq konsorsium tarmog'ini yuritish shart emas, natijani
har kim ochiq explorer'da ko'ra oladi.

## Cheklovlar

- Blokcheyn hujjatning **mavjudligi va o'zgarmaganligini** isbotlaydi, uning yuridik kuchini emas. Yuridik kuchni
  E-IMZO imzosi, kerak bo'lsa notarial tasdiq beradi.
- Polygon **mainnet**'ga o'tishda relayer xarajati va kalitni saqlash (HSM / secret manager) masalasi alohida hal qilinadi.
- Amoy — test tarmoq. Unda qayd etilgan ma'lumotlarga uzoq muddatli yuridik dalil sifatida tayanmang.

---

## Konsepsiya uchun matn: «12. Rivojlanish yo'l xaritasi»

> Quyidagi qatorlarni loyiha hujjatidagi bosqichlar jadvaliga qo'shish mumkin.

**3-bosqich. Yurist arxivi va dalillar bazasi (2 oy)** — texnologik yadro: *blokcheynda qayd etish (anchoring)*.

- Yurist yuklagan har bir dalil fayli (rasm, skaner, audio) uchun SHA-256 xesh va vaqt tamg'asi olinadi.
  Bu xeshlar Merkle ildizi orqali Polygon blokcheyniga qayd etiladi.
- Dalillar to'plami (ZIP) har bir fayl uchun blokcheyn isbotini o'z ichiga oladi. Sud yoki qarama-qarshi tomon
  faylning o'zgartirilmaganini platformaga ishonmasdan, ochiq tarmoqda mustaqil tekshira oladi.
- Audit log boshi ham muntazam qayd etiladi, shuning uchun platformaning o'z jurnalini ham yashirincha o'zgartirib bo'lmaydi.
- Shaxsiy ma'lumotlar mamlakatdan chiqmaydi: zanjirda faqat 32 baytlik ildiz turadi.

**4-bosqich. To'lov va E-imzo integratsiyasi (davomli)** — texnologik yadro: *E-IMZO + blokcheyn qaydi*.

- Shartnoma E-IMZO bilan imzolanadi: vaqt tamg'asi qo'yiladi, imzolovchining JShShIR/STIR'i tekshiriladi,
  ikkala tomon imzosi bitta `.p7s` faylga birlashtiriladi.
- Imzolangan versiyaning xeshi va imzolovchilarning tuzli commitment'lari blokcheynga qayd etiladi.
  Natijada «kim, qachon, qaysi matnni imzolagan» degan savolga o'chirib bo'lmaydigan ochiq dalil paydo bo'ladi.
- Foydalanuvchi kripto-hamyon ko'rmaydi: tranzaksiya to'lovini platforma relayer'i to'laydi («gasless»).
- To'lovlar (Payme, Click, Uzum) muvaffaqiyatli o'tganda to'lov kvitansiyasining xeshi ham shu mexanizm orqali
  qayd etilishi mumkin.
