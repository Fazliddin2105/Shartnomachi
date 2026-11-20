# Frontend ↔ LexLab API — topshiriq (Gemini uchun)

## Sizga (o'zbekcha, qisqa)

1. Antigravity'da `HuquqiyPlatforma` papkasini oching.
2. Gemini'ga quyidagi **«Gemini'ga yuboriladigan matn»** bo'limini yuboring va shu faylni biriktiring:
   `C:\Users\xxaak\Desktop\lexlab-platform\docs\FRONTEND_GEMINI.md`
3. Backend ishlab turgan bo'lishi kerak: http://127.0.0.1:8000. Saytni ham shu manzildan oching (backend sizning papkangizni o'zi ko'rsatadi).

**Muhim:** papkangizdagi `server.py` va `huquqiy_platforma.db` — alohida, soddalashtirilgan ikkinchi backend (8090-port). Unda lex.uz va tashkilot shablonlari, DeepSeek AI, SMS-kod bilan kirish, xesh bilan imzolash yo'q. Frontend LexLab backendiga ulangach, `server.py` kerak bo'lmaydi. Uni o'chirish yoki qoldirishni o'zingiz hal qilasiz, topshiriq unga tegmaydi.

---

## Gemini'ga yuboriladigan matn

> You are wiring the existing web UI in this folder (`index.html`, `css/styles.css`, `js/app.js`) to the **LexLab API**.
> Read the attached `FRONTEND_GEMINI.md` fully before editing.
> **Do not change the design.** Layout, colors, fonts, spacing, icons, texts and CSS stay as they are.
> You may only:
> - change JavaScript behaviour;
> - add one `<script src="/sdk/lexlab-api.js"></script>` tag before `js/app.js`;
> - render dynamic data with the markup patterns and CSS classes that already exist.
>
> All server calls go through `window.LexLab` (the SDK). Do not call `fetch('/api/...')` and do not use `server.py` (port 8090).
> Test at http://127.0.0.1:8000/. The dev SMS code is `111111`.
> When done, run the acceptance checklist in section 12 and report the result of each step.

---

## 1. Hard rules

1. **Design freeze.**
   - Do not edit `css/styles.css` and do not change existing elements' classes, IDs, order or text.
   - Do not add new visual styles. New content (lists, modals, form fields) must reuse existing patterns: `.hp-card`, `.hp-form-group` + `label` + `.hp-input`, `.hp-form-row-2`, `.hp-btn-navy`, `.hp-btn-outline`, `.hp-btn-navy-sm`, `.hp-btn-outline-sm`, `.hp-pill-badge` + `.hp-pill-success|warning|danger|neutral`, `.hp-rule-item` + `.hp-rule-red|amber|blue`, `.hp-clause-alert` + `.hp-clause-illegal|risky`, `.hp-timeline-*`, `.hp-ob-row-card`, `.hp-case-step-card`, the modal `#hp-modal-*` and toasts `#hp-toast-container`.
   - If something truly has no existing pattern, ask instead of inventing a style.
2. **Real data only.** Remove the hard-coded demo arrays (contracts, obligations, case steps, scan presets results, user name «Abdullo K.») as data sources. Every number and list on screen comes from the API.
3. **One client.**
   - Load `/sdk/lexlab-api.js`. It handles tokens, refresh, two sessions, errors and downloads.
   - Do not re-implement HTTP, do not store tokens yourself.
   - Remove the `fetch('/api/state' | '/api/contracts' | ...)` calls aimed at `server.py`.
4. **Safety.**
   - Server strings (contract text, names, AI answers) are user-controlled. Escape them before `innerHTML`, or use `textContent`.
   - Never `eval`.
5. **Errors are visible.**
   - Every `catch` shows `showToast(LexLab.humanError(e))`. No silent `console.warn`.
   - While a request runs, disable the button that started it.

## 2. Runtime

