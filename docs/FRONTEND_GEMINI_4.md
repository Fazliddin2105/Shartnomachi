# Frontend — 4-topshiriq (Gemini uchun): qonun moddalarini ko'rsatish

## Sizga (o'zbekcha)

- **Nima o'zgardi:** backend endi O'zbekiston qonunlarini lex.uz'dan oladi (Fuqarolik kodeksi, Mehnat kodeksi, Iste'molchilar huquqlari qonuni). Har bir ogohlantirishda aniq modda bor, masalan «FK 615-modda. Ijara shartnomasini bekor qilish».
- **Bu topshiriq nima qiladi:** foydalanuvchi moddani bosganda uning lex.uz'dagi asl matni ochiladi.

Gemini'ga faqat **shu faylni** biriktiring va pastdagi matnni yuboring:
`C:\Users\xxaak\Desktop\lexlab-platform\docs\FRONTEND_GEMINI_4.md`

1–3-topshiriqlarni qayta yubormang.

---

## Gemini'ga yuboriladigan matn

> Small feature in `js/app.js` only. Do not touch `index.html` or `css/styles.css`; no design changes; existing modal and classes only.
> Law references shown in findings must open the article text from lex.uz, as described in the attached `FRONTEND_GEMINI_4.md`.
> Hard-reload first so SDK v1.2 is loaded (`LexLab.version === '1.2.0'`). When done, run the checklist and report each step.

### 1. Data

Every finding (builder `validation.findings`, `field_warnings`, scanner `red_clauses` / `risky_clauses` / `missing_elements`, AI issues) has a `law_ref` string, e.g. `"FK 237-modda. Majburiyatni …; FK 382-modda. Shartnomani …"`. Builder findings also have `lex_url` (direct lex.uz link).

SDK v1.2:

```js
await LexLab.laws.resolve(lawRefText)   // -> [{code, short, number, title, chapter, text, url, edition_date, law}]
await LexLab.laws.article('fk2', 615)   // one article
await LexLab.laws.search('ijara muddati')
await LexLab.laws.list()                // sources with edition dates
```

### 2. What to build

1. **Clickable references.** Wherever a `law_ref` is rendered, render it as a link-styled element: reuse an existing link/button class used in the app (for example `.hp-clause-expand-link` or `.hp-text-link-btn`) and add `data-law-ref="<escaped law_ref>"`. Do not add new CSS.
2. **One delegated click handler** for `[data-law-ref]`:
   - call `LexLab.laws.resolve(ref)`;
   - open the existing modal with title «Qonun moddasi».
3. **Modal body**, for each returned article:
   - **bold** `${short} ${number}-modda. ${title}`;
   - a muted line `${law} — lex.uz tahriri: ${edition_date}`;
   - the article `text` (escaped, line breaks kept);
   - a link «lex.uz'da ochish» → `url` (`target="_blank" rel="noopener"`).

   If nothing resolves, show the `law_ref` text plus, if present, the `lex_url` link.
4. **Mark AI findings.** In AI findings (`source === 'ai'`) keep the existing «AI» tag. The reference is still clickable, because the AI is required to cite only articles it was given from lex.uz.

### 3. New contract types (nothing to code — verify only)

The builder renders questionnaires dynamically, so these new types must work as-is:

- **«Avtotransport vositasini ayirboshlash shartnomasi»** (`vehicle_exchange`, 62 fields):
  - field keys are dotted, e.g. `party_a.vehicle.make` (same handling as other dotted keys);
  - `b_via_representative = "yes"` makes the representative fields required — the backend returns them in `missing_fields`.
- **«Pullik tibbiy xizmat ko'rsatish shartnomasi»** (`medical_paid`):
  - `type: "text"` fields (optional extra rights/duties) should be textareas.

### 4. Checklist

1. In the builder choose «Mehnat shartnomasi», position «Hisobchi», probation 5 months.
   - The warning shows «MK 130-modda …».
   - Clicking it opens the modal with the article text («Dastlabki sinov muddati uch oydan …») and a working lex.uz link.
2. Scanner: analyse a residential lease text containing «Ijara muddati 7 yil». The AI finding cites «FK 612-modda». Clicking it shows the article text.
3. «Avtotransport vositasini ayirboshlash» renders all sections.
   - Choosing «vakil orqali» makes the representative fields required.
   - The preview shows the long notarial date (««20» noyabr ikki ming yigirma oltinchi yil»).
4. «Pullik tibbiy xizmat» renders; the extra-rights fields are textareas.
5. No console errors; design unchanged.
