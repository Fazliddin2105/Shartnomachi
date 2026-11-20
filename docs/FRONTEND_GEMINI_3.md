# Frontend — 3-topshiriq (Gemini uchun): «Shartnomani tekshir» bo'sh holati

## Sizga (o'zbekcha)

- **Muammo:** hech narsa tekshirilmagan bo'lsa ham, «Shartnomani tekshir» bo'limida tahlil ko'rinadi: «Ijara shartnomasi #42», «O'rta xavf», qonunga zid 1, qaltis 1. Bu `index.html` ga oldindan yozib qo'yilgan namuna matn; `app.js` uni tozalamaydi.
- **Kerak:** tahlil bo'lmasa, bu joy bo'sh turadi.

Gemini'ga faqat **shu faylni** biriktiring va pastdagi matnni yuboring:
`C:\Users\xxaak\Desktop\lexlab-platform\docs\FRONTEND_GEMINI_3.md`

1- va 2-topshiriqlarni qayta yubormang.

---

## Gemini'ga yuboriladigan matn

> Small bug fix in `js/app.js` only (do not touch `index.html` or `css/styles.css`, no design changes).
> In the «Shartnomani tekshir» view (`#view-scanner`) the static demo report from `index.html` is visible although the user has not analysed anything. Implement the empty state described in the attached `FRONTEND_GEMINI_3.md` exactly, then run its checklist and report each step.

### 1. The bug

These elements keep the static demo content from `index.html` until a real scan is rendered:

- `#scan-report-doc-title` — «2. Tekshiruv xulosasi: Ijara shartnomasi #42»;
- `#scan-report-risk-badge` — «O'rta xavf»;
- `#scan-count-illegal` — `1`;
- `#scan-count-risky` — `1`;
- the first `[data-scan-preset]` button has the `active` class.

They are shown on page load. They are also still shown when the user has older scans, because opening the view only fills the history strip. After switching 1-Tomon / 2-Tomon, the previous user's report stays on screen.

### 2. Add this function (next to `renderScanReport`)

```js
  // No analysis selected: the report area is empty (no demo data, nothing from another user).
  function renderScanEmptyState() {
    state.currentScanId = null;
    state.currentScanReport = null;
    state.currentScanTitle = null;

    const titleEl = document.getElementById('scan-report-doc-title');
    const badgeEl = document.getElementById('scan-report-risk-badge');
    const illegalEl = document.getElementById('scan-count-illegal');
    const riskyEl = document.getElementById('scan-count-risky');
    const dutiesEl = document.getElementById('scan-duties-list');
    const cardsEl = document.getElementById('scan-decision-cards');

    if (titleEl) titleEl.textContent = '2. Tekshiruv xulosasi';
    if (badgeEl) { badgeEl.hidden = true; badgeEl.textContent = ''; }
    if (illegalEl) illegalEl.textContent = '—';
    if (riskyEl) riskyEl.textContent = '—';
    if (dutiesEl) dutiesEl.innerHTML = '<li class="hp-text-muted">Hali tahlil yo\'q — shartnoma faylini yuklang.</li>';
    if (cardsEl) cardsEl.innerHTML = '';
    document.querySelectorAll('[data-scan-preset]').forEach(b => b.classList.remove('active'));
  }
```

### 3. Call it in these places

1. **On page start**, right after login/session restore and before any data is loaded (the `DOMContentLoaded` init): `renderScanEmptyState();`.
2. **When the active party/slot changes** (the `[data-switch-party]` handler, after `LexLab.useSlot(...)`) and **after logout**: `renderScanEmptyState();`. The report of one user must never stay visible for another.
3. **When opening the scanner view** (`navigateTo('scanner')`, next to `loadScannerHistory()`):
   ```js
   if (state.currentScanReport) renderScanReport(state.currentScanReport, state.currentScanTitle);
   else renderScanEmptyState();
   ```
   Do **not** auto-open the latest scan from history. The user picks one from «Oxirgi tahlillar» or uploads a new file.
4. **After deleting a scan** (`[data-delete-scan]` handler, after `LexLab.scans.remove(id)` succeeds): if the deleted `id === state.currentScanId`, call `renderScanEmptyState()`.

### 4. In `renderScanReport(r, docTitle)` (existing function)

The badge was hidden by the empty state, so show it again. Add right after the badge text is set:

```js
      badgeEl.hidden = false;
```

### 5. Sample buttons `[data-scan-preset]`

Keep them as they are; they only run when the user clicks one. `runScannerPreset` already sets `active` on the clicked button. The empty state removes it.

### 6. Checklist

1. Hard reload, log in with a new phone, open «Shartnomani tekshir»:
   - title «2. Tekshiruv xulosasi», no risk badge, counters «—»;
   - one line «Hali tahlil yo'q…», no cards, no sample button highlighted.
2. Upload a contract file: the real report appears with the badge and counters.
3. Go to the dashboard and back: the same report is still shown.
4. Delete that analysis with «Tahlilni o'chirish»: the area becomes empty again.
5. Switch to 2-Tomon (another user): the scanner area is empty, not 1-Tomon's report.
6. Click a sample button: a real analysis of that sample runs and is shown; the button becomes active.
7. No console errors; layout and styles unchanged.
