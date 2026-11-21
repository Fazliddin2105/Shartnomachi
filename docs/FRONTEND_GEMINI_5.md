# Frontend — 5-topshiriq (Gemini uchun): «Shartnomachi AI» chat va «Mediatorga murojaat»

## Sizga (o'zbekcha)

- **Nima qo'shildi (backend tayyor va sinovdan o'tgan):**
  1. **«Shartnomachi AI»** — saytning istalgan sahifasidan ochiladigan AI yordamchi chat. U shartnomalar, nizolar, mediatsiya va qonunlar bo'yicha javob beradi, lex.uz moddalariga havola qiladi va keyingi qadamni taklif qiladi (masalan, «Shartnoma tuzish» yoki «Mediatorga ariza tayyorlash»). Shartnoma oynasi ochiq bo'lsa, o'sha shartnomaga tayanib javob beradi.
  2. **«Mediatorga murojaat»** — nizo bo'yicha mediatorga ariza tayyorlash. Tomonlar shartnomadan avtomatik to'ldiriladi. AI xolis nizo matni va murosa variantlarini taklif qiladi. Natija DOCX: ariza va «Mediatsiyani qo'llash to'g'risidagi kelishuv» loyihasi («Mediatsiya to'g'risida»gi Qonun, O'RQ-482). Platforma arizani hech qayerga yubormaydi, faqat tayyorlab beradi.
- **Bu topshiriq:** shu ikkalasining interfeysini mavjud dizaynni buzmasdan qo'shish.

Gemini'ga faqat **shu faylni** biriktiring va pastdagi matnni yuboring:
`C:\Users\xxaak\Desktop\lexlab-platform\docs\FRONTEND_GEMINI_5.md`

1–4-topshiriqlarni qayta yubormang.

---

## Gemini'ga yuboriladigan matn

> Add two features to the existing web app (`index.html`, `js/app.js`, `css/styles.css`) as described in the attached `FRONTEND_GEMINI_5.md`.
> **Do not redesign anything.** Do not change or remove existing markup, classes or CSS rules. Reuse existing components (`.hp-card`, `.hp-input`, `.hp-form-group`, `.hp-form-row-2`, `.hp-btn-navy(-sm)`, `.hp-btn-outline(-sm)`, `.hp-rule-item` + `.hp-rule-green/amber/red/blue`, `.hp-pill-badge`, `.hp-sug-tag`, the existing modal, `showToast`, `withBusy`, `esc`, `lawRefLink`, `adviceHtml`). New CSS is allowed **only** for the floating chat button/panel, appended at the end of `styles.css` in one commented block, using the existing CSS variables, with dark-mode overrides (`body.dark-mode …`).
> Hard-reload first so SDK v1.4 is loaded (`LexLab.version === '1.4.0'`). When done, run the checklist and report each step.

### 1. SDK v1.4.0 (already served at `/sdk/lexlab-api.js`)

```js
// «Shartnomachi AI» chat — the server stores nothing; send the recent history every time (max 20 messages)
const r = await LexLab.assistant.chat(
  [{ role: 'user', content: 'Ijarachi 2 oydan beri to\'lamayapti, nima qilay?' }],   // last item = user question
  { contractId: state.openModalContractId || null, page: state.currentView }        // both optional
);
// r = { answer, law_refs: [{ ref, title, url }], action: { type, type_code, label } | null,
//       consult_lawyer: bool, disclaimer, model }
// action.type ∈ 'builder' (with type_code) | 'scanner' | 'mediation' | 'contracts' | 'archive' | 'reminders'

// Mediator application (O'RQ-482)
const m = await LexLab.mediation.create({}, contractId);   // contractId optional: prefills parties + subject
await LexLab.mediation.update(m.id, { description: '...', claims: 'qator1\nqator2' });  // null/'' clears a field
await LexLab.mediation.get(id); await LexLab.mediation.list(); await LexLab.mediation.remove(id);
const s = await LexLab.mediation.aiHelp(id);  // { subject, statement, claims[], options[], law_refs[{ref,title,url}], disclaimer }
await LexLab.mediation.downloadDocx(id);      // 422 {code:'mediation_incomplete', details:[missing labels]} if incomplete
```

A mediation request object: `{ id, contract_id, contract_title, status: 'draft'|'ready', form: {...}, missing: [labels], ai_draft, created_at }`.
`form` keys: `applicant_name, applicant_address, applicant_phone, respondent_name, respondent_address, respondent_phone, mediator_name, mediator_org, subject, description, claims, desired_outcome, amount, city`.
Required for DOCX: `applicant_name`, `respondent_name`, `subject`, `description` (≥ 20 characters). `missing` lists what is still needed, in Uzbek.

Errors: `ai_disabled` (503) → «AI hozircha ulanmagan»; `rate_limited` (429) → «So'rovlar ko'p — birozdan keyin urinib ko'ring»; others → `LexLab.humanError(e)`.

### 2. «Shartnomachi AI» chat

1. **Floating button** (bottom-right, every view, only when logged in): round button with a chat/sparkle icon and the tooltip «Shartnomachi AI». It must not cover the toast container or modal buttons on mobile (shift up / smaller at ≤ 640 px).
2. **Panel** (opens above the button; on ≤ 640 px full width): header «Shartnomachi AI» + close button; scrollable message list; input (textarea, Enter = send, Shift+Enter = new line) + send button; a muted line with `disclaimer`.
3. **Empty state:** a short greeting and 3 example chips that send a question when clicked:
   «Kvartirani ijaraga berish uchun nima kerak?», «Qarz bermoqchiman, qanday rasmiylashtiraman?», «Ikkinchi tomon shartnomani bajarmayapti, nima qilay?»