- The backend serves this folder at **http://127.0.0.1:8000/** (same origin, no CORS issues). API: `/api/v1/...`. Swagger: `/docs`. SDK: `/sdk/lexlab-api.js`.
- If you must use another dev server, ports 3000, 5173, 5500 and 8080 on localhost/127.0.0.1 are allowed. Then call `LexLab.configure({ baseUrl: 'http://127.0.0.1:8000' })`.
- Demo accounts: any phone `+998XXXXXXXXX`, code from `(await LexLab.meta()).dev_otp_code` (= `111111`). Verified lawyer: `+998900000004`.

## 3. SDK cheat sheet (all methods return Promises)

```js
// auth & sessions — two slots so one browser can be both sides
LexLab.useSlot('party_a' | 'party_b');  LexLab.activeSlot();
await LexLab.auth.requestOtp(phone);                      // {expires_in, resend_in}
await LexLab.auth.verify(phone, code, {consent:true});    // {ok, isNewUser} | {mfa, mfaToken}
await LexLab.auth.logout();  LexLab.auth.isLoggedIn(slot);  LexLab.auth.phoneOf(slot);
LexLab.on('logout', ({slot}) => ...);  LexLab.on('unauthorized', ...);
LexLab.humanError(e)   // Uzbek message;  e.code, e.status, e.details

await LexLab.meta()            // {dev_otp_code, features:{ai,eimzo,...}, ai:{enabled,model,local}}
await LexLab.me.get()          // {phone, role, profile:{full_name,...}, preferences:{channels}, identity_verified_via}
await LexLab.me.update({channels:['in_app','sms','telegram']});  await LexLab.me.profile({full_name});
await LexLab.dashboard()       // see §5
await LexLab.assistant.situation(text)
await LexLab.lookup.stir('305891247')
await LexLab.types.list(); await LexLab.types.get(code)      // questionnaire, library, source
LexLab.contracts.{list(tab), get(id), create(code, 'A'|'B'), saveAnswers(id, answers, selectedClauses?),
  validate, autofix, preview(id, lang), generate(id,{acknowledgeRed}), versions, download(id,n),
  invite(id, phone,'B'), requestApprovalCode(id), approve(id, code, sha256), setStatus(id,status),
  aiReview(id), aiAsk(id, q), invitations(), invitationPreview(pid), acceptInvitation(pid), declineInvitation(pid)}
LexLab.scans.{upload(file), fromText(text), get, waitDone(id), report(id), waitAi(id), decide(id, fid,'agree'|'object'),
  toObligations(id), text(id), saveText(id, text), aiAsk(id,q), downloadReport(id), list()}
LexLab.obligations.{list(params), dashboard(), create({title, due_date, amount}), setStatus(id,'done'|'pending')}
LexLab.cases.{list(), create({title}), get(id), addStep(id,{title, description, tags}), exportZip(id)}
LexLab.notifications.{list(), markRead(ids?)}     LexLab.calc.bhm()
```

## 4. Login and the «1-Tomon / 2-Tomon» switch

- **On start:**
  - If `!LexLab.auth.isLoggedIn(LexLab.activeSlot())`, open the existing modal with a login form: phone input, «Kod yuborish» button, code input, and a consent checkbox «Shaxsiy ma'lumotlarimni qayta ishlashga roziman». Use `.hp-form-group`/`.hp-input`/`.hp-btn-navy`.
  - In dev, show «Demo kod: 111111» under the code input.
  - The modal must not be closable until logged in.
- **`[data-switch-party="party_a"|"party_b"]`:**
  - Call `LexLab.useSlot(slot)`.
  - If that slot is not logged in, open the same login modal (party B logs in with the phone A invited).
  - Then reload all widgets.
- **Header:**
  - `#current-user-name` = `me.profile.full_name` || masked phone.
  - `#current-user-badge` = «OneID tasdiqlangan» only if `me.identity_verified_via`, else «Telefon tasdiqlangan».
- **`#btn-logout`:** `LexLab.auth.logout()`, then show login.
- **`#btn-profile-modal`:** modal with phone, role and a `full_name` input. Save with `LexLab.me.profile({full_name})`.

## 5. Dashboard (`#view-dashboard`) — one call: `const d = await LexLab.dashboard()`

