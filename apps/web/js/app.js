/**
 * HUQUQIY PLATFORMA — LexLab API Frontend Integration (js/app.js)
 * All server communication goes exclusively through window.LexLab (/sdk/lexlab-api.js).
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
    bhmBaseValue: 375000,
    contractFilter: 'all',
    docPreviewLang: 'uz',

    // Builder
    contractTypes: [],
    builderTypeCode: null,
    builderTypeDetail: null,
    builderContractId: null,
    builderAnswers: {},
    builderFieldMap: {},
    builderDebounceTimer: null,
    builderPendingPatch: {},
    builderPreviewSha256: null,

    // Scanner
    currentScanId: null,
    currentScanTitle: null,
    currentScanReport: null,

    // Archive
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
  }

  function closeModal(force) {
    if (state.modalLocked && !force) return;
    state.modalLocked = false;
    const backdrop = document.getElementById('hp-modal-backdrop');
    const closeBtn = document.getElementById('hp-modal-close');
    const footerEl = document.getElementById('hp-modal-footer');
    if (closeBtn) closeBtn.hidden = false;
    if (footerEl) footerEl.hidden = false;
    if (backdrop) backdrop.hidden = true;
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

    if (sendBtn) {
      sendBtn.addEventListener('click', () => {
        const phone = (phoneInput?.value || '').trim();
        withBusy(sendBtn, async () => {
          await LexLab.auth.requestOtp(phone);
          otpRequestedFor = phone;
          showToast('SMS-kod yuborildi');
          codeInput?.focus();
        }).catch(() => {});
      });
    }

    if (form) {
      form.addEventListener('submit', (e) => {
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
  }

  async function loadMe() {
    const me = await LexLab.me.get();
    state.me = me;

    const nameEl = document.getElementById('current-user-name');
    const badgeEl = document.getElementById('current-user-badge');
    const fullName = me.profile && me.profile.full_name;

    if (nameEl) nameEl.textContent = fullName || maskPhone(me.phone);
    if (badgeEl) {
      badgeEl.textContent = me.identity_verified_via ? 'OneID tasdiqlangan' : 'Telefon tasdiqlangan';
    }

    // Channel chips initial state from me.preferences.channels (default ['in_app', 'sms'])
    const channels = (me.preferences && me.preferences.channels) || ['in_app', 'sms'];
    document.querySelectorAll('.hp-channel-chip[data-channel]').forEach(chip => {
      const ch = chip.getAttribute('data-channel');
      if (ch === 'sms' || ch === 'telegram') {
        chip.classList.toggle('active', channels.includes(ch));
      } else if (ch === 'push') {
        chip.classList.toggle('active', false);
      }
    });

    // Settings profile view update if present
    renderSettingsProfile(me);
  }

  function renderSettingsProfile(me) {
    const list = document.querySelector('#view-settings .hp-setting-list');
    if (!list || !me) return;
    const fullName = (me.profile && me.profile.full_name) || 'Kiritilmagan';
    const badgeText = me.identity_verified_via ? 'OneID tasdiqlangan' : 'Telefon tasdiqlangan';
    list.innerHTML = `
      <div class="hp-setting-item">
        <div>
          <strong>${esc(fullName)} (${esc(me.role)})</strong>
          <p>Telefon: ${esc(me.phone || '—')} · Faol slot: ${esc(LexLab.activeSlot() === 'party_b' ? '2-Tomon' : '1-Tomon')}</p>
        </div>
        <span class="hp-pill-badge hp-pill-success">${esc(badgeText)}</span>
      </div>
    `;
  }

  function openProfileModal() {
    const me = state.me;
    if (!me) return;
    const currentName = (me.profile && me.profile.full_name) || '';

    openModal(
      'Foydalanuvchi profili',
      `
      <form id="profile-edit-form" class="hp-builder-form">
        <div class="hp-form-row-2">
          <div class="hp-form-group">
            <label>Telefon raqami</label>
            <input type="text" class="hp-input" value="${esc(me.phone || '')}" disabled />
          </div>
          <div class="hp-form-group">
            <label>Rol</label>
            <input type="text" class="hp-input" value="${esc(me.role || 'user')}" disabled />
          </div>
        </div>
        <div class="hp-form-group">
          <label for="profile-fullname-input">F.I.Sh. (To'liq ism)</label>
          <input type="text" id="profile-fullname-input" class="hp-input" value="${esc(currentName)}" placeholder="Ism va familiyangizni kiriting" required />
        </div>
        <div class="hp-builder-actions">
          <button type="submit" class="hp-btn-navy" id="btn-save-profile">Saqlash</button>
        </div>
      </form>
      `
    );

    const form = document.getElementById('profile-edit-form');
    const btn = document.getElementById('btn-save-profile');
    if (form) {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        const full_name = (document.getElementById('profile-fullname-input')?.value || '').trim();
        withBusy(btn, async () => {
          await LexLab.me.profile({ full_name });
          await loadMe();
          closeModal();
          showToast('Profil ma\'lumotlari saqlandi');
        }).catch(() => {});
      });
    }
  }

  // ==================== §5 DASHBOARD ====================
  async function loadDashboard() {
    const d = await LexLab.dashboard();
    state.dashboardData = d;

    // 1. Nav contracts count
    const countBadge = document.getElementById('nav-contracts-count');
    if (countBadge) countBadge.textContent = String(d.contracts?.total ?? 0);

    // 2. Notification unread dot
    const notifDot = document.querySelector('#btn-notif-panel .hp-notif-dot');
    if (notifDot) {
      notifDot.style.display = (d.notifications_unread || 0) > 0 ? 'block' : 'none';
    }

    // 3. Invitations banner & party-b badge
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
              <strong>Sizga imzolash uchun ${invCount} ta shartnoma taklifi kelgan</strong>
              <span>Shartnoma matnini ko'rib chiqib, qabul qilishingiz va SMS-kod bilan imzolashingiz mumkin.</span>
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

    // 4. Dashboard recent contracts table
    renderDashboardContractsTable(d.contracts?.recent || []);

    // 5. Risk gauge & top findings
    renderDashboardLastScan(d.last_scan);

    // 6. Obligations timeline
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

  function renderDashboardLastScan(lastScan) {
    const arcEl = document.getElementById('dash-gauge-arc');
    const needleEl = document.getElementById('dash-gauge-needle');
    const line1El = document.getElementById('dash-gauge-line1');
    const line2El = document.getElementById('dash-gauge-line2');
    const clause1El = document.getElementById('dash-clause-1');
    const clause2El = document.getElementById('dash-clause-2');

    if (!lastScan) {
      if (arcEl) arcEl.setAttribute('stroke-dashoffset', '300');
      if (needleEl) needleEl.setAttribute('transform', 'translate(100, 82) rotate(-66)');
      if (line1El) line1El.textContent = 'Tahlil';
      if (line2El) line2El.textContent = 'yo\'q';

      if (clause1El) {
        clause1El.className = 'hp-clause-alert';
        clause1El.innerHTML = `
          <div class="hp-clause-main-row">
            <span class="hp-pill-badge hp-pill-neutral">Ma'lumot</span>
            <p class="hp-clause-text">Hali tahlil yo'q — shartnomani tekshiring</p>
          </div>
        `;
      }
      if (clause2El) clause2El.hidden = true;
      return;
    }

    const pct = lastScan.risk_percent ?? 0;
    const dashOffset = Math.min(300, Math.max(15, 300 - 2.9 * pct));
    const angle = -66 + 1.35 * pct;

    if (arcEl) arcEl.setAttribute('stroke-dashoffset', String(dashOffset));
    if (needleEl) needleEl.setAttribute('transform', `translate(100, 82) rotate(${angle})`);

    const labelParts = String(lastScan.risk_label || 'Past xavf').split(/\s+/);
    if (line1El) line1El.textContent = labelParts[0] || 'Past';
    if (line2El) line2El.textContent = labelParts.slice(1).join(' ') || 'xavf';

    const findings = lastScan.top_findings || [];

    if (clause1El) {
      if (findings[0]) {
        const f0 = findings[0];
        const isRed = f0.severity === 'red';
        const pillCls = isRed ? 'hp-pill-danger' : (f0.severity === 'yellow' ? 'hp-pill-warning' : 'hp-pill-neutral');
        const pillText = isRed ? 'Qonunga zid' : (f0.severity === 'yellow' ? 'Qaltis band' : 'Maslahat');
        const showDetail = f0.user_decision === 'object' && f0.suggestion;
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
              ${f0.law_ref ? `<br/><small class="hp-text-muted">${esc(f0.law_ref)}</small>` : ''}
            </p>
          </div>
          <div class="hp-clause-actions-row">
            <span class="hp-decision-feedback" id="dash-clause-1-status">${esc(feedbackText)}</span>
            <div class="hp-clause-btns">
              <button type="button" class="hp-btn-navy-sm" data-clause-action="agree" data-scan-id="${esc(lastScan.id)}" data-finding-id="${esc(f0.id)}">Roziman</button>
              <button type="button" class="hp-btn-outline-sm" data-clause-action="object" data-scan-id="${esc(lastScan.id)}" data-finding-id="${esc(f0.id)}">E'tiroz</button>
            </div>
          </div>
          <div class="hp-clause-detail-collapse" id="dash-clause-1-detail" ${showDetail ? '' : 'hidden'}>
            ${f0.suggestion ? `<strong>Taklif:</strong> ${esc(f0.suggestion)}` : ''}
          </div>
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
        const pillCls = isRed ? 'hp-pill-danger' : (f1.severity === 'yellow' ? 'hp-pill-warning' : 'hp-pill-neutral');
        const pillText = isRed ? 'Qonunga zid' : (f1.severity === 'yellow' ? 'Qaltis band' : 'Maslahat');

        clause2El.hidden = false;
        clause2El.className = `hp-clause-alert ${isRed ? 'hp-clause-illegal' : 'hp-clause-risky'}`;
        clause2El.innerHTML = `
          <div class="hp-clause-main-row">
            <span class="hp-pill-badge ${pillCls}">${esc(pillText)}</span>
            <p class="hp-clause-text" id="dash-clause-2-text">
              ${esc(f1.explanation)}
              ${f1.law_ref ? `<br/><small class="hp-text-muted">${esc(f1.law_ref)}</small>` : ''}
            </p>
          </div>
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
        state.bhmBaseValue = Number(res.amount) || 375000;
      }
    } catch (e) {
      // Fallback if not logged in yet
    }
    updateBhmCalculator();
  }

  function updateBhmCalculator() {
    const countInput = document.getElementById('bhm-count-input');
    const outputEl = document.getElementById('bhm-calculated-output');
    if (!countInput || !outputEl) return;

    const count = Math.max(1, parseFloat(countInput.value) || 1);
    const total = state.bhmBaseValue * count;
    outputEl.textContent = `${formatNumberUz(total, 0)} so'm`;
  }

  // ==================== §6 BUILDER (#view-builder) ====================
  function resolveTypeCode(code) {
    if (!code) return null;
    return LEGACY_TYPE_MAP[code] || code;
  }

  function draftStorageKey(code) {
    return `lexlab.draft.${LexLab.activeSlot()}.${code}`;
  }

  async function initBuilder(preselectCode) {
    const selectEl = document.getElementById('cb-type');
    if (!selectEl) return;

    const types = await LexLab.types.list();
    state.contractTypes = types || [];

    selectEl.innerHTML = state.contractTypes.map(t => {
      const srcKind = t.source && t.source.kind;
      const suffix = srcKind === 'lexuz'
        ? ' (lex.uz rasmiy shakl)'
        : (srcKind === 'organization' ? ' (tashkilot shabloni)' : '');
      return `<option value="${esc(t.code)}">${esc(t.title_uz + suffix)}</option>`;
    }).join('');

    const targetCode = resolveTypeCode(preselectCode) || (state.contractTypes[0] && state.contractTypes[0].code);
    if (targetCode) {
      selectEl.value = targetCode;
      await selectBuilderType(targetCode);
    }
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

    // Remember one draft per type in sessionStorage
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

    renderQuestionnaireForm(t, state.builderAnswers);

    const validation = await LexLab.contracts.validate(state.builderContractId);
    renderBuilderValidation(validation);
    await refreshBuilderPreview();
  }

  function renderQuestionnaireForm(typeDetail, existingAnswers) {
    const form = document.getElementById('contract-builder-form');
    if (!form) return;

    let dynContainer = document.getElementById('cb-dynamic-questionnaire');
    if (!dynContainer) {
      // Remove old fixed demo inputs (#cb-party-a, #cb-party-b, #cb-amount, #cb-penalty) while keeping #cb-type, #cb-rule-alerts-list, .hp-builder-actions
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

    state.builderFieldMap = {};
    const sections = (typeDetail.questionnaire && typeDetail.questionnaire.sections) || [];
    const allFields = [];
    sections.forEach(s => (s.fields || []).forEach(f => allFields.push(f)));
    const hasPartyBStir = allFields.some(f => f.key === 'party_b.stir');

    let html = '';
    const defaultPatch = {};

    sections.forEach(sec => {
      const fields = sec.fields || [];
      if (fields.length === 0) return;

      html += `<div style="font-size:13px;font-weight:700;color:var(--text-secondary);margin-top:6px;">${esc(sec.title || '')}</div>`;

      let i = 0;
      while (i < fields.length) {
        const f1 = fields[i];
        const f2 = fields[i + 1];
        if (f1.type === 'text' || !f2 || f2.type === 'text') {
          html += renderQuestionnaireFieldHtml(f1, existingAnswers, hasPartyBStir, defaultPatch);
          i += 1;
        } else {
          html += `<div class="hp-form-row-2">
            ${renderQuestionnaireFieldHtml(f1, existingAnswers, hasPartyBStir, defaultPatch)}
            ${renderQuestionnaireFieldHtml(f2, existingAnswers, hasPartyBStir, defaultPatch)}
          </div>`;
          i += 2;
        }
      }
    });

    dynContainer.innerHTML = html;

    // If defaults were populated for empty fields, save them
    if (Object.keys(defaultPatch).length > 0 && state.builderContractId) {
      LexLab.contracts.saveAnswers(state.builderContractId, defaultPatch)
        .then(r => {
          renderBuilderValidation(r);
          return refreshBuilderPreview();
        })
        .catch(() => {});
    }
  }

  function renderQuestionnaireFieldHtml(field, existingAnswers, hasPartyBStir, defaultPatch) {
    const fType = field.type || 'string';
    const actualKey = fType === 'party' ? `${field.key}.name` : field.key;
    state.builderFieldMap[actualKey] = field.label || actualKey;
    state.builderFieldMap[field.key] = field.label || field.key;

    let currentVal = getPath(existingAnswers, actualKey);
    if ((currentVal === undefined || currentVal === null || currentVal === '') && field.default !== undefined) {
      currentVal = field.default;
      defaultPatch[actualKey] = field.default;
    }
    const valStr = currentVal !== undefined && currentVal !== null ? String(currentVal) : '';
    const reqStar = field.required ? ' *' : '';
    const placeholder = field.hint || '';

    let inputHtml = '';
    if (fType === 'text') {
      inputHtml = `<textarea class="hp-input" rows="2" data-q-key="${esc(actualKey)}" data-q-type="text" placeholder="${esc(placeholder)}">${esc(valStr)}</textarea>`;
    } else if (fType === 'enum') {
      const opts = (field.options || []).map(o => {
        const oVal = typeof o === 'object' ? o.value : o;
        const oLabel = typeof o === 'object' ? o.label : o;
        const sel = String(oVal) === valStr ? 'selected' : '';
        return `<option value="${esc(oVal)}" ${sel}>${esc(oLabel)}</option>`;
      }).join('');
      inputHtml = `
        <select class="hp-input" data-q-key="${esc(actualKey)}" data-q-type="enum">
          <option value="">— Tanlang —</option>
          ${opts}
        </select>
      `;
    } else if (fType === 'number') {
      const minAttr = field.min !== undefined ? `min="${esc(field.min)}"` : '';
      const maxAttr = field.max !== undefined ? `max="${esc(field.max)}"` : '';
      inputHtml = `<input type="number" class="hp-input" data-q-key="${esc(actualKey)}" data-q-type="number" value="${esc(valStr)}" ${minAttr} ${maxAttr} step="any" placeholder="${esc(placeholder)}" />`;
    } else if (fType === 'date') {
      inputHtml = `<input type="date" class="hp-input" data-q-key="${esc(actualKey)}" data-q-type="date" value="${esc(valStr)}" />`;
    } else {
      inputHtml = `<input type="text" class="hp-input" data-q-key="${esc(actualKey)}" data-q-type="string" value="${esc(valStr)}" placeholder="${esc(placeholder)}" />`;
    }

    const isStirLookupField =
      actualKey === 'party_b.stir' || (!hasPartyBStir && actualKey === 'party_b.tin');

    if (isStirLookupField) {
      inputHtml = `
        <div class="hp-input-with-btn">
          ${inputHtml}
          <button type="button" class="hp-mini-lookup-btn" id="btn-stir-lookup-b">STIR orqali topish</button>
        </div>
      `;
    }

    return `
      <div class="hp-form-group">
        <label>${esc(field.label || actualKey)}${reqStar}</label>
        ${inputHtml}
        <span class="hp-field-hint" data-field-err="${esc(actualKey)}" style="color:#DC2626;" hidden></span>
      </div>
    `;
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
    renderBuilderValidation(r);
    await refreshBuilderPreview();
    return r;
  }

  function renderBuilderValidation(r) {
    if (!r) return;

    // 1. Clear field error highlights
    document.querySelectorAll('#cb-dynamic-questionnaire [data-q-key]').forEach(inp => {
      inp.style.borderColor = '';
    });
    document.querySelectorAll('#cb-dynamic-questionnaire [data-field-err]').forEach(errEl => {
      errEl.hidden = true;
      errEl.textContent = '';
    });

    // 2. Highlight field_errors
    (r.field_errors || []).forEach(fe => {
      const inp = document.querySelector(`#cb-dynamic-questionnaire [data-q-key="${CSS.escape(fe.field)}"]`);
      const errEl = document.querySelector(`#cb-dynamic-questionnaire [data-field-err="${CSS.escape(fe.field)}"]`);
      if (inp) inp.style.borderColor = '#DC2626';
      if (errEl) {
        errEl.textContent = fe.error || 'Format noto\'g\'ri';
        errEl.hidden = false;
      }
    });

    // 3. Render alerts in #cb-rule-alerts-list
    const alertsContainer = document.getElementById('cb-rule-alerts-list');
    if (!alertsContainer) return;

    const itemsHtml = [];
    const counts = (r.summary && r.summary.counts) || {};
    const isBlocking = !!(r.summary && r.summary.blocking);

    // Overall badge
    if (isBlocking) {
      itemsHtml.push(`
        <div class="hp-rule-item hp-rule-red">
          <strong>Holat: <span class="hp-pill-badge hp-pill-danger">Qonunga zid (${counts.red || 1})</span></strong>
          <span>Qizil bandlarni tuzating yoki avtomatik moslashtiring.</span>
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

    // Form requirement warning
    if (r.form && r.form.warning) {
      itemsHtml.push(`
        <div class="hp-rule-item hp-rule-amber">
          <strong>Shakl talabi</strong>
          <span>${esc(r.form.warning)}</span>
        </div>
      `);
    }

    // Findings
    (r.findings || []).forEach(f => {
      const cls = f.severity === 'red' ? 'hp-rule-red' : (f.severity === 'yellow' ? 'hp-rule-amber' : 'hp-rule-blue');
      itemsHtml.push(`
        <div class="hp-rule-item ${cls}">
          <strong>${esc(f.message)}</strong>
          ${f.law_ref ? `<span>Asos: ${esc(f.law_ref)}</span>` : ''}
          ${f.fix_suggestion ? `<span>Tavsiya: ${esc(f.fix_suggestion)}</span>` : ''}
        </div>
      `);
    });

    // Missing fields
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
        ${p.preamble ? `<p style="margin-bottom:10px;">${esc(p.preamble)}</p>` : ''}
        ${sectionsHtml}
        ${p.closing ? `<p style="margin-top:12px;font-style:italic;">${esc(p.closing)}</p>` : ''}
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
            if (inp) {
              inp.value = mapping[k];
              patch[k] = mapping[k];
            }
          }
        });
        if (Object.keys(patch).length > 0 && state.builderContractId) {
          const r = await LexLab.contracts.saveAnswers(state.builderContractId, patch);
          renderBuilderValidation(r);
          await refreshBuilderPreview();
        }
        showToast('Tashkilot ma\'lumotlari to\'ldirildi');
      } else {
        showToast((res && res.message) || 'STIR topilmadi');
      }
    });
  }

  async function handleBuilderAutofix(btn) {
    if (!state.builderContractId) return;
    await withBusy(btn, async () => {
      await flushBuilderAnswers();
      const r = await LexLab.contracts.autofix(state.builderContractId);
      const applied = r.applied || [];
      if (applied.length === 0) {
        showToast('Avtomatik tuzatiladigan band yo\'q');
        return;
      }
      applied.forEach(item => {
        const inp = document.querySelector(`#cb-dynamic-questionnaire [data-q-key="${CSS.escape(item.field)}"]`);
        if (inp) inp.value = item.value ?? '';
      });
      renderBuilderValidation(r);
      await refreshBuilderPreview();
      showToast('Qonunga mos ravishda avtomatik tuzatildi');
    });
  }

  async function handleBuilderGenerate(btn, acknowledgeRed = false) {
    if (!state.builderContractId) return;
    await withBusy(btn, async () => {
      await flushBuilderAnswers();
      try {
        const g = await LexLab.contracts.generate(state.builderContractId, {
          language: state.docPreviewLang,
          acknowledgeRed: !!acknowledgeRed
        });
        const generatedContractId = state.builderContractId;
        if (state.builderTypeCode) {
          sessionStorage.removeItem(draftStorageKey(state.builderTypeCode));
        }

        await loadDashboard();
        openGeneratedVersionModal(generatedContractId, g.version);
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
          handleErr(e);
          return;
        }
        if (e && e.code === 'illegal_clauses') {
          const redList = Array.isArray(e.details) ? e.details : [];
          openModal(
            'Diqqat: Qonunga zid bandlar mavjud',
            `
            <div class="hp-builder-form">
              <div class="hp-rule-alerts">
                ${redList.map(item => `
                  <div class="hp-rule-item hp-rule-red">
                    <strong>${esc(item.message)}</strong>
                    ${item.law_ref ? `<span>${esc(item.law_ref)}</span>` : ''}
                  </div>
                `).join('')}
              </div>
              <div class="hp-builder-actions">
                <button type="button" class="hp-btn-navy" id="btn-acknowledge-red-generate">Tushundim, baribir yaratish</button>
              </div>
            </div>
            `
          );
          document.getElementById('btn-acknowledge-red-generate')?.addEventListener('click', (ev) => {
            handleBuilderGenerate(ev.currentTarget, true).catch(() => {});
          });
          return;
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
      `
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

  // ==================== §7 CONTRACTS & CONTRACT MODAL & INVITATIONS ====================
  async function loadFullContracts(filter = 'all') {
    state.contractFilter = filter;
    const tab = filter === 'all' ? undefined : filter;
    const list = await LexLab.contracts.list(tab);
    renderFullContractsTable(list || []);
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

  async function openContractModal(contractId) {
    try {
      const [c, vs] = await Promise.all([
        LexLab.contracts.get(contractId),
        LexLab.contracts.versions(contractId)
      ]);
      const latest = (vs && vs[0]) || null;
      const myId = state.me && state.me.id;
      const isOwner = c.owner_id === myId;
      const myParty = (c.parties || []).find(p => p.user_id === myId);
      const canInvite = isOwner && (c.status === 'draft' || c.status === 'pending_approval');
      const canApprove = c.status === 'pending_approval' && myParty && !myParty.confirmed_at && latest;
      const canSetActiveStatus = c.status === 'active';
      const devOtp = (state.meta && state.meta.dev_otp_code) || '111111';

      const partiesHtml = (c.parties || []).map(p => {
        const pName = p.display_name || (c.party_names && c.party_names[p.role]) || `${p.role} tomon`;
        const joinedBadge = p.confirmed_at
          ? '<span class="hp-pill-badge hp-pill-success">Tasdiqlagan</span>'
          : (p.joined_at
            ? '<span class="hp-pill-badge hp-pill-warning">Qo\'shilgan (Imzo kutilmoqda)</span>'
            : (p.invited_at
              ? '<span class="hp-pill-badge hp-pill-neutral">Taklif yuborilgan</span>'
              : '<span class="hp-pill-badge hp-pill-neutral">Taklif qilinmagan</span>'));
        return `
          <div class="hp-ob-row-card" style="padding:10px 14px;">
            <div>
              <strong>${esc(p.role)}-Tomon: ${esc(pName)}</strong>
            </div>
            ${joinedBadge}
          </div>
        `;
      }).join('');

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
            ${latest ? `<button type="button" class="hp-btn-navy-sm" id="btn-cm-download">DOCX yuklab olish</button>` : ''}
            ${canSetActiveStatus ? `
              <button type="button" class="hp-btn-outline-sm" id="btn-cm-complete">Yakunlandi</button>
              <button type="button" class="hp-btn-outline-sm" id="btn-cm-dispute">Nizo</button>
            ` : ''}
            <button type="button" class="hp-btn-outline-sm" id="btn-cm-ai-review">AI tekshiruv</button>
          </div>

          ${canInvite ? `
            <div class="hp-card" style="padding:12px;">
              <div class="hp-form-group">
                <label for="cm-invite-phone">Taklif qilish (2-Tomon telefoni)</label>
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
        </div>
        `
      );

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
    } catch (e) {
      handleErr(e);
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
            showToast('Shartnoma kuchga kirdi');
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
          renderContractAiReview(aiCont, rev);
        }).catch(() => {
          aiCont.innerHTML = '';
        });
      });
    }

    const aiAskBtn = document.getElementById(cfg.aiAskBtnId);
    if (aiAskBtn && aiCont) {
      aiAskBtn.addEventListener('click', () => {
        const q = (document.getElementById(cfg.aiAskInputId)?.value || '').trim();
        if (!q) return;
        aiCont.innerHTML = `<div class="hp-rule-item hp-rule-blue"><strong>AI javob tayyorlamoqda…</strong></div>`;
        withBusy(aiAskBtn, async () => {
          const ans = await LexLab.contracts.aiAsk(cfg.contractId, q);
          aiCont.innerHTML = `
            <div class="hp-rule-item hp-rule-blue">
              <strong><span class="hp-sug-tag">AI</span> Javob:</strong>
              <span>${esc(ans.answer || ans.summary || JSON.stringify(ans))}</span>
            </div>
          `;
        }).catch(() => {
          aiCont.innerHTML = '';
        });
      });
    }
  }

  function renderContractAiReview(container, rev) {
    if (!container || !rev) return;
    const issues = (rev.issues || []).map(iss => `
      <div class="hp-rule-item hp-rule-amber">
        <strong><span class="hp-sug-tag">AI</span> ${esc(iss.title || 'Tavsiya')}</strong>
        <span>${esc(iss.explanation || '')}</span>
        ${iss.suggestion ? `<span>Taklif: ${esc(iss.suggestion)}</span>` : ''}
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

  // §7.4 Invitations Modal
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
          <div id="inv-preview-box-${esc(inv.party_id)}" style="margin-top:10px;" hidden></div>
        </div>
      `).join('');

      openModal('Menga kelgan shartnoma takliflari', `<div>${listHtml}</div>`);
    } catch (e) {
      handleErr(e);
    }
  }

  // ==================== §8 SCANNER (#view-scanner) ====================
  async function runScannerUpload(file) {
    if (!file) return;
    showToast(`"${file.name}" yuklanmoqda va tahlil qilinmoqda...`);
    try {
      const s = await LexLab.scans.upload(file);
      await processScanJob(s.id, file.name);
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
    const dutiesList = r.your_obligations || [];

    if (titleEl) titleEl.textContent = docTitle || 'Tahlil hisoboti';
    if (badgeEl) {
      const riskLvl = r.overall.risk_level;
      badgeEl.className = `hp-pill-badge ${riskLvl === 'high' ? 'hp-pill-danger' : (riskLvl === 'medium' ? 'hp-pill-warning' : 'hp-pill-success')}`;
      badgeEl.textContent = `${r.overall.risk_label || 'Xavf'} (${r.overall.risk_percent ?? 0}/100)`;
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
        </li>
      `;
    }

    if (cardsEl) {
      const allFindings = []
        .concat(redList.map(f => Object.assign({}, f, { _cardType: 'red' })))
        .concat(riskyList.map(f => Object.assign({}, f, { _cardType: 'yellow' })))
        .concat(missingList.map(f => Object.assign({}, f, { _cardType: 'blue' })));

      const aiStatus = r.ai && r.ai.status;
      let aiBlockHtml = '';
      if (aiStatus === 'pending') {
        aiBlockHtml = `
          <div class="hp-rule-item hp-rule-blue">
            <strong><span class="hp-sug-tag">AI</span> AI tahlil qilmoqda…</strong>
          </div>
        `;
      } else if (aiStatus === 'done') {
        const devHtml = (r.ai.template_deviations || []).map(d => `
          <div style="margin-top:6px;font-size:12.5px;">
            <strong>${esc(d.status || 'Farq')}:</strong> ${esc(d.comment || d.template_clause || '')}
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
        const isBlue = f._cardType === 'blue';
        const cardCls = isRed ? 'hp-clause-illegal' : 'hp-clause-risky';
        const pillCls = isRed ? 'hp-pill-danger' : (isBlue ? 'hp-pill-neutral' : 'hp-pill-warning');
        const pillLabel = isRed ? 'Qonunga zid' : (isBlue ? 'Yetishmaydi' : 'Qaltis band');
        const sourceTag = f.source === 'ai'
          ? ' <span class="hp-sug-tag">AI</span>'
          : (f.source === 'template' ? ' <span class="hp-sug-tag">Shablon</span>' : '');
        const explanation = f.ai_explanation || f.explanation || '';
        const decision = f.user_decision;

        return `
          <div class="hp-clause-alert ${cardCls}">
            <div class="hp-clause-main-row" style="margin-bottom:6px;">
              <span class="hp-pill-badge ${pillCls}">${esc(pillLabel)}</span>${sourceTag}
              <strong style="font-size:13.8px;">${esc(explanation)}</strong>
            </div>
            ${f.law_ref ? `<div class="hp-text-muted" style="font-size:12px;margin-bottom:4px;">Huquqiy asos: ${esc(f.law_ref)}</div>` : ''}
            ${f.clause_text ? `<div style="font-size:12.5px;color:var(--text-secondary);margin-bottom:8px;">"${esc(f.clause_text)}"</div>` : ''}
            <div class="hp-clause-actions-row">
              <span class="hp-decision-feedback">
                ${decision === 'agree' ? 'Rozilik bildirildi' : (decision === 'object' ? 'E\'tiroz bildirildi' : '')}
              </span>
              <div class="hp-clause-btns">
                <button type="button" class="hp-btn-navy-sm" data-scan-decision="agree" data-finding-id="${esc(f.id)}">Roziman</button>
                <button type="button" class="hp-btn-outline-sm" data-scan-decision="object" data-finding-id="${esc(f.id)}">E'tiroz</button>
              </div>
            </div>
            ${decision === 'object' && f.suggestion ? `
              <div class="hp-clause-detail-collapse">
                <strong>Muqobil band:</strong> ${esc(f.suggestion)}
              </div>
            ` : ''}
          </div>
        `;
      }).join('');

      cardsEl.innerHTML = aiBlockHtml + (cardsHtml || `<div class="hp-rule-item hp-rule-blue"><strong>Xavfli bandlar topilmadi</strong></div>`);
    }
  }

  // ==================== §9 REMINDERS, ARCHIVE, NOTIFICATIONS, SEARCH ====================
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
      const btnText = ob.status === 'done' ? 'Qaytarish' : 'Bajarildi';

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

  async function loadArchiveView() {
    const timelineEl = document.getElementById('lawyer-case-timeline');
    const form = document.getElementById('case-step-form');
    if (!timelineEl) return;

    const isLawyer = state.me && state.me.role === 'lawyer';
    setArchiveFormLawyerMode(form, isLawyer);

    const cases = await LexLab.cases.list();
    state.casesList = cases || [];

    if (state.casesList.length === 0) {
      state.currentCaseId = null;
      timelineEl.innerHTML = `<p class="hp-text-muted">Hozircha arxivda ishlar yo'q.</p>`;
      return;
    }

    state.currentCaseId = state.casesList[0].id;
    const detail = await LexLab.cases.get(state.currentCaseId);
    const steps = detail.steps || [];

    if (steps.length === 0) {
      timelineEl.innerHTML = `<p class="hp-text-muted">Hozircha qadamlar qo'shilmagan.</p>`;
      return;
    }

    timelineEl.innerHTML = steps.map(step => {
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
    }).join('');
  }

  function setArchiveFormLawyerMode(form, isAllowed) {
    if (!form) return;
    let notice = document.getElementById('lawyer-only-notice');
    if (!isAllowed) {
      if (!notice) {
        notice = document.createElement('div');
        notice.id = 'lawyer-only-notice';
        notice.className = 'hp-rule-item hp-rule-amber';
        notice.innerHTML = `<strong>Ish yuritish faqat tasdiqlangan yuristlar uchun</strong><span>Demo yurist raqami: +998900000004</span>`;
        form.prepend(notice);
      }
      form.querySelectorAll('input, select, textarea, button').forEach(el => { el.disabled = true; });
    } else {
      if (notice) notice.remove();
      form.querySelectorAll('input, select, textarea, button').forEach(el => { el.disabled = false; });
    }
  }

  async function openNotificationsModal() {
    try {
      const res = await LexLab.notifications.list();
      const items = (res && res.items) || [];

      if (items.length === 0) {
        openModal('Bildirishnomalar', `<p class="hp-text-muted">Yangi bildirishnomalar yo'q.</p>`);
      } else {
        const html = items.map(n => `
          <div class="hp-case-step-card" style="margin-bottom:8px;">
            <div>
              <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
                <strong>${esc(n.title)}</strong>
                <span class="hp-text-muted" style="font-size:12px;">${esc(formatDateDdMmYyyy(n.created_at))}</span>
              </div>
              <p style="font-size:13px;color:var(--text-secondary);margin-top:3px;">${esc(n.body)}</p>
            </div>
          </div>
        `).join('');
        openModal('Bildirishnomalar', `<div>${html}</div>`);
      }

      await LexLab.notifications.markRead();
      const notifDot = document.querySelector('#btn-notif-panel .hp-notif-dot');
      if (notifDot) notifDot.style.display = 'none';
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
    if (!LexLab.auth.isLoggedIn(LexLab.activeSlot())) {
      showLoginModal();
      return;
    }
    try {
      await loadMe();
      await Promise.all([
        loadDashboard(),
        loadBhmRate(),
        initBuilder(state.builderTypeCode)
      ]);
      if (state.currentView === 'contracts') await loadFullContracts(state.contractFilter);
      if (state.currentView === 'reminders') await loadObligationsView();
      if (state.currentView === 'archive') await loadArchiveView();
    } catch (e) {
      handleErr(e);
    }
  }

  // ==================== EVENT LISTENERS ====================
  function initEventListeners() {
    document.addEventListener('click', async (e) => {
      // Navigation
      const navBtn = e.target.closest('[data-nav]');
      if (navBtn) {
        navigateTo(navBtn.getAttribute('data-nav'));
        return;
      }

      const gotoBtn = e.target.closest('[data-goto]');
      if (gotoBtn) {
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
        if (!LexLab.auth.isLoggedIn(slot)) {
          showLoginModal();
        } else {
          await reloadAllWidgets();
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

      // Invitation preview / accept / decline (§7.4)
      const invPrevBtn = e.target.closest('[data-inv-preview]');
      if (invPrevBtn) {
        const pid = invPrevBtn.getAttribute('data-inv-preview');
        const box = document.getElementById(`inv-preview-box-${pid}`);
        if (box) {
          await withBusy(invPrevBtn, async () => {
            const p = await LexLab.contracts.invitationPreview(pid);
            box.hidden = false;
            box.className = 'hp-doc-paper';
            box.innerHTML = renderPreviewDocumentHtml(p);
          }).catch(() => {});
        }
        return;
      }

      const invAccBtn = e.target.closest('[data-inv-accept]');
      if (invAccBtn) {
        const pid = invAccBtn.getAttribute('data-inv-accept');
        await withBusy(invAccBtn, async () => {
          const c = await LexLab.contracts.acceptInvitation(pid);
          showToast('Taklif qabul qilindi');
          await loadDashboard();
          await openContractModal(c.id);
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
            if (action === 'object' && res && res.alternative) {
              detailEl.innerHTML = `<strong>Taklif:</strong> ${esc(res.alternative)}`;
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

      // Obligations toggle & confirm (§9)
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
      handleBuilderGenerate(e.currentTarget, false).catch(() => {});
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

    // Lawyer archive form & export ZIP (§9)
    const caseForm = document.getElementById('case-step-form');
    if (caseForm) {
      caseForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const submitBtn = caseForm.querySelector('button[type="submit"]');
        const titleEl = document.getElementById('cs-title');
        const typeEl = document.getElementById('cs-type');
        const descEl = document.getElementById('cs-desc');
        if (!titleEl || !descEl) return;

        withBusy(submitBtn, async () => {
          try {
            let caseId = state.currentCaseId;
            if (!caseId) {
              const created = await LexLab.cases.create({ title: 'Asosiy ish' });
              caseId = created.id;
              state.currentCaseId = caseId;
            }
            await LexLab.cases.addStep(caseId, {
              title: titleEl.value.trim(),
              description: descEl.value.trim(),
              tags: [typeEl ? typeEl.value : 'Hujjat']
            });
            titleEl.value = '';
            descEl.value = '';
            showToast('Qadam arxivga qo\'shildi');
            await loadArchiveView();
          } catch (err) {
            if (err && err.code === 'lawyer_only') {
              setArchiveFormLawyerMode(caseForm, false);
            }
            throw err;
          }
        }).catch(() => {});
      });
    }

    const exportZipBtn = document.getElementById('btn-export-case-zip');
    if (exportZipBtn) {
      exportZipBtn.addEventListener('click', () => {
        if (!state.currentCaseId) {
          showToast('Eksport qilish uchun arxivda ish mavjud emas');
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
      showLoginModal();
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

    initEventListeners();
    syncSlotButtons();

    LexLab.on('logout', () => {
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