4. **Sending:** append the user bubble, show a typing indicator, call `LexLab.assistant.chat(history.slice(-10), { contractId, page })`. Disable the send button while waiting (`withBusy`).
5. **Assistant bubble:**
   - `answer` (escaped, line breaks kept);
   - if `law_refs.length`: a small «Qonun (lex.uz):» list, each item `lawRefLink(ref.ref, ref.url)` + ` — ${title}` (clicking opens the existing law modal);
   - if `consult_lawyer`: `adviceHtml('Aniq xulosa uchun yurist bilan maslahatlashing.')`;
   - if `action`: one button `action.label` that navigates:
     - `builder` → open the builder with `action.type_code` preselected (existing builder init / type select);
     - `scanner` / `contracts` / `archive` / `reminders` → switch to that view (existing navigation);
     - `mediation` → open the mediation form (section 3); if a contract modal was open, pass its id.
6. **History:** keep it in memory and in `sessionStorage` (`lexlab.chat.v1`, wrapped in try/catch); a «Tozalash» (clear) link in the header. Clear it on logout or when the active slot changes (1-Tomon / 2-Tomon).
7. **Context:** when the contract modal is open, show a small chip in the panel header «Shartnoma: <title>» — the answer is then based on that contract.

### 3. «Mediatorga murojaat»

**Entry points**

- In the contract modal action row: a new button **«Mediatorga murojaat»** (`.hp-btn-outline-sm`) for any contract that is not a draft. Click → `LexLab.mediation.create({}, c.id)` → open the form.
- From the chat action `mediation`.
- **List:** on the «Shartnomalarim» page, below the contracts table, a new `.hp-card` titled **«Mediatorga arizalarim»** with a «+ Yangi ariza» button (creates without a contract) and rows: subject, contract title (if any), status pill («Tayyor» = success / «Qoralama» = neutral), date, and buttons «Ochish», «DOCX», «O'chirish» (confirm with the existing `confirmDeleteModal`). Empty state: «Hozircha ariza yo'q».

**Form** (existing modal, title «Mediatorga ariza»)

- A `.hp-rule-item.hp-rule-blue` info block at the top:
  «Mediatsiya — nizoni sudsiz, betaraf mediator yordamida hal qilish (O'RQ-482). Mediatsiya ixtiyoriy, 30 kungacha davom etadi, mediator xarajati odatda teng bo'linadi. Platforma arizani tayyorlab beradi — uni mediatorga o'zingiz topshirasiz.»
- Fields (labels in Uzbek; `.hp-form-row-2` for pairs):
  - Arizachi: F.I.Sh./nomi*, manzil, telefon;
  - Ikkinchi tomon: F.I.Sh./nomi*, manzil, telefon;
  - Mediator (ixtiyoriy): F.I.Sh., tashkilot;
  - Nizo predmeti*;
  - Nizo mazmuni* (textarea, rows 5, hint «kamida 20 belgi»);
  - Talablarim (textarea, «har biri yangi qatorda»);
  - Murosa bo'yicha taklifim (textarea);
  - Nizo summasi (so'm), Shahar.
- If `contract_title`: a muted line «Shartnoma: …» under the title.
- Buttons: **«Saqlash»** (`update` with all fields), **«AI yordam»**, **«DOCX yuklab olish»**.
  - Before AI or DOCX: save first.
  - DOCX is disabled while `missing.length > 0`; show `missing` as an amber `.hp-rule-item` list «To'ldirish kerak: …».
  - On 422, show `details`.
- **AI yordam** (call after saving; the backend needs a description ≥ 20 chars) → render a green block «AI taklifi» with:
  - `subject` + «Qo'llash» → fills Nizo predmeti;
  - `statement` + «Qo'llash» → fills Nizo mazmuni;
  - `claims` (list) + «Qo'llash» → fills Talablarim (joined with `\n`);
  - `options` (each + «Tanlash» → fills Murosa bo'yicha taklifim);
  - `law_refs` via `lawRefLink(ref, url)`;
  - `disclaimer` (muted).

  Applying only fills the inputs. The user then presses «Saqlash».

### 4. Checklist (report each step)

1. `LexLab.version === '1.4.0'`; no console errors on any view.
2. The chat button is visible on every view after login, absent before login; the panel opens and closes; it looks right in dark mode and at 375 px width.
3. Ask «Kvartiramni ijaraga bermoqchiman» → the answer cites FK articles; clicking a reference opens the law modal; the action button opens the builder with «Turar joy ijarasi» selected.
4. Ask «Ijarachi to'lamayapti, sudsiz qanday hal qilaman?» → the answer cites MQ articles; the action «Mediatorga ariza tayyorlash» opens the mediation form.
5. Open a contract modal, open the chat → the context chip shows the contract; ask about it → the answer refers to its clauses.
6. Reload the page → chat history is still there (sessionStorage); «Tozalash» empties it; switching 1-Tomon/2-Tomon empties it.
7. Contract modal → «Mediatorga murojaat» → parties and subject are prefilled; DOCX is disabled and the missing list shows «Nizo mazmuni».
8. Fill in the description → Saqlash → AI yordam → suggestions appear; «Qo'llash»/«Tanlash» fill the fields → Saqlash → DOCX downloads (`mediatorga_ariza_….docx`).
9. «Shartnomalarim» → «Mediatorga arizalarim» lists the request; Ochish / DOCX / O'chirish work; «+ Yangi ariza» works without a contract.
10. Existing features are unchanged: the builder, scanner colours and green advice, archive documents, BHM calculator, profile.