| Element | Data |
|---|---|
| `#nav-contracts-count` | `d.contracts.total` |
| `#dash-contracts-tbody` | `d.contracts.recent` (title, `party_names.A/B`, status badge §10, `created_at` dd.mm.yyyy). Row click → contract modal §7 |
| `#bilateral-inbox-banner`, `#party-b-pending-count` | `d.invitations` (count). Click → invitations list §7.4 |
| Risk gauge `#dash-gauge-arc` | `pct = d.last_scan?.risk_percent ?? 0`; `stroke-dashoffset = 300 - 2.9*pct` (clamp 15..300) |
| `#dash-gauge-needle` | `transform = translate(100,82) rotate(${-66 + 1.35*pct})` |
| `#dash-gauge-line1/2` | `last_scan.risk_label` (e.g. «Yuqori» / «xavf») |
| `#dash-clause-1`, `#dash-clause-2` | `d.last_scan.top_findings[0..1]` (explanation, law_ref, clause_text, suggestion) |
| `[data-clause-action]` | `LexLab.scans.decide(d.last_scan.id, finding.id, 'agree'|'object')`; on object show `suggestion` in `#dash-clause-1-detail` |
| No scan yet | Hide or neutral-state the two clause cards and show «Hali tahlil yo'q — shartnomani tekshiring» |
| `#dash-timeline-list` | `d.obligations.overdue` then `upcoming_30d` (top 3). Days left = `due_date - today`. ✓ button → `LexLab.obligations.setStatus(id,'done')` |
| Channel chips `[data-channel]` | Initial state from `me.preferences.channels` (default `['in_app','sms']`). Toggle → `LexLab.me.update({channels})`. `push` is not configured server-side (falls back to in-app) — keep the chip but tell the user once via toast |
| BHM card | `const {amount} = await LexLab.calc.bhm()`. 1 BHM = `amount` so'm; the multiplier input multiplies it |

## 6. Builder (`#view-builder`)

1. **`#cb-type`:**
   - Options from `LexLab.types.list()`: `value=code`, `text=title_uz`.
   - Show the source on the option text: `source.kind === 'lexuz'` → « (lex.uz rasmiy shakl)»; `'organization'` → « (tashkilot shabloni)».
   - Legacy design codes for links/suggestions: `ijara→rent_residential`, `noturar→rent_commercial`, `mehnat→labor`, `xizmat→services`, `oldi_sotdi→sale`, `qarz→loan`, `notarial_qarz→loan_notarial`, `ijara_jismoniy→rent_private`.
2. **On type selection:**
   - `const t = await LexLab.types.get(code)`.
   - `const c = await LexLab.contracts.create(code, 'A')`. Keep `c.id`; one draft per type, remember it in `sessionStorage`.
3. **Render the questionnaire inside `#contract-builder-form`:**
   - It replaces the fixed demo inputs `#cb-party-a`, `#cb-party-b`, `#cb-amount`, `#cb-penalty`. Keep their look: `.hp-form-group` + `label` + `.hp-input`, two per row with `.hp-form-row-2`. Keep the action buttons.
   - One block per `t.questionnaire.sections[]` (section `title` as a small label/heading).
   - One input per `fields[]`:
     - `key` (may be dotted, e.g. `party_a.stir`), `label`, `type`, `required`, `hint`, `options`, `min`, `max`, `pattern`.
     - Input by type: `string`/`text` → text input (text → textarea); `number` → number input; `date` → date input; `enum` → `<select>` from `options[]` (`{value,label}`); `party` → name input saved as `${key}.name`.
     - Show `*` for required fields and use `hint` as the placeholder.
4. **Save as the user types** (debounce 600 ms): `const r = await LexLab.contracts.saveAnswers(c.id, {[key]: value})`. Numbers are sent as numbers; an empty string becomes `null`. Then:
   - **`#cb-rule-alerts-list`:** one `.hp-rule-item` per `r.findings[]` (class by severity: red→`hp-rule-red`, yellow→`hp-rule-amber`, blue→`hp-rule-blue`), with `message`, `law_ref` and `fix_suggestion`.
   - **Missing fields:** list `r.missing_fields[]` (match to labels) as one blue item «To'ldirilmagan: …».
   - **Format errors:** mark `r.field_errors[]` inputs as invalid and show the error under the input.
   - **Form warning:** if `r.form.warning`, show it as an amber item.
   - **Overall badge:** red if `r.summary.blocking`, amber if there are yellow findings, otherwise green «Qonunga mos».
