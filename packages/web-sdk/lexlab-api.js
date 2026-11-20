/**
 * LexLab Web SDK — the only way the web app talks to the LexLab API.
 * Served by the backend at /sdk/lexlab-api.js (same version as the API).
 *
 *   <script src="/sdk/lexlab-api.js"></script>
 *   await LexLab.auth.requestOtp('+998901234567');
 *   await LexLab.auth.verify('+998901234567', '111111', { consent: true });
 *   const d = await LexLab.dashboard();
 *
 * Sessions are kept per *slot* so one browser can act as both sides of a contract in a demo:
 *   LexLab.useSlot('party_b')  -> following calls use party B's tokens (log in once per slot).
 * Errors are thrown as LexLab.Error {status, code, message, details}; LexLab.humanError(e) gives Uzbek text.
 * No dependencies, ES2018, works in every modern browser.
 */
(function (global) {
  'use strict';

  const STORE = 'lexlab.sessions.v1';
  const ACTIVE = 'lexlab.activeSlot.v1';
  const cfg = { baseUrl: '', apiPrefix: '/api/v1' };

  class LexLabError extends Error {
    constructor(status, code, message, details) {
      super(message || code);
      this.name = 'LexLabError';
      this.status = status;
      this.code = code;
      this.details = details;
    }
  }

  // ---------- sessions (per slot) ----------
  function readStore() {
    try { return JSON.parse(localStorage.getItem(STORE) || '{}'); } catch (e) { return {}; }
  }
  function writeStore(s) { localStorage.setItem(STORE, JSON.stringify(s)); }
  function activeSlot() { return localStorage.getItem(ACTIVE) || 'party_a'; }
  function getSession(slot) { return readStore()[slot || activeSlot()] || null; }
  function setSession(slot, pair, phone) {
    const s = readStore();
    s[slot] = { access: pair.access_token, refresh: pair.refresh_token, phone: phone || (s[slot] || {}).phone || null };
    writeStore(s);
  }
  function clearSession(slot) {
    const s = readStore();
    delete s[slot];
    writeStore(s);
  }

  const listeners = {};
  function on(event, fn) { (listeners[event] = listeners[event] || []).push(fn); }
  function emit(event, data) { (listeners[event] || []).forEach((fn) => { try { fn(data); } catch (e) { /* ignore */ } }); }

  // ---------- HTTP ----------
  function url(path, query) {
    const u = new URL(cfg.baseUrl + cfg.apiPrefix + path, global.location.origin);
    if (query) {
      Object.keys(query).forEach((k) => {
        const v = query[k];
        if (v !== undefined && v !== null && v !== '') u.searchParams.set(k, v);
      });
    }
    return u.toString();
  }

  const refreshing = {};
  function refresh(slot) {
    const sess = getSession(slot);
    if (!sess || !sess.refresh) return Promise.reject(new LexLabError(401, 'unauthorized', 'Not logged in'));
    if (!refreshing[slot]) {
      refreshing[slot] = fetch(url('/auth/refresh'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: sess.refresh }),
      })
        .then(async (res) => {
          if (!res.ok) {
            clearSession(slot);
            emit('logout', { slot, reason: 'expired' });
            throw new LexLabError(401, 'token_expired', 'Session expired');
          }
          setSession(slot, await res.json());
        })
        .finally(() => { delete refreshing[slot]; });
    }
    return refreshing[slot];
  }

  async function request(method, path, opts) {
    opts = opts || {};
    const slot = opts.slot || activeSlot();
    const headers = {};
    let body;
    if (opts.form) {
      body = opts.form;
    } else if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(opts.body);
    }
    const sess = getSession(slot);
    if (opts.auth !== false && sess && sess.access) headers.Authorization = 'Bearer ' + sess.access;

    let res;
    try {
      res = await fetch(url(path, opts.query), { method, headers, body });
    } catch (e) {
      throw new LexLabError(0, 'network', 'Server bilan aloqa yo\'q');
    }
    if (res.status === 401 && opts.auth !== false && !opts._retried && sess && sess.refresh) {
      await refresh(slot);
      return request(method, path, Object.assign({}, opts, { _retried: true, slot }));
    }
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch (e) { /* not JSON */ }
      const err = (data && data.error) || {};
      const e = new LexLabError(res.status, err.code || 'http_' + res.status, err.message || res.statusText, err.details);
      if (res.status === 401) emit('unauthorized', { slot, error: e });
      throw e;
    }
    if (opts.raw) return res;
    if (res.status === 204) return null;
    const ct = res.headers.get('Content-Type') || '';
    return ct.includes('application/json') ? res.json() : res;
  }

  async function download(path, fallbackName, query) {
    const res = await request('GET', path, { raw: true, query });
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^";]+)"?/);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (m && m[1]) || fallbackName;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
    return { filename: a.download, size: blob.size, sha256: res.headers.get('X-Content-SHA256') };
  }

  const get = (p, q) => request('GET', p, { query: q });
  const post = (p, b, q) => request('POST', p, { body: b, query: q });
  const patch = (p, b) => request('PATCH', p, { body: b });
  const put = (p, b) => request('PUT', p, { body: b });
  const del = (p) => request('DELETE', p);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---------- human-readable errors (Uzbek) ----------
  const MESSAGES = {
    network: 'Server bilan aloqa yo\'q. Backend ishga tushganini tekshiring',
    unauthorized: 'Avval tizimga kiring',
    token_expired: 'Sessiya muddati tugadi — qaytadan kiring',
    refresh_reused: 'Xavfsizlik: sessiya bekor qilindi. Qaytadan kiring',
    phone_invalid: 'Telefon raqam noto\'g\'ri. Format: +998 XX XXX XX XX',
    otp_cooldown: 'Yangi kod so\'rashdan oldin biroz kuting',
    otp_hourly_limit: 'Bu raqamga juda ko\'p kod so\'raldi. Keyinroq urinib ko\'ring',
    otp_invalid: 'SMS-kod noto\'g\'ri',
    otp_expired: 'Kod muddati o\'tgan. Yangisini so\'rang',
    otp_locked: 'Urinishlar tugadi. Yangi kod so\'rang',
    consent_required: 'Ro\'yxatdan o\'tish uchun shaxsiy ma\'lumotlarni qayta ishlashga rozilik kerak',
    totp_invalid: 'Authenticator kodi noto\'g\'ri',
    rate_limited: 'Juda ko\'p so\'rov. Biroz kuting',
    permission_denied: 'Bu amal uchun huquqingiz yo\'q',
    not_found: 'Topilmadi',
    validation_failed: 'Kiritilgan ma\'lumot noto\'g\'ri',
    contract_locked: 'Shartnoma tasdiqlash bosqichida yoki faol — tahrirlab bo\'lmaydi',
    answers_incomplete: 'Savolnomaning majburiy maydonlarini to\'ldiring yoki formatini tuzating',
    illegal_clauses: 'Shartnomada qonunga zid bandlar bor — avval tuzating yoki ogohlantirishni tasdiqlang',
    language_unavailable: 'Bu tildagi shablon hali tayyor emas',
    version_mismatch: 'Hujjat siz ochganingizdan keyin o\'zgargan. Qaytadan oching',
    already_approved: 'Siz bu versiyani allaqachon tasdiqlagansiz',
    not_signing_party: 'Faqat A yoki B tomon tasdiqlay oladi',
    not_pending: 'Shartnoma tasdiqlash bosqichida emas',
    invite_invalid: 'Taklif topilmadi yoki ishlatilgan',
    invite_expired: 'Taklif muddati tugagan',
    invite_phone_mismatch: 'Bu taklif boshqa telefon raqamga yuborilgan',
    party_taken: 'Bu tomon allaqachon qo\'shilgan',
    already_party: 'Siz bu shartnomada allaqachon tomonsiz',
    file_type: 'Fayl turi qo\'llab-quvvatlanmaydi (PDF, DOCX, TXT, JPG, PNG)',
    file_too_large: 'Fayl hajmi juda katta',
    no_text: 'Hujjatdan matn o\'qib bo\'lmadi',
    ocr_unavailable: 'Rasmdan matn o\'qish (OCR) serverda o\'rnatilmagan — matnli PDF, DOCX yoki TXT yuklang',
    pdf_unavailable: 'PDF generatori o\'rnatilmagan — DOCX yuklab oling',
    scan_not_done: 'Tahlil hali tugamagan',
    lawyer_only: 'Bu bo\'lim faqat tasdiqlangan yuristlar uchun',
    ai_disabled: 'AI ulanmagan',
    ai_unavailable: 'AI xizmati vaqtincha ishlamayapti — qoidalar tekshiruvi natijasi ko\'rsatildi',
    ai_auth_failed: 'AI kaliti noto\'g\'ri',
    ai_quota: 'AI hisobida mablag\' tugagan',
    ai_rate_limited: 'AI so\'rovlar limiti oshdi, keyinroq urining',
    ai_bad_output: 'AI javobi yaroqsiz — qayta urinib ko\'ring',
    eimzo_unavailable: 'E-IMZO serveri ulanmagan',
    integration_unavailable: 'Tashqi xizmat hozircha ulanmagan',
    internal_error: 'Serverda kutilmagan xato',
  };
  function humanError(e) {
    if (!e) return 'Xato';
    if (e instanceof LexLabError) return MESSAGES[e.code] || e.message || 'Xato';
    return e.message || String(e);
  }

  // ---------- auth ----------
  const auth = {
    /** Step 1: send SMS code. Returns {expires_in, resend_in}. In dev the code is LexLab.meta().dev_otp_code. */
    requestOtp: (phone) => request('POST', '/auth/otp', { body: { phone }, auth: false }),
    /**
     * Step 2: verify the code. New users must pass consent:true (personal-data consent checkbox).
     * Returns {ok:true, isNewUser} or {mfa:true, mfaToken} (then call verify2fa).
     */
    async verify(phone, code, options) {
      const o = options || {};
      const slot = o.slot || activeSlot();
      const r = await request('POST', '/auth/otp/verify', {
        body: { phone, code: String(code).trim(), consent: !!o.consent }, auth: false,
      });
      if (r.mfa_required) return { mfa: true, mfaToken: r.mfa_token };
      setSession(slot, r, phone);
      emit('login', { slot, phone });
      return { ok: true, isNewUser: !!r.is_new_user };
    },
    async verify2fa(mfaToken, code, options) {
      const slot = (options && options.slot) || activeSlot();
      const r = await request('POST', '/auth/2fa/verify', { body: { mfa_token: mfaToken, code }, auth: false });
      setSession(slot, r);
      emit('login', { slot });
      return { ok: true };
    },
    async logout(options) {
      const slot = (options && options.slot) || activeSlot();
      try { await request('POST', '/auth/logout', { slot }); } catch (e) { /* already expired */ }
      clearSession(slot);
      emit('logout', { slot, reason: 'user' });
    },
    isLoggedIn: (slot) => !!getSession(slot),
    phoneOf: (slot) => (getSession(slot) || {}).phone || null,
  };

  // ---------- domain helpers ----------
  const contracts = {
    list: (tab, limit) => get('/contracts', { tab, limit: limit || 100 }),
    get: (id) => get(`/contracts/${id}`),
    /** myRole: 'A' | 'B' — which side the creator is on */
    create: (typeCode, myRole, title) => post('/contracts', { type_code: typeCode, my_role: myRole || 'A', title }),
    /**
     * Save answers (partial is fine: nested objects are merged, dotted keys like "party_a.stir" accepted).
     * Returns the live validation report {findings[], summary{counts,blocking}, missing_fields[], field_errors[],
     * form{requirement,warning}, ready}.
     */
    saveAnswers: (id, answers, selectedClauses) =>
      patch(`/contracts/${id}/answers`, Object.assign({ answers }, selectedClauses ? { selected_clauses: selectedClauses } : {})),
    validate: (id) => post(`/contracts/${id}/validate`),
    autofix: (id) => post(`/contracts/${id}/autofix`),
    /** Rendered text {title, header, preamble, sections[{title,text}], parties, content_sha256} */
    preview: (id, language) => get(`/contracts/${id}/preview`, { language: language || 'uz' }),
    generate: (id, opts) => post(`/contracts/${id}/generate`, {
      language: (opts && opts.language) || 'uz', acknowledge_red: !!(opts && opts.acknowledgeRed),
    }),
    versions: (id) => get(`/contracts/${id}/versions`),
    content: (id, n) => get(`/contracts/${id}/versions/${n}/content`),
    verify: (id, n) => get(`/contracts/${id}/versions/${n}/verify`),
    download: (id, n, format) => download(`/contracts/${id}/versions/${n}/download`, `shartnoma-v${n}.${format || 'docx'}`, { format: format || 'docx' }),
    invite: (id, phone, role, displayName) => post(`/contracts/${id}/invite`, { phone, role: role || 'B', display_name: displayName }),
    requestApprovalCode: (id) => post(`/contracts/${id}/approve/otp`),
    /** sha256 = the hash shown to the user (latest version). Returns {contract_status, pending_parties, ...} */
    approve: (id, code, sha256) => post(`/contracts/${id}/approve`, { method: 'otp', code: String(code).trim(), sha256 }),
    setStatus: (id, status, reason) => post(`/contracts/${id}/status`, { status, reason }),
    aiReview: (id) => post(`/contracts/${id}/ai/review`),
    aiAsk: (id, question) => post(`/contracts/${id}/ai/ask`, { question }),
    invitations: () => get('/contracts/invitations'),
    invitationPreview: (partyId) => get(`/contracts/invitations/${partyId}/preview`),
    acceptInvitation: (partyId) => post(`/contracts/invitations/${partyId}/accept`),
    declineInvitation: (partyId) => post(`/contracts/invitations/${partyId}/decline`),
    anchor: (id, n) => get(`/contracts/${id}/versions/${n}/anchor`),
  };

  const scans = {
    list: (limit) => get('/scans', { limit: limit || 20 }),
    fromText: (text, opts) => post('/scans/text', { text }, {
      contract_type_code: opts && opts.typeCode, side: opts && opts.side,
    }),
    upload(file, opts) {
      const form = new FormData();
      form.append('file', file);
      if (opts && opts.typeCode) form.append('contract_type_code', opts.typeCode);
      if (opts && opts.side) form.append('side', opts.side);
      return request('POST', '/scans', { form });
    },
    get: (id) => get(`/scans/${id}`),
    report: (id) => get(`/scans/${id}/report`),
    text: (id) => get(`/scans/${id}/text`),
    /** Fix OCR text and re-analyse */
    saveText: (id, text) => put(`/scans/${id}/text`, { text }),
    /** Wait until rules analysis is finished (uploads are processed in background). */
    async waitDone(id, timeoutMs) {
      const end = Date.now() + (timeoutMs || 60000);
      for (;;) {
        const s = await scans.get(id);
        if (['done', 'needs_review', 'failed'].includes(s.status)) return s;
        if (Date.now() > end) return s;
        await sleep(1000);
      }
    },
    /** Wait for the AI part of the report (status done | failed | null when AI is off). */
    async waitAi(id, timeoutMs) {
      const end = Date.now() + (timeoutMs || 90000);
      for (;;) {
        const r = await scans.report(id);
        const st = r.ai && r.ai.status;
        if (!st || st === 'done' || st === 'failed' || st === 'disabled' || Date.now() > end) return r;
        await sleep(2000);
      }
    },
    decide: (id, findingId, decision) => post(`/scans/${id}/findings/${findingId}/decision`, { decision }),
    toObligations: (id) => post(`/scans/${id}/obligations`),
    aiReview: (id) => post(`/scans/${id}/ai/review`),
    aiAsk: (id, question) => post(`/scans/${id}/ai/ask`, { question }),
    downloadReport: (id) => download(`/scans/${id}/report/download`, 'tahlil.docx'),
  };

  const obligations = {
    list: (params) => get('/obligations', Object.assign({ limit: 100 }, params || {})),
    dashboard: () => get('/obligations/dashboard'),
    create: (body) => post('/obligations', body),
    /** status: 'done' | 'pending' | 'cancelled' */
    setStatus: (id, status) => patch(`/obligations/${id}`, { status }),
    confirm: (id) => patch(`/obligations/${id}`, { confirmed: true }),
  };

  const cases = {
    list: (params) => get('/cases', Object.assign({ limit: 100 }, params || {})),
    create: (body) => post('/cases', body),
    get: (id) => get(`/cases/${id}`),
    addStep: (id, body) => post(`/cases/${id}/steps`, body),
    attach(id, stepId, file, note) {
      const form = new FormData();
      form.append('step_id', stepId);
      form.append('file', file);
      if (note) form.append('note', note);
      return request('POST', `/cases/${id}/attachments`, { form });
    },
    exportZip: (id) => download(`/cases/${id}/export`, 'dalillar.zip'),
  };

  const LexLab = {
    Error: LexLabError,
    configure(o) { Object.assign(cfg, o || {}); },
    useSlot(slot) { localStorage.setItem(ACTIVE, slot); emit('slot', { slot }); },
    activeSlot,
    on,
    humanError,
    request,
    download,
    auth,
    meta: () => request('GET', '/meta', { auth: false }),
    me: {
      get: () => get('/me'),
      /** {channels:['in_app','sms','telegram'], locale, email} */
      update: (body) => patch('/me', body),
      profile: (body) => put('/me/profile', body),
    },
    dashboard: () => get('/dashboard'),
    assistant: { situation: (text) => post('/assistant/situation', { text }) },
    lookup: { stir: (stir) => get(`/lookup/stir/${encodeURIComponent(String(stir).trim())}`) },
    types: {
      list: () => request('GET', '/contract-types', { auth: false }),
      get: (code) => request('GET', `/contract-types/${code}`, { auth: false }),
    },
    contracts,
    scans,
    obligations,
    cases,
    notifications: {
      list: (params) => get('/notifications', Object.assign({ limit: 30 }, params || {})),
      /** ids omitted => mark all as read */
      markRead: (ids) => post('/notifications/read', ids || null),
    },
    calc: { bhm: (onDate) => get('/calc/bhm', { on_date: onDate }) },
    version: '1.0.0',
  };

  global.LexLab = LexLab;
})(window);
