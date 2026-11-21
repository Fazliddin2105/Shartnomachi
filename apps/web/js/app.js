/**
 * HUQUQIY PLATFORMA — LexLab API Frontend Integration (js/app.js — Task 2: Negotiation, Personal Archive, Cleanup)
 * All server communication goes exclusively through window.LexLab (/sdk/lexlab-api.js v1.1.0).
 */

(function () {
  'use strict';

  const LEGACY_TYPE_MAP = {
    ijara: 'rent_residential',
    noturar: 'rent_commercial',
    mehnat: 'labor',
    xizmat: 'services',
    oldi_sotdi: 'sale',
    qarz: 'loan',
    notarial_qarz: 'loan_notarial',
    ijara_jismoniy: 'rent_private'
  };

  const SCAN_SAMPLE_TEXTS = {
    ijara:
      'IJARA SHARTNOMASI № 42\n' +
      'Toshkent sh. 20.04.2026 y.\n' +
      '1.1. Ijaraga beruvchi Toshkent shahri, Yunusobod tumani, Amir Temur ko\'chasi 15-uyda joylashgan 65 kv.m binoni Ijaraga oluvchiga 12 oy muddatga ijaraga beradi.\n' +
      '2.1. Oylik ijara haqi 4 500 000 so\'mni tashkil etadi va har oyning 5-sanasigacha to\'lanadi.\n' +
      '5.2. Ijara to\'lovi kechiktirilgan har bir kun uchun kechiktirilgan summaning 1,5% miqdorida cheklovsiz penya (neustoyka) to\'lanadi.\n' +
      '6.4. Ijaraga beruvchi oldindan ogohlantirmasdan 24 soat ichida shartnomani bir tomonlama bekor qilishga haqli.',
    mehnat:
      'MEHNAT SHARTNOMASI № 12\n' +
      'Toshkent sh. 15.04.2026 y.\n' +
      '1.1. Ish beruvchi Xodimni dasturchi lavozimiga ishga qabul qiladi. Oylik maosh 12 000 000 so\'m.\n' +
      '2.1. Oddiy xodim uchun dastlabki sinov muddati 6 oy etib belgilanadi.\n' +
      '4.3. Xodim o\'z xohishi bilan ishdan bo\'shasa, ish beruvchiga 15 000 000 so\'m miqdorida jarima to\'lashga majbur.',
    xizmat:
      'XIZMAT KO\'RSATISH SHARTNOMASI № 18\n' +
      'Toshkent sh. 10.04.2026 y.\n' +
      '1.1. Ijrochi Buyurtmachining topshirig\'iga ko\'ra veb-sayt va mobil ilova ishlab chiqish xizmatini 30 ish kuni muddatda ko\'rsatadi.\n' +
      '2.1. Xizmat narxi 18 000 000 so\'m bo\'lib, 50% oldindan to\'lanadi.\n' +
      '3.4. Buyurtmachi loyiha davomida cheklanmagan miqdorda bepul qo\'shimcha o\'zgartirishlar talab qilishga haqli.\n' +
      '5.1. Nizolar muzokaralar yo\'li bilan yoki sud tartibida hal qilinadi.'
  };

  const state = {
    lang: 'uz',
    currentView: 'dashboard',
    meta: null,
    me: null,
    dashboardData: null,
    modalLocked: false,
    pushToastShown: false,
    bhmBaseValue: 440000, // PF-115 (23.06.2026): 440 000 so'm from 01.09.2026; refreshed from /calc/bhm
    contractFilter: 'all',
    docPreviewLang: 'uz',

    // Builder & Negotiation
    contractTypes: [],
    builderTypeCode: null,
    builderTypeDetail: null,
    builderContractId: null,
    builderAnswers: {},
    builderFieldMap: {},
    builderFieldDefs: [],
    builderNegotiation: null,
    builderDebounceTimer: null,
    builderPendingPatch: {},
    builderPreviewSha256: null,

    // Modal tracking & Polling
    openModalContractId: null,
    openModalContractTitle: null,
    pollTimer: null,

    // «Shartnomachi AI» Chat & «Mediatorga murojaat» (FRONTEND_GEMINI_5)
    chatOpen: false,
    chatHistory: [],
    chatDisclaimer: "AI javobi ma'lumot uchun; yuridik maslahat o'rnini bosmaydi.",
    mediationList: [],
    activeMediation: null,
    activeMediationAi: null,

    // Scanner
    currentScanId: null,
    currentScanTitle: null,
    currentScanReport: null,
    scansHistory: [],

    // Personal Archive & Lawyer Cases
    archiveItems: [],
    archiveQuery: '',
    currentCaseId: null,
    casesList: []
  };

  const i18n = {
    uz: {
      nav_dashboard: 'Asosiy',
      nav_builder: 'Shartnoma tuz',
      nav_scanner: 'Shartnomani tekshir',
      nav_contracts: 'Shartnomalarim',
      nav_reminders: 'Eslatmalar',
      nav_archive: 'Yurist arxivi',
      nav_settings: 'Sozlamalar',
      nav_logout: 'Logout',
      search_placeholder: 'Vaziyatingizni yozing...',
      oneid_verified: 'OneID tasdiqlangan',
      hero2_title: 'Shartnoma tuz',
      hero2_desc: 'Savolnoma asosida qonuniy shartnoma generatsiya qilish.',
      hero3_title: 'Shartnomani tekshir',
      hero3_desc: 'Tayyor shartnomani yuklab, xavflarni skaner qilish.',
      ai_analysis_eyebrow: 'AI Shartnoma tahlili',
      ai_analysis_title: 'Shartnomani tekshir',
      flagged_clauses_title: 'Belgilangan bandlar',
      badge_illegal: 'Qonunga zid',
      badge_risky: 'Qaltis band',
      btn_agree: 'Roziman',
      btn_object: 'E\'tiroz',
      my_contracts_title: 'Shartnomalarim',
      th_doc_name: 'Hujjat nomi',
      th_party_name: '2-Tomon va imzo holati',
      th_date: 'Sana',
      th_actions: 'Harakat',
      obligations_title: 'Majburiyatlar va eslatmalar',
      bhm_calc_title: 'Davlat boji (BHM) kalkulyatori',
      bhm_amount_label: 'To\'lanadigan davlat boji:',
      btn_calculate: 'Hisoblash'
    },
    ru: {
      nav_dashboard: 'Главная',
      nav_builder: 'Создать договор',
      nav_scanner: 'Проверить договор',
      nav_contracts: 'Мои договоры',
      nav_reminders: 'Напоминания',
      nav_archive: 'Архив юриста',
      nav_settings: 'Настройки',
      nav_logout: 'Выйти',
      search_placeholder: 'Опишите вашу ситуацию...',
      oneid_verified: 'Подтвержден OneID',
      hero2_title: 'Создать договор',
      hero2_desc: 'Генерация законного договора на основе анкеты.',
      hero3_title: 'Проверить договор',
      hero3_desc: 'Загрузка готового договора и сканирование рисков.',
      ai_analysis_eyebrow: 'AI Анализ договора',
      ai_analysis_title: 'Проверить договор',
      flagged_clauses_title: 'Отмеченные пункты',
      badge_illegal: 'Незаконно',
      badge_risky: 'Опасный пункт',
      btn_agree: 'Согласен',
      btn_object: 'Возражаю',
      my_contracts_title: 'Мои договоры',
      th_doc_name: 'Название документа',
      th_party_name: 'Сторона 2 и статус',
      th_date: 'Дата',
      th_actions: 'Действия',
      obligations_title: 'Обязательства и напоминания',
      bhm_calc_title: 'Калькулятор госпошлины (БРВ)',
      bhm_amount_label: 'Сумма госпошлины:',
      btn_calculate: 'Рассчитать'
    }
  };

  // ==================== SAFETY & UI HELPERS ====================
  function esc(val) {
    if (val === null || val === undefined) return '';
    return String(val)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showToast(message) {
    const container = document.getElementById('hp-toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'hp-toast';
    toast.textContent = message || 'Xato';
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.25s ease';
      setTimeout(() => toast.remove(), 250);
    }, 3600);
  }

  function handleErr(e) {
    const msg = window.LexLab ? LexLab.humanError(e) : (e && e.message) || 'Xato';
    showToast(msg);
    // U2.6: For field_not_yours, highlight e.details.fields
    if (e && e.code === 'field_not_yours' && e.details && Array.isArray(e.details.fields)) {
      e.details.fields.forEach(k => {
        const inp = document.querySelector(`#cb-dynamic-questionnaire [data-q-key="${CSS.escape(k)}"]`);
        if (inp) inp.style.borderColor = '#DC2626';
      });
    }
  }

  async function withBusy(btn, fn) {
    if (btn) btn.disabled = true;
    try {
      return await fn();
    } catch (e) {
      handleErr(e);
      throw e;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function openModal(title, htmlContent, opts) {
    const options = opts || {};
    state.modalLocked = !!options.locked;
    if (!options.keepContractId) {
      state.openModalContractId = options.contractId || null;
      state.openModalContractTitle = options.contractId ? (title || null) : null;
    }
    const backdrop = document.getElementById('hp-modal-backdrop');
    const titleEl = document.getElementById('hp-modal-title');
    const bodyEl = document.getElementById('hp-modal-body');
    const closeBtn = document.getElementById('hp-modal-close');
    const footerEl = document.getElementById('hp-modal-footer');
    if (!backdrop || !titleEl || !bodyEl) return;

    titleEl.textContent = title;
    bodyEl.innerHTML = htmlContent;
    if (closeBtn) closeBtn.hidden = state.modalLocked;
    if (footerEl) footerEl.hidden = state.modalLocked || !!options.hideFooter;
    backdrop.hidden = false;
    updateChatContextChip();
  }

  function closeModal(force) {
    if (state.modalLocked && !force) return;
    state.modalLocked = false;
    state.openModalContractId = null;
    state.openModalContractTitle = null;
    const backdrop = document.getElementById('hp-modal-backdrop');
    const closeBtn = document.getElementById('hp-modal-close');
    const footerEl = document.getElementById('hp-modal-footer');
    if (closeBtn) closeBtn.hidden = false;
    if (footerEl) footerEl.hidden = false;
    if (backdrop) backdrop.hidden = true;
    updateChatContextChip();
  }

  // U2.5: Confirmation modal before every delete
  function confirmDeleteModal(title, message, onConfirm, reopenFn) {
    openModal(
      title,
      `
      <div class="hp-builder-form">
        <p style="font-size:14px;color:var(--text-main);">${esc(message)}</p>
        <div class="hp-builder-actions">
          <button type="button" class="hp-btn-outline" id="btn-confirm-cancel">Bekor qilish</button>
          <button type="button" class="hp-btn-navy" id="btn-confirm-proceed" style="background:#DC2626;">Tasdiqlash (O'chirish)</button>
        </div>
      </div>
      `,
      { hideFooter: true }
    );

    document.getElementById('btn-confirm-cancel')?.addEventListener('click', () => {
      closeModal();
      if (reopenFn) reopenFn();
    });

    const proceedBtn = document.getElementById('btn-confirm-proceed');
    proceedBtn?.addEventListener('click', () => {
      withBusy(proceedBtn, async () => {
        await onConfirm();
      }).catch(() => {});
    });
  }

  function formatNumberUz(num, decimals = 0) {
    const n = Number(num);
    if (!Number.isFinite(n)) return '0';
    const fixed = n.toFixed(decimals);
    const parts = fixed.split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return decimals > 0 ? `${parts[0]},${parts[1]}` : parts[0];
  }

  function formatDateDdMmYyyy(isoStr) {
    if (!isoStr) return '—';
    const d = new Date(isoStr);
    if (Number.isNaN(d.getTime())) return String(isoStr).slice(0, 10);
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const yyyy = d.getFullYear();
    return `${dd}.${mm}.${yyyy}`;
  }

  // ==================== FRONTEND_GEMINI_4: LAW REFERENCES (lex.uz) ====================
  // A law reference ("FK 615-modda. …") rendered as a link-styled button; the click handler resolves it
  // to the article text published on lex.uz. Existing class only (.hp-clause-expand-link), no new CSS.
  // Green «Maslahat» box: every recommendation (rule fix, AI suggestion) is shown the same way, in green.
  function adviceHtml(text, label) {
    if (!text) return '';
    return `<div class="hp-clause-advice"><span class="hp-pill-badge hp-pill-success">${esc(label || 'Maslahat')}</span> ${esc(text)}</div>`;
  }

  function lawRefLink(ref, lexUrl) {
    if (!ref) return '';
    // only real articles (FK/MK/IHHQ/MQ + number) or references with a lex.uz link are clickable
    if (!lexUrl && !/\b(FK|MK|IHHQ|MQ)\s*\d/i.test(ref)) return esc(ref);
    const urlAttr = lexUrl ? ` data-lex-url="${esc(lexUrl)}"` : '';
    return `<button type="button" class="hp-clause-expand-link" style="padding:0;text-align:left;" data-law-ref="${esc(ref)}"${urlAttr} title="Modda matnini ko'rish (lex.uz)">${esc(ref)}</button>`;
  }

  function renderLawArticlesHtml(arts, ref, lexUrl) {
    if (!arts || arts.length === 0) {
      return `
        <p style="font-size:13.5px;">${esc(ref)}</p>
        ${lexUrl ? `<a class="hp-text-link-btn" style="padding:0;" href="${esc(lexUrl)}" target="_blank" rel="noopener">lex.uz'da ochish ↗</a>` : ''}
      `;
    }
    return arts.map(a => `
      <div style="margin-bottom:16px;">
        <strong style="display:block;font-size:14px;margin-bottom:2px;">${esc(a.short)} ${esc(a.number)}-modda. ${esc(a.title)}</strong>
        <div class="hp-text-muted" style="font-size:12px;margin-bottom:8px;">${esc(a.law)} — lex.uz tahriri: ${esc(formatDateDdMmYyyy(a.edition_date))}</div>
        <div style="font-size:13px;line-height:1.55;white-space:pre-wrap;">${esc(a.text)}</div>
        <a class="hp-text-link-btn" style="display:inline-block;margin-top:6px;padding:0;" href="${esc(a.url)}" target="_blank" rel="noopener">lex.uz'da ochish ↗</a>
      </div>
    `).join('');
  }

  async function openLawReference(btn) {
    const ref = btn.getAttribute('data-law-ref') || '';
    const lexUrl = btn.getAttribute('data-lex-url') || '';
    const backdrop = document.getElementById('hp-modal-backdrop');
    const insideOpenModal = !!(backdrop && !backdrop.hidden && btn.closest('#hp-modal-backdrop'));

    // Inside an already open modal (contract, invitation…) the article opens inline, so the user's
    // modal is not replaced. Clicking again folds it.
    if (insideOpenModal) {
      const next = btn.nextElementSibling;
      if (next && next.hasAttribute('data-law-inline')) {
        next.remove();
        return;
      }
    }

    let arts = [];
    if (!LexLab.laws) {
      // stale SDK in the browser cache (< v1.2): show the reference itself
      showToast('Modda matnini ko\'rish uchun sahifani yangilang (Ctrl+F5)');
    } else {
      btn.disabled = true;
      try {
        arts = await LexLab.laws.resolve(ref);
      } catch (e) {
        handleErr(e);
      } finally {
        btn.disabled = false;
      }
    }
    const html = renderLawArticlesHtml(arts, ref, lexUrl);
    if (insideOpenModal) {
      const box = document.createElement('div');
      box.setAttribute('data-law-inline', '1');
      box.className = 'hp-rule-item hp-rule-blue';
      box.style.cssText = 'display:block;margin-top:6px;max-height:260px;overflow-y:auto;';
      box.innerHTML = html;
      btn.insertAdjacentElement('afterend', box);
    } else {
      openModal('Qonun moddasi', html);
    }
  }

  function maskPhone(phone) {
    if (!phone) return 'Foydalanuvchi';
    const s = String(phone);
    if (s.length >= 10) return `${s.slice(0, 6)}***${s.slice(-2)}`;
    return s;
  }

  function getPath(obj, dottedKey) {
    if (!obj || !dottedKey) return undefined;
    return String(dottedKey).split('.').reduce((acc, part) => (acc && acc[part] !== undefined ? acc[part] : undefined), obj);
  }

  // ==================== §10 VALUE MAPPINGS ====================
  function contractStatusBadgeHtml(status) {
    const map = {
      draft: { label: 'Qoralama', cls: 'hp-pill-neutral' },
      pending_approval: { label: 'Imzolash kutilmoqda', cls: 'hp-pill-warning' },
      active: { label: 'Faol', cls: 'hp-pill-success' },
      completed: { label: 'Yakunlangan', cls: 'hp-pill-neutral' },
      expired: { label: 'Muddati o\'tgan', cls: 'hp-pill-neutral' },
      disputed: { label: 'Nizoli', cls: 'hp-pill-danger' },
      cancelled: { label: 'Bekor qilingan', cls: 'hp-pill-neutral' }
    };
    const info = map[status] || { label: status || '—', cls: 'hp-pill-neutral' };
    return `<span class="hp-pill-badge ${info.cls}">${esc(info.label)}</span>`;
  }

  function obligationStatusBadgeHtml(status) {
    const map = {
      pending: { label: 'Kutilmoqda', cls: 'hp-pill-warning' },
      reminded: { label: 'Eslatilgan', cls: 'hp-pill-warning' },
      done: { label: 'Bajarildi', cls: 'hp-pill-success' },
      overdue: { label: 'Muddati o\'tgan', cls: 'hp-pill-danger' },
      cancelled: { label: 'Bekor qilingan', cls: 'hp-pill-neutral' }
    };
    const info = map[status] || { label: status || '—', cls: 'hp-pill-neutral' };
    return `<span class="hp-pill-badge ${info.cls}">${esc(info.label)}</span>`;
  }

  function navigateTo(viewName) {
    if (!viewName) return;
    state.currentView = viewName;

    document.querySelectorAll('.hp-view').forEach(v => {
      v.classList.toggle('active', v.id === `view-${viewName}`);
    });

    document.querySelectorAll('.hp-nav-item[data-nav]').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-nav') === viewName);
    });

    window.scrollTo({ top: 0, behavior: 'smooth' });

    if (LexLab.auth.isLoggedIn(LexLab.activeSlot())) {
      if (viewName === 'dashboard') loadDashboard().catch(handleErr);
      if (viewName === 'contracts') loadFullContracts(state.contractFilter).catch(handleErr);
      if (viewName === 'reminders') loadObligationsView().catch(handleErr);
      if (viewName === 'archive') loadArchiveView().catch(handleErr);
      if (viewName === 'scanner') {
        if (state.currentScanReport) renderScanReport(state.currentScanReport, state.currentScanTitle);
        else renderScanEmptyState();
        loadScannerHistory().catch(() => {});
      }
      if (viewName === 'builder' && !state.builderContractId) initBuilder().catch(handleErr);
    }
  }

  // ==================== §4 LOGIN & PARTY SWITCHER ====================
  function syncSlotButtons() {
    const slot = LexLab.activeSlot();
    document.querySelectorAll('[data-switch-party]').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-switch-party') === slot);
    });
  }

  function showLoginModal() {
    syncSlotButtons();
    const slot = LexLab.activeSlot();
    const slotLabel = slot === 'party_b' ? '2-Tomon' : '1-Tomon';
    const defaultPhone = LexLab.auth.phoneOf(slot) || (slot === 'party_b' ? '+998901110002' : '+998901110001');
    const devOtp = state.meta && state.meta.dev_otp_code;

    openModal(
      `Tizimga kirish — ${slotLabel}`,
      `
      <form id="lexlab-login-form" class="hp-builder-form" autocomplete="off">
        <div class="hp-form-group">
          <label for="login-phone-input">Telefon raqami *</label>
          <div class="hp-input-with-btn">
            <input type="text" id="login-phone-input" class="hp-input" value="${esc(defaultPhone)}" placeholder="+998901110001" required />
            <button type="button" class="hp-btn-outline-sm" id="btn-login-send-otp">Kod yuborish</button>
          </div>
        </div>

        <div class="hp-form-group">
          <label for="login-code-input">SMS tasdiqlash kodi *</label>
          <input type="text" id="login-code-input" class="hp-input" value="${esc(devOtp || '')}" placeholder="6 xonali kodni kiriting" required />
          ${devOtp ? `<span class="hp-field-hint">Demo kod: ${esc(devOtp)}</span>` : ''}
        </div>

        <div class="hp-form-group" id="login-mfa-group" hidden>
          <label for="login-mfa-input">2FA Authenticator kodi *</label>
          <input type="text" id="login-mfa-input" class="hp-input" placeholder="6 xonali TOTP kod" />
        </div>

        <label class="hp-channel-row" style="margin-top:4px;">
          <input type="checkbox" id="login-consent-cb" checked />
          <div>
            <strong>Shaxsiy ma'lumotlarimni qayta ishlashga roziman</strong>
          </div>
        </label>

        <div class="hp-builder-actions" style="margin-top:10px;">
          <button type="submit" class="hp-btn-navy" id="btn-login-submit" style="width:100%;">Kirish</button>
        </div>
      </form>
      `,
      { locked: true, hideFooter: true }
    );

    let otpRequestedFor = null;
    let pendingMfaToken = null;

    const sendBtn = document.getElementById('btn-login-send-otp');
    const phoneInput = document.getElementById('login-phone-input');
    const codeInput = document.getElementById('login-code-input');
    const consentCb = document.getElementById('login-consent-cb');
    const mfaGroup = document.getElementById('login-mfa-group');
    const mfaInput = document.getElementById('login-mfa-input');
    const form = document.getElementById('lexlab-login-form');
    const submitBtn = document.getElementById('btn-login-submit');

    sendBtn?.addEventListener('click', () => {
      const phone = (phoneInput?.value || '').trim();
      withBusy(sendBtn, async () => {
        await LexLab.auth.requestOtp(phone);
        otpRequestedFor = phone;
        showToast('SMS-kod yuborildi');
        codeInput?.focus();
      }).catch(() => {});
    });

    form?.addEventListener('submit', (e) => {
      e.preventDefault();
      const phone = (phoneInput?.value || '').trim();
      const code = (codeInput?.value || '').trim();
      const consent = !!consentCb?.checked;

      withBusy(submitBtn, async () => {
        if (pendingMfaToken) {
          const totp = (mfaInput?.value || '').trim();
          await LexLab.auth.verify2fa(pendingMfaToken, totp);
        } else {
          if (otpRequestedFor !== phone) {
            try {
              await LexLab.auth.requestOtp(phone);
              otpRequestedFor = phone;
            } catch (otpErr) {
              if (!otpErr || otpErr.code !== 'otp_cooldown') throw otpErr;
            }
          }
          const res = await LexLab.auth.verify(phone, code, { consent });
          if (res && res.mfa) {
            pendingMfaToken = res.mfaToken;
            if (mfaGroup) mfaGroup.hidden = false;
            showToast('2FA Authenticator kodini kiriting');
            return;
          }
        }

        closeModal(true);
        showToast('Tizimga muvaffaqiyatli kirildi');
        await reloadAllWidgets();
      }).catch(() => {});
    });
  }

  async function loadMe() {
    const me = await LexLab.me.get();
    state.me = me;

    const nameEl = document.getElementById('current-user-name');
    const badgeEl = document.getElementById('current-user-badge');
    const fullName = me.profile && me.profile.full_name;

    if (nameEl) {
      nameEl.textContent = shortPersonName(fullName) || maskPhone(me.phone);
      nameEl.title = fullName || 'Ism-familiya kiritilmagan — profilni to\'ldiring';
    }
    if (badgeEl) {
      badgeEl.textContent = me.identity_verified_via ? 'OneID tasdiqlangan' : 'Telefon tasdiqlangan';
    }

    const channels = (me.preferences && me.preferences.channels) || ['in_app', 'sms'];
    document.querySelectorAll('.hp-channel-chip[data-channel]').forEach(chip => {
      const ch = chip.getAttribute('data-channel');
      if (ch === 'sms' || ch === 'telegram') {
        chip.classList.toggle('active', channels.includes(ch));
      } else if (ch === 'push') {
        chip.classList.toggle('active', false);
      }
    });

    renderSettingsProfile(me);
  }

  // ---- Profile: F.I.Sh. is stored as one string «Familiya Ism Otasining ismi» ----
  const ROLE_LABELS = {
    citizen: 'Fuqaro', business: 'Tadbirkor (MChJ / YaTT)', lawyer: 'Yurist',
    editor: 'Kontent muharriri', moderator: 'Moderator', admin: 'Administrator'
  };
  const REGIONS = [
    'Toshkent sh.', 'Toshkent viloyati', 'Andijon viloyati', 'Buxoro viloyati', 'Farg\'ona viloyati',
    'Jizzax viloyati', 'Xorazm viloyati', 'Namangan viloyati', 'Navoiy viloyati', 'Qashqadaryo viloyati',
    'Qoraqalpog\'iston Respublikasi', 'Samarqand viloyati', 'Sirdaryo viloyati', 'Surxondaryo viloyati'
  ];
  const NAME_PART_RE = /^[\p{L}]+(?:[ '’ʻʼ`.-][\p{L}]+|[’ʻʼ'`.])*$/u;

  function splitFullName(full) {
    const parts = String(full || '').trim().split(/\s+/).filter(Boolean);
    return { last: parts[0] || '', first: parts[1] || '', middle: parts.slice(2).join(' ') };
  }

  function capitalizeName(s) {
    return String(s || '').trim().replace(/\s+/g, ' ')
      .split(' ').map(w => (w ? w.charAt(0).toLocaleUpperCase('uz') + w.slice(1) : w)).join(' ');
  }

  // «Karimov Abdullo Aliyevich» -> «Abdullo K.» (sidebar)
  function shortPersonName(full) {
    const n = splitFullName(full);
    if (!n.last) return '';
    return n.first ? `${n.first} ${n.last.charAt(0)}.` : n.last;
  }

  function renderSettingsProfile(me) {
    const list = document.querySelector('#view-settings .hp-setting-list');
    if (!list || !me) return;
    const prof = me.profile || {};
    const fullName = prof.full_name || '';
    const roleLabel = ROLE_LABELS[me.role] || me.role || '—';
    const badgeText = me.identity_verified_via === 'eimzo' ? 'E-imzo tasdiqlangan'
      : (me.identity_verified_via ? 'OneID tasdiqlangan' : 'Telefon tasdiqlangan');
    list.innerHTML = `
      <div class="hp-setting-item">
        <div>
          <strong>${fullName ? esc(fullName) : 'Ism-familiya kiritilmagan'}</strong>
          <p>${esc(roleLabel)} · Tel: ${esc(me.phone || '—')}${prof.region ? ` · ${esc(prof.region)}` : ''}</p>
          ${fullName ? '' : `<p style="color:#B45309;">Shartnomalarda va imzo varag'ida to'g'ri ko'rinishi uchun F.I.Sh.ni kiriting.</p>`}
        </div>
        <button type="button" class="${fullName ? 'hp-btn-outline-sm' : 'hp-btn-navy-sm'}" data-open-profile>${fullName ? 'O\'zgartirish' : 'Ism-familiyani kiritish'}</button>
      </div>
      <div class="hp-setting-item">
        <div>
          <strong>Shaxsni tasdiqlash</strong>
          <p>${me.identity_verified_via ? `Tasdiqlangan: ${esc(formatDateDdMmYyyy(me.identity_verified_at))}` : 'Telefon raqami SMS-kod orqali tasdiqlangan'}</p>
        </div>
        <span class="hp-pill-badge hp-pill-success">${esc(badgeText)}</span>
      </div>
      <div class="hp-setting-item">
        <div>
          <strong>Faol tomon (demo)</strong>
          <p>Hozir ${esc(LexLab.activeSlot() === 'party_b' ? '2-Tomon' : '1-Tomon')} sifatida ishlayapsiz.</p>
        </div>
      </div>
    `;
    list.querySelectorAll('[data-open-profile]').forEach(b => b.addEventListener('click', openProfileModal));
  }

  function openProfileModal() {
    const me = state.me;
    if (!me) return;
    const prof = me.profile || {};
    const n = splitFullName(prof.full_name);
    const regionOptions = ['<option value="">— tanlang —</option>']
      .concat(REGIONS.map(r => `<option value="${esc(r)}"${prof.region === r ? ' selected' : ''}>${esc(r)}</option>`))
      .join('');

    openModal(
      'Foydalanuvchi profili',
      `
      <form id="profile-edit-form" class="hp-builder-form" novalidate>
        <div class="hp-form-row-2">
          <div class="hp-form-group">
            <label>Telefon raqami</label>
            <input type="text" class="hp-input" value="${esc(me.phone || '')}" disabled />
          </div>
          <div class="hp-form-group">
            <label>Rol</label>
            <input type="text" class="hp-input" value="${esc(ROLE_LABELS[me.role] || me.role || '')}" disabled />
          </div>
        </div>
        <div class="hp-form-row-2">
          <div class="hp-form-group">
            <label for="profile-last-input">Familiya *</label>
            <input type="text" id="profile-last-input" class="hp-input" value="${esc(n.last)}" placeholder="Masalan: Karimov" maxlength="60" autocomplete="family-name" />
          </div>
          <div class="hp-form-group">
            <label for="profile-first-input">Ism *</label>
            <input type="text" id="profile-first-input" class="hp-input" value="${esc(n.first)}" placeholder="Masalan: Abdullo" maxlength="60" autocomplete="given-name" />
          </div>
        </div>
        <div class="hp-form-row-2">
          <div class="hp-form-group">
            <label for="profile-middle-input">Otasining ismi</label>
            <input type="text" id="profile-middle-input" class="hp-input" value="${esc(n.middle)}" placeholder="Masalan: Aliyevich" maxlength="80" autocomplete="additional-name" />
          </div>
          <div class="hp-form-group">
            <label for="profile-region-input">Hudud</label>
            <select id="profile-region-input" class="hp-input">${regionOptions}</select>
          </div>
        </div>
        <span class="hp-field-hint" id="profile-error" style="color:#DC2626;" hidden></span>
        <span class="hp-field-hint">Shartnomalarda shu ko'rinishda chiqadi: <strong id="profile-preview">${esc(prof.full_name || '—')}</strong></span>
        <div class="hp-builder-actions">
          <button type="submit" class="hp-btn-navy" id="btn-save-profile">Saqlash</button>
        </div>
      </form>
      `
    );

    const form = document.getElementById('profile-edit-form');
    const btn = document.getElementById('btn-save-profile');
    const errEl = document.getElementById('profile-error');
    const val = id => capitalizeName(document.getElementById(id)?.value);
    const compose = () => [val('profile-last-input'), val('profile-first-input'), val('profile-middle-input')].filter(Boolean).join(' ');
    const showErr = (msg, focusId) => {
      if (errEl) { errEl.textContent = msg; errEl.hidden = !msg; }
      if (focusId) document.getElementById(focusId)?.focus();
    };
    form?.addEventListener('input', () => {
      const p = document.getElementById('profile-preview');
      if (p) p.textContent = compose() || '—';
      showErr('');
    });
    form?.addEventListener('submit', (e) => {
      e.preventDefault();
      const last = val('profile-last-input');
      const first = val('profile-first-input');
      const middle = val('profile-middle-input');
      if (!last) return showErr('Familiyani kiriting', 'profile-last-input');
      if (!first) return showErr('Ismni kiriting', 'profile-first-input');
      for (const [v, id, label] of [[last, 'profile-last-input', 'Familiya'], [first, 'profile-first-input', 'Ism'], [middle, 'profile-middle-input', 'Otasining ismi']]) {
        if (v && (!NAME_PART_RE.test(v) || v.length < 2)) return showErr(`${label} faqat harflardan iborat bo'lishi kerak`, id);
      }
      const region = document.getElementById('profile-region-input')?.value || null;
      withBusy(btn, async () => {
        await LexLab.me.profile({ full_name: compose(), region });
        await loadMe();
        closeModal();
        showToast('Profil ma\'lumotlari saqlandi');
      }).catch((err) => showErr(LexLab.humanError(err)));
    });
  }

  // ==================== §5 DASHBOARD ====================
  async function loadDashboard() {
    const d = await LexLab.dashboard();
    state.dashboardData = d;

    const countBadge = document.getElementById('nav-contracts-count');
    if (countBadge) countBadge.textContent = String(d.contracts?.total ?? 0);

    const notifDot = document.querySelector('#btn-notif-panel .hp-notif-dot');
    if (notifDot) {
      notifDot.style.display = (d.notifications_unread || 0) > 0 ? 'block' : 'none';
    }

    const invCount = d.invitations || 0;
    const badgeB = document.getElementById('party-b-pending-count');
    if (badgeB) {
      badgeB.textContent = String(invCount);
      badgeB.style.display = invCount > 0 ? 'inline-block' : 'none';
    }

    const bannerEl = document.getElementById('bilateral-inbox-banner');
    if (bannerEl) {
      if (invCount > 0) {
        bannerEl.hidden = false;
        bannerEl.innerHTML = `
          <div class="hp-guide-left">
            <span class="hp-guide-step-pill">YANGI TAKLIF (${invCount})</span>
            <div class="hp-guide-text">
              <strong>Sizga ko'rib chiqish va kelishish uchun ${invCount} ta shartnoma taklifi kelgan</strong>
              <span>Shartnoma matni va ogohlantirishlarni ko'rib chiqib, qabul qilishingiz mumkin.</span>
            </div>
          </div>
          <div class="hp-guide-actions">
            <button type="button" class="hp-btn-navy-sm" id="btn-open-invitations">Takliflarni ko'rish</button>
          </div>
        `;
      } else {
        bannerEl.hidden = true;
        bannerEl.innerHTML = '';
      }
    }

    renderDashboardContractsTable(d.contracts?.recent || []);
    renderDashboardLastScan(d.last_scan);

    const overdue = d.obligations?.overdue || [];
    const upcoming = d.obligations?.upcoming_30d || [];
    renderDashboardTimeline(overdue.concat(upcoming).slice(0, 3));
  }

  function renderDashboardContractsTable(recent) {
    const tbody = document.getElementById('dash-contracts-tbody');
    if (!tbody) return;

    if (!recent || recent.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="4" class="hp-text-muted" style="text-align:center;padding:18px;">
            Hozircha shartnomalar yo'q
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = recent.map(c => {
      const pNames = c.party_names || {};
      const partyLabel = pNames.B || pNames.A || '—';
      const badgeHtml = contractStatusBadgeHtml(c.status);

      return `
        <tr data-contract-id="${esc(c.id)}">
          <td class="hp-doc-title-cell">${esc(c.title)}</td>
          <td><div class="hp-party-cell">${badgeHtml} <span>${esc(partyLabel)}</span></div></td>
          <td>${esc(formatDateDdMmYyyy(c.created_at))}</td>
          <td class="hp-td-right">
            <button type="button" class="hp-btn-outline-sm" data-inspect-contract="${esc(c.id)}">Ko'rish</button>
          </td>
        </tr>
      `;
    }).join('');
  }

  function setDashScanEyebrow() {
    const el = document.querySelector('[data-i18n="ai_analysis_eyebrow"]');
    if (!el) return;
    const base = (i18n[state.lang] || i18n.uz).ai_analysis_eyebrow || 'AI Shartnoma tahlili';
    el.textContent = state.lastScanTitle ? `${base} (${shortTitle(state.lastScanTitle, 48)})` : base;
    el.title = state.lastScanTitle || '';
  }

  function renderDashboardLastScan(lastScan) {
    const arcEl = document.getElementById('dash-gauge-arc');
    const needleEl = document.getElementById('dash-gauge-needle');
    const line1El = document.getElementById('dash-gauge-line1');
    const line2El = document.getElementById('dash-gauge-line2');
    const clause1El = document.getElementById('dash-clause-1');
    const clause2El = document.getElementById('dash-clause-2');

    if (!lastScan) {
      state.lastScanTitle = null;
      setDashScanEyebrow();
      if (arcEl) arcEl.setAttribute('stroke-dashoffset', '88');
      if (needleEl) needleEl.setAttribute('transform', 'translate(100, 92.9) rotate(-92.3)');
      if (line1El) line1El.textContent = "Tahlil";
      if (line2El) line2El.textContent = "yo'q";
      if (clause1El) {
        clause1El.hidden = false;
        clause1El.className = 'hp-clause-alert';
        clause1El.innerHTML = `
          <div class="hp-clause-top">
            <span class="hp-pill-badge">Ma'lumot</span>
            <strong class="hp-clause-name">Hali tahlil yo'q — shartnomani tekshiring</strong>
          </div>
          <p class="hp-clause-desc">Shartnomani tekshir bo'limiga o'tib hujjatingizni tahlil qiling.</p>
        `;
      }
      if (clause2El) clause2El.hidden = true;
      return;
    }

    state.lastScanTitle = lastScan.title || null;
    setDashScanEyebrow();
    const pct = Math.min(100, Math.max(0, Number(lastScan.risk_percent ?? 0)));
    const dashOffset = Math.min(96, Math.max(0, 100 - pct));
    const visiblePct = 100 - dashOffset;
    const angle = (-121.42 + 2.4284 * visiblePct).toFixed(2);

    if (arcEl) arcEl.setAttribute('stroke-dashoffset', String(dashOffset));
    if (needleEl) needleEl.setAttribute('transform', `translate(100, 92.9) rotate(${angle})`);

    const labelParts = String(lastScan.risk_label || 'Past xavf').split(/\s+/);
    if (line1El) line1El.textContent = labelParts[0] || 'Past';
    if (line2El) line2El.textContent = labelParts.slice(1).join(' ') || 'xavf';

    const findings = lastScan.top_findings || [];

    if (clause1El) {
      if (findings[0]) {
        const f0 = findings[0];
        const isRed = f0.severity === 'red';
        const pillCls = isRed ? 'hp-pill-danger' : (f0.severity === 'yellow' ? 'hp-pill-warning' : 'hp-pill-success');
        const pillText = isRed ? 'Qonunga zid' : (f0.severity === 'yellow' ? 'Qaltis band' : 'Maslahat');
        const feedbackText = f0.user_decision === 'agree'
          ? 'Rozilik bildirildi'
          : (f0.user_decision === 'object' ? 'E\'tiroz bildirildi' : '');

        clause1El.hidden = false;
        clause1El.className = `hp-clause-alert ${isRed ? 'hp-clause-illegal' : 'hp-clause-risky'}`;
        clause1El.innerHTML = `
          <div class="hp-clause-main-row">
            <span class="hp-pill-badge ${pillCls}">${esc(pillText)}</span>
            <p class="hp-clause-text" id="dash-clause-1-text">
              ${esc(f0.explanation)}
              ${f0.law_ref ? `<br/><small class="hp-text-muted">${lawRefLink(f0.law_ref)}</small>` : ''}
            </p>
          </div>
          ${f0.severity !== 'blue' ? adviceHtml(f0.suggestion) : ''}
          <div class="hp-clause-actions-row">
            <span class="hp-decision-feedback" id="dash-clause-1-status">${esc(feedbackText)}</span>
            <div class="hp-clause-btns">
              <button type="button" class="hp-btn-navy-sm" data-clause-action="agree" data-scan-id="${esc(lastScan.id)}" data-finding-id="${esc(f0.id)}">Roziman</button>
              <button type="button" class="hp-btn-outline-sm" data-clause-action="object" data-scan-id="${esc(lastScan.id)}" data-finding-id="${esc(f0.id)}">E'tiroz</button>
            </div>
          </div>
          <div class="hp-clause-detail-collapse" id="dash-clause-1-detail" hidden></div>
        `;
      } else {
        clause1El.className = 'hp-clause-alert';
        clause1El.innerHTML = `
          <div class="hp-clause-main-row">
            <span class="hp-pill-badge hp-pill-success">Toza</span>
            <p class="hp-clause-text">Xavfli bandlar aniqlanmadi</p>
          </div>
        `;
      }
    }

    if (clause2El) {
      if (findings[1]) {
        const f1 = findings[1];
        const isRed = f1.severity === 'red';
        const pillCls = isRed ? 'hp-pill-danger' : (f1.severity === 'yellow' ? 'hp-pill-warning' : 'hp-pill-success');
        const pillText = isRed ? 'Qonunga zid' : (f1.severity === 'yellow' ? 'Qaltis band' : 'Maslahat');

        clause2El.hidden = false;
        clause2El.className = `hp-clause-alert ${isRed ? 'hp-clause-illegal' : 'hp-clause-risky'}`;
        clause2El.innerHTML = `
          <div class="hp-clause-main-row">
            <span class="hp-pill-badge ${pillCls}">${esc(pillText)}</span>
            <p class="hp-clause-text" id="dash-clause-2-text">
              ${esc(f1.explanation)}
              ${f1.law_ref ? `<br/><small class="hp-text-muted">${lawRefLink(f1.law_ref)}</small>` : ''}
            </p>
          </div>
          ${f1.severity !== 'blue' ? adviceHtml(f1.suggestion) : ''}
        `;
      } else {
        clause2El.hidden = true;
      }
    }
  }

  function renderDashboardTimeline(items) {
    const container = document.getElementById('dash-timeline-list');
    if (!container) return;

    if (!items || items.length === 0) {
      container.innerHTML = `
        <div class="hp-timeline-item">
          <div class="hp-timeline-rail">
            <span class="hp-timeline-dot hp-dot-gray"></span>
          </div>
          <div class="hp-timeline-content">
            <span class="hp-timeline-title hp-text-muted">Hozircha yaqin majburiyatlar yo'q</span>
          </div>
        </div>
      `;
      return;
    }

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    container.innerHTML = items.map((ob, idx) => {
      const due = new Date(ob.due_date);
      due.setHours(0, 0, 0, 0);
      const diffDays = Math.round((due - today) / 86400000);
      const daysText = diffDays < 0
        ? `(${Math.abs(diffDays)} kun o'tgan)`
        : (diffDays === 0 ? '(Bugun)' : `(${diffDays} kun qoldi)`);
      const dotCls = diffDays < 0 ? 'hp-dot-gray' : (idx === 0 ? 'hp-dot-emerald' : 'hp-dot-teal');
      const hasLine = idx < items.length - 1;
      const amtText = ob.amount ? ` — ${formatNumberUz(ob.amount)} ${ob.currency || 'UZS'}` : '';

      return `
        <div class="hp-timeline-item" data-ob-id="${esc(ob.id)}">
          <div class="hp-timeline-rail">
            <span class="hp-timeline-dot ${dotCls}"></span>
            ${hasLine ? `<span class="hp-timeline-line hp-line-emerald"></span>` : ''}
          </div>
          <div class="hp-timeline-content">
            <div class="hp-timeline-row">
              <span class="hp-timeline-title">${esc(ob.title)}${esc(amtText)} <strong class="hp-timeline-days">${esc(daysText)}</strong></span>
              <button type="button" class="hp-btn-outline-sm" data-dash-ob-done="${esc(ob.id)}" title="Bajarildi">✓</button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  async function loadBhmRate() {
    try {
      const res = await LexLab.calc.bhm();
      if (res && res.amount) {
        state.bhmBaseValue = Number(res.amount) || 440000;
      }
    } catch (e) {
      // ignore if not logged in
    }
    updateBhmCalculator();
  }

  function updateBhmCalculator() {
    const countInput = document.getElementById('bhm-count-input');
    const outputEl = document.getElementById('bhm-calculated-output');
    const rateEl = document.getElementById('bhm-rate-text');
    if (rateEl) rateEl.textContent = formatNumberUz(state.bhmBaseValue, 0);
    if (!countInput || !outputEl) return;

    const count = Math.max(1, parseFloat(countInput.value) || 1);
    const total = state.bhmBaseValue * count;
    outputEl.textContent = `${formatNumberUz(total, 0)} so'm`;
  }

  // ==================== §6 & U2.1–U2.3 BUILDER & TWO-PARTY NEGOTIATION ====================
  function resolveTypeCode(code) {
    if (!code) return null;
    return LEGACY_TYPE_MAP[code] || code;
  }

  function draftStorageKey(code) {
    return `lexlab.draft.${LexLab.activeSlot()}.${code}`;
  }

  async function ensureContractTypesLoaded() {
    const selectEl = document.getElementById('cb-type');
    if (!selectEl) return;
    if (!state.contractTypes || state.contractTypes.length === 0) {
      state.contractTypes = (await LexLab.types.list()) || [];
    }
    selectEl.innerHTML = state.contractTypes.map(t => {
      const srcKind = t.source && t.source.kind;
      const suffix = srcKind === 'lexuz'
        ? ' (lex.uz rasmiy shakl)'
        : (srcKind === 'organization' ? ' (tashkilot shabloni)' : '');
      return `<option value="${esc(t.code)}">${esc(t.title_uz + suffix)}</option>`;
    }).join('');
  }

  async function initBuilder(preselectCode) {
    await ensureContractTypesLoaded();
    const selectEl = document.getElementById('cb-type');
    const targetCode = resolveTypeCode(preselectCode) || (state.contractTypes[0] && state.contractTypes[0].code);
    if (targetCode) {
      if (selectEl) selectEl.value = targetCode;
      await selectBuilderType(targetCode);
    }
  }

  async function openContractInBuilder(contractId) {
    if (state.builderDebounceTimer) {
      clearTimeout(state.builderDebounceTimer);
      state.builderDebounceTimer = null;
    }
    state.builderPendingPatch = {};

    await ensureContractTypesLoaded();
    const c = await LexLab.contracts.get(contractId);
    const typeObj = state.contractTypes.find(t => t.id === c.type_id) || state.contractTypes[0];
    const code = typeObj ? typeObj.code : 'rent_commercial';

    const selectEl = document.getElementById('cb-type');
    if (selectEl) selectEl.value = code;

    const t = await LexLab.types.get(code);
    state.builderTypeCode = code;
    state.builderTypeDetail = t;
    state.builderContractId = c.id;
    state.builderAnswers = c.answers || {};
    sessionStorage.setItem(draftStorageKey(code), c.id);

    const n = await LexLab.contracts.negotiation(c.id);
    state.builderNegotiation = n;

    renderQuestionnaireForm(t, state.builderAnswers, n);
    renderBuilderNegotiationAndValidation(n);
    await refreshBuilderPreview();
    navigateTo('builder');
  }

  async function selectBuilderType(rawCode) {
    const code = resolveTypeCode(rawCode);
    if (!code) return;

    if (state.builderDebounceTimer) {
      clearTimeout(state.builderDebounceTimer);
      state.builderDebounceTimer = null;
    }
    state.builderPendingPatch = {};

    const t = await LexLab.types.get(code);
    state.builderTypeCode = code;
    state.builderTypeDetail = t;

    let draftContract = null;
    const savedId = sessionStorage.getItem(draftStorageKey(code));
    if (savedId) {
      try {
        const existing = await LexLab.contracts.get(savedId);
        if (existing && (existing.status === 'draft' || existing.status === 'pending_approval')) {
          draftContract = existing;
        }
      } catch (e) {
        sessionStorage.removeItem(draftStorageKey(code));
      }
    }

    if (!draftContract) {
      const created = await LexLab.contracts.create(code, 'A');
      draftContract = await LexLab.contracts.get(created.id);
      sessionStorage.setItem(draftStorageKey(code), draftContract.id);
    }

    state.builderContractId = draftContract.id;
    state.builderAnswers = draftContract.answers || {};

    const n = await LexLab.contracts.negotiation(state.builderContractId);
    state.builderNegotiation = n;

    renderQuestionnaireForm(t, state.builderAnswers, n);
    renderBuilderNegotiationAndValidation(n);
    await refreshBuilderPreview();
  }

  function buildFieldOwnershipMap(neg) {
    const map = {};
    if (neg && Array.isArray(neg.fields)) {
      neg.fields.forEach(f => {
        map[f.key] = { side: f.side, editable: f.editable };
      });
    }
    return map;
  }

  function getFieldOwnership(fieldKey, ownershipMap, neg) {
    if (ownershipMap[fieldKey]) return ownershipMap[fieldKey];
    const root = String(fieldKey).split('.')[0];
    if (ownershipMap[root]) return ownershipMap[root];
    const side = root === 'party_a' ? 'A' : (root === 'party_b' ? 'B' : 'shared');
    const editable = !neg || !neg.both_joined || side === 'shared' || side === neg.my_side;
    return { side, editable };
  }

  function renderQuestionnaireForm(typeDetail, existingAnswers, neg) {
    const form = document.getElementById('contract-builder-form');
    if (!form) return;

    let dynContainer = document.getElementById('cb-dynamic-questionnaire');
    if (!dynContainer) {
      const typeGroup = document.getElementById('cb-type')?.closest('.hp-form-group');
      const alertsEl = document.getElementById('cb-rule-alerts-list');
      const actionsEl = form.querySelector('.hp-builder-actions');

      Array.from(form.children).forEach(child => {
        if (child !== typeGroup && child !== alertsEl && child !== actionsEl) {
          child.remove();
        }
      });

      dynContainer = document.createElement('div');
      dynContainer.id = 'cb-dynamic-questionnaire';
      dynContainer.className = 'hp-builder-form';
      form.insertBefore(dynContainer, alertsEl);
    }

    // Ensure "Norozilik bildirish" button exists in .hp-builder-actions
    const actionsEl = form.querySelector('.hp-builder-actions');
    if (actionsEl && !document.getElementById('btn-builder-object')) {
      const objBtn = document.createElement('button');
      objBtn.type = 'button';
      objBtn.id = 'btn-builder-object';
      objBtn.className = 'hp-btn-outline';
      objBtn.textContent = 'Norozilik bildirish';
      actionsEl.insertBefore(objBtn, document.getElementById('btn-builder-generate'));
      objBtn.addEventListener('click', () => {
        if (state.builderContractId) openObjectionModal(state.builderContractId);
      });
    }

    state.builderFieldMap = {};
    state.builderFieldDefs = [];
    const ownershipMap = buildFieldOwnershipMap(neg);
    const mySide = (neg && neg.my_side) || 'A';

    const sections = (typeDetail.questionnaire && typeDetail.questionnaire.sections) || [];
    const allFields = [];
    sections.forEach(s => (s.fields || []).forEach(f => {
      allFields.push(f);
      state.builderFieldDefs.push(f);
    }));
    const hasPartyBStir = allFields.some(f => f.key === 'party_b.stir');

    let html = '';
    const defaultPatch = {};

    sections.forEach(sec => {
      const fields = sec.fields || [];
      if (fields.length === 0) return;

      // U2.3.1: Next to a section owned by the other side, show a muted «2-tomon to'ldiradi»
      const sectionSides = fields.map(f => getFieldOwnership(f.key, ownershipMap, neg).side);
      const isOtherSideSection = sectionSides.length > 0 && sectionSides.every(s => s !== 'shared' && s !== mySide);
      const otherNote = isOtherSideSection
        ? ` <span class="hp-text-muted" style="font-weight:400;font-size:12px;">(2-tomon to'ldiradi)</span>`
        : '';

      html += `<div style="font-size:13px;font-weight:700;color:var(--text-secondary);margin-top:6px;">${esc(sec.title || '')}${otherNote}</div>`;

      let i = 0;
      while (i < fields.length) {
        const f1 = fields[i];
        const f2 = fields[i + 1];
        if (f1.type === 'text' || !f2 || f2.type === 'text') {
          html += renderQuestionnaireFieldHtml(f1, existingAnswers, hasPartyBStir, defaultPatch, ownershipMap, neg);
          i += 1;
        } else {
          html += `<div class="hp-form-row-2">
            ${renderQuestionnaireFieldHtml(f1, existingAnswers, hasPartyBStir, defaultPatch, ownershipMap, neg)}
            ${renderQuestionnaireFieldHtml(f2, existingAnswers, hasPartyBStir, defaultPatch, ownershipMap, neg)}
          </div>`;
          i += 2;
        }
      }
    });

    dynContainer.innerHTML = html;

    if (Object.keys(defaultPatch).length > 0 && state.builderContractId) {
      LexLab.contracts.saveAnswers(state.builderContractId, defaultPatch)
        .then(() => refreshBuilderNegotiation())
        .catch(() => {});
    }
  }

  function renderQuestionnaireFieldHtml(field, existingAnswers, hasPartyBStir, defaultPatch, ownershipMap, neg) {
    const fType = field.type || 'string';
    const actualKey = fType === 'party' ? `${field.key}.name` : field.key;
    state.builderFieldMap[actualKey] = field.label || actualKey;
    state.builderFieldMap[field.key] = field.label || field.key;

    const own = getFieldOwnership(actualKey, ownershipMap, neg);
    const isEditable = own.editable !== false;
    const disabledAttr = isEditable ? '' : 'disabled';

    let currentVal = getPath(existingAnswers, actualKey);
    if ((currentVal === undefined || currentVal === null || currentVal === '') && field.default !== undefined && isEditable) {
      currentVal = field.default;
      defaultPatch[actualKey] = field.default;
    }
    const valStr = currentVal !== undefined && currentVal !== null ? String(currentVal) : '';
    const reqStar = field.required ? ' *' : '';
    const placeholder = field.hint || '';

    let inputHtml = '';
    if (fType === 'text') {
      inputHtml = `<textarea class="hp-input" rows="2" data-q-key="${esc(actualKey)}" data-q-type="text" placeholder="${esc(placeholder)}" ${disabledAttr}>${esc(valStr)}</textarea>`;
    } else if (fType === 'enum') {
      const opts = (field.options || []).map(o => {
        const oVal = typeof o === 'object' ? o.value : o;
        const oLabel = typeof o === 'object' ? o.label : o;
        const sel = String(oVal) === valStr ? 'selected' : '';
        return `<option value="${esc(oVal)}" ${sel}>${esc(oLabel)}</option>`;
      }).join('');
      inputHtml = `
        <select class="hp-input" data-q-key="${esc(actualKey)}" data-q-type="enum" ${disabledAttr}>
          <option value="">— Tanlang —</option>
          ${opts}
        </select>
      `;
    } else if (fType === 'number') {
      const minAttr = field.min !== undefined ? `min="${esc(field.min)}"` : '';
      const maxAttr = field.max !== undefined ? `max="${esc(field.max)}"` : '';
      inputHtml = `<input type="number" class="hp-input" data-q-key="${esc(actualKey)}" data-q-type="number" value="${esc(valStr)}" ${minAttr} ${maxAttr} step="any" placeholder="${esc(placeholder)}" ${disabledAttr} />`;
    } else if (fType === 'date') {
      inputHtml = `<input type="date" class="hp-input" data-q-key="${esc(actualKey)}" data-q-type="date" value="${esc(valStr)}" ${disabledAttr} />`;
    } else {
      inputHtml = `<input type="text" class="hp-input" data-q-key="${esc(actualKey)}" data-q-type="string" value="${esc(valStr)}" placeholder="${esc(placeholder)}" ${disabledAttr} />`;
    }

    const isStirLookupField =
      actualKey === 'party_b.stir' || (!hasPartyBStir && actualKey === 'party_b.tin');

    if (isStirLookupField) {
      inputHtml = `
        <div class="hp-input-with-btn">
          ${inputHtml}
          <button type="button" class="hp-mini-lookup-btn" id="btn-stir-lookup-b" ${disabledAttr}>STIR orqali topish</button>
        </div>
      `;
    }

    return `
      <div class="hp-form-group">
        <label>${esc(field.label || actualKey)}${reqStar}</label>
        ${inputHtml}
        <span class="hp-field-hint" data-field-err="${esc(actualKey)}" style="color:#DC2626;" hidden></span>
        <div data-field-warn="${esc(actualKey)}"></div>
      </div>
    `;
  }

  function applyFieldOwnershipAndValues(neg, answers) {
    const ownershipMap = buildFieldOwnershipMap(neg);
    document.querySelectorAll('#cb-dynamic-questionnaire [data-q-key]').forEach(el => {
      const key = el.getAttribute('data-q-key');
      const own = getFieldOwnership(key, ownershipMap, neg);
      el.disabled = own.editable === false;
      if (answers && document.activeElement !== el) {
        const v = getPath(answers, key);
        const vStr = v !== undefined && v !== null ? String(v) : '';
        if (el.value !== vStr) el.value = vStr;
      }
    });
    const stirBtn = document.getElementById('btn-stir-lookup-b');
    if (stirBtn) {
      const ownB = getFieldOwnership('party_b.stir', ownershipMap, neg);
      stirBtn.disabled = ownB.editable === false;
    }
  }

  function collectFieldValue(el) {
    const qType = el.getAttribute('data-q-type') || 'string';
    const raw = el.value;
    if (qType === 'number') {
      if (raw === '' || raw === null) return null;
      const n = Number(raw);
      return Number.isFinite(n) ? n : raw;
    }
    return raw.trim() === '' ? null : raw;
  }

  function queueBuilderAnswerSave(key, value) {
    if (!state.builderContractId || !key) return;
    state.builderPendingPatch[key] = value;

    if (state.builderDebounceTimer) clearTimeout(state.builderDebounceTimer);
    state.builderDebounceTimer = setTimeout(() => {
      flushBuilderAnswers().catch(handleErr);
    }, 600);
  }

  async function flushBuilderAnswers() {
    if (state.builderDebounceTimer) {
      clearTimeout(state.builderDebounceTimer);
      state.builderDebounceTimer = null;
    }
    const patch = Object.assign({}, state.builderPendingPatch);
    state.builderPendingPatch = {};
    if (Object.keys(patch).length === 0 || !state.builderContractId) return null;

    const r = await LexLab.contracts.saveAnswers(state.builderContractId, patch);
    await refreshBuilderNegotiation(r);
    await refreshBuilderPreview();
    return r;
  }

  async function refreshBuilderNegotiation(latestValidation) {
    if (!state.builderContractId) return null;
    const [c, n] = await Promise.all([
      LexLab.contracts.get(state.builderContractId),
      LexLab.contracts.negotiation(state.builderContractId)
    ]);
    state.builderAnswers = c.answers || {};
    if (latestValidation && latestValidation.field_warnings) {
      n.validation = latestValidation;
    }
    state.builderNegotiation = n;
    applyFieldOwnershipAndValues(n, state.builderAnswers);
    renderBuilderNegotiationAndValidation(n);
    return n;
  }

  function renderFieldWarnings(fieldWarnings) {
    document.querySelectorAll('#cb-dynamic-questionnaire [data-field-warn]').forEach(wContainer => {
      wContainer.innerHTML = '';
    });
    if (!fieldWarnings) return;

    Object.keys(fieldWarnings).forEach(key => {
      const warnings = fieldWarnings[key] || [];
      const wContainer = document.querySelector(`#cb-dynamic-questionnaire [data-field-warn="${CSS.escape(key)}"]`);
      if (wContainer && warnings.length > 0) {
        wContainer.innerHTML = warnings.map(w => {
          const cls = w.severity === 'red' ? 'hp-rule-red' : (w.severity === 'yellow' ? 'hp-rule-amber' : 'hp-rule-green');
          return `
            <div class="hp-rule-item ${cls}" style="margin-top:4px;padding:6px 10px;">
              <strong>${esc(w.message)}</strong>
              ${adviceHtml(w.fix_suggestion)}
              ${w.law_ref ? `<span>Asos: ${lawRefLink(w.law_ref, w.lex_url)}</span>` : ''}
            </div>
          `;
        }).join('');
      }
    });
  }

  function renderBuilderNegotiationAndValidation(n) {
    if (!n) return;
    const r = n.validation || {};

    // 1. Field format errors
    document.querySelectorAll('#cb-dynamic-questionnaire [data-q-key]').forEach(inp => {
      inp.style.borderColor = '';
    });
    document.querySelectorAll('#cb-dynamic-questionnaire [data-field-err]').forEach(errEl => {
      errEl.hidden = true;
      errEl.textContent = '';
    });

    (r.field_errors || []).forEach(fe => {
      const inp = document.querySelector(`#cb-dynamic-questionnaire [data-q-key="${CSS.escape(fe.field)}"]`);
      const errEl = document.querySelector(`#cb-dynamic-questionnaire [data-field-err="${CSS.escape(fe.field)}"]`);
      if (inp) inp.style.borderColor = '#DC2626';
      if (errEl) {
        errEl.textContent = fe.error || 'Format noto\'g\'ri';
        errEl.hidden = false;
      }
    });

    // 2. Live warnings under individual fields (U2.3.2)
    renderFieldWarnings(r.field_warnings);

    // 3. Update primary Builder button (#btn-builder-generate) based on negotiation state (U2.2)
    const genBtn = document.getElementById('btn-builder-generate');
    if (genBtn) {
      const nxt = n.next_action;
      const waitActions = [
        'wait_other_party_join',
        'wait_other_party_data',
        'wait_other_party_agreement',
        'wait_objection_answer',
        'wait_signatures'
      ];
      if (nxt === 'agree' || (n.both_joined && n.status === 'draft' && !waitActions.includes(nxt))) {
        genBtn.textContent = 'Shartlarga roziman';
        genBtn.disabled = !!(r.summary && r.summary.blocking);
      } else if (waitActions.includes(nxt)) {
        genBtn.textContent = n.next_action_text || 'Ikkinchi tomon kutilmoqda';
        genBtn.disabled = true;
      } else if (nxt === 'sign') {
        genBtn.textContent = 'Imzolash (SMS-kod)';
        genBtn.disabled = false;
      } else if (['active', 'completed', 'disputed', 'expired', 'cancelled'].includes(nxt)) {
        genBtn.textContent = 'Arxivda ko\'rish';
        genBtn.disabled = false;
      } else {
        genBtn.textContent = 'Shartnomani yaratish';
        genBtn.disabled = false;
      }
    }

    // 4. Overall negotiation & validation alerts in #cb-rule-alerts-list
    const alertsContainer = document.getElementById('cb-rule-alerts-list');
    if (!alertsContainer) return;

    const itemsHtml = [];

    // Negotiation next_action banner + primary action widget (U2.2)
    itemsHtml.push(renderNegotiationActionCardHtml(n, 'builder'));

    // Open objections cards (U2.3.4)
    if (Array.isArray(n.objections_open) && n.objections_open.length > 0) {
      itemsHtml.push(renderOpenObjectionsHtml(n.contract_id, n.objections_open, n.my_side));
    }

    // Overall legality status
    const counts = (r.summary && r.summary.counts) || {};
    const isBlocking = !!(r.summary && r.summary.blocking);

    if (isBlocking) {
      itemsHtml.push(`
        <div class="hp-rule-item hp-rule-red">
          <strong>Holat: <span class="hp-pill-badge hp-pill-danger">Qonunga zid (${counts.red || 1})</span></strong>
          <span>Qonunga zid shartlar tuzatilmaguncha shartnoma yaratilmaydi.</span>
        </div>
      `);
    } else if ((counts.yellow || 0) > 0) {
      itemsHtml.push(`
        <div class="hp-rule-item hp-rule-amber">
          <strong>Holat: <span class="hp-pill-badge hp-pill-warning">Qaltis bandlar bor (${counts.yellow})</span></strong>
          <span>Shartnomada e'tibor talab qiluvchi bandlar mavjud.</span>
        </div>
      `);
    } else {
      itemsHtml.push(`
        <div class="hp-rule-item hp-rule-blue">
          <strong>Holat: <span class="hp-pill-badge hp-pill-success">Qonunga mos</span></strong>
          <span>Qonunga zid bandlar aniqlanmadi.</span>
        </div>
      `);
    }

    if (r.form && r.form.warning) {
      itemsHtml.push(`
        <div class="hp-rule-item hp-rule-amber">
          <strong>Shakl talabi</strong>
          <span>${esc(r.form.warning)}</span>
        </div>
      `);
    }

    (r.findings || []).forEach(f => {
      const cls = f.severity === 'red' ? 'hp-rule-red' : (f.severity === 'yellow' ? 'hp-rule-amber' : 'hp-rule-green');
      itemsHtml.push(`
        <div class="hp-rule-item ${cls}">
          <strong>${esc(f.message)}</strong>
          ${f.law_ref ? `<span>Asos: ${lawRefLink(f.law_ref, f.lex_url)}</span>` : ''}
          ${adviceHtml(f.fix_suggestion)}
        </div>
      `);
    });

    const missing = r.missing_fields || [];
    if (missing.length > 0) {
      const labels = missing.map(k => state.builderFieldMap[k] || k);
      itemsHtml.push(`
        <div class="hp-rule-item hp-rule-blue">
          <strong>To'ldirilmagan:</strong>
          <span>${esc(labels.join(', '))}</span>
        </div>
      `);
    }

    alertsContainer.innerHTML = itemsHtml.join('');
  }

  function renderNegotiationActionCardHtml(n, contextPrefix) {
    if (!n) return '';
    const nxt = n.next_action;
    const partiesBadges = (n.parties || []).map(p => {
      const statusText = p.signed_at
        ? 'Imzolagan ✓'
        : (p.agreed ? 'Rozi ✓' : (p.joined ? 'Qo\'shilgan' : (p.invited ? 'Taklif yuborilgan' : 'Taklif qilinmagan')));
      const pillCls = p.signed_at || p.agreed ? 'hp-pill-success' : (p.joined ? 'hp-pill-warning' : 'hp-pill-neutral');
      return `<span class="hp-pill-badge ${pillCls}">${esc(p.side)}-Tomon: ${esc(statusText)}</span>`;
    }).join(' ');

    let actionControls = '';
    if (nxt === 'fill_your_data') {
      actionControls = `
        <button type="button" class="hp-btn-outline-sm" data-neg-focus-missing="${esc(n.contract_id)}">
          Bo'sh maydonga o'tish
        </button>
      `;
    } else if (nxt === 'invite_other_party') {
      actionControls = `
        <div class="hp-input-with-btn" style="margin-top:6px;">
          <input type="text" id="${contextPrefix}-neg-invite-phone" class="hp-input" value="+998901110002" placeholder="+998901110002" />
          <button type="button" class="hp-btn-navy-sm" data-neg-invite="${esc(n.contract_id)}" data-phone-input="${contextPrefix}-neg-invite-phone">
            2-tomonni taklif qilish
          </button>
        </div>
      `;
    } else if (nxt === 'fix_illegal_terms') {
      actionControls = `
        <button type="button" class="hp-btn-outline-sm" data-neg-autofix="${esc(n.contract_id)}">
          Avtomatik tuzatish
        </button>
      `;
    } else if (nxt === 'agree') {
      actionControls = `
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;">
          <button type="button" class="hp-btn-navy-sm" data-neg-agree="${esc(n.contract_id)}">Shartlarga roziman</button>
          <button type="button" class="hp-btn-outline-sm" data-neg-open-object="${esc(n.contract_id)}">Norozilik bildirish</button>
        </div>
      `;
    } else if (nxt === 'generate') {
      actionControls = `
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;">
          <button type="button" class="hp-btn-navy-sm" data-neg-generate="${esc(n.contract_id)}">Shartnomani yaratish</button>
        </div>
      `;
    } else if (nxt === 'sign') {
      actionControls = `
        <button type="button" class="hp-btn-navy-sm" data-inspect-contract="${esc(n.contract_id)}">
          Imzolash (SMS-kod)
        </button>
      `;
    } else if (['active', 'completed', 'disputed', 'expired', 'cancelled'].includes(nxt)) {
      actionControls = `
        <button type="button" class="hp-btn-outline-sm" data-goto="archive">
          Arxivda ko'rish
        </button>
      `;
    }

    const ruleCls = nxt === 'fix_illegal_terms'
      ? 'hp-rule-red'
      : (nxt === 'resolve_objections' ? 'hp-rule-amber' : 'hp-rule-blue');

    return `
      <div class="hp-rule-item ${ruleCls}">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
          <strong>Keyingi qadam (${esc(n.my_side || 'A')}-Tomon): ${esc(n.next_action_text || '')}</strong>
          <div>${partiesBadges}</div>
        </div>
        ${actionControls}
      </div>
    `;
  }

  function renderOpenObjectionsHtml(contractId, openObjections, mySide) {
    return (openObjections || []).map(o => {
      const isMine = o.side === mySide;
      const proposedEntries = Object.entries(o.proposed || {});
      const proposedHtml = proposedEntries.length > 0
        ? `<div style="font-size:12.5px;margin-top:4px;">
            <strong>Taklif qilingan o'zgarishlar:</strong>
            ${proposedEntries.map(([k, v]) => `<div>• ${esc(state.builderFieldMap[k] || k)}: <strong>${esc(v)}</strong></div>`).join('')}
           </div>`
        : '';

      const actionsHtml = isMine
        ? `<button type="button" class="hp-btn-outline-sm" data-obj-resolve="${esc(o.id)}" data-obj-contract="${esc(contractId)}" data-obj-action="withdraw">Qaytarib olish</button>`
        : `
          <button type="button" class="hp-btn-navy-sm" data-obj-resolve="${esc(o.id)}" data-obj-contract="${esc(contractId)}" data-obj-action="accept">Qabul qilish</button>
          <button type="button" class="hp-btn-outline-sm" data-obj-resolve="${esc(o.id)}" data-obj-contract="${esc(contractId)}" data-obj-action="reject">Rad etish</button>
        `;

      return `
        <div class="hp-clause-alert hp-clause-risky" style="margin-top:6px;">
          <div class="hp-clause-main-row">
            <span class="hp-pill-badge hp-pill-warning">${esc(o.side)}-Tomon noroziligi</span>
            <p class="hp-clause-text"><strong>${esc(o.comment)}</strong></p>
          </div>
          ${proposedHtml}
          <div class="hp-clause-actions-row" style="margin-top:8px;">
            <span></span>
            <div class="hp-clause-btns">${actionsHtml}</div>
          </div>
        </div>
      `;
    }).join('');
  }

  // U2.3.4 Objection Modal
  async function openObjectionModal(contractId) {
    try {
      const c = await LexLab.contracts.get(contractId);
      const typeObj = state.contractTypes.find(t => t.id === c.type_id) || state.contractTypes[0];
      const tDetail = state.builderTypeDetail && state.builderTypeDetail.id === c.type_id
        ? state.builderTypeDetail
        : (typeObj ? await LexLab.types.get(typeObj.code) : null);

      const sharedFields = [];
      if (tDetail && tDetail.questionnaire && tDetail.questionnaire.sections) {
        tDetail.questionnaire.sections.forEach(sec => {
          (sec.fields || []).forEach(f => {
            const root = String(f.key).split('.')[0];
            if (root !== 'party_a' && root !== 'party_b') {
              sharedFields.push(f);
            }
          });
        });
      }

      const fieldsHtml = sharedFields.map(f => {
        const currentVal = getPath(c.answers || {}, f.key);
        const valStr = currentVal !== undefined && currentVal !== null ? String(currentVal) : '';
        if (f.type === 'enum') {
          const opts = (f.options || []).map(o => {
            const oVal = typeof o === 'object' ? o.value : o;
            const oLabel = typeof o === 'object' ? o.label : o;
            return `<option value="${esc(oVal)}">${esc(oLabel)}</option>`;
          }).join('');
          return `
            <div class="hp-form-group">
              <label>${esc(f.label)} (Taklifim)</label>
              <select class="hp-input" data-prop-key="${esc(f.key)}" data-prop-type="enum" data-orig-val="${esc(valStr)}">
                <option value="">— O'zgartirmaslik (${esc(valStr || 'bo\'sh')}) —</option>
                ${opts}
              </select>
            </div>
          `;
        }
        return `
          <div class="hp-form-group">
            <label>${esc(f.label)} (Taklifim)</label>
            <input type="${f.type === 'number' ? 'number' : (f.type === 'date' ? 'date' : 'text')}"
                   class="hp-input"
                   data-prop-key="${esc(f.key)}"
                   data-prop-type="${esc(f.type || 'string')}"
                   data-orig-val="${esc(valStr)}"
                   placeholder="Hozirgi: ${esc(valStr || '—')}" />
          </div>
        `;
      }).join('');

      openModal(
        'Norozilik bildirish va muqobil taklif',
        `
        <form id="objection-submit-form" class="hp-builder-form">
          <div class="hp-form-group">
            <label for="obj-comment-input">Nimaga rozi emassiz va nima taklif qilasiz? *</label>
            <textarea id="obj-comment-input" class="hp-input" rows="3" placeholder="Izohingizni yozing..." required></textarea>
          </div>
          <div style="font-size:13px;font-weight:700;color:var(--text-secondary);">Shartlar bo'yicha taklifim (ixtiyoriy):</div>
          <div style="max-height:240px;overflow-y:auto;padding-right:4px;" class="hp-builder-form">
            ${fieldsHtml}
          </div>
          <div class="hp-builder-actions">
            <button type="submit" class="hp-btn-navy" id="btn-submit-objection">Norozilikni yuborish</button>
          </div>
        </form>
        `
      );

      const form = document.getElementById('objection-submit-form');
      const btn = document.getElementById('btn-submit-objection');
      form?.addEventListener('submit', (e) => {
        e.preventDefault();
        const comment = (document.getElementById('obj-comment-input')?.value || '').trim();
        const proposed = {};
        const fields = [];

        form.querySelectorAll('[data-prop-key]').forEach(inp => {
          const k = inp.getAttribute('data-prop-key');
          const pType = inp.getAttribute('data-prop-type');
          const raw = inp.value.trim();
          if (raw !== '') {
            fields.push(k);
            proposed[k] = pType === 'number' ? Number(raw) : raw;
          }
        });

        withBusy(btn, async () => {
          await LexLab.contracts.object(contractId, { comment, fields, proposed });
          closeModal();
          showToast('Norozilik yuborildi');
          if (state.builderContractId === contractId) {
            await refreshBuilderNegotiation();
          }
          await loadDashboard();
        }).catch(() => {});
      });
    } catch (e) {
      handleErr(e);
    }
  }

  function renderPreviewDocumentHtml(p) {
    if (!p) return '';
    const titleLines = String(p.title || '').split('\n').map(l => esc(l)).join('<br/>');
    const sectionsHtml = (p.sections || []).map(sec => {
      const paragraphs = String(sec.text || '')
        .split('\n')
        .filter(line => line.trim() !== '')
        .map(line => `<p style="margin:4px 0;">${esc(line)}</p>`)
        .join('');
      return `
        <div style="margin-top:12px;">
          ${sec.title ? `<strong style="display:block;margin-bottom:4px;">${esc(sec.title)}</strong>` : ''}
          ${paragraphs}
        </div>
      `;
    }).join('');

    const sha = p.content_sha256 || p.sha256 || '';

    return `
      <div style="font-size:13px;line-height:1.6;color:var(--text-main);">
        <div style="text-align:center;font-weight:800;font-size:14.5px;margin-bottom:8px;">${titleLines}</div>
        ${p.header ? `<div style="display:flex;justify-content:space-between;font-weight:600;margin-bottom:10px;white-space:pre-wrap;">${esc(p.header)}</div>` : ''}
        ${p.subheader ? `<div style="text-align:center;margin-bottom:10px;white-space:pre-wrap;">${esc(p.subheader)}</div>` : ''}
        ${p.preamble ? `<p style="margin-bottom:10px;">${esc(p.preamble)}</p>` : ''}
        ${sectionsHtml}
        ${p.closing ? `<p style="margin-top:12px;font-style:italic;white-space:pre-wrap;">${esc(p.closing)}</p>` : ''}
        ${sha ? `<div class="hp-text-muted" style="margin-top:16px;padding-top:10px;border-top:1px dashed var(--border-color);font-size:11.5px;word-break:break-all;">SHA-256: ${esc(sha)}</div>` : ''}
      </div>
    `;
  }

  async function refreshBuilderPreview() {
    const previewEl = document.getElementById('cb-doc-preview-content');
    if (!previewEl || !state.builderContractId) return;

    try {
      const p = await LexLab.contracts.preview(state.builderContractId, state.docPreviewLang);
      state.builderPreviewSha256 = p.content_sha256;
      previewEl.innerHTML = renderPreviewDocumentHtml(p);
    } catch (e) {
      if (e && e.code === 'language_unavailable') {
        handleErr(e);
        state.docPreviewLang = 'uz';
        document.querySelectorAll('[data-doc-lang]').forEach(t => {
          t.classList.toggle('active', t.getAttribute('data-doc-lang') === 'uz');
        });
        const pUz = await LexLab.contracts.preview(state.builderContractId, 'uz');
        state.builderPreviewSha256 = pUz.content_sha256;
        previewEl.innerHTML = renderPreviewDocumentHtml(pUz);
      } else {
        throw e;
      }
    }
  }

  async function handleBuilderStirLookup(btn) {
    const stirInput =
      document.querySelector('#cb-dynamic-questionnaire [data-q-key="party_b.stir"]') ||
      document.querySelector('#cb-dynamic-questionnaire [data-q-key="party_b.tin"]');
    const stirVal = (stirInput?.value || '').trim();
    if (!stirVal) {
      showToast('Avval STIR raqamini kiriting');
      stirInput?.focus();
      return;
    }

    await withBusy(btn, async () => {
      const res = await LexLab.lookup.stir(stirVal);
      if (res && res.found) {
        const patch = {};
        const mapping = {
          'party_b.name': res.name,
          'party_b.address': res.address,
          'party_b.director': res.director,
          'party_b.mfo': res.mfo,
          'party_b.oked': res.oked
        };
        Object.keys(mapping).forEach(k => {
          if (mapping[k]) {
            const inp = document.querySelector(`#cb-dynamic-questionnaire [data-q-key="${CSS.escape(k)}"]`);
            if (inp && !inp.disabled) {
              inp.value = mapping[k];
              patch[k] = mapping[k];
            }
          }
        });
        if (Object.keys(patch).length > 0 && state.builderContractId) {
          await LexLab.contracts.saveAnswers(state.builderContractId, patch);
          await refreshBuilderNegotiation();
          await refreshBuilderPreview();
        }
        showToast('Tashkilot ma\'lumotlari to\'ldirildi');
      } else {
        showToast((res && res.message) || 'STIR topilmadi');
      }
    });
  }

  async function handleBuilderAutofix(btn, contractId) {
    const targetId = contractId || state.builderContractId;
    if (!targetId) return;
    await withBusy(btn, async () => {
      if (targetId === state.builderContractId) await flushBuilderAnswers();
      const r = await LexLab.contracts.autofix(targetId);
      const applied = r.applied || [];
      if (applied.length === 0) {
        showToast('Avtomatik tuzatiladigan band yo\'q');
        return;
      }
      if (targetId === state.builderContractId) {
        applied.forEach(item => {
          const inp = document.querySelector(`#cb-dynamic-questionnaire [data-q-key="${CSS.escape(item.field)}"]`);
          if (inp) inp.value = item.value ?? '';
        });
        await refreshBuilderNegotiation(r);
        await refreshBuilderPreview();
      }
      if (state.openModalContractId === targetId) {
        await openContractModal(targetId);
      }
      showToast('Qonunga mos ravishda avtomatik tuzatildi');
    });
  }

  // U2.3.5 Consent (agree)
  async function handleContractAgree(btn, contractId) {
    const targetId = contractId || state.builderContractId;
    if (!targetId) return;
    await withBusy(btn, async () => {
      if (targetId === state.builderContractId) await flushBuilderAnswers();
      try {
        const res = await LexLab.contracts.agree(targetId);
        if (res && res.generated) {
          showToast(`Umumiy shartnoma tayyor (v${res.generated.number})`);
          if (state.builderContractId === targetId) await refreshBuilderNegotiation();
          await loadDashboard();
          await openContractModal(targetId);
        } else {
          showToast('Rozilik saqlandi. 2-tomon kutilmoqda');
          if (state.builderContractId === targetId) await refreshBuilderNegotiation();
          if (state.openModalContractId === targetId) await openContractModal(targetId);
          await loadDashboard();
        }
      } catch (e) {
        if (e && e.code === 'illegal_clauses') {
          if (state.builderContractId === targetId) await refreshBuilderNegotiation();
        }
        throw e;
      }
    });
  }

  // U2.1 & §6.8 Generate (no acknowledge_red override — illegal terms are never generated)
  async function handleBuilderPrimaryAction(btn) {
    if (!state.builderContractId) return;
    const n = state.builderNegotiation;
    if (n) {
      if (n.next_action === 'sign') {
        await openContractModal(state.builderContractId);
        return;
      }
      if (['active', 'completed', 'disputed', 'expired', 'cancelled'].includes(n.next_action)) {
        navigateTo('archive');
        return;
      }
      if (n.both_joined && n.status === 'draft') {
        await handleContractAgree(btn, state.builderContractId);
        return;
      }
    }
    await handleContractGenerate(btn, state.builderContractId);
  }

  async function handleContractGenerate(btn, contractId) {
    const targetId = contractId || state.builderContractId;
    if (!targetId) return;
    await withBusy(btn, async () => {
      if (targetId === state.builderContractId) await flushBuilderAnswers();
      try {
        const g = await LexLab.contracts.generate(targetId, {
          language: state.docPreviewLang
        });
        if (state.builderTypeCode && targetId === state.builderContractId) {
          sessionStorage.removeItem(draftStorageKey(state.builderTypeCode));
        }
        await loadDashboard();
        if (targetId === state.builderContractId) await refreshBuilderNegotiation();
        openGeneratedVersionModal(targetId, g.version);
      } catch (e) {
        if (e && e.code === 'answers_incomplete' && e.details) {
          (e.details.missing || []).forEach(k => {
            const inp = document.querySelector(`#cb-dynamic-questionnaire [data-q-key="${CSS.escape(k)}"]`);
            if (inp) inp.style.borderColor = '#DC2626';
          });
          (e.details.errors || []).forEach(fe => {
            const inp = document.querySelector(`#cb-dynamic-questionnaire [data-q-key="${CSS.escape(fe.field)}"]`);
            const errEl = document.querySelector(`#cb-dynamic-questionnaire [data-field-err="${CSS.escape(fe.field)}"]`);
            if (inp) inp.style.borderColor = '#DC2626';
            if (errEl) {
              errEl.textContent = fe.error;
              errEl.hidden = false;
            }
          });
        } else if (e && e.code === 'illegal_clauses') {
          if (targetId === state.builderContractId) await refreshBuilderNegotiation();
        }
        throw e;
      }
    });
  }

  function openGeneratedVersionModal(contractId, version) {
    const devOtp = (state.meta && state.meta.dev_otp_code) || '111111';
    openModal(
      `Shartnoma yaratildi — Versiya ${version.number}`,
      `
      <div class="hp-builder-form">
        <div class="hp-rule-item hp-rule-blue">
          <strong>Versiya ${esc(version.number)} tayyor</strong>
          <span style="word-break:break-all;">SHA-256: ${esc(version.sha256)}</span>
        </div>

        <div class="hp-builder-actions" style="justify-content:flex-start;">
          <button type="button" class="hp-btn-navy-sm" id="btn-gen-download-docx">DOCX yuklab olish</button>
          <button type="button" class="hp-btn-outline-sm" id="btn-gen-ai-review">AI tekshiruv</button>
        </div>

        <div class="hp-card" style="padding:14px;">
          <div class="hp-form-group">
            <label for="gen-invite-phone">2-tomonni taklif qilish (Telefon raqami)</label>
            <div class="hp-input-with-btn">
              <input type="text" id="gen-invite-phone" class="hp-input" value="+998901110002" placeholder="+998901110002" />
              <button type="button" class="hp-btn-navy-sm" id="btn-gen-send-invite">2-tomonni taklif qilish</button>
            </div>
          </div>
        </div>

        <div class="hp-card" style="padding:14px;">
          <div class="hp-form-group">
            <label for="gen-approve-code">Imzolash (SMS-kod)</label>
            <div class="hp-input-with-btn">
              <input type="text" id="gen-approve-code" class="hp-input" value="${esc(devOtp)}" placeholder="SMS-kod" />
              <button type="button" class="hp-btn-outline-sm" id="btn-gen-req-otp">Kod so'rash</button>
              <button type="button" class="hp-btn-navy-sm" id="btn-gen-approve">Imzolash (SMS-kod)</button>
            </div>
            ${state.meta?.dev_otp_code ? `<span class="hp-field-hint">Demo kod: ${esc(state.meta.dev_otp_code)}</span>` : ''}
          </div>
        </div>

        <div id="gen-ai-review-container"></div>
      </div>
      `,
      { contractId }
    );

    wireContractActionHandlers({
      contractId,
      versionNumber: version.number,
      sha256: version.sha256,
      downloadBtnId: 'btn-gen-download-docx',
      invitePhoneId: 'gen-invite-phone',
      inviteBtnId: 'btn-gen-send-invite',
      reqOtpBtnId: 'btn-gen-req-otp',
      approveCodeId: 'gen-approve-code',
      approveBtnId: 'btn-gen-approve',
      aiReviewBtnId: 'btn-gen-ai-review',
      aiContainerId: 'gen-ai-review-container'
    });
  }

  // ==================== §7 & U2.2–U2.5 CONTRACTS & CONTRACT MODAL & INVITATIONS ====================
  async function loadFullContracts(filter = 'all') {
    state.contractFilter = filter;
    const tab = filter === 'all' ? undefined : filter;
    const list = await LexLab.contracts.list(tab);
    renderFullContractsTable(list || []);
    await loadMediationRequests().catch(() => {});
  }

  function renderFullContractsTable(list) {
    const tbody = document.getElementById('full-contracts-tbody');
    if (!tbody) return;

    if (!list || list.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" class="hp-text-muted" style="text-align:center;padding:20px;">
            Ushbu bo'limda shartnomalar topilmadi
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = list.map(c => {
      const pNames = c.party_names || {};
      const partyA = pNames.A || 'A tomon';
      const partyB = pNames.B || 'B tomon';
      const amt = c.total_amount !== null && c.total_amount !== undefined
        ? `${formatNumberUz(c.total_amount)} ${c.currency || 'UZS'}`
        : '—';

      return `
        <tr data-contract-id="${esc(c.id)}">
          <td class="hp-doc-title-cell">${esc(c.title)}</td>
          <td>${esc(partyA)}</td>
          <td>${esc(partyB)}</td>
          <td>${esc(amt)}</td>
          <td>${contractStatusBadgeHtml(c.status)}</td>
          <td>${esc(formatDateDdMmYyyy(c.created_at))}</td>
          <td class="hp-td-right">
            <button type="button" class="hp-btn-navy-sm" data-inspect-contract="${esc(c.id)}">Ko'rish</button>
          </td>
        </tr>
      `;
    }).join('');
  }

  // Snapshot of what the user typed / received in the open contract modal, so a refresh does not wipe it.
  function captureModalState() {
    const body = document.getElementById('hp-modal-body');
    if (!body) return null;
    const values = {};
    body.querySelectorAll('input[id], textarea[id], select[id]').forEach(el => {
      if (!el.disabled) values[el.id] = el.value;
    });
    const ai = document.getElementById('cm-ai-container');
    const modal = body.closest('.hp-modal');
    return { values, aiHtml: ai ? ai.innerHTML : '', scrollBody: body.scrollTop, scrollModal: modal ? modal.scrollTop : 0 };
  }

  function restoreModalState(snap) {
    if (!snap) return;
    const body = document.getElementById('hp-modal-body');
    if (!body) return;
    Object.entries(snap.values).forEach(([id, v]) => {
      const el = document.getElementById(id);
      if (el && !el.disabled && body.contains(el)) el.value = v;
    });
    const ai = document.getElementById('cm-ai-container');
    if (ai && snap.aiHtml) ai.innerHTML = snap.aiHtml;
    body.scrollTop = snap.scrollBody;
    const modal = body.closest('.hp-modal');
    if (modal) modal.scrollTop = snap.scrollModal;
  }

  async function openContractModal(contractId, opts) {
    const background = !!(opts && opts.background);
    if (background) {
      // never repaint under the user's hands
      const active = document.activeElement;
      const body = document.getElementById('hp-modal-body');
      if (body && active && body.contains(active) && /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName)) return;
      if (document.querySelector('#hp-modal-body button:disabled')) return; // a request is in flight
    }
    try {
      const [c, vs, neg, timelineEvents] = await Promise.all([
        LexLab.contracts.get(contractId),
        LexLab.contracts.versions(contractId),
        LexLab.contracts.negotiation(contractId),
        LexLab.contracts.timeline(contractId)
      ]);
      const sig = JSON.stringify([
        c.status, c.title, c.updated_at,
        (c.parties || []).map(p => [p.role, p.display_name, p.invited_at, p.joined_at, p.confirmed_at]),
        (vs || []).length, neg.next_action,
        (neg.parties || []).map(p => [p.role, p.agreed, p.invited]),
        (neg.objections_open || []).length, (timelineEvents || []).length
      ]);
      if (background && (state.openModalContractId !== contractId || state.modalSig === sig)) return;
      const keep = state.openModalContractId === contractId ? captureModalState() : null;
      const latest = (vs && vs[0]) || null;
      const myId = state.me && state.me.id;
      const isOwner = c.owner_id === myId;
      const myParty = (c.parties || []).find(p => p.user_id === myId);
      const canInvite = isOwner && (c.status === 'draft' || c.status === 'pending_approval');
      const canApprove = c.status === 'pending_approval' && myParty && !myParty.confirmed_at && latest;
      const canSetActiveStatus = c.status === 'active';
      const isEditable = c.status === 'draft' || c.status === 'pending_approval';
      const devOtp = (state.meta && state.meta.dev_otp_code) || '111111';

      const partiesHtml = (c.parties || []).map(p => {
        const pName = p.display_name || (c.party_names && c.party_names[p.role]) || `${p.role} tomon`;
        const negParty = (neg.parties || []).find(np => np.role === p.role);
        const hasPendingInvite = isOwner && p.invited_at && !p.joined_at && (negParty ? negParty.invited : true);
        const joinedBadge = p.confirmed_at
          ? '<span class="hp-pill-badge hp-pill-success">Imzolagan ✓</span>'
          : (negParty && negParty.agreed
            ? '<span class="hp-pill-badge hp-pill-success">Shartlarga rozi ✓</span>'
            : (p.joined_at
              ? '<span class="hp-pill-badge hp-pill-warning">Qo\'shilgan</span>'
              : (p.invited_at
                ? '<span class="hp-pill-badge hp-pill-neutral">Taklif yuborilgan</span>'
                : '<span class="hp-pill-badge hp-pill-neutral">Taklif qilinmagan</span>')));

        return `
          <div class="hp-ob-row-card" style="padding:10px 14px;">
            <div>
              <strong>${esc(p.role)}-Tomon: ${esc(pName)}</strong>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              ${joinedBadge}
              ${hasPendingInvite ? `<button type="button" class="hp-btn-outline-sm" data-revoke-invite="${esc(p.id)}" data-revoke-contract="${esc(c.id)}">Taklifni bekor qilish</button>` : ''}
            </div>
          </div>
        `;
      }).join('');

      const timelineHtml = (timelineEvents || []).map((ev, idx) => `
        <div class="hp-timeline-item">
          <div class="hp-timeline-rail">
            <span class="hp-timeline-dot hp-dot-emerald"></span>
            ${idx < timelineEvents.length - 1 ? '<span class="hp-timeline-line hp-line-muted"></span>' : ''}
          </div>
          <div class="hp-timeline-content">
            <span class="hp-timeline-title">${esc(ev.text)}</span>
            <span class="hp-timeline-sub">${esc(formatDateDdMmYyyy(ev.at))}</span>
          </div>
        </div>
      `).join('');

      const amtText = c.total_amount !== null && c.total_amount !== undefined
        ? `${formatNumberUz(c.total_amount)} ${c.currency || 'UZS'}`
        : '—';
      const datesText = (c.starts_on || c.ends_on)
        ? `${c.starts_on || '—'} → ${c.ends_on || '—'}`
        : formatDateDdMmYyyy(c.created_at);

      openModal(
        c.title,
        `
        <div class="hp-builder-form">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
            <div>${contractStatusBadgeHtml(c.status)}</div>
            <div style="font-size:13px;"><strong>Summa:</strong> ${esc(amtText)} · <strong>Muddat:</strong> ${esc(datesText)}</div>
          </div>

          ${isOwner ? `
            <div class="hp-input-with-btn">
              <input type="text" id="cm-rename-input" class="hp-input" value="${esc(c.title)}" />
              <button type="button" class="hp-btn-outline-sm" id="btn-cm-rename">Nomini saqlash</button>
            </div>
          ` : ''}

          ${renderNegotiationActionCardHtml(neg, 'modal')}
          ${renderOpenObjectionsHtml(c.id, neg.objections_open, neg.my_side)}

          ${c.form_requirement && c.form_requirement !== 'simple' ? `
            <div class="hp-rule-item hp-rule-amber">
              <strong>Shakl talabi: ${esc(c.form_requirement)}</strong>
              <span>Ushbu shartnoma notarial tasdiq yoki davlat ro'yxatidan o'tkazishni talab qilishi mumkin.</span>
            </div>
          ` : ''}

          ${latest ? `
            <div class="hp-rule-item hp-rule-blue">
              <strong>Versiya ${esc(latest.number)}</strong>
              <span style="word-break:break-all;">SHA-256: ${esc(latest.sha256)}</span>
            </div>
          ` : ''}

          <div class="hp-obligations-full-list">
            ${partiesHtml}
          </div>

          <div class="hp-builder-actions" style="justify-content:flex-start;">
            ${isEditable ? `<button type="button" class="hp-btn-navy-sm" id="btn-cm-open-builder">Savolnomada tahrirlash</button>` : ''}
            ${isEditable && c.status === 'draft' ? `<button type="button" class="hp-btn-navy-sm" data-neg-agree="${esc(c.id)}">Shartlarga roziman</button>` : ''}
            ${isEditable ? `<button type="button" class="hp-btn-outline-sm" data-neg-open-object="${esc(c.id)}">Norozilik bildirish</button>` : ''}
            ${latest ? `<button type="button" class="hp-btn-navy-sm" id="btn-cm-download">DOCX yuklab olish</button>` : ''}
            ${canSetActiveStatus ? `
              <button type="button" class="hp-btn-outline-sm" id="btn-cm-complete">Yakunlandi</button>
              <button type="button" class="hp-btn-outline-sm" id="btn-cm-dispute">Nizo</button>
            ` : ''}
            <button type="button" class="hp-btn-outline-sm" id="btn-cm-duplicate">Shu asosida yangi shartnoma</button>
            <button type="button" class="hp-btn-outline-sm" id="btn-cm-ai-review">AI tekshiruv</button>
            ${c.status !== 'draft' ? `<button type="button" class="hp-btn-outline-sm" id="btn-cm-mediation" data-contract-mediation="${esc(c.id)}">Mediatorga murojaat</button>` : ''}
            ${isOwner ? `<button type="button" class="hp-btn-outline-sm" id="btn-cm-delete" style="color:#DC2626;border-color:#FCA5A5;">O'chirish</button>` : ''}
          </div>

          ${canInvite ? `
            <div class="hp-card" style="padding:12px;">
              <div class="hp-form-group">
                <label for="cm-invite-phone">2-tomonni taklif qilish (Telefon raqami)</label>
                <div class="hp-input-with-btn">
                  <input type="text" id="cm-invite-phone" class="hp-input" value="+998901110002" placeholder="+998901110002" />
                  <button type="button" class="hp-btn-navy-sm" id="btn-cm-invite">Taklif qilish</button>
                </div>
              </div>
            </div>
          ` : ''}

          ${canApprove ? `
            <div class="hp-card" style="padding:12px;">
              <div class="hp-form-group">
                <label for="cm-approve-code">Imzolash (SMS-kod)</label>
                <div class="hp-input-with-btn">
                  <input type="text" id="cm-approve-code" class="hp-input" value="${esc(devOtp)}" placeholder="SMS-kod" />
                  <button type="button" class="hp-btn-outline-sm" id="btn-cm-req-otp">Kod so'rash</button>
                  <button type="button" class="hp-btn-navy-sm" id="btn-cm-approve">Imzolash (SMS-kod)</button>
                </div>
                ${state.meta?.dev_otp_code ? `<span class="hp-field-hint">Demo kod: ${esc(state.meta.dev_otp_code)}</span>` : ''}
              </div>
            </div>
          ` : ''}

          <div class="hp-card" style="padding:12px;">
            <div class="hp-form-group">
              <label for="cm-ai-question">AI savol</label>
              <div class="hp-input-with-btn">
                <input type="text" id="cm-ai-question" class="hp-input" placeholder="Shartnoma bo'yicha savolingizni yozing..." />
                <button type="button" class="hp-btn-outline-sm" id="btn-cm-ai-ask">So'rash</button>
              </div>
            </div>
            <div id="cm-ai-container" style="margin-top:8px;"></div>
          </div>

          ${timelineHtml ? `
            <div class="hp-card" style="padding:12px;">
              <strong style="display:block;font-size:13.5px;margin-bottom:10px;">Kelishuv va harakatlar tarixi</strong>
              <div class="hp-timeline">${timelineHtml}</div>
            </div>
          ` : ''}
        </div>
        `,
        { contractId: c.id }
      );

      document.getElementById('btn-cm-open-builder')?.addEventListener('click', () => {
        closeModal();
        openContractInBuilder(c.id).catch(handleErr);
      });

      const renameBtn = document.getElementById('btn-cm-rename');
      renameBtn?.addEventListener('click', () => {
        const newTitle = (document.getElementById('cm-rename-input')?.value || '').trim();
        if (!newTitle) return;
        withBusy(renameBtn, async () => {
          await LexLab.contracts.rename(c.id, newTitle);
          showToast('Shartnoma nomi o\'zgartirildi');
          await reloadAllWidgets();
          await openContractModal(c.id);
        }).catch(() => {});
      });

      const dupBtn = document.getElementById('btn-cm-duplicate');
      dupBtn?.addEventListener('click', () => {
        withBusy(dupBtn, async () => {
          const dup = await LexLab.contracts.duplicate(c.id);
          closeModal();
          showToast('Yangi shartnoma qoralamasi yaratildi');
          await openContractInBuilder(dup.id);
        }).catch(() => {});
      });

      const delBtn = document.getElementById('btn-cm-delete');
      delBtn?.addEventListener('click', () => {
        confirmDeleteModal(
          'Shartnomani o\'chirish / bekor qilish',
          `"${c.title}" shartnomasini o'chirishni tasdiqlaysizmi?`,
          async () => {
            try {
              const r = await LexLab.contracts.remove(c.id);
              closeModal();
              if (r && r.deleted) {
                showToast('Qoralama o\'chirildi');
                if (state.builderContractId === c.id) state.builderContractId = null;
              } else {
                showToast('Shartnoma bekor qilindi');
              }
              await reloadAllWidgets();
            } catch (err) {
              closeModal();
              await openContractModal(c.id);
              throw err;
            }
          },
          () => openContractModal(c.id)
        );
      });

      wireContractActionHandlers({
        contractId: c.id,
        versionNumber: latest ? latest.number : null,
        sha256: latest ? latest.sha256 : null,
        downloadBtnId: 'btn-cm-download',
        invitePhoneId: 'cm-invite-phone',
        inviteBtnId: 'btn-cm-invite',
        reqOtpBtnId: 'btn-cm-req-otp',
        approveCodeId: 'cm-approve-code',
        approveBtnId: 'btn-cm-approve',
        aiReviewBtnId: 'btn-cm-ai-review',
        aiAskInputId: 'cm-ai-question',
        aiAskBtnId: 'btn-cm-ai-ask',
        aiContainerId: 'cm-ai-container',
        completeBtnId: 'btn-cm-complete',
        disputeBtnId: 'btn-cm-dispute'
      });
      restoreModalState(keep);
      state.modalSig = sig;
    } catch (e) {
      if (!background) handleErr(e);
    }
  }

  function wireContractActionHandlers(cfg) {
    let otpSent = false;

    const dlBtn = document.getElementById(cfg.downloadBtnId);
    if (dlBtn && cfg.versionNumber) {
      dlBtn.addEventListener('click', () => {
        withBusy(dlBtn, async () => {
          await LexLab.contracts.download(cfg.contractId, cfg.versionNumber);
          showToast('DOCX yuklab olindi');
        }).catch(() => {});
      });
    }

    const invBtn = document.getElementById(cfg.inviteBtnId);
    if (invBtn) {
      invBtn.addEventListener('click', () => {
        const phone = (document.getElementById(cfg.invitePhoneId)?.value || '').trim();
        withBusy(invBtn, async () => {
          await LexLab.contracts.invite(cfg.contractId, phone, 'B');
          showToast(`Taklif ${phone} raqamiga yuborildi`);
          if (state.builderContractId === cfg.contractId) await refreshBuilderNegotiation();
          if (state.openModalContractId === cfg.contractId) await openContractModal(cfg.contractId);
          await loadDashboard();
        }).catch(() => {});
      });
    }

    const reqOtpBtn = document.getElementById(cfg.reqOtpBtnId);
    if (reqOtpBtn) {
      reqOtpBtn.addEventListener('click', () => {
        withBusy(reqOtpBtn, async () => {
          await LexLab.contracts.requestApprovalCode(cfg.contractId);
          otpSent = true;
          showToast('Tasdiqlash SMS-kodi yuborildi');
        }).catch(() => {});
      });
    }

    const appBtn = document.getElementById(cfg.approveBtnId);
    if (appBtn && cfg.sha256) {
      appBtn.addEventListener('click', () => {
        const code = (document.getElementById(cfg.approveCodeId)?.value || '').trim();
        withBusy(appBtn, async () => {
          if (!otpSent) {
            try {
              await LexLab.contracts.requestApprovalCode(cfg.contractId);
              otpSent = true;
            } catch (otpErr) {
              if (!otpErr || otpErr.code !== 'otp_cooldown') throw otpErr;
            }
          }
          const res = await LexLab.contracts.approve(cfg.contractId, code, cfg.sha256);
          if (res && res.contract_status === 'active') {
            showToast('Shartnoma kuchga kirdi va shaxsiy arxivga saqlandi');
          } else {
            const waiting = (res && res.pending_parties && res.pending_parties.join(', ')) || '2-';
            showToast(`Imzo qo'yildi, ${waiting} tomon kutilmoqda`);
          }
          await reloadAllWidgets();
          await openContractModal(cfg.contractId);
        }).catch(() => {});
      });
    }

    const completeBtn = document.getElementById(cfg.completeBtnId);
    if (completeBtn) {
      completeBtn.addEventListener('click', () => {
        withBusy(completeBtn, async () => {
          await LexLab.contracts.setStatus(cfg.contractId, 'completed');
          showToast('Shartnoma yakunlandi');
          await reloadAllWidgets();
          await openContractModal(cfg.contractId);
        }).catch(() => {});
      });
    }

    const disputeBtn = document.getElementById(cfg.disputeBtnId);
    if (disputeBtn) {
      disputeBtn.addEventListener('click', () => {
        withBusy(disputeBtn, async () => {
          await LexLab.contracts.setStatus(cfg.contractId, 'disputed');
          showToast('Shartnoma nizoli deb belgilandi');
          await reloadAllWidgets();
          await openContractModal(cfg.contractId);
        }).catch(() => {});
      });
    }

    const aiRevBtn = document.getElementById(cfg.aiReviewBtnId);
    const aiCont = document.getElementById(cfg.aiContainerId);
    if (aiRevBtn && aiCont) {
      aiRevBtn.addEventListener('click', () => {
        aiCont.innerHTML = `<div class="hp-rule-item hp-rule-blue"><strong>AI tahlil qilmoqda… (3–15 soniya)</strong></div>`;
        withBusy(aiRevBtn, async () => {
          const rev = await LexLab.contracts.aiReview(cfg.contractId);
          renderContractAiReview(document.getElementById(cfg.aiContainerId) || aiCont, rev);
        }).catch((e) => {
          (document.getElementById(cfg.aiContainerId) || aiCont).innerHTML = renderAiErrorHtml(e);
        });
      });
    }

    const aiAskBtn = document.getElementById(cfg.aiAskBtnId);
    const aiAskInput = document.getElementById(cfg.aiAskInputId);
    if (aiAskBtn && aiCont) {
      const ask = () => {
        const q = (aiAskInput?.value || '').trim();
        if (q.length < 3) {
          aiCont.innerHTML = `<div class="hp-rule-item hp-rule-amber"><strong>Savolni yozing</strong><span>Masalan: "Ijara haqini kechiktirsam nima bo'ladi?"</span></div>`;
          aiAskInput?.focus();
          return;
        }
        if (aiAskBtn.disabled) return;
        aiCont.innerHTML = `<div class="hp-rule-item hp-rule-blue"><strong><span class="hp-sug-tag">AI</span> Javob tayyorlanmoqda… (3–15 soniya)</strong><span>Savol: ${esc(q)}</span></div>`;
        withBusy(aiAskBtn, async () => {
          const ans = await LexLab.contracts.aiAsk(cfg.contractId, q);
          (document.getElementById(cfg.aiContainerId) || aiCont).innerHTML = renderAiAnswerHtml(q, ans);
        }).catch((e) => {
          (document.getElementById(cfg.aiContainerId) || aiCont).innerHTML = renderAiErrorHtml(e);
        });
      };
      aiAskBtn.addEventListener('click', ask);
      aiAskInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); ask(); }
      });
    }
  }

  function renderAiErrorHtml(e) {
    const code = e && e.code;
    const msg = code === 'ai_disabled'
      ? 'AI hozircha o\'chirilgan. Qoidalar tizimi tekshiruvi ishlayveradi.'
      : (code === 'rate_limited' ? 'So\'rovlar ko\'p bo\'ldi — bir necha daqiqadan keyin qayta urinib ko\'ring.'
        : LexLab.humanError(e));
    return `<div class="hp-rule-item hp-rule-red"><strong>AI javob bera olmadi</strong><span>${esc(msg)}</span></div>`;
  }

  function renderAiAnswerHtml(question, ans) {
    const a = ans || {};
    const quotes = (a.clauses || []).map(c => `
      <div class="hp-ai-answer-quote">[${esc(String(c.index + 1))}-band] ${esc(c.text)}</div>
    `).join('');
    const laws = (a.law_refs || []).map(l => `<span>${lawRefLink(l.ref, l.url)} — ${esc(l.title || '')}</span>`).join('');
    return `
      <div class="hp-rule-item ${a.consult_lawyer ? 'hp-rule-amber' : 'hp-rule-green'}">
        <strong><span class="hp-sug-tag">AI</span> ${esc(question)}</strong>
        <span style="white-space:pre-wrap;">${esc(a.answer || 'Javob olinmadi.')}</span>
        ${quotes || laws ? `<div class="hp-ai-answer-meta">
          ${quotes ? `<strong>Shartnomadagi band:</strong>${quotes}` : ''}
          ${laws ? `<strong>Qonun (lex.uz):</strong>${laws}` : ''}
        </div>` : ''}
        ${a.consult_lawyer ? adviceHtml('Aniq xulosa uchun yurist bilan maslahatlashing.') : ''}
        <span class="hp-text-muted" style="font-size:11.5px;">${esc(a.disclaimer || 'AI javobi ma\'lumot uchun; yuridik maslahat o\'rnini bosmaydi.')}</span>
      </div>
    `;
  }

  function renderContractAiReview(container, rev) {
    if (!container || !rev) return;
    const issues = (rev.issues || []).map(iss => `
      <div class="hp-rule-item ${iss.severity === 'blue' ? 'hp-rule-green' : 'hp-rule-amber'}">
        <strong><span class="hp-sug-tag">AI</span> ${esc(iss.title || 'Tavsiya')}</strong>
        <span>${esc(iss.explanation || '')}</span>
        ${adviceHtml(iss.suggestion)}
        ${iss.law_ref ? `<span>Asos: ${lawRefLink(iss.law_ref)}</span>` : ''}
      </div>
    `).join('');

    const devs = (rev.template_deviations || []).map(d => `
      <div class="hp-rule-item hp-rule-blue">
        <strong><span class="hp-sug-tag">AI · Shablon</span> ${esc(d.status || '')}</strong>
        <span>${esc(d.comment || d.template_clause || '')}</span>
      </div>
    `).join('');

    container.innerHTML = `
      <div class="hp-rule-alerts">
        <div class="hp-rule-item hp-rule-blue">
          <strong><span class="hp-sug-tag">AI</span> Umumiy xulosa (${esc(rev.model || 'AI')})</strong>
          <span>${esc(rev.summary || 'Qo\'shimcha xavf topilmadi.')}</span>
        </div>
        ${issues}
        ${devs}
      </div>
    `;
  }

  // §7.4 & U2.3.7 Invitations Modal with warnings preview
  async function openInvitationsModal() {
    try {
      const invs = await LexLab.contracts.invitations();
      if (!invs || invs.length === 0) {
        openModal('Kelgan takliflar', `<p class="hp-text-muted">Hozircha yangi takliflar yo'q.</p>`);
        return;
      }

      const listHtml = invs.map(inv => `
        <div class="hp-card" style="padding:14px;margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap;">
            <div>
              <strong style="font-size:15px;">${esc(inv.contract_title)}</strong>
              <div class="hp-text-muted" style="font-size:12.5px;margin-top:3px;">
                Rol: ${esc(inv.role_title)} · Taklif qiluvchi: ${esc(inv.inviter_name || '1-Tomon')}
                ${inv.total_amount ? ` · Summa: ${esc(formatNumberUz(inv.total_amount))} ${esc(inv.currency || 'UZS')}` : ''}
              </div>
              ${inv.current_sha256 ? `<div class="hp-text-muted" style="font-size:11px;margin-top:4px;word-break:break-all;">SHA-256: ${esc(inv.current_sha256)}</div>` : ''}
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button type="button" class="hp-btn-outline-sm" data-inv-preview="${esc(inv.party_id)}">Ko'rish</button>
              <button type="button" class="hp-btn-navy-sm" data-inv-accept="${esc(inv.party_id)}">Qabul qilish</button>
              <button type="button" class="hp-btn-outline-sm" data-inv-decline="${esc(inv.party_id)}">Rad etish</button>
            </div>
          </div>
          <div id="inv-warnings-box-${esc(inv.party_id)}" style="margin-top:10px;" hidden></div>
          <div id="inv-preview-box-${esc(inv.party_id)}" style="margin-top:10px;" hidden></div>
        </div>
      `).join('');

      openModal('Menga kelgan shartnoma takliflari', `<div>${listHtml}</div>`);

      // Automatically load warnings & preview for the first invitation so Party B immediately sees risky points
      for (const inv of invs) {
        loadInvitationPreviewAndWarnings(inv.party_id, false).catch(() => {});
      }
    } catch (e) {
      handleErr(e);
    }
  }

  async function loadInvitationPreviewAndWarnings(partyId, showFullDoc) {
    const warnBox = document.getElementById(`inv-warnings-box-${partyId}`);
    const prevBox = document.getElementById(`inv-preview-box-${partyId}`);
    const p = await LexLab.contracts.invitationPreview(partyId);

    if (warnBox) {
      const warnings = p.warnings || [];
      const rc = p.risk_counts || {};
      if (warnings.length > 0) {
        warnBox.hidden = false;
        warnBox.innerHTML = `
          <div class="hp-rule-alerts">
            <div style="font-size:12.5px;font-weight:700;">
              Ogohlantirishlar (Qizil: ${rc.red || 0}, Qaltis: ${rc.yellow || 0}):
            </div>
            ${warnings.map(w => {
              const cls = w.severity === 'red' ? 'hp-rule-red' : (w.severity === 'yellow' ? 'hp-rule-amber' : 'hp-rule-green');
              return `
                <div class="hp-rule-item ${cls}">
                  <strong>${esc(w.message)}</strong>
                  ${adviceHtml(w.fix_suggestion)}
                  ${w.law_ref ? `<span>Asos: ${lawRefLink(w.law_ref)}</span>` : ''}
                </div>
              `;
            }).join('')}
          </div>
        `;
      }
    }

    if (prevBox && showFullDoc) {
      prevBox.hidden = false;
      prevBox.className = 'hp-doc-paper';
      prevBox.innerHTML = renderPreviewDocumentHtml(p);
    }
  }

  // ==================== §8 & U2.5 SCANNER (#view-scanner) ====================
  async function loadScannerHistory() {
    const scans = await LexLab.scans.list(10);
    state.scansHistory = scans || [];
    renderScannerHistoryStrip();
  }

  function shortTitle(t, max) {
    const m = max || 38;
    if (!t) return '';
    return t.length > m ? t.slice(0, m - 1).trimEnd() + '…' : t;
  }

  function renderScannerHistoryStrip() {
    const uploadBar = document.querySelector('#view-scanner .hp-scanner-upload-bar');
    if (!uploadBar) return;

    let histBox = document.getElementById('scanner-history-list');
    if (!histBox) {
      histBox = document.createElement('div');
      histBox.id = 'scanner-history-list';
      histBox.style.marginTop = '12px';
      uploadBar.appendChild(histBox);
    }

    if (!state.scansHistory || state.scansHistory.length === 0) {
      histBox.innerHTML = '';
      return;
    }

    histBox.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        <span class="hp-sample-label">Oxirgi tahlillar:</span>
        ${state.scansHistory.slice(0, 5).map(s => `
          <span style="display:inline-flex;align-items:center;gap:4px;">
            <button type="button" class="hp-btn-outline-sm" data-open-scan="${esc(s.id)}">
              ${esc(shortTitle(s.title) || ('Tahlil #' + String(s.id).slice(0, 6)))} (${esc(s.risk_percent ?? 0)}%)
            </button>
            <button type="button" class="hp-btn-outline-sm" data-delete-scan="${esc(s.id)}" title="O'chirish" style="color:#DC2626;">✕</button>
          </span>
        `).join('')}
      </div>
    `;
  }

  async function runScannerUpload(file) {
    if (!file) return;
    showToast(`"${file.name}" yuklanmoqda va tahlil qilinmoqda...`);
    try {
      const s = await LexLab.scans.upload(file);
      await processScanJob(s.id, file.name);
      await loadScannerHistory();
    } catch (e) {
      handleErr(e);
    }
  }

  async function runScannerPreset(presetKey, btn) {
    const sampleText = SCAN_SAMPLE_TEXTS[presetKey] || SCAN_SAMPLE_TEXTS.ijara;
    const titles = {
      ijara: 'Ijara shartnomasi #42',
      mehnat: 'Mehnat shartnomasi',
      xizmat: 'IT Xizmat shartnomasi'
    };
    document.querySelectorAll('[data-scan-preset]').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-scan-preset') === presetKey);
    });

    await withBusy(btn, async () => {
      const s = await LexLab.scans.fromText(sampleText);
      await processScanJob(s.id, titles[presetKey] || 'Namunaviy shartnoma');
      await loadScannerHistory();
    });
  }

  async function processScanJob(scanId, docTitle) {
    state.currentScanId = scanId;
    state.currentScanTitle = docTitle || 'Shartnoma tahlili';

    const done = await LexLab.scans.waitDone(scanId);
    if (done.status === 'needs_review') {
      const t = await LexLab.scans.text(scanId);
      openModal(
        'OCR matnini tasdiqlang',
        `
        <div class="hp-builder-form">
          <p class="hp-text-muted">Skanerlangan matnda noaniqlik bo'lsa, tahrirlab tasdiqlang:</p>
          <textarea id="ocr-review-textarea" class="hp-ocr-textarea" rows="8">${esc(t.text || '')}</textarea>
          <div class="hp-builder-actions">
            <button type="button" class="hp-btn-navy" id="btn-confirm-ocr-text">Tasdiqlash va tahlil qilish</button>
          </div>
        </div>
        `
      );
      const confirmBtn = document.getElementById('btn-confirm-ocr-text');
      confirmBtn?.addEventListener('click', () => {
        const edited = document.getElementById('ocr-review-textarea')?.value || '';
        withBusy(confirmBtn, async () => {
          await LexLab.scans.saveText(scanId, edited);
          closeModal();
          await processScanJob(scanId, docTitle);
        }).catch(() => {});
      });
      return;
    }

    if (done.status === 'failed') {
      showToast(done.error || 'Hujjatni tahlil qilib bo\'lmadi');
      return;
    }

    const r = await LexLab.scans.report(scanId);
    state.currentScanReport = r;
    renderScanReport(r, state.currentScanTitle);
    await loadDashboard();

    if (r.ai && r.ai.status === 'pending') {
      const full = await LexLab.scans.waitAi(scanId);
      if (state.currentScanId === scanId) {
        state.currentScanReport = full;
        renderScanReport(full, state.currentScanTitle);
        await loadDashboard();
      }
    }
  }

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
    renderScanDocMeta(null);
    if (badgeEl) { badgeEl.hidden = true; badgeEl.textContent = ''; }
    if (illegalEl) illegalEl.textContent = '—';
    if (riskyEl) riskyEl.textContent = '—';
    const adviceEl = document.getElementById('scan-count-advice');
    if (adviceEl) adviceEl.textContent = '—';
    if (dutiesEl) dutiesEl.innerHTML = '<li class="hp-text-muted">Hali tahlil yo\'q — shartnoma faylini yuklang.</li>';
    if (cardsEl) cardsEl.innerHTML = '';
    document.querySelectorAll('[data-scan-preset]').forEach(b => b.classList.remove('active'));
  }

  // Under the report title: which file, which contract type was recognised, how many clauses were read.
  function renderScanDocMeta(doc, docTitle) {
    const titleEl = document.getElementById('scan-report-doc-title');
    if (!titleEl) return;
    let meta = document.getElementById('scan-report-doc-meta');
    if (!meta) {
      meta = document.createElement('p');
      meta.id = 'scan-report-doc-meta';
      meta.className = 'hp-text-muted';
      meta.style.cssText = 'font-size:12.5px;margin:-6px 0 12px;';
      titleEl.closest('.hp-card-header').insertAdjacentElement('afterend', meta);
    }
    if (!doc) { meta.hidden = true; meta.textContent = ''; return; }
    const file = doc.filename || (docTitle && docTitle !== doc.title ? docTitle : '');
    const parts = [];
    if (file) parts.push(`Fayl: ${file}`);
    if (doc.type_title) parts.push(`Turi: ${doc.type_title}${doc.type_detected ? ' (avtomatik aniqlandi)' : ''}`);
    else parts.push("Turi: aniqlanmadi — umumiy qoidalar bo'yicha tekshirildi");
    if (doc.clauses) parts.push(`${doc.clauses} ta band o'qildi`);
    meta.textContent = parts.join(' · ');
    meta.hidden = false;
  }

  function renderScanReport(r, docTitle) {
    if (!r || !r.overall) return;

    const titleEl = document.getElementById('scan-report-doc-title');
    const badgeEl = document.getElementById('scan-report-risk-badge');
    const illegalEl = document.getElementById('scan-count-illegal');
    const riskyEl = document.getElementById('scan-count-risky');
    const dutiesEl = document.getElementById('scan-duties-list');
    const cardsEl = document.getElementById('scan-decision-cards');

    const redList = r.red_clauses || [];
    const riskyList = r.risky_clauses || [];
    const missingList = r.missing_elements || [];
    const adviceList = r.advice || [];
    const dutiesList = r.your_obligations || [];
    const adviceEl = document.getElementById('scan-count-advice');
    if (adviceEl) adviceEl.textContent = String(adviceList.length + missingList.length);

    const doc = r.document || {};
    if (titleEl) titleEl.textContent = `Tekshirilayotgan shartnoma: ${doc.title || docTitle || 'Shartnoma'}`;
    renderScanDocMeta(doc, docTitle);
    if (badgeEl) {
      const riskLvl = r.overall.risk_level;
      badgeEl.className = `hp-pill-badge ${riskLvl === 'high' ? 'hp-pill-danger' : (riskLvl === 'medium' ? 'hp-pill-warning' : 'hp-pill-success')}`;
      badgeEl.textContent = `${r.overall.risk_label || 'Xavf'} (${r.overall.risk_percent ?? 0}/100)`;
      badgeEl.hidden = false;
    }
    if (illegalEl) illegalEl.textContent = String(redList.length);
    if (riskyEl) riskyEl.textContent = String(riskyList.length);

    if (dutiesEl) {
      const dutyItems = dutiesList.length > 0
        ? dutiesList.map(d => `<li>${esc(d.clause_text || d.explanation)}</li>`).join('')
        : `<li>Majburiyat bandlari ajratilmadi</li>`;

      const tplCheck = r.overall.template_check;
      const tplHtml = tplCheck
        ? `<li style="margin-top:6px;font-weight:700;color:#1D4ED8;">Shablonga muvofiqlik: ${Math.round((tplCheck.conformity || 0) * 100)}% (${esc((tplCheck.source && tplCheck.source.label) || 'rasmiy shablon')})</li>`
        : '';

      dutiesEl.innerHTML = `
        ${dutyItems}
        ${tplHtml}
        <li style="list-style:none;margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">
          <button type="button" class="hp-btn-outline-sm" id="btn-scan-to-obligations">Majburiyatlarni eslatmalarga qo'shish</button>
          <button type="button" class="hp-btn-navy-sm" id="btn-scan-download-report">Hisobotni yuklab olish</button>
          <button type="button" class="hp-btn-outline-sm" data-delete-scan="${esc(r.id)}" style="color:#DC2626;">Tahlilni o'chirish</button>
        </li>
      `;
    }

    if (cardsEl) {
      const allFindings = []
        .concat(redList.map(f => Object.assign({}, f, { _cardType: 'red' })))
        .concat(riskyList.map(f => Object.assign({}, f, { _cardType: 'yellow' })))
        .concat(adviceList.map(f => Object.assign({}, f, { _cardType: 'green' })))
        .concat(missingList.map(f => Object.assign({}, f, { _cardType: 'green', _missing: true })));

      const aiStatus = r.ai && r.ai.status;
      let aiBlockHtml = '';
      if (aiStatus === 'pending') {
        aiBlockHtml = `
          <div class="hp-rule-item hp-rule-blue">
            <strong><span class="hp-sug-tag">AI</span> AI tahlil qilmoqda…</strong>
          </div>
        `;
      } else if (aiStatus === 'done') {
        const DEV_LABELS = { changed: 'Shablondan o\'zgartirilgan', missing: 'Shablondagi band yo\'q', added: 'Qo\'shimcha band' };
        const devHtml = (r.ai.template_deviations || []).map(d => `
          <div style="margin-top:6px;font-size:12.5px;">
            <strong>${esc(DEV_LABELS[d.status] || 'Farq')}:</strong> ${esc(d.comment || d.template_clause || '')}
          </div>
        `).join('');
        if (r.ai.summary || devHtml) {
          aiBlockHtml = `
            <div class="hp-rule-item hp-rule-blue">
              <strong><span class="hp-sug-tag">AI</span> AI xulosasi</strong>
              <span>${esc(r.ai.summary || '')}</span>
              ${devHtml}
            </div>
          `;
        }
      }

      const cardsHtml = allFindings.map(f => {
        const isRed = f._cardType === 'red';
        const isGreen = f._cardType === 'green';
        const cardCls = isRed ? 'hp-clause-illegal hp-sev-red' : (isGreen ? 'hp-clause-risky hp-sev-green' : 'hp-clause-risky hp-sev-yellow');
        const pillCls = isRed ? 'hp-pill-danger' : (isGreen ? 'hp-pill-success' : 'hp-pill-warning');
        const pillLabel = isRed ? 'Qonunga zid' : (isGreen ? (f._missing ? 'Maslahat · yetishmaydi' : 'Maslahat') : 'Qaltis band');
        const sourceTag = f.source === 'ai'
          ? ' <span class="hp-sug-tag">AI</span>'
          : (f.source === 'template' ? ' <span class="hp-sug-tag">Shablon</span>' : '');
        const explanation = f.ai_explanation || f.explanation || '';
        const decision = f.user_decision;
        // every illegal / risky clause gets a green «what to do» box under it
        const advice = f.suggestion || (isRed
          ? 'Imzolashdan oldin bu bandni qonunga moslab o\'zgartirishni yoki olib tashlashni talab qiling.'
          : 'Imzolashdan oldin bandni aniqlashtiring yoki o\'zingiz uchun xavfsiz tahrirda kelishib oling.');

        return `
          <div class="hp-clause-alert ${cardCls}">
            <div class="hp-clause-main-row" style="margin-bottom:6px;">
              <span class="hp-pill-badge ${pillCls}">${esc(pillLabel)}</span>${sourceTag}
              <strong style="font-size:13.8px;">${esc(explanation)}</strong>
            </div>
            ${f.law_ref ? `<div class="hp-text-muted" style="font-size:12px;margin-bottom:4px;">Huquqiy asos: ${lawRefLink(f.law_ref)}</div>` : ''}
            ${f.clause_text ? `<div style="font-size:12.5px;color:var(--text-secondary);margin-bottom:8px;">"${esc(f.clause_text)}"</div>` : ''}
            ${isRed && f.source === 'ai' ? `<div class="hp-text-muted" style="font-size:11.5px;margin-bottom:6px;">AI aniqlagan — yakuniy xulosa uchun yurist tasdiqlashi tavsiya etiladi.</div>` : ''}
            ${isGreen ? adviceHtml(f.suggestion, 'Tavsiya') : `
            ${adviceHtml(advice)}
            <div class="hp-clause-actions-row">
              <span class="hp-decision-feedback">
                ${decision === 'agree' ? 'Rozilik bildirildi' : (decision === 'object' ? 'E\'tiroz bildirildi' : '')}
              </span>
              <div class="hp-clause-btns">
                <button type="button" class="hp-btn-navy-sm" data-scan-decision="agree" data-finding-id="${esc(f.id)}">Roziman</button>
                <button type="button" class="hp-btn-outline-sm" data-scan-decision="object" data-finding-id="${esc(f.id)}">E'tiroz</button>
              </div>
            </div>`}
          </div>
        `;
      }).join('');

      const noDanger = !redList.length && !riskyList.length
        ? `<div class="hp-rule-item hp-rule-green"><strong>Qonunga zid yoki qaltis band topilmadi</strong></div>` : '';
      cardsEl.innerHTML = aiBlockHtml + noDanger + cardsHtml;
    }
  }

  // ==================== §9, U2.4 & U2.5 REMINDERS, PERSONAL ARCHIVE, NOTIFICATIONS, SEARCH ====================
  async function loadObligationsView() {
    const list = await LexLab.obligations.list();
    const container = document.getElementById('full-obligations-list');
    if (!container) return;

    if (!list || list.length === 0) {
      container.innerHTML = `<p class="hp-text-muted" style="padding:12px;">Hozircha majburiyatlar va eslatmalar yo'q.</p>`;
      return;
    }

    container.innerHTML = list.map(ob => {
      const amt = ob.amount !== null && ob.amount !== undefined
        ? `${formatNumberUz(ob.amount)} ${ob.currency || 'UZS'}`
        : '';
      const nextStatus = ob.status === 'done' ? 'pending' : 'done';
      const btnText = ob.status === 'done' ? 'Bajarildini bekor qilish' : 'Bajarildi';

      return `
        <div class="hp-ob-row-card">
          <div>
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <strong style="font-size:14.5px;${ob.status === 'done' ? 'text-decoration:line-through;color:var(--text-muted);' : ''}">
                ${esc(ob.title)}
              </strong>
              ${obligationStatusBadgeHtml(ob.status)}
              ${!ob.confirmed ? `<span class="hp-pill-badge hp-pill-warning">Tasdiqlanmagan</span>` : ''}
            </div>
            <div style="font-size:13px;color:var(--text-muted);margin-top:3px;">
              Muddat: <strong>${esc(ob.due_date)}</strong>
              ${amt ? ` · Summa: <strong>${esc(amt)}</strong>` : ''}
            </div>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            ${!ob.confirmed ? `<button type="button" class="hp-btn-navy-sm" data-confirm-ob="${esc(ob.id)}">Tasdiqlash</button>` : ''}
            <button type="button" class="hp-btn-outline-sm" data-complete-ob="${esc(ob.id)}" data-next-status="${esc(nextStatus)}">${esc(btnText)}</button>
            <button type="button" class="hp-btn-outline-sm" data-delete-ob="${esc(ob.id)}" data-ob-title="${esc(ob.title)}" style="color:#DC2626;">O'chirish</button>
          </div>
        </div>
      `;
    }).join('');
  }

  function openAddObligationModal() {
    const todayIso = new Date().toISOString().slice(0, 10);
    openModal(
      'Yangi eslatma qo\'shish',
      `
      <form id="modal-add-ob-form" class="hp-builder-form">
        <div class="hp-form-group">
          <label for="ob-new-title">Majburiyat nomi *</label>
          <input type="text" id="ob-new-title" class="hp-input" placeholder="Masalan: Oylik ijara to'lovi" required />
        </div>
        <div class="hp-form-row-2">
          <div class="hp-form-group">
            <label for="ob-new-date">Muddat (Sana) *</label>
            <input type="date" id="ob-new-date" class="hp-input" value="${esc(todayIso)}" required />
          </div>
          <div class="hp-form-group">
            <label for="ob-new-amount">Summa (so'm)</label>
            <input type="number" id="ob-new-amount" class="hp-input" placeholder="4500000" min="0" />
          </div>
        </div>
        <div class="hp-builder-actions">
          <button type="submit" class="hp-btn-navy" id="btn-submit-new-ob">Saqlash</button>
        </div>
      </form>
      `
    );

    const form = document.getElementById('modal-add-ob-form');
    const btn = document.getElementById('btn-submit-new-ob');
    form?.addEventListener('submit', (e) => {
      e.preventDefault();
      const title = (document.getElementById('ob-new-title')?.value || '').trim();
      const due_date = document.getElementById('ob-new-date')?.value;
      const rawAmt = document.getElementById('ob-new-amount')?.value;
      const amount = rawAmt ? Number(rawAmt) : undefined;

      withBusy(btn, async () => {
        await LexLab.obligations.create({ title, due_date, amount });
        closeModal();
        showToast('Eslatma qo\'shildi');
        await loadObligationsView();
        await loadDashboard();
      }).catch(() => {});
    });
  }

  // ---- Archive documents: payment receipts / addenda filed by any user (not only lawyers) ----
  function fillArchiveContractSelect(form) {
    const sel = form && form.querySelector('#cs-archive');
    if (!sel) return;
    const keep = sel.value;
    sel.innerHTML = `<option value="">— shartnomaga bog'lanmagan —</option>` + (state.archiveItems || []).map(it =>
      `<option value="${esc(it.id)}">${esc(shortTitle(it.title, 42))}${it.counterparty ? ` · ${esc(shortTitle(it.counterparty, 24))}` : ''}</option>`
    ).join('');
    if (keep && (state.archiveItems || []).some(it => it.id === keep)) sel.value = keep;
  }

  function formatFileSize(n) {
    const b = Number(n) || 0;
    return b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
  }

  function renderArchiveDocItemHtml(d) {
    const meta = [];
    if (d.amount) meta.push(`<strong>${esc(formatNumberUz(d.amount))} ${esc(d.currency === 'UZS' ? "so'm" : d.currency)}</strong>`);
    if (d.doc_date) meta.push(esc(formatDateDdMmYyyy(d.doc_date)));
    if (d.contract_title) meta.push(`Shartnoma: ${esc(d.contract_title)}`);
    return `
      <div class="hp-case-step-card">
        <div>
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;">
            <span class="hp-sug-tag">${esc(d.kind_label || 'Hujjat')}</span>
            ${d.file ? `<span class="hp-pill-badge hp-pill-success" title="SHA-256: ${esc(d.file.sha256)}">Fayl saqlangan ✓</span>` : ''}
            <span style="font-size:12px;color:var(--text-muted);">Qo'shilgan: ${esc(formatDateDdMmYyyy(d.created_at))}</span>
          </div>
          <strong style="display:block;font-size:14.5px;margin-bottom:3px;">${esc(d.title)}</strong>
          ${meta.length ? `<p style="font-size:13px;color:var(--text-secondary);">${meta.join(' · ')}</p>` : ''}
          ${d.description ? `<p class="hp-text-muted" style="font-size:12.5px;margin-top:3px;">${esc(d.description)}</p>` : ''}
          ${d.file ? `<p class="hp-text-muted" style="font-size:12px;margin-top:3px;">${esc(d.file.name)} · ${esc(formatFileSize(d.file.size))}</p>` : ''}
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          ${d.file ? `<button type="button" class="hp-btn-navy-sm" data-doc-download="${esc(d.id)}">Yuklab olish</button>` : ''}
          <button type="button" class="hp-btn-outline-sm" data-doc-delete="${esc(d.id)}" style="color:#DC2626;">O'chirish</button>
        </div>
      </div>
    `;
  }

  function renderArchiveDocsHtml(docs) {
    return `
      <div style="margin-top:18px;padding-top:14px;border-top:1px solid var(--border-color);">
        <strong style="display:block;font-size:15px;margin-bottom:10px;">To'lov cheklari va hujjatlar</strong>
        ${(docs || []).length === 0
          ? `<p class="hp-text-muted">Hozircha chek yoki hujjat qo'shilmagan — o'ngdagi forma orqali qo'shing.</p>`
          : `<div class="hp-case-timeline">${docs.map(renderArchiveDocItemHtml).join('')}</div>`}
      </div>
    `;
  }

  // U2.4 Personal Archive + Lawyer Case File Timeline in #view-archive
  async function loadArchiveView(qFilter) {
    const timelineEl = document.getElementById('lawyer-case-timeline');
    const form = document.getElementById('case-step-form');
    if (!timelineEl) return;

    if (qFilter !== undefined) state.archiveQuery = qFilter;

    const isLawyer = state.me && state.me.role === 'lawyer';

    const [archiveItems, cases, docs] = await Promise.all([
      LexLab.archive.list(state.archiveQuery ? { q: state.archiveQuery } : {}),
      LexLab.cases.list().catch(() => []),
      LexLab.archive.documents()
    ]);

    state.archiveItems = archiveItems || [];
    state.casesList = cases || [];
    state.archiveDocs = docs || [];
    fillArchiveContractSelect(form);

    let html = `
      <div style="margin-bottom:14px;">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px;flex-wrap:wrap;">
          <strong style="font-size:15px;">Mening arxivim (Imzolangan shartnomalar)</strong>
          <div class="hp-input-with-btn" style="max-width:260px;">
            <input type="text" id="archive-search-input" class="hp-input" value="${esc(state.archiveQuery)}" placeholder="Arxivdan qidirish..." />
            <button type="button" class="hp-btn-outline-sm" id="btn-archive-search">Qidirish</button>
          </div>
        </div>
        ${state.archiveItems.length === 0 ? `<p class="hp-text-muted">Hozircha imzolangan shartnomalar arxivda yo'q.</p>` : ''}
        <div class="hp-case-timeline">
          ${state.archiveItems.map(item => {
            const amt = item.total_amount ? ` · ${formatNumberUz(item.total_amount)} ${item.currency || 'UZS'}` : '';
            return `
              <div class="hp-case-step-card">
                <div>
                  <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;">
                    <span class="hp-pill-badge hp-pill-success">SHA-256 tasdiqlangan ✓</span>
                    <span class="hp-sug-tag">v${esc(item.version)} · ${esc(item.side || 'A')}-Tomon</span>
                    <span style="font-size:12px;color:var(--text-muted);">${esc(formatDateDdMmYyyy(item.signed_at))}</span>
                  </div>
                  <strong style="display:block;font-size:14.5px;margin-bottom:3px;">${esc(item.title)}</strong>
                  <p style="font-size:13px;color:var(--text-secondary);">
                    Ikkinchi tomon: <strong>${esc(item.counterparty || '—')}</strong>${esc(amt)}
                  </p>
                  ${item.note ? `<p class="hp-text-muted" style="font-size:12px;margin-top:3px;">Izoh: ${esc(item.note)}</p>` : ''}
                </div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;">
                  <button type="button" class="hp-btn-outline-sm" data-archive-view="${esc(item.id)}">Ko'rish</button>
                  <button type="button" class="hp-btn-navy-sm" data-archive-download="${esc(item.id)}">Yuklab olish</button>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
      ${renderArchiveDocsHtml(state.archiveDocs)}
    `;

    // For lawyers (or if shared cases exist), keep the case-file timeline below Mening arxivim
    if (isLawyer || state.casesList.length > 0) {
      let stepsHtml = '';
      if (state.casesList.length > 0) {
        state.currentCaseId = state.casesList[0].id;
        const detail = await LexLab.cases.get(state.currentCaseId);
        const steps = detail.steps || [];
        stepsHtml = steps.length > 0
          ? steps.map(step => {
              const tag = (step.tags && step.tags[0]) || 'Qadam';
              return `
                <div class="hp-case-step-card">
                  <div>
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                      <span class="hp-sug-tag">${esc(tag)}</span>
                      <span style="font-size:12px;color:var(--text-muted);">${esc(formatDateDdMmYyyy(step.step_at))}</span>
                    </div>
                    <strong style="display:block;font-size:14.5px;margin-bottom:3px;">${esc(step.title)}</strong>
                    <p style="font-size:13px;color:var(--text-secondary);">${esc(step.description || '')}</p>
                  </div>
                </div>
              `;
            }).join('')
          : `<p class="hp-text-muted">Yurist ishida hozircha qadamlar yo'q.</p>`;
      } else {
        state.currentCaseId = null;
        stepsHtml = `<p class="hp-text-muted">Hozircha yurist ishlari yo'q.</p>`;
      }

      html += `
        <div style="margin-top:18px;padding-top:14px;border-top:1px solid var(--border-color);">
          <strong style="display:block;font-size:14.5px;margin-bottom:10px;">Yurist ish yuritish xronologiyasi</strong>
          <div class="hp-case-timeline">${stepsHtml}</div>
        </div>
      `;
    }

    timelineEl.innerHTML = html;

    document.getElementById('btn-archive-search')?.addEventListener('click', () => {
      const q = (document.getElementById('archive-search-input')?.value || '').trim();
      loadArchiveView(q).catch(handleErr);
    });
  }

  async function openArchiveItemModal(itemId) {
    try {
      const item = await LexLab.archive.get(itemId);
      const intact = item.integrity && item.integrity.intact;
      // the modal's download/delete buttons resolve documents from state.archiveDocs
      const known = new Set((state.archiveDocs || []).map(d => d.id));
      state.archiveDocs = (state.archiveDocs || []).concat((item.documents || []).filter(d => !known.has(d.id)));
      const sigsHtml = (item.signatures || []).map(s => `
        <div class="hp-ob-row-card" style="padding:10px 14px;">
          <div>
            <strong>${esc(s.side || '—')}-Tomon (${esc(s.method.toUpperCase())})</strong>
            <div class="hp-text-muted" style="font-size:12px;">Imzolangan vaqt: ${esc(formatDateDdMmYyyy(s.signed_at))}</div>
          </div>
          <span class="hp-pill-badge hp-pill-success">Tasdiqlangan ✓</span>
        </div>
      `).join('');

      openModal(
        `Arxiv: ${item.title} (v${item.version})`,
        `
        <div class="hp-builder-form">
          <div class="hp-rule-item ${intact ? 'hp-rule-blue' : 'hp-rule-red'}">
            <strong>Hujjat yaxlitligi: <span class="hp-pill-badge ${intact ? 'hp-pill-success' : 'hp-pill-danger'}">${intact ? 'SHA-256 tasdiqlangan ✓' : 'Xesh mos kelmadi'}</span></strong>
            <span style="word-break:break-all;">SHA-256: ${esc(item.sha256)}</span>
          </div>

          <div class="hp-obligations-full-list">${sigsHtml}</div>

          <div class="hp-builder-actions" style="justify-content:flex-start;">
            <button type="button" class="hp-btn-navy-sm" id="btn-arch-modal-dl">DOCX yuklab olish</button>
          </div>

          <div>
            <strong style="display:block;font-size:14px;margin-bottom:8px;">Shu shartnoma bo'yicha cheklar va hujjatlar (${(item.documents || []).length})</strong>
            ${(item.documents || []).length
              ? `<div class="hp-case-timeline">${item.documents.map(renderArchiveDocItemHtml).join('')}</div>`
              : `<p class="hp-text-muted" style="font-size:13px;">Hozircha yo'q. "Arxivga yangi to'lov cheki yoki hujjat qo'shish" formasida shu shartnomani tanlab qo'shing.</p>`}
          </div>

          <form id="archive-note-form" class="hp-builder-form" style="margin-top:8px;">
            <div class="hp-form-group">
              <label for="arch-note-input">Shaxsiy izoh (faqat sizga ko'rinadi)</label>
              <textarea id="arch-note-input" class="hp-input" rows="2" placeholder="Shaxsiy eslatma...">${esc(item.note || '')}</textarea>
            </div>
            <div class="hp-form-group">
              <label for="arch-tags-input">Teglar (vergul bilan)</label>
              <input type="text" id="arch-tags-input" class="hp-input" value="${esc((item.tags || []).join(', '))}" placeholder="ijara, 2026, muhim" />
            </div>
            <div class="hp-builder-actions">
              <button type="submit" class="hp-btn-outline-sm" id="btn-arch-save-note">Izohni saqlash</button>
            </div>
          </form>
        </div>
        `
      );

      const dlBtn = document.getElementById('btn-arch-modal-dl');
      dlBtn?.addEventListener('click', () => {
        withBusy(dlBtn, async () => {
          await LexLab.archive.download(item);
          showToast('DOCX yuklab olindi');
        }).catch(() => {});
      });

      const noteForm = document.getElementById('archive-note-form');
      const saveBtn = document.getElementById('btn-arch-save-note');
      noteForm?.addEventListener('submit', (e) => {
        e.preventDefault();
        const note = document.getElementById('arch-note-input')?.value || '';
        const rawTags = document.getElementById('arch-tags-input')?.value || '';
        const tags = rawTags.split(',').map(t => t.trim()).filter(Boolean);
        withBusy(saveBtn, async () => {
          await LexLab.archive.update(item.id, { note, tags });
          showToast('Arxiv izohi saqlandi');
          await loadArchiveView();
        }).catch(() => {});
      });
    } catch (e) {
      handleErr(e);
    }
  }

  // §9 & U2.5 Notifications modal with delete one / clear read
  async function openNotificationsModal() {
    try {
      const res = await LexLab.notifications.list();
      const items = (res && res.items) || [];

      await LexLab.notifications.markRead();
      const notifDot = document.querySelector('#btn-notif-panel .hp-notif-dot');
      if (notifDot) notifDot.style.display = 'none';

      if (items.length === 0) {
        openModal('Bildirishnomalar', `<p class="hp-text-muted">Yangi bildirishnomalar yo'q.</p>`);
        return;
      }

      const html = `
        <div style="display:flex;justify-content:flex-end;margin-bottom:10px;">
          <button type="button" class="hp-btn-outline-sm" id="btn-clear-read-notifs">O'qilganlarni tozalash</button>
        </div>
        <div>
          ${items.map(n => `
            <div class="hp-case-step-card" style="margin-bottom:8px;">
              <div>
                <div style="display:flex;align-items:center;gap:8px;">
                  <strong>${esc(n.title)}</strong>
                  <span class="hp-text-muted" style="font-size:12px;">${esc(formatDateDdMmYyyy(n.created_at))}</span>
                </div>
                <p style="font-size:13px;color:var(--text-secondary);margin-top:3px;">${esc(n.body)}</p>
              </div>
              <button type="button" class="hp-btn-outline-sm" data-delete-notif="${esc(n.id)}" title="O'chirish" style="color:#DC2626;">✕</button>
            </div>
          `).join('')}
        </div>
      `;
      openModal('Bildirishnomalar', html);

      document.getElementById('btn-clear-read-notifs')?.addEventListener('click', () => {
        confirmDeleteModal(
          'Bildirishnomalarni tozalash',
          'O\'qilgan barcha bildirishnomalarni o\'chirishni tasdiqlaysizmi?',
          async () => {
            await LexLab.notifications.clear(true);
            showToast('O\'qilgan bildirishnomalar tozalandi');
            await openNotificationsModal();
          },
          () => openNotificationsModal()
        );
      });
    } catch (e) {
      handleErr(e);
    }
  }

  async function handleSituationSearch(text) {
    const dropdown = document.getElementById('ai-search-dropdown');
    if (!dropdown || !text || text.trim().length < 3) return;

    dropdown.hidden = false;
    dropdown.innerHTML = `<div style="padding:12px;font-size:13px;">Tahlil qilinmoqda...</div>`;

    try {
      const a = await LexLab.assistant.situation(text.trim());
      const stepsHtml = (a.steps || []).map(s => `<li style="margin-left:16px;font-size:12.5px;">${esc(s)}</li>`).join('');

      let mainBtnHtml = '';
      if (a.action === 'builder' && a.contract_type) {
        mainBtnHtml = `
          <button type="button" class="hp-search-suggestion" data-assist-action="builder" data-assist-code="${esc(a.contract_type.code)}">
            <span class="hp-sug-tag">Shartnoma tuz</span>
            <span>${esc(a.contract_type.title)}</span>
          </button>
        `;
      } else if (a.action === 'scanner') {
        mainBtnHtml = `
          <button type="button" class="hp-search-suggestion" data-assist-action="scanner">
            <span class="hp-sug-tag">Tekshirish</span>
            <span>Shartnomani tekshirish bo'limiga o'tish</span>
          </button>
        `;
      } else {
        mainBtnHtml = `
          <button type="button" class="hp-search-suggestion" data-assist-action="consult">
            <span class="hp-sug-tag">Maslahat</span>
            <span>Yurist bilan maslahatlashish</span>
          </button>
        `;
      }

      const altsHtml = (a.alternatives || []).map(alt => `
        <button type="button" class="hp-search-suggestion" data-assist-action="builder" data-assist-code="${esc(alt.code)}">
          <span class="hp-sug-tag">Muqobil</span>
          <span>${esc(alt.title)}</span>
        </button>
      `).join('');

      dropdown.innerHTML = `
        <div style="padding:10px 12px;border-bottom:1px solid var(--border-light);">
          <div style="font-size:13px;font-weight:600;margin-bottom:4px;">${esc(a.answer)}</div>
          ${stepsHtml ? `<ul style="margin:4px 0;">${stepsHtml}</ul>` : ''}
        </div>
        ${mainBtnHtml}
        ${altsHtml}
      `;
    } catch (e) {
      dropdown.hidden = true;
      handleErr(e);
    }
  }

  function applyLanguage(lang) {
    state.lang = lang;
    const dict = i18n[lang] || i18n.uz;

    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (dict[key]) el.textContent = dict[key];
    });

    setDashScanEyebrow();

    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      if (dict[key]) el.setAttribute('placeholder', dict[key]);
    });

    document.querySelectorAll('.hp-lang-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-lang') === lang);
    });
  }

  async function reloadAllWidgets() {
    syncSlotButtons();
    syncChatVisibility();
    if (!LexLab.auth.isLoggedIn(LexLab.activeSlot())) {
      showLoginModal();
      return;
    }
    try {
      await loadMe();
      await Promise.all([
        loadDashboard(),
        loadBhmRate(),
        initBuilder(state.builderTypeCode),
        loadMediationRequests().catch(() => {})
      ]);
      if (state.currentView === 'contracts') await loadFullContracts(state.contractFilter);
      if (state.currentView === 'reminders') await loadObligationsView();
      if (state.currentView === 'archive') await loadArchiveView();
      if (state.currentView === 'scanner') await loadScannerHistory();
    } catch (e) {
      handleErr(e);
    }
  }

  // ==================== FRONTEND_GEMINI_5: «SHARTNOMACHI AI» CHAT & «MEDIATORGA MUROJAAT» ====================
  const CHAT_STORAGE_KEY = 'lexlab.chat.v1';
  const CHAT_EXAMPLES = [
    'Kvartirani ijaraga berish uchun nima kerak?',
    'Qarz bermoqchiman, qanday rasmiylashtiraman?',
    'Ikkinchi tomon shartnomani bajarmayapti, nima qilay?'
  ];

  function formatAiFeatureError(e) {
    const code = e && e.code;
    const status = e && e.status;
    if (code === 'ai_disabled' || status === 503) return 'AI hozircha ulanmagan';
    if (code === 'rate_limited' || code === 'ai_rate_limited' || status === 429) {
      return "So'rovlar ko'p — birozdan keyin urinib ko'ring";
    }
    return window.LexLab ? LexLab.humanError(e) : ((e && e.message) || 'Xato');
  }

  function loadChatHistoryFromStorage() {
    try {
      const raw = sessionStorage.getItem(CHAT_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      state.chatHistory = Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      state.chatHistory = [];
    }
  }

  function saveChatHistoryToStorage() {
    try {
      sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify((state.chatHistory || []).slice(-20)));
    } catch (e) {
      // ignore storage errors
    }
  }

  function clearChatHistory() {
    state.chatHistory = [];
    try {
      sessionStorage.removeItem(CHAT_STORAGE_KEY);
    } catch (e) {
      // ignore
    }
    renderChatMessages();
  }

  function updateChatContextChip() {
    const chip = document.getElementById('hp-chat-context-chip');
    if (!chip) return;
    if (state.openModalContractId && state.openModalContractTitle) {
      chip.textContent = `Shartnoma: ${state.openModalContractTitle}`;
      chip.title = state.openModalContractTitle;
      chip.hidden = false;
    } else {
      chip.textContent = '';
      chip.hidden = true;
    }
  }

  function syncChatVisibility() {
    const loggedIn = !!(window.LexLab && LexLab.auth.isLoggedIn(LexLab.activeSlot()));
    const fab = document.getElementById('hp-chat-fab');
    const panel = document.getElementById('hp-chat-panel');
    if (fab) fab.hidden = !loggedIn;
    if (!loggedIn) {
      state.chatOpen = false;
      if (panel) panel.hidden = true;
    } else if (panel) {
      panel.hidden = !state.chatOpen;
    }
    updateChatContextChip();
  }

  function toggleChatPanel(open) {
    const loggedIn = !!(window.LexLab && LexLab.auth.isLoggedIn(LexLab.activeSlot()));
    if (!loggedIn) return;
    state.chatOpen = typeof open === 'boolean' ? open : !state.chatOpen;
    const panel = document.getElementById('hp-chat-panel');
    if (panel) {
      panel.hidden = !state.chatOpen;
      if (state.chatOpen) {
        updateChatContextChip();
        renderChatMessages();
        document.getElementById('hp-chat-input')?.focus();
      }
    }
  }

  function renderChatMessages() {
    const container = document.getElementById('hp-chat-messages');
    if (!container) return;

    const history = state.chatHistory || [];
    if (history.length === 0) {
      container.innerHTML = `
        <div class="hp-chat-empty">
          <div class="hp-chat-empty-greeting">
            Assalomu alaykum! Men <strong>Shartnomachi AI</strong> yordamchisiman. Shartnomalar, nizolar, mediatsiya va O'zR qonunchiligi bo'yicha savolingizni yozing yoki quyidagi namunalardan birini tanlang:
          </div>
          <div class="hp-chat-chip-list">
            ${CHAT_EXAMPLES.map(q => `<button type="button" class="hp-chat-example-chip" data-chat-example="${esc(q)}">${esc(q)}</button>`).join('')}
          </div>
        </div>
      `;
      return;
    }

    container.innerHTML = history.map(m => {
      if (m.role === 'user') {
        return `
          <div class="hp-chat-msg hp-chat-msg-user">
            <div class="hp-chat-bubble">${esc(m.content)}</div>
          </div>
        `;
      }
      const laws = Array.isArray(m.law_refs) ? m.law_refs : [];
      const lawsHtml = laws.length > 0
        ? `
          <div class="hp-chat-laws">
            <strong>Qonun (lex.uz):</strong>
            ${laws.map(r => `<div>${lawRefLink(r.ref, r.url)}${r.title ? ` — ${esc(r.title)}` : ''}</div>`).join('')}
          </div>
        `
        : '';
      const consultHtml = m.consult_lawyer
        ? adviceHtml('Aniq xulosa uchun yurist bilan maslahatlashing.')
        : '';
      const act = m.action && m.action.type ? m.action : null;
      const actionHtml = act
        ? `
          <div class="hp-chat-action-wrap">
            <button type="button" class="hp-btn-navy-sm" data-chat-action="${esc(act.type)}" data-chat-type-code="${esc(act.type_code || '')}">
              ${esc(act.label || 'Davom etish →')}
            </button>
          </div>
        `
        : '';

      return `
        <div class="hp-chat-msg hp-chat-msg-assistant">
          <div class="hp-chat-bubble">
            <div class="hp-chat-answer-text">${esc(m.content)}</div>
            ${lawsHtml}
            ${consultHtml}
            ${actionHtml}
          </div>
        </div>
      `;
    }).join('');

    container.scrollTop = container.scrollHeight;
  }

  async function sendChatMessage(rawText) {
    const text = String(rawText || '').trim();
    if (!text) return;
    if (!window.LexLab || !LexLab.assistant || typeof LexLab.assistant.chat !== 'function') {
      showToast('SDK v1.4.0 yuklanmagan — sahifani Ctrl+F5 bilan yangilang');
      return;
    }

    const inputEl = document.getElementById('hp-chat-input');
    const sendBtn = document.getElementById('hp-chat-send');
    if (sendBtn && sendBtn.disabled) return;
    if (inputEl) inputEl.value = '';

    state.chatHistory.push({ role: 'user', content: text });
    if (state.chatHistory.length > 20) state.chatHistory = state.chatHistory.slice(-20);
    saveChatHistoryToStorage();
    renderChatMessages();

    const container = document.getElementById('hp-chat-messages');
    const typingEl = document.createElement('div');
    typingEl.className = 'hp-chat-msg hp-chat-msg-assistant';
    typingEl.id = 'hp-chat-typing';
    typingEl.innerHTML = `<div class="hp-chat-bubble hp-text-muted">Javob tayyorlanmoqda…</div>`;
    if (container) {
      container.appendChild(typingEl);
      container.scrollTop = container.scrollHeight;
    }

    const apiMessages = state.chatHistory.slice(-10).map(m => ({
      role: m.role === 'assistant' ? 'assistant' : 'user',
      content: String(m.content || '')
    }));

    if (sendBtn) sendBtn.disabled = true;
    try {
      const r = await LexLab.assistant.chat(apiMessages, {
        contractId: state.openModalContractId || null,
        page: state.currentView || 'dashboard'
      });
      typingEl.remove();

      state.chatHistory.push({
        role: 'assistant',
        content: (r && r.answer) || '',
        law_refs: (r && Array.isArray(r.law_refs)) ? r.law_refs : [],
        action: (r && r.action) || null,
        consult_lawyer: !!(r && r.consult_lawyer),
        disclaimer: (r && r.disclaimer) || ''
      });
      if (state.chatHistory.length > 20) state.chatHistory = state.chatHistory.slice(-20);
      if (r && r.disclaimer) {
        state.chatDisclaimer = r.disclaimer;
        const discEl = document.getElementById('hp-chat-disclaimer');
        if (discEl) discEl.textContent = r.disclaimer;
      }
      saveChatHistoryToStorage();
      renderChatMessages();
    } catch (e) {
      typingEl.remove();
      const msg = formatAiFeatureError(e);
      showToast(msg);
      if (container) {
        const errDiv = document.createElement('div');
        errDiv.className = 'hp-rule-item hp-rule-red';
        errDiv.innerHTML = `<strong>Xato</strong><span>${esc(msg)}</span>`;
        container.appendChild(errDiv);
        container.scrollTop = container.scrollHeight;
      }
    } finally {
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  async function handleChatActionClick(btn) {
    const actType = btn.getAttribute('data-chat-action');
    const typeCode = btn.getAttribute('data-chat-type-code');
    if (!actType) return;

    if (actType === 'mediation') {
      const contractId = state.openModalContractId || null;
      await startAndOpenMediation(contractId, btn);
      return;
    }

    if (actType === 'builder') {
      closeModal();
      navigateTo('builder');
      await ensureContractTypesLoaded();
      const resolved = resolveTypeCode(typeCode);
      if (resolved) {
        const sel = document.getElementById('cb-type');
        if (sel) sel.value = resolved;
        await selectBuilderType(resolved).catch(handleErr);
      }
      return;
    }

    if (['scanner', 'contracts', 'archive', 'reminders'].includes(actType)) {
      closeModal();
      navigateTo(actType);
    }
  }

  // ---- «Mediatorga murojaat» (O'RQ-482) ----
  const MEDIATION_FORM_KEYS = [
    'applicant_name', 'applicant_address', 'applicant_phone',
    'respondent_name', 'respondent_address', 'respondent_phone',
    'mediator_name', 'mediator_org',
    'subject', 'description', 'claims', 'desired_outcome',
    'amount', 'city'
  ];

  async function loadMediationRequests() {
    if (!window.LexLab || !LexLab.mediation) return [];
    const list = await LexLab.mediation.list();
    state.mediationList = Array.isArray(list) ? list : [];
    renderMediationRequestsList(state.mediationList);
    return state.mediationList;
  }

  function renderMediationRequestsList(list) {
    const container = document.getElementById('mediation-requests-list');
    if (!container) return;

    if (!list || list.length === 0) {
      container.innerHTML = `<div class="hp-text-muted" style="text-align:center;padding:16px;">Hozircha ariza yo'q</div>`;
      return;
    }

    container.innerHTML = list.map(item => {
      const f = item.form || {};
      const subj = f.subject || 'Nizo predmeti kiritilmagan';
      const statusBadge = item.status === 'ready'
        ? '<span class="hp-pill-badge hp-pill-success">Tayyor</span>'
        : '<span class="hp-pill-badge hp-pill-neutral">Qoralama</span>';
      const contractNote = item.contract_title ? `Shartnoma: ${item.contract_title} · ` : '';

      return `
        <div class="hp-ob-row-card" data-mediation-id="${esc(item.id)}">
          <div class="hp-ob-left">
            <div>
              <strong class="hp-ob-title">${esc(subj)}</strong>
              <span class="hp-ob-sub">${esc(contractNote)}Sana: ${esc(formatDateDdMmYyyy(item.created_at))}</span>
            </div>
          </div>
          <div class="hp-ob-right">
            ${statusBadge}
            <button type="button" class="hp-btn-outline-sm" data-med-open="${esc(item.id)}">Ochish</button>
            <button type="button" class="hp-btn-navy-sm" data-med-docx="${esc(item.id)}">DOCX</button>
            <button type="button" class="hp-btn-outline-sm" data-med-delete="${esc(item.id)}" data-med-subject="${esc(subj)}" style="color:#DC2626;border-color:#FCA5A5;">O'chirish</button>
          </div>
        </div>
      `;
    }).join('');
  }

  async function startAndOpenMediation(contractId, triggerBtn) {
    const run = async () => {
      const m = await LexLab.mediation.create({}, contractId || null);
      await loadMediationRequests().catch(() => {});
      openMediationFormModal(m);
    };
    if (triggerBtn) {
      await withBusy(triggerBtn, run).catch(() => {});
    } else {
      try { await run(); } catch (e) { handleErr(e); }
    }
  }

  function renderMediationMissingHtml(missing) {
    const arr = Array.isArray(missing) ? missing.filter(Boolean) : [];
    if (arr.length === 0) return '';
    return `
      <div class="hp-rule-item hp-rule-amber">
        <strong>To'ldirish kerak: ${esc(arr.join(', '))}</strong>
      </div>
    `;
  }

  function renderMediationAiSuggestionHtml(s) {
    if (!s) return '';
    const claims = Array.isArray(s.claims) ? s.claims : [];
    const options = Array.isArray(s.options) ? s.options : [];
    const laws = Array.isArray(s.law_refs) ? s.law_refs : [];

    return `
      <div class="hp-rule-item hp-rule-green" id="med-ai-suggestion-box">
        <strong><span class="hp-sug-tag">AI</span> AI taklifi</strong>

        ${s.subject ? `
          <div style="margin-top:6px;">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
              <strong>Nizo predmeti:</strong>
              <button type="button" class="hp-btn-outline-sm" data-med-apply="subject">Qo'llash</button>
            </div>
            <div style="margin-top:2px;">${esc(s.subject)}</div>
          </div>
        ` : ''}

        ${s.statement ? `
          <div style="margin-top:8px;">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
              <strong>Nizo mazmuni (xolis bayon):</strong>
              <button type="button" class="hp-btn-outline-sm" data-med-apply="statement">Qo'llash</button>
            </div>
            <div style="margin-top:2px;white-space:pre-wrap;">${esc(s.statement)}</div>
          </div>
        ` : ''}

        ${claims.length > 0 ? `
          <div style="margin-top:8px;">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
              <strong>Talablarim:</strong>
              <button type="button" class="hp-btn-outline-sm" data-med-apply="claims">Qo'llash</button>
            </div>
            <ul style="margin:4px 0 0 18px;padding:0;">
              ${claims.map(c => `<li>${esc(c)}</li>`).join('')}
            </ul>
          </div>
        ` : ''}

        ${options.length > 0 ? `
          <div style="margin-top:8px;">
            <strong>Murosa variantlari:</strong>
            <div style="display:flex;flex-direction:column;gap:6px;margin-top:4px;">
              ${options.map((opt, idx) => `
                <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 8px;border-radius:8px;background:rgba(255,255,255,0.6);">
                  <span style="flex:1;">${esc(opt)}</span>
                  <button type="button" class="hp-btn-outline-sm" data-med-pick-option="${idx}">Tanlash</button>
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}

        ${laws.length > 0 ? `
          <div style="margin-top:8px;">
            <strong>Qonun (lex.uz):</strong>
            <div style="display:flex;flex-direction:column;gap:3px;margin-top:2px;">
              ${laws.map(r => `<div>${lawRefLink(r.ref, r.url)}${r.title ? ` — ${esc(r.title)}` : ''}</div>`).join('')}
            </div>
          </div>
        ` : ''}

        ${s.disclaimer ? `<span class="hp-text-muted" style="font-size:11.5px;margin-top:6px;">${esc(s.disclaimer)}</span>` : ''}
      </div>
    `;
  }

  function collectMediationFormValues() {
    const out = {};
    MEDIATION_FORM_KEYS.forEach(k => {
      const el = document.getElementById(`med-field-${k}`);
      if (!el) return;
      const v = String(el.value || '').trim();
      out[k] = v === '' ? null : v;
    });
    return out;
  }

  function openMediationFormModal(m) {
    if (!m) return;
    state.activeMediation = m;
    state.activeMediationAi = m.ai_draft || null;
    const f = m.form || {};
    const missing = Array.isArray(m.missing) ? m.missing : [];

    openModal(
      'Mediatorga ariza',
      `
      <form id="mediation-request-form" class="hp-builder-form" novalidate>
        ${m.contract_title ? `<div class="hp-text-muted" style="font-size:13px;">Shartnoma: <strong>${esc(m.contract_title)}</strong></div>` : ''}

        <div class="hp-rule-item hp-rule-blue">
          <span>Mediatsiya — nizoni sudsiz, betaraf mediator yordamida hal qilish (O'RQ-482). Mediatsiya ixtiyoriy, 30 kungacha davom etadi, mediator xarajati odatda teng bo'linadi. Platforma arizani tayyorlab beradi — uni mediatorga o'zingiz topshirasiz.</span>
        </div>

        <div id="med-missing-container">${renderMediationMissingHtml(missing)}</div>

        <div style="font-size:13px;font-weight:700;color:var(--text-secondary);margin-top:4px;">1. Arizachi (1-taraf)</div>
        <div class="hp-form-group">
          <label for="med-field-applicant_name">Arizachi F.I.Sh. / nomi *</label>
          <input type="text" id="med-field-applicant_name" class="hp-input" value="${esc(f.applicant_name || '')}" required />
        </div>
        <div class="hp-form-row-2">
          <div class="hp-form-group">
            <label for="med-field-applicant_address">Arizachi manzili</label>
            <input type="text" id="med-field-applicant_address" class="hp-input" value="${esc(f.applicant_address || '')}" />
          </div>
          <div class="hp-form-group">
            <label for="med-field-applicant_phone">Arizachi telefoni</label>
            <input type="text" id="med-field-applicant_phone" class="hp-input" value="${esc(f.applicant_phone || '')}" />
          </div>
        </div>

        <div style="font-size:13px;font-weight:700;color:var(--text-secondary);margin-top:4px;">2. Ikkinchi tomon (2-taraf)</div>
        <div class="hp-form-group">
          <label for="med-field-respondent_name">Ikkinchi tomon F.I.Sh. / nomi *</label>
          <input type="text" id="med-field-respondent_name" class="hp-input" value="${esc(f.respondent_name || '')}" required />
        </div>
        <div class="hp-form-row-2">
          <div class="hp-form-group">
            <label for="med-field-respondent_address">Ikkinchi tomon manzili</label>
            <input type="text" id="med-field-respondent_address" class="hp-input" value="${esc(f.respondent_address || '')}" />
          </div>
          <div class="hp-form-group">
            <label for="med-field-respondent_phone">Ikkinchi tomon telefoni</label>
            <input type="text" id="med-field-respondent_phone" class="hp-input" value="${esc(f.respondent_phone || '')}" />
          </div>
        </div>

        <div style="font-size:13px;font-weight:700;color:var(--text-secondary);margin-top:4px;">3. Mediator (ixtiyoriy)</div>
        <div class="hp-form-row-2">
          <div class="hp-form-group">
            <label for="med-field-mediator_name">Mediator F.I.Sh.</label>
            <input type="text" id="med-field-mediator_name" class="hp-input" value="${esc(f.mediator_name || '')}" />
          </div>
          <div class="hp-form-group">
            <label for="med-field-mediator_org">Mediator tashkiloti</label>
            <input type="text" id="med-field-mediator_org" class="hp-input" value="${esc(f.mediator_org || '')}" />
          </div>
        </div>

        <div style="font-size:13px;font-weight:700;color:var(--text-secondary);margin-top:4px;">4. Nizo tafsilotlari</div>
        <div class="hp-form-group">
          <label for="med-field-subject">Nizo predmeti *</label>
          <input type="text" id="med-field-subject" class="hp-input" value="${esc(f.subject || '')}" required />
        </div>

        <div class="hp-form-group">
          <label for="med-field-description">Nizo mazmuni *</label>
          <textarea id="med-field-description" class="hp-input" rows="5" required>${esc(f.description || '')}</textarea>
          <span class="hp-field-hint">kamida 20 belgi</span>
        </div>

        <div class="hp-form-group">
          <label for="med-field-claims">Talablarim</label>
          <textarea id="med-field-claims" class="hp-input" rows="3">${esc(f.claims || '')}</textarea>
          <span class="hp-field-hint">har biri yangi qatorda</span>
        </div>

        <div class="hp-form-group">
          <label for="med-field-desired_outcome">Murosa bo'yicha taklifim</label>
          <textarea id="med-field-desired_outcome" class="hp-input" rows="3">${esc(f.desired_outcome || '')}</textarea>
        </div>

        <div class="hp-form-row-2">
          <div class="hp-form-group">
            <label for="med-field-amount">Nizo summasi (so'm)</label>
            <input type="text" id="med-field-amount" class="hp-input" value="${esc(f.amount ?? '')}" />
          </div>
          <div class="hp-form-group">
            <label for="med-field-city">Shahar</label>
            <input type="text" id="med-field-city" class="hp-input" value="${esc(f.city || '')}" />
          </div>
        </div>

        <div id="med-ai-container">${renderMediationAiSuggestionHtml(state.activeMediationAi)}</div>

        <div class="hp-builder-actions" style="justify-content:flex-start;">
          <button type="button" class="hp-btn-outline" id="btn-med-save">Saqlash</button>
          <button type="button" class="hp-btn-outline" id="btn-med-ai">AI yordam</button>
          <button type="button" class="hp-btn-navy" id="btn-med-docx" ${missing.length > 0 ? 'disabled' : ''}>DOCX yuklab olish</button>
        </div>
      </form>
      `
    );

    const saveBtn = document.getElementById('btn-med-save');
    const aiBtn = document.getElementById('btn-med-ai');
    const docxBtn = document.getElementById('btn-med-docx');
    const missingBox = document.getElementById('med-missing-container');
    const aiBox = document.getElementById('med-ai-container');

    const saveMediationNow = async () => {
      const updated = await LexLab.mediation.update(m.id, collectMediationFormValues());
      state.activeMediation = updated;
      const miss = Array.isArray(updated.missing) ? updated.missing : [];
      if (missingBox) missingBox.innerHTML = renderMediationMissingHtml(miss);
      if (docxBtn) docxBtn.disabled = miss.length > 0;
      await loadMediationRequests().catch(() => {});
      return updated;
    };

    saveBtn?.addEventListener('click', () => {
      withBusy(saveBtn, async () => {
        await saveMediationNow();
        showToast('Ariza saqlandi');
      }).catch(() => {});
    });

    aiBtn?.addEventListener('click', async () => {
      if (aiBtn.disabled) return;
      aiBtn.disabled = true;
      try {
        await saveMediationNow();
        if (aiBox) {
          aiBox.innerHTML = `<div class="hp-rule-item hp-rule-blue"><strong><span class="hp-sug-tag">AI</span> AI taklifi tayyorlanmoqda…</strong></div>`;
        }
        const s = await LexLab.mediation.aiHelp(m.id);
        state.activeMediationAi = s;
        if (aiBox) aiBox.innerHTML = renderMediationAiSuggestionHtml(s);
        showToast('AI taklifi tayyor');
      } catch (e) {
        const msg = formatAiFeatureError(e);
        if (aiBox) {
          aiBox.innerHTML = `<div class="hp-rule-item hp-rule-red"><strong>AI yordam</strong><span>${esc(msg)}</span></div>`;
        }
        showToast(msg);
      } finally {
        aiBtn.disabled = false;
      }
    });

    docxBtn?.addEventListener('click', async () => {
      if (docxBtn.disabled) return;
      docxBtn.disabled = true;
      try {
        const updated = await saveMediationNow();
        const miss = Array.isArray(updated.missing) ? updated.missing : [];
        if (miss.length > 0) {
          if (missingBox) missingBox.innerHTML = renderMediationMissingHtml(miss);
          showToast(`To'ldirish kerak: ${miss.join(', ')}`);
          docxBtn.disabled = true;
          return;
        }
        await LexLab.mediation.downloadDocx(m.id);
        showToast('DOCX yuklab olindi');
      } catch (e) {
        if (e && (e.status === 422 || e.code === 'mediation_incomplete')) {
          const details = Array.isArray(e.details) ? e.details : ((e.details && e.details.missing) || []);
          if (details.length > 0) {
            if (missingBox) missingBox.innerHTML = renderMediationMissingHtml(details);
            showToast(`To'ldirish kerak: ${details.join(', ')}`);
          } else {
            handleErr(e);
          }
        } else {
          handleErr(e);
        }
      } finally {
        const curMiss = (state.activeMediation && state.activeMediation.missing) || [];
        docxBtn.disabled = curMiss.length > 0;
      }
    });
  }

  // U2.2: Poll every 15s while contract modal or builder is open
  function startNegotiationPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(async () => {
      if (!LexLab.auth.isLoggedIn(LexLab.activeSlot())) return;
      try {
        if (state.currentView === 'builder' && state.builderContractId && !state.builderDebounceTimer) {
          await refreshBuilderNegotiation();
          await refreshBuilderPreview();
        }
        if (state.openModalContractId) {
          await openContractModal(state.openModalContractId, { background: true });
        }
      } catch (e) {
        // ignore background poll error
      }
    }, 15000);
  }

  // ==================== EVENT LISTENERS ====================
  function initEventListeners() {
    document.addEventListener('click', async (e) => {
      // FRONTEND_GEMINI_4: law reference -> article text from lex.uz
      const lawBtn = e.target.closest('[data-law-ref]');
      if (lawBtn) {
        e.preventDefault();
        openLawReference(lawBtn).catch(() => {});
        return;
      }

      const navBtn = e.target.closest('[data-nav]');
      if (navBtn) {
        navigateTo(navBtn.getAttribute('data-nav'));
        return;
      }

      const gotoBtn = e.target.closest('[data-goto]');
      if (gotoBtn) {
        closeModal();
        navigateTo(gotoBtn.getAttribute('data-goto'));
        return;
      }

      // Party slot switcher (§4)
      const partyBtn = e.target.closest('[data-switch-party]');
      if (partyBtn) {
        const slot = partyBtn.getAttribute('data-switch-party');
        LexLab.useSlot(slot);
        syncSlotButtons();
        state.builderContractId = null;
        clearChatHistory();
        renderScanEmptyState();
        syncChatVisibility();
        if (!LexLab.auth.isLoggedIn(slot)) {
          showLoginModal();
        } else {
          await reloadAllWidgets();
        }
        return;
      }

      // FRONTEND_GEMINI_5: Chat example chips & action buttons
      const chatExBtn = e.target.closest('[data-chat-example]');
      if (chatExBtn) {
        await sendChatMessage(chatExBtn.getAttribute('data-chat-example'));
        return;
      }

      const chatActBtn = e.target.closest('[data-chat-action]');
      if (chatActBtn) {
        await handleChatActionClick(chatActBtn);
        return;
      }

      // FRONTEND_GEMINI_5: Mediation entry from contract modal, list & AI suggestions
      const cmMedBtn = e.target.closest('[data-contract-mediation]');
      if (cmMedBtn) {
        const cid = cmMedBtn.getAttribute('data-contract-mediation');
        await startAndOpenMediation(cid, cmMedBtn);
        return;
      }

      const medOpenBtn = e.target.closest('[data-med-open]');
      if (medOpenBtn) {
        const mid = medOpenBtn.getAttribute('data-med-open');
        await withBusy(medOpenBtn, async () => {
          const m = await LexLab.mediation.get(mid);
          openMediationFormModal(m);
        }).catch(() => {});
        return;
      }

      const medDocxBtn = e.target.closest('[data-med-docx]');
      if (medDocxBtn) {
        const mid = medDocxBtn.getAttribute('data-med-docx');
        await withBusy(medDocxBtn, async () => {
          try {
            await LexLab.mediation.downloadDocx(mid);
            showToast('DOCX yuklab olindi');
          } catch (err) {
            if (err && (err.status === 422 || err.code === 'mediation_incomplete')) {
              const details = Array.isArray(err.details) ? err.details : [];
              showToast(details.length ? `To'ldirish kerak: ${details.join(', ')}` : LexLab.humanError(err));
              const m = await LexLab.mediation.get(mid);
              openMediationFormModal(m);
              return;
            }
            throw err;
          }
        }).catch(() => {});
        return;
      }

      const medDelBtn = e.target.closest('[data-med-delete]');
      if (medDelBtn) {
        const mid = medDelBtn.getAttribute('data-med-delete');
        const subj = medDelBtn.getAttribute('data-med-subject') || 'Ariza';
        confirmDeleteModal(
          'Arizani o\'chirish',
          `"${subj}" mediatorga arizasini o'chirishni tasdiqlaysizmi?`,
          async () => {
            await LexLab.mediation.remove(mid);
            closeModal();
            showToast('Ariza o\'chirildi');
            await loadMediationRequests();
          }
        );
        return;
      }

      const medApplyBtn = e.target.closest('[data-med-apply]');
      if (medApplyBtn && state.activeMediationAi) {
        const kind = medApplyBtn.getAttribute('data-med-apply');
        const s = state.activeMediationAi;
        if (kind === 'subject' && s.subject) {
          const el = document.getElementById('med-field-subject');
          if (el) el.value = s.subject;
          showToast('Nizo predmeti to\'ldirildi — «Saqlash» tugmasini bosing');
        } else if (kind === 'statement' && s.statement) {
          const el = document.getElementById('med-field-description');
          if (el) el.value = s.statement;
          showToast('Nizo mazmuni to\'ldirildi — «Saqlash» tugmasini bosing');
        } else if (kind === 'claims' && Array.isArray(s.claims)) {
          const el = document.getElementById('med-field-claims');
          if (el) el.value = s.claims.join('\n');
          showToast('Talablar to\'ldirildi — «Saqlash» tugmasini bosing');
        }
        return;
      }

      const medPickOptBtn = e.target.closest('[data-med-pick-option]');
      if (medPickOptBtn && state.activeMediationAi && Array.isArray(state.activeMediationAi.options)) {
        const idx = Number(medPickOptBtn.getAttribute('data-med-pick-option'));
        const val = state.activeMediationAi.options[idx];
        if (val) {
          const el = document.getElementById('med-field-desired_outcome');
          if (el) el.value = val;
          showToast('Murosa taklifi tanlandi — «Saqlash» tugmasini bosing');
        }
        return;
      }

      // Invitations modal trigger
      if (e.target.closest('#btn-open-invitations') || e.target.closest('#bilateral-inbox-banner')) {
        if (!e.target.closest('[data-inv-preview],[data-inv-accept],[data-inv-decline]')) {
          await openInvitationsModal();
          return;
        }
      }

      // Invitation preview / accept / decline (§7.4 & U2.3.7)
      const invPrevBtn = e.target.closest('[data-inv-preview]');
      if (invPrevBtn) {
        const pid = invPrevBtn.getAttribute('data-inv-preview');
        await withBusy(invPrevBtn, async () => {
          await loadInvitationPreviewAndWarnings(pid, true);
        }).catch(() => {});
        return;
      }

      const invAccBtn = e.target.closest('[data-inv-accept]');
      if (invAccBtn) {
        const pid = invAccBtn.getAttribute('data-inv-accept');
        await withBusy(invAccBtn, async () => {
          const c = await LexLab.contracts.acceptInvitation(pid);
          showToast('Taklif qabul qilindi');
          closeModal();
          await loadDashboard();
          if (c.status === 'draft') {
            await openContractInBuilder(c.id);
          } else {
            await openContractModal(c.id);
          }
        }).catch(() => {});
        return;
      }

      const invDecBtn = e.target.closest('[data-inv-decline]');
      if (invDecBtn) {
        const pid = invDecBtn.getAttribute('data-inv-decline');
        await withBusy(invDecBtn, async () => {
          await LexLab.contracts.declineInvitation(pid);
          showToast('Taklif rad etildi');
          await loadDashboard();
          await openInvitationsModal();
        }).catch(() => {});
        return;
      }

      // Negotiation action card buttons (U2.2)
      const focusMissBtn = e.target.closest('[data-neg-focus-missing]');
      if (focusMissBtn) {
        const n = state.builderNegotiation;
        if (n && n.missing_by_side) {
          const keys = (n.missing_by_side[n.my_side] || []).concat(n.missing_by_side.shared || []);
          if (keys[0]) {
            const inp = document.querySelector(`#cb-dynamic-questionnaire [data-q-key="${CSS.escape(keys[0])}"]`);
            inp?.focus();
          }
        }
        return;
      }

      const negInvBtn = e.target.closest('[data-neg-invite]');
      if (negInvBtn) {
        const cid = negInvBtn.getAttribute('data-neg-invite');
        const phoneInputId = negInvBtn.getAttribute('data-phone-input');
        const phone = (document.getElementById(phoneInputId)?.value || '').trim();
        await withBusy(negInvBtn, async () => {
          await LexLab.contracts.invite(cid, phone, 'B');
          showToast(`Taklif ${phone} raqamiga yuborildi`);
          if (state.builderContractId === cid) await refreshBuilderNegotiation();
          if (state.openModalContractId === cid) await openContractModal(cid);
          await loadDashboard();
        }).catch(() => {});
        return;
      }

      const negAutofixBtn = e.target.closest('[data-neg-autofix]');
      if (negAutofixBtn) {
        const cid = negAutofixBtn.getAttribute('data-neg-autofix');
        await handleBuilderAutofix(negAutofixBtn, cid).catch(() => {});
        return;
      }

      const negAgreeBtn = e.target.closest('[data-neg-agree]');
      if (negAgreeBtn) {
        const cid = negAgreeBtn.getAttribute('data-neg-agree');
        await handleContractAgree(negAgreeBtn, cid).catch(() => {});
        return;
      }

      const negOpenObjBtn = e.target.closest('[data-neg-open-object]');
      if (negOpenObjBtn) {
        const cid = negOpenObjBtn.getAttribute('data-neg-open-object');
        await openObjectionModal(cid);
        return;
      }

      const negGenBtn = e.target.closest('[data-neg-generate]');
      if (negGenBtn) {
        const cid = negGenBtn.getAttribute('data-neg-generate');
        await handleContractGenerate(negGenBtn, cid).catch(() => {});
        return;
      }

      // Objection resolve: accept / reject / withdraw (U2.3.4)
      const objResBtn = e.target.closest('[data-obj-resolve]');
      if (objResBtn) {
        const oid = objResBtn.getAttribute('data-obj-resolve');
        const cid = objResBtn.getAttribute('data-obj-contract');
        const act = objResBtn.getAttribute('data-obj-action');
        await withBusy(objResBtn, async () => {
          await LexLab.contracts.resolveObjection(cid, oid, act);
          const msgMap = {
            accept: 'Taklif qabul qilindi va shartlarga qo\'llandi',
            reject: 'Norozilik rad etildi',
            withdraw: 'Norozilik qaytarib olindi'
          };
          showToast(msgMap[act] || 'Bajarildi');
          if (state.builderContractId === cid) {
            await refreshBuilderNegotiation();
            await refreshBuilderPreview();
          }
          if (state.openModalContractId === cid) {
            await openContractModal(cid);
          }
          await loadDashboard();
        }).catch(() => {});
        return;
      }

      // Revoke pending invitation (U2.5)
      const revInvBtn = e.target.closest('[data-revoke-invite]');
      if (revInvBtn) {
        const pid = revInvBtn.getAttribute('data-revoke-invite');
        const cid = revInvBtn.getAttribute('data-revoke-contract');
        confirmDeleteModal(
          'Taklifni bekor qilish',
          'Yuborilgan taklifni bekor qilishni tasdiqlaysizmi?',
          async () => {
            await LexLab.contracts.revokeInvitation(cid, pid);
            showToast('Taklif bekor qilindi');
            if (state.builderContractId === cid) await refreshBuilderNegotiation();
            await openContractModal(cid);
          },
          () => openContractModal(cid)
        );
        return;
      }

      // Personal Archive view & download (U2.4)
      const archViewBtn = e.target.closest('[data-archive-view]');
      if (archViewBtn) {
        const itemId = archViewBtn.getAttribute('data-archive-view');
        await openArchiveItemModal(itemId);
        return;
      }

      const archDlBtn = e.target.closest('[data-archive-download]');
      if (archDlBtn) {
        const itemId = archDlBtn.getAttribute('data-archive-download');
        const item = state.archiveItems.find(x => x.id === itemId);
        if (item) {
          await withBusy(archDlBtn, async () => {
            await LexLab.archive.download(item);
            showToast('DOCX yuklab olindi');
          }).catch(() => {});
        }
        return;
      }

      // Archive documents: download / delete
      const docDlBtn = e.target.closest('[data-doc-download]');
      if (docDlBtn) {
        const doc = (state.archiveDocs || []).find(x => x.id === docDlBtn.getAttribute('data-doc-download'));
        if (doc) {
          await withBusy(docDlBtn, async () => {
            await LexLab.archive.downloadDocument(doc);
            showToast('Fayl yuklab olindi');
          }).catch(() => {});
        }
        return;
      }
      const docDelBtn = e.target.closest('[data-doc-delete]');
      if (docDelBtn) {
        const doc = (state.archiveDocs || []).find(x => x.id === docDelBtn.getAttribute('data-doc-delete'));
        if (doc) {
          confirmDeleteModal('Hujjatni o\'chirish', `"${doc.title}" hujjati va uning fayli o'chiriladi. Tasdiqlaysizmi?`, async () => {
            await LexLab.archive.deleteDocument(doc.id);
            closeModal();
            showToast('Hujjat o\'chirildi');
            await loadArchiveView();
          });
        }
        return;
      }

      // Scanner history open & delete (U2.5)
      const openScanBtn = e.target.closest('[data-open-scan]');
      if (openScanBtn) {
        const sid = openScanBtn.getAttribute('data-open-scan');
        await withBusy(openScanBtn, async () => {
          await processScanJob(sid, `Tahlil #${String(sid).slice(0, 6)}`);
        }).catch(() => {});
        return;
      }

      const delScanBtn = e.target.closest('[data-delete-scan]');
      if (delScanBtn) {
        const sid = delScanBtn.getAttribute('data-delete-scan');
        confirmDeleteModal(
          'Tahlilni o\'chirish',
          'Ushbu skaner tahlili va yuklangan faylni o\'chirishni tasdiqlaysizmi?',
          async () => {
            await LexLab.scans.remove(sid);
            if (sid === state.currentScanId) renderScanEmptyState();
            closeModal();
            showToast('Tahlil o\'chirildi');
            await loadScannerHistory();
            await loadDashboard();
          }
        );
        return;
      }

      // Delete notification (U2.5)
      const delNotifBtn = e.target.closest('[data-delete-notif]');
      if (delNotifBtn) {
        const nid = delNotifBtn.getAttribute('data-delete-notif');
        confirmDeleteModal(
          'Bildirishnomani o\'chirish',
          'Ushbu bildirishnomani o\'chirishni tasdiqlaysizmi?',
          async () => {
            await LexLab.notifications.remove(nid);
            showToast('Bildirishnoma o\'chirildi');
            await openNotificationsModal();
          },
          () => openNotificationsModal()
        );
        return;
      }

      // Dashboard obligation done button (§5)
      const dashObBtn = e.target.closest('[data-dash-ob-done]');
      if (dashObBtn) {
        const obId = dashObBtn.getAttribute('data-dash-ob-done');
        await withBusy(dashObBtn, async () => {
          await LexLab.obligations.setStatus(obId, 'done');
          showToast('Majburiyat bajarildi deb belgilandi');
          await loadDashboard();
        }).catch(() => {});
        return;
      }

      // Dashboard clause action (§5)
      const dashClauseBtn = e.target.closest('[data-clause-action]');
      if (dashClauseBtn) {
        const action = dashClauseBtn.getAttribute('data-clause-action');
        const scanId = dashClauseBtn.getAttribute('data-scan-id') || (state.dashboardData?.last_scan?.id);
        const findingId = dashClauseBtn.getAttribute('data-finding-id') || (state.dashboardData?.last_scan?.top_findings?.[0]?.id);
        if (!scanId || !findingId) return;

        await withBusy(dashClauseBtn, async () => {
          const res = await LexLab.scans.decide(scanId, findingId, action);
          const statusEl = document.getElementById('dash-clause-1-status');
          const detailEl = document.getElementById('dash-clause-1-detail');
          if (statusEl) statusEl.textContent = action === 'agree' ? 'Rozilik bildirildi' : 'E\'tiroz bildirildi';
          if (detailEl) {
            if (action === 'object' && res && res.alternative && !detailEl.parentElement.querySelector('.hp-clause-advice')) {
              detailEl.innerHTML = adviceHtml(res.alternative, 'Muqobil band');
              detailEl.hidden = false;
            } else {
              detailEl.hidden = action !== 'object';
            }
          }
          showToast('Qaror saqlandi');
        }).catch(() => {});
        return;
      }

      // Scanner decision cards (§8.2)
      const scanDecBtn = e.target.closest('[data-scan-decision]');
      if (scanDecBtn) {
        const decision = scanDecBtn.getAttribute('data-scan-decision');
        const fid = scanDecBtn.getAttribute('data-finding-id');
        if (!state.currentScanId || !fid) return;

        await withBusy(scanDecBtn, async () => {
          await LexLab.scans.decide(state.currentScanId, fid, decision);
          const updated = await LexLab.scans.report(state.currentScanId);
          state.currentScanReport = updated;
          renderScanReport(updated, state.currentScanTitle);
          await loadDashboard();
        }).catch(() => {});
        return;
      }

      // Scanner post-report buttons (§8.4)
      const toObBtn = e.target.closest('#btn-scan-to-obligations');
      if (toObBtn && state.currentScanId) {
        await withBusy(toObBtn, async () => {
          const res = await LexLab.scans.toObligations(state.currentScanId);
          const count = (res && res.created && res.created.length) || 0;
          showToast(`${count} ta majburiyat eslatmalarga qo'shildi`);
          await loadDashboard();
        }).catch(() => {});
        return;
      }

      const dlRepBtn = e.target.closest('#btn-scan-download-report');
      if (dlRepBtn && state.currentScanId) {
        await withBusy(dlRepBtn, async () => {
          await LexLab.scans.downloadReport(state.currentScanId);
          showToast('Hisobot (DOCX) yuklab olindi');
        }).catch(() => {});
        return;
      }

      // Builder STIR lookup (§6.6)
      const stirBtn = e.target.closest('#btn-stir-lookup-b');
      if (stirBtn) {
        await handleBuilderStirLookup(stirBtn).catch(() => {});
        return;
      }

      // Contract inspect / row click (§7)
      const inspectBtn = e.target.closest('[data-inspect-contract]');
      if (inspectBtn) {
        e.stopPropagation();
        await openContractModal(inspectBtn.getAttribute('data-inspect-contract'));
        return;
      }

      const contractRow = e.target.closest('tr[data-contract-id]');
      if (contractRow) {
        await openContractModal(contractRow.getAttribute('data-contract-id'));
        return;
      }

      // Obligations toggle, confirm & delete (§9 & U2.5)
      const confirmObBtn = e.target.closest('[data-confirm-ob]');
      if (confirmObBtn) {
        const obId = confirmObBtn.getAttribute('data-confirm-ob');
        await withBusy(confirmObBtn, async () => {
          await LexLab.obligations.confirm(obId);
          showToast('Majburiyat tasdiqlandi');
          await loadObligationsView();
          await loadDashboard();
        }).catch(() => {});
        return;
      }

      const obToggleBtn = e.target.closest('[data-complete-ob]');
      if (obToggleBtn) {
        const obId = obToggleBtn.getAttribute('data-complete-ob');
        const nextSt = obToggleBtn.getAttribute('data-next-status') || 'done';
        await withBusy(obToggleBtn, async () => {
          await LexLab.obligations.setStatus(obId, nextSt);
          showToast('Majburiyat holati yangilandi');
          await loadObligationsView();
          await loadDashboard();
        }).catch(() => {});
        return;
      }

      const delObBtn = e.target.closest('[data-delete-ob]');
      if (delObBtn) {
        const obId = delObBtn.getAttribute('data-delete-ob');
        const obTitle = delObBtn.getAttribute('data-ob-title') || 'Eslatma';
        confirmDeleteModal(
          'Eslatmani o\'chirish',
          `"${obTitle}" eslatmasini o'chirishni tasdiqlaysizmi?`,
          async () => {
            try {
              await LexLab.obligations.remove(obId);
              closeModal();
              showToast('Eslatma o\'chirildi');
              await loadObligationsView();
              await loadDashboard();
            } catch (err) {
              closeModal();
              throw err;
            }
          }
        );
        return;
      }

      // Channel chips (§5)
      const channelChip = e.target.closest('.hp-channel-chip[data-channel]');
      if (channelChip) {
        const ch = channelChip.getAttribute('data-channel');
        channelChip.classList.toggle('active');
        if (ch === 'push' && !state.pushToastShown) {
          state.pushToastShown = true;
          showToast('Push xabarnoma serverda sozlanmagan — ilova ichidagi bildirishnoma ishlatiladi');
        }
        const activeChannels = ['in_app'];
        if (document.querySelector('.hp-channel-chip[data-channel="sms"]')?.classList.contains('active')) {
          activeChannels.push('sms');
        }
        if (document.querySelector('.hp-channel-chip[data-channel="telegram"]')?.classList.contains('active')) {
          activeChannels.push('telegram');
        }
        try {
          await LexLab.me.update({ channels: activeChannels });
        } catch (err) {
          handleErr(err);
        }
        return;
      }

      // Search assistant dynamic buttons (§9)
      const assistBtn = e.target.closest('[data-assist-action]');
      if (assistBtn) {
        const act = assistBtn.getAttribute('data-assist-action');
        const code = assistBtn.getAttribute('data-assist-code');
        const dropdown = document.getElementById('ai-search-dropdown');
        if (dropdown) dropdown.hidden = true;

        if (act === 'builder') {
          navigateTo('builder');
          if (code) {
            const sel = document.getElementById('cb-type');
            if (sel) sel.value = resolveTypeCode(code);
            await selectBuilderType(code).catch(handleErr);
          }
        } else if (act === 'scanner') {
          navigateTo('scanner');
        } else {
          showToast('Maslahat uchun Yurist arxivi yoki yuristga murojaat qiling');
        }
        return;
      }
    });

    // Static search suggestions (§9 / §6.1)
    document.querySelectorAll('.hp-search-suggestion[data-action]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const action = btn.getAttribute('data-action');
        const cType = btn.getAttribute('data-contract-type');
        const sKey = btn.getAttribute('data-scan-key');
        const dropdown = document.getElementById('ai-search-dropdown');
        if (dropdown) dropdown.hidden = true;

        if (action === 'builder') {
          const code = resolveTypeCode(cType);
          navigateTo('builder');
          const sel = document.getElementById('cb-type');
          if (sel && code) sel.value = code;
          if (code) await selectBuilderType(code).catch(handleErr);
        } else if (action === 'scanner') {
          navigateTo('scanner');
          if (sKey) await runScannerPreset(sKey, null).catch(handleErr);
        }
      });
    });

    // Search form submit (§9)
    const searchInput = document.getElementById('ai-situation-input');
    const searchDropdown = document.getElementById('ai-search-dropdown');
    const suggestBtn = document.getElementById('btn-ai-prompt-suggest');
    const searchForm = document.getElementById('ai-situation-form');

    if (searchInput && searchDropdown) {
      searchInput.addEventListener('focus', () => { searchDropdown.hidden = false; });
      suggestBtn?.addEventListener('click', () => { searchDropdown.hidden = !searchDropdown.hidden; });
      document.addEventListener('click', (e) => {
        if (!e.target.closest('.hp-search-wrapper')) searchDropdown.hidden = true;
      });
    }

    searchForm?.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = (searchInput?.value || '').trim();
      if (text) handleSituationSearch(text);
    });

    // Builder type change & dynamic form input (§6)
    document.getElementById('cb-type')?.addEventListener('change', (e) => {
      selectBuilderType(e.target.value).catch(handleErr);
    });

    const builderForm = document.getElementById('contract-builder-form');
    if (builderForm) {
      builderForm.addEventListener('input', (e) => {
        const target = e.target.closest('[data-q-key]');
        if (!target) return;
        queueBuilderAnswerSave(target.getAttribute('data-q-key'), collectFieldValue(target));
      });
      builderForm.addEventListener('change', (e) => {
        const target = e.target.closest('[data-q-key]');
        if (!target) return;
        queueBuilderAnswerSave(target.getAttribute('data-q-key'), collectFieldValue(target));
      });
    }

    document.getElementById('btn-builder-autofix')?.addEventListener('click', (e) => {
      handleBuilderAutofix(e.currentTarget).catch(() => {});
    });

    document.getElementById('btn-builder-generate')?.addEventListener('click', (e) => {
      handleBuilderPrimaryAction(e.currentTarget).catch(() => {});
    });

    document.querySelectorAll('[data-doc-lang]').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('[data-doc-lang]').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        state.docPreviewLang = tab.getAttribute('data-doc-lang') || 'uz';
        refreshBuilderPreview().catch(handleErr);
      });
    });

    // Contract list filters (§7.1)
    document.querySelectorAll('#full-contract-filters .hp-filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('#full-contract-filters .hp-filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        const filter = pill.getAttribute('data-filter') || 'all';
        loadFullContracts(filter).catch(handleErr);
      });
    });

    // Scanner upload & presets (§8)
    document.querySelectorAll('[data-scan-preset]').forEach(btn => {
      btn.addEventListener('click', () => {
        runScannerPreset(btn.getAttribute('data-scan-preset'), btn).catch(() => {});
      });
    });

    const dropzone = document.getElementById('scanner-dropzone');
    const fileInput = document.getElementById('scanner-file-input');
    const triggerUploadBtn = document.getElementById('btn-trigger-file-upload');

    if (triggerUploadBtn && fileInput) {
      triggerUploadBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
      });
    }
    if (dropzone && fileInput) {
      dropzone.addEventListener('click', (e) => {
        if (e.target !== fileInput) fileInput.click();
      });
      dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
      });
      dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        const file = e.dataTransfer?.files?.[0];
        if (file) runScannerUpload(file);
      });
      fileInput.addEventListener('change', () => {
        const file = fileInput.files?.[0];
        if (file) runScannerUpload(file);
        fileInput.value = '';
      });
    }

    // Reminders add button (§9)
    document.getElementById('btn-add-obligation')?.addEventListener('click', openAddObligationModal);

    // Archive form: any user files a payment receipt / document (+ for lawyers also a case-file step) & export ZIP (§9)
    const caseForm = document.getElementById('case-step-form');
    if (caseForm) {
      caseForm.setAttribute('novalidate', '');
      caseForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const submitBtn = caseForm.querySelector('button[type="submit"]');
        const val = id => (document.getElementById(id)?.value || '').trim();
        const fileEl = document.getElementById('cs-file');
        const file = fileEl && fileEl.files && fileEl.files[0] ? fileEl.files[0] : null;
        const title = val('cs-title');
        const amountRaw = val('cs-amount').replace(/\s+/g, '').replace(',', '.');
        const maxMb = (state.meta && state.meta.max_upload_mb) || 20;

        let problem = '';
        if (title.length < 2) problem = 'Hujjat nomini kiriting';
        else if (amountRaw && !/^\d+(\.\d{1,2})?$/.test(amountRaw)) problem = 'Summa faqat raqam bo\'lishi kerak (masalan: 3000000)';
        else if (file && file.size > maxMb * 1048576) problem = `Fayl hajmi ${maxMb} MB dan oshmasligi kerak`;
        else if (file && !/\.(pdf|jpe?g|png|webp|docx)$/i.test(file.name)) problem = 'Faqat PDF, rasm (JPG/PNG) yoki DOCX fayl yuklash mumkin';
        if (problem) {
          showToast(problem);
          return;
        }

        const kind = val('cs-type') || 'receipt';
        withBusy(submitBtn, async () => {
          const doc = await LexLab.archive.addDocument({
            title,
            kind,
            description: val('cs-desc'),
            amount: amountRaw,
            docDate: val('cs-date'),
            archiveId: val('cs-archive'),
            file
          });
          // a lawyer's case file also gets the step (+ the evidence file); never blocks the archive entry
          if (state.me && state.me.role === 'lawyer' && state.currentCaseId) {
            try {
              const step = await LexLab.cases.addStep(state.currentCaseId, {
                title, description: val('cs-desc'), tags: [doc.kind_label || 'Hujjat']
              });
              if (file && step && step.id) await LexLab.cases.attach(state.currentCaseId, step.id, file);
            } catch (err) { /* case file is optional */ }
          }
          caseForm.reset();
          showToast(file ? 'Hujjat va fayl arxivga saqlandi' : 'Hujjat arxivga saqlandi');
          await loadArchiveView();
        }).catch(() => {});
      });
    }

    const exportZipBtn = document.getElementById('btn-export-case-zip');
    if (exportZipBtn) {
      exportZipBtn.addEventListener('click', () => {
        if (!state.currentCaseId) {
          showToast('Eksport qilish uchun yurist arxivida ish mavjud emas');
          return;
        }
        withBusy(exportZipBtn, async () => {
          await LexLab.cases.exportZip(state.currentCaseId);
          showToast('Dalillar to\'plami (ZIP) yuklab olindi');
        }).catch(() => {});
      });
    }

    // BHM Calculator (§5)
    const bhmInput = document.getElementById('bhm-count-input');
    const bhmInc = document.getElementById('bhm-inc-btn');
    const bhmDec = document.getElementById('bhm-dec-btn');
    const bhmCalcBtn = document.getElementById('btn-bhm-calculate');

    bhmInput?.addEventListener('input', updateBhmCalculator);
    bhmInc?.addEventListener('click', () => {
      if (bhmInput) bhmInput.value = (parseFloat(bhmInput.value) || 0) + 1;
      updateBhmCalculator();
    });
    bhmDec?.addEventListener('click', () => {
      if (bhmInput) bhmInput.value = Math.max(1, (parseFloat(bhmInput.value) || 1) - 1);
      updateBhmCalculator();
    });
    bhmCalcBtn?.addEventListener('click', () => {
      updateBhmCalculator();
      showToast(`Davlat boji: ${document.getElementById('bhm-calculated-output')?.textContent}`);
    });

    // Header actions: Logout, Profile, Notifications, Lang, Theme
    document.getElementById('btn-logout')?.addEventListener('click', async () => {
      await LexLab.auth.logout();
      clearChatHistory();
      renderScanEmptyState();
      syncChatVisibility();
      showLoginModal();
    });

    // FRONTEND_GEMINI_5: Floating Chat & "+ Yangi ariza" listeners
    document.getElementById('hp-chat-fab')?.addEventListener('click', () => toggleChatPanel());
    document.getElementById('hp-chat-close')?.addEventListener('click', () => toggleChatPanel(false));
    document.getElementById('hp-chat-clear')?.addEventListener('click', () => clearChatHistory());

    const chatForm = document.getElementById('hp-chat-form');
    const chatInput = document.getElementById('hp-chat-input');
    chatForm?.addEventListener('submit', (e) => {
      e.preventDefault();
      sendChatMessage(chatInput?.value || '');
    });
    chatInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage(chatInput.value || '');
      }
    });

    document.getElementById('btn-new-mediation')?.addEventListener('click', (e) => {
      startAndOpenMediation(null, e.currentTarget);
    });

    document.getElementById('btn-profile-modal')?.addEventListener('click', openProfileModal);
    document.getElementById('btn-notif-panel')?.addEventListener('click', openNotificationsModal);

    document.querySelectorAll('.hp-lang-btn').forEach(btn => {
      btn.addEventListener('click', () => applyLanguage(btn.getAttribute('data-lang')));
    });

    const themeToggle = document.getElementById('btn-theme-toggle');
    themeToggle?.addEventListener('click', () => {
      document.body.classList.toggle('dark-mode');
      themeToggle.classList.toggle('switched');
    });

    // Modal close handlers
    document.getElementById('hp-modal-close')?.addEventListener('click', () => closeModal(false));
    document.getElementById('hp-modal-ok')?.addEventListener('click', () => closeModal(false));
    document.getElementById('hp-modal-backdrop')?.addEventListener('click', (e) => {
      if (e.target.id === 'hp-modal-backdrop') closeModal(false);
    });
  }

  // ==================== STARTUP ====================
  document.addEventListener('DOMContentLoaded', async () => {
    if (!window.LexLab) {
      showToast('LexLab SDK (/sdk/lexlab-api.js) yuklanmadi. Saytni http://127.0.0.1:8000 orqali oching.');
      return;
    }

    if (['3000', '5173', '5500', '8080', '8090'].includes(window.location.port)) {
      LexLab.configure({ baseUrl: 'http://127.0.0.1:8000' });
    }

    loadChatHistoryFromStorage();
    renderChatMessages();
    initEventListeners();
    syncSlotButtons();
    syncChatVisibility();
    renderScanEmptyState();
    startNegotiationPolling();

    LexLab.on('login', () => {
      syncChatVisibility();
    });
    LexLab.on('slot', () => {
      clearChatHistory();
      syncChatVisibility();
    });
    LexLab.on('logout', () => {
      clearChatHistory();
      renderScanEmptyState();
      syncChatVisibility();
      if (!LexLab.auth.isLoggedIn(LexLab.activeSlot())) {
        showLoginModal();
      }
    });
    LexLab.on('unauthorized', () => {
      if (!LexLab.auth.isLoggedIn(LexLab.activeSlot())) {
        showLoginModal();
      }
    });

    try {
      state.meta = await LexLab.meta();
    } catch (e) {
      handleErr(e);
    }

    if (!LexLab.auth.isLoggedIn(LexLab.activeSlot())) {
      showLoginModal();
    } else {
      await reloadAllWidgets();
    }
  });
})();