5. **Preview `#cb-doc-preview-content`:**
   - `const p = await LexLab.contracts.preview(c.id, lang)`.
   - Render `p.title` (keep line breaks), `p.header`, `p.preamble`, then each `p.sections[]` (`title` bold if not empty, `text` lines as paragraphs).
   - Show `p.content_sha256` in small muted text at the bottom: «SHA-256: …». This is exactly the hash the parties will sign.
   - `[data-doc-lang]`: `ru` may throw `language_unavailable` → toast and switch back to `uz`.
6. **`#btn-stir-lookup-b`:**
   - `LexLab.lookup.stir(value of the party_b.stir input)`.
   - If `found`: fill `party_b.name`, `address`, `director`, `mfo`, `oked`. Else: toast `message`.
7. **`#btn-builder-autofix`:**
   - `const r = await LexLab.contracts.autofix(c.id)`.
   - Write each `r.applied[i].value` into its input; re-render alerts.
   - If `applied` is empty, toast «Avtomatik tuzatiladigan band yo'q».
8. **`#btn-builder-generate`:**
   - `const g = await LexLab.contracts.generate(c.id)`.
   - Error `answers_incomplete`: highlight `e.details.missing` / `e.details.errors`.
   - Error `illegal_clauses`: a confirm modal listing `e.details[].message`. On «Tushundim, baribir yaratish», call `generate(c.id, {acknowledgeRed:true})`.
   - On success, a modal shows «Versiya N», `g.version.sha256` and three buttons:
     - «DOCX yuklab olish» → `LexLab.contracts.download(c.id, g.version.number)`;
     - «2-tomonni taklif qilish» → phone input → `LexLab.contracts.invite(c.id, phone, 'B')`;
     - «Imzolash (SMS-kod)» → `requestApprovalCode(c.id)` → code input → `approve(c.id, code, g.version.sha256)`.
   - After generation the draft is locked: forget it and refresh the lists.
9. **AI:**
   - A «AI tekshiruv» action (inside the generate/contract modal, not a new styled button) → `LexLab.contracts.aiReview(id)`. It returns `{summary, risk_level, issues[], obligations[], template_deviations[], model}` and takes 3–15 s, so show a loading state.
   - AI items are advisory: label them «AI», never as «Qonunga zid».

## 7. Contracts (`#view-contracts`) and the contract modal

1. **List:**
   - `#full-contract-filters [data-filter]`: `all` → `LexLab.contracts.list()`; `active|pending|disputed|completed|expired` → `list(tab)`.
   - Render into `#full-contracts-tbody` with status badges (§10).
2. **Contract modal:** `const [c, vs] = await Promise.all([LexLab.contracts.get(id), LexLab.contracts.versions(id)])`. Show:
   - title, status, parties (`c.parties[]` role/joined/confirmed), amount (`total_amount currency`), dates, `form_requirement` (notarial/registration warning);
   - latest version number + sha256.
3. **Actions**, shown only when allowed:
   - draft/pending_approval and I am the owner → «Taklif qilish»;
   - pending_approval and my party has `confirmed_at == null` → «Imzolash (SMS-kod)», via `approve(..., latest.sha256)`;
     - after `approve`: `contract_status === 'active'` → toast «Shartnoma kuchga kirdi»; else «Imzo qo'yildi, … tomon kutilmoqda» (`pending_parties`);
   - any version → «DOCX» download;
   - active → «Yakunlandi» / «Nizo» via `setStatus(id, 'completed'|'disputed')`;
   - always → «AI savol» (`aiAsk`) and «AI tekshiruv» (`aiReview`).
4. **Invitations (party B inbox):**
   - `const inv = await LexLab.contracts.invitations()` gives `[{party_id, contract_title, role_title, inviter_name, total_amount, current_sha256}]`.
   - «Ko'rish» → `invitationPreview(party_id)`, rendered like §6.5.
   - «Qabul qilish» → `acceptInvitation(party_id)`, then open the contract modal and offer «Imzolash».
   - «Rad etish» → `declineInvitation(party_id)`.

## 8. Scanner (`#view-scanner`)

1. **Upload** (`#scanner-dropzone` click/drop, `#btn-trigger-file-upload`, `#scanner-file-input`; PDF/DOCX/TXT/JPG/PNG):
   - `const s = await LexLab.scans.upload(file)`, then `await LexLab.scans.waitDone(s.id)`.
   - If `status === 'needs_review'` (OCR uncertain): show `LexLab.scans.text(id)` in a textarea in the modal → `saveText(id, text)` → `waitDone`.
   - If `failed`: toast the error.
2. **Render** `const r = await LexLab.scans.report(id)`:
   - `#scan-report-doc-title`: file name.
   - `#scan-report-risk-badge`: `${r.overall.risk_label} (${r.overall.risk_percent}/100)`.
   - `#scan-count-illegal`: `r.red_clauses.length`. `#scan-count-risky`: `r.risky_clauses.length`.
   - `#scan-duties-list`: `r.your_obligations[]` (`clause_text` or `explanation`).
   - `#scan-decision-cards`: `r.red_clauses` then `r.risky_clauses` (`.hp-clause-alert` + `.hp-clause-illegal|risky`), then `r.missing_elements` as blue cards. Each card shows the explanation (prefer `ai_explanation` when present), `law_ref` and `clause_text`. Roziman/E'tiroz → `LexLab.scans.decide(id, f.id, 'agree'|'object')`; on object show `f.suggestion`. Keep `user_decision` state.
   - Template comparison: if `r.overall.template_check`, show «Shablonga muvofiqlik: X%» (`conformity*100`) and the source label. Template cards have `source==='template'`.
   - AI:
     - right after the rules report, show «AI tahlil qilmoqda…»;
     - `const full = await LexLab.scans.waitAi(id)` and re-render;
     - `full.ai.summary` and `full.ai.template_deviations[]` (status, template_clause, comment) go in an existing card style;
     - findings with `source==='ai'` get an «AI» tag.
3. **Presets `[data-scan-preset]`:** keep the buttons, but send a short built-in sample text for that type through `LexLab.scans.fromText(text)`. The result is a real analysis, not static data.
4. **After the report:**
   - offer «Majburiyatlarni eslatmalarga qo'shish» → `LexLab.scans.toObligations(id)`;
   - offer «Hisobotni yuklab olish» → `LexLab.scans.downloadReport(id)` (DOCX).

## 9. Reminders, archive, notifications, search

- **`#view-reminders`:**
  - `#full-obligations-list` ← `LexLab.obligations.list()` (title, contract, amount currency, due date, status).
  - Toggle → `setStatus(id, 'done'|'pending')`.
  - `#btn-add-obligation` → modal form (title, due_date, amount) → `LexLab.obligations.create({title, due_date, amount})`.
- **`#view-archive` (lawyers only):**
  - `LexLab.cases.list()` works for everyone: lawyers see their cases, citizens see cases shared with them.
  - `cases.create` / `addStep` need a verified lawyer. Error `lawyer_only` (403) → show the form disabled with «Ish yuritish faqat tasdiqlangan yuristlar uchun» (demo lawyer `+998900000004`).
  - Timeline `#lawyer-case-timeline` ← `cases.get(id).steps`.
  - `#case-step-form` (`#cs-title`, `#cs-type`, `#cs-desc`): if no case yet, `cases.create({title:'Asosiy ish'})`, then `addStep(caseId, {title, description, tags:[type]})`.
  - «PDF Dalil to'plami» button (if present) → `cases.exportZip(id)` (ZIP with documents + manifest + timeline).
- **`#btn-notif-panel`:**
  - modal with `LexLab.notifications.list().items` (title, body, time); then `markRead()`;
  - the red dot is visible when `unread > 0` (also `d.notifications_unread`).
- **`#ai-situation-form` / `#ai-situation-input`:**
  - submit → `const a = await LexLab.assistant.situation(text)`;
  - show `a.answer` and `a.steps[]` in `#ai-search-dropdown`, with one button for `a.action`:
    - `builder` → go to builder with `a.contract_type.code` preselected;
    - `scanner` → go to scanner;
    - `consult` → toast;
  - `a.alternatives[]` as secondary options.
  - The static suggestions (`[data-action][data-contract-type]`) keep working via the code mapping in §6.1.
- **Language switch UZ/RU:** UI texts only (as today). Contract preview language is §6.5.

## 10. Value mappings

| Contract `status` | Badge |
|---|---|
| `draft` | Qoralama — neutral |
| `pending_approval` | Imzolash kutilmoqda — warning |
| `active` | Faol — success |
| `completed` | Yakunlangan — neutral |
| `expired` | Muddati o'tgan — neutral |
| `disputed` | Nizoli — danger |
| `cancelled` | Bekor qilingan — neutral |

| Finding `severity` | Meaning |
|---|---|
| `red` | Qonunga zid (only rules can mark this) |
| `yellow` | Qaltis band |
| `blue` | Maslahat / yetishmaydi |

| Obligation `status` | Meaning |
|---|---|
| `pending`, `reminded` | Active |
| `done` | Bajarildi |
| `overdue` | Muddati o'tgan (red) |
| `cancelled` | Bekor qilingan |

`kind`: `duty` (majburiyat) / `right` (huquq). `confirmed:false` means extracted by the scanner or AI: ask the user to confirm via `LexLab.obligations.confirm(id)`.

## 11. Old `server.py` calls → LexLab

| Was (`server.py`, 8090) | Now |
|---|---|
| `GET /api/state` | `LexLab.dashboard()` + `contracts.list()` + `obligations.list()` |
| `GET /api/stir/{stir}` | `LexLab.lookup.stir(stir)` |
| `POST /api/contracts/validate` | `contracts.saveAnswers(id, answers)` (returns the validation) |
| `POST /api/contracts` | `contracts.create` → `saveAnswers` → `generate` |
| `POST /api/contracts/{id}/sign` | `requestApprovalCode(id)` → `approve(id, code, sha256)`. Objection = a scan `decide(...,'object')` or a new version after editing answers |
| `POST /api/scans/analyze-text`, `/api/scans/upload` | `scans.fromText`, `scans.upload` (+ `waitDone`, `report`, `waitAi`) |
| `POST /api/obligations`, `PATCH /api/obligations/{id}/toggle` | `obligations.create`, `obligations.setStatus` |
| `POST /api/cases/steps` | `cases.addStep(caseId, …)` |

## 12. Acceptance checklist (run it, report each step)

1. Open http://127.0.0.1:8000/. The login modal appears. Log in as 1-Tomon `+998901110001` / `111111`.
2. The header shows the user; the dashboard is empty but has no errors.
3. Builder: choose «Ijara shartnomasi (jismoniy shaxslar o'rtasida)». The fields appear; fill them.
   - Payment method = «Pul ko'chirish» with an empty bank account shows an amber rule.
   - Fill the account: the rule disappears. The preview updates live and shows the SHA-256.
4. Generate → DOCX downloads. Invite `+998901110002`.
5. Switch to 2-Tomon. Log in with `+998901110002`. The inbox banner shows 1 invitation: view the text → accept → sign with the SMS code.
6. Switch to 1-Tomon → sign.
   - The contract becomes «Faol».
   - Reminders show the monthly payment.
   - The notification bell shows new items.
7. Scanner: upload any contract DOCX/PDF.
   - The rules report appears, then the AI part.
   - Roziman/E'tiroz work. The report DOCX downloads.
8. The dashboard gauge and clause cards reflect that scan.
9. Search «ofis uchun bino ijaraga olmoqchimiz» → the answer suggests «Noturar joyni ijaraga berish» and opens the builder with it.
10. No page errors in the console. Every failure shows an Uzbek toast. The design looks exactly as before.
