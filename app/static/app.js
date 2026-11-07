const API_BASE = '/api';
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

const state = {
  user: null,
  schemes: [],
  activeScheme: localStorage.getItem('ukk-active-scheme') || 'ALL',
  configScheme: localStorage.getItem('ukk-config-scheme') || 'JNT-SMK',
  schools: [],
  schoolData: null,
  assessment: null,
  scores: {},
  pendingKeys: new Set(),
  failedKeys: new Set(),
  openUnits: new Set(),
  outboxCount: 0,
  flushing: false,
  noteTimers: {},
  offline: !navigator.onLine,
  configUnits: [],
  instrument: null,
};

const memoryOutbox = new Map();

/* ------------------------------------------------------------------ */
/* Utilities                                                          */
/* ------------------------------------------------------------------ */
function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function fmtDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${String(date.getDate()).padStart(2, '0')} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

function fmtDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${fmtDate(value)} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function fmtPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(2)}%`;
}

function fmtNumber(value) {
  if (value == null) return '—';
  return new Intl.NumberFormat('id-ID').format(value);
}

function statusBadge(status) {
  const map = {
    locked: ['success', 'Terkunci'],
    in_progress: ['warning', 'Sedang dinilai'],
    not_started: ['', 'Belum mulai'],
    belum_mulai: ['', 'Belum mulai'],
  };
  const [tone, label] = map[status] || ['', status || '—'];
  return `<span class="badge ${tone}">${esc(label)}</span>`;
}

function outcomeBadge(result) {
  if (!result) return '<span class="badge">—</span>';
  const map = {
    kompeten_penuh: 'success',
    kompeten_sub: 'primary',
    kompeten_unit: 'info',
    belum_kompeten: 'danger',
  };
  return `<span class="badge ${map[result.outcome] || ''}">${esc(result.outcome_label || result.outcome || '—')}</span>`;
}

function schemeBadge(kode) {
  const colors = {
    'JNT-SMK': 'primary',
    'LSA-PRO': 'teal',
    'CNA-MTC': 'purple',
  };
  return `<span class="badge ${colors[kode] || 'info'} mono">${esc(kode || 'JNT-SMK')}</span>`;
}

function iconCircle(tone, svgPath) {
  return `<span class="wh-45 ${tone}" aria-hidden="true"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${svgPath}</svg></span>`;
}

/* ------------------------------------------------------------------ */
/* API                                                                */
/* ------------------------------------------------------------------ */
class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data || {};
  }
}

async function api(path, options = {}) {
  const { method = 'GET', body, headers = {}, silent401 = false } = options;
  const finalHeaders = { ...headers };
  const init = { method, credentials: 'same-origin', headers: finalHeaders };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    finalHeaders['Content-Type'] = 'application/json';
  }
  if (method !== 'GET' && method !== 'HEAD') finalHeaders['X-Requested-With'] = 'fetch';

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError('Tidak dapat terhubung ke server.', 0, { error: 'network_error' });
  }

  const text = await response.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = null; }
  }

  if (!response.ok) {
    if (response.status === 401 && !silent401) {
      state.user = null;
      showAuth();
    }
    const message = data?.message || data?.error || `Permintaan gagal (${response.status}).`;
    throw new ApiError(message, response.status, data);
  }
  return data;
}

/* ------------------------------------------------------------------ */
/* IndexedDB outbox                                                   */
/* ------------------------------------------------------------------ */
let idbPromise = null;

function openOutbox() {
  if (!('indexedDB' in window)) return Promise.reject(new Error('IndexedDB tidak tersedia'));
  if (!idbPromise) {
    idbPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open('ukk_outbox', 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains('outbox')) {
          db.createObjectStore('outbox', { keyPath: 'key' });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  return idbPromise;
}

async function idbPut(item) {
  const db = await openOutbox();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('outbox', 'readwrite');
    tx.objectStore('outbox').put(item);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function idbAll() {
  const db = await openOutbox();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('outbox', 'readonly');
    const request = tx.objectStore('outbox').getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

async function idbDelete(keys) {
  if (!keys.length) return;
  const db = await openOutbox();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('outbox', 'readwrite');
    const store = tx.objectStore('outbox');
    keys.forEach((key) => store.delete(key));
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function outboxAll() {
  try {
    return await idbAll();
  } catch {
    return [...memoryOutbox.values()];
  }
}

async function outboxPut(item) {
  memoryOutbox.set(item.key, item);
  try {
    await idbPut(item);
  } catch {
    /* fallback memori tetap dipakai */
  }
}

async function outboxDelete(keys) {
  keys.forEach((key) => memoryOutbox.delete(key));
  try {
    await idbDelete(keys);
  } catch {
    /* fallback memori */
  }
}

/* ------------------------------------------------------------------ */
/* Toast & modal                                                      */
/* ------------------------------------------------------------------ */
let toastTimer = null;

function toast(message, type = '') {
  const el = document.querySelector('#toast');
  el.textContent = message;
  el.className = `toast ${type}`.trim();
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 3800);
}

function openModal({ title, body, actions = [], onMount = null }) {
  const root = document.querySelector('#modal-root');
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="modal-head">
        <h3>${esc(title)}</h3>
        <button class="modal-close" type="button" aria-label="Tutup">&times;</button>
      </div>
      <div class="modal-body">${body}</div>
      <div class="modal-foot"></div>
    </div>`;
  root.appendChild(backdrop);

  const close = () => {
    backdrop.remove();
    document.removeEventListener('keydown', onKey);
  };
  const onKey = (event) => { if (event.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  backdrop.addEventListener('click', (event) => { if (event.target === backdrop) close(); });
  backdrop.querySelector('.modal-close').addEventListener('click', close);

  const footer = backdrop.querySelector('.modal-foot');
  actions.forEach((action) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `btn ${action.className || ''}`.trim();
    button.textContent = action.label;
    if (action.dataAttr) button.setAttribute(action.dataAttr, 'true');
    button.addEventListener('click', async () => {
      if (action.onClick) {
        await action.onClick({ close, button, root: backdrop });
      } else {
        close();
      }
    });
    footer.appendChild(button);
  });

  if (onMount) onMount(backdrop, close);
  const firstInput = backdrop.querySelector('input, textarea, select');
  if (firstInput) firstInput.focus();
  return close;
}

/* ------------------------------------------------------------------ */
/* Auth                                                               */
/* ------------------------------------------------------------------ */
function showAuth() {
  document.querySelector('#login-view').classList.remove('hidden');
  document.querySelector('#app-shell').classList.add('hidden');
}

function showAppShell() {
  document.querySelector('#login-view').classList.add('hidden');
  document.querySelector('#app-shell').classList.remove('hidden');
  const line = document.querySelector('#sidebar-user');
  if (state.user && line) {
    line.innerHTML = `<strong>${esc(state.user.username)}</strong><span class="muted">Asesor Kompetensi</span>`;
  }
}

async function bootAuth() {
  const status = await api('/auth/status', { silent401: true });
  if (status.needs_setup) {
    showAuth();
    renderSetup();
  } else if (status.authenticated) {
    state.user = status.user;
    showAppShell();
    await loadSchemes();
    if (!location.hash) location.hash = '#/dashboard';
    await route();
  } else {
    showAuth();
    renderLogin();
  }
  refreshInstrumentVersion();
}

function authCard(content) {
  document.querySelector('#auth-content').innerHTML = content;
}

function renderLogin(message = '') {
  showAuth();
  authCard(`
    <h2>Masuk</h2>
    <p class="sub muted">Gunakan akun asesor dan kode TOTP dari aplikasi authenticator.</p>
    <form id="login-form" novalidate>
      <div class="field">
        <label for="login-username">Username</label>
        <input id="login-username" name="username" autocomplete="username" required>
      </div>
      <div class="field">
        <label for="login-password">Password</label>
        <input id="login-password" name="password" type="password" autocomplete="current-password" required>
      </div>
      <div class="field">
        <label for="login-totp">Kode TOTP (6 digit)</label>
        <input id="login-totp" name="totp" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" required>
      </div>
      <p id="login-error" class="error-text" role="alert">${esc(message)}</p>
      <button class="btn primary wide" type="submit">Masuk</button>
    </form>`);
  const form = document.querySelector('#login-form');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    const errorEl = document.querySelector('#login-error');
    button.disabled = true;
    errorEl.textContent = '';
    try {
      const data = await api('/auth/login', {
        method: 'POST',
        body: {
          username: form.username.value.trim(),
          password: form.password.value,
          totp: form.totp.value.trim(),
        },
        silent401: true,
      });
      state.user = data.user;
      showAppShell();
      await loadSchemes();
      if (!location.hash || location.hash === '#/') {
        location.hash = '#/dashboard';
      } else {
        await route();
      }
    } catch (error) {
      errorEl.textContent = error.status === 429
        ? 'Terlalu banyak percobaan. Tunggu satu menit.'
        : 'Username, password, atau kode TOTP tidak sesuai.';
      button.disabled = false;
    }
  });
}

function renderSetup() {
  showAuth();
  authCard(`
    <h2>Setup awal</h2>
    <p class="sub muted">Buat satu akun asesor. Setelah dibuat, hubungkan kode TOTP ke aplikasi authenticator.</p>
    <form id="setup-form" novalidate>
      <div class="field">
        <label for="setup-username">Username</label>
        <input id="setup-username" name="username" autocomplete="username" minlength="3" required>
      </div>
      <div class="field">
        <label for="setup-password">Password (minimal 8 karakter)</label>
        <input id="setup-password" name="password" type="password" minlength="8" autocomplete="new-password" required>
      </div>
      <div class="field">
        <label for="setup-password2">Ulangi password</label>
        <input id="setup-password2" name="password2" type="password" minlength="8" autocomplete="new-password" required>
      </div>
      <p id="setup-error" class="error-text" role="alert"></p>
      <button class="btn primary wide" type="submit">Buat akun</button>
    </form>`);
  const form = document.querySelector('#setup-form');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const errorEl = document.querySelector('#setup-error');
    const button = form.querySelector('button[type="submit"]');
    errorEl.textContent = '';
    if (form.password.value !== form.password2.value) {
      errorEl.textContent = 'Password dan konfirmasi tidak sama.';
      return;
    }
    button.disabled = true;
    try {
      const data = await api('/auth/setup', {
        method: 'POST',
        body: { username: form.username.value.trim(), password: form.password.value },
      });
      renderSetupSuccess(data);
    } catch (error) {
      errorEl.textContent = error.message;
      button.disabled = false;
    }
  });
}

function renderSetupSuccess(data) {
  authCard(`
    <h2>Akun dibuat</h2>
    <p class="sub muted">Masukkan secret ini ke aplikasi authenticator (TOTP), lalu masuk memakai kode 6 digit.</p>
    <div class="field">
      <label>Secret TOTP</label>
      <div class="secret-box"><span class="mono">${esc(data.secret)}</span></div>
    </div>
    <div class="field">
      <label>URI otpauth</label>
      <div class="secret-box"><span class="uri">${esc(data.otpauth_uri)}</span></div>
    </div>
    <div class="copy-row">
      <button id="copy-secret" class="btn small" type="button">Salin secret</button>
      <button id="copy-uri" class="btn small" type="button">Salin URI</button>
    </div>
    <div class="divider"></div>
    <button id="to-login" class="btn primary wide" type="button">Lanjut ke login</button>`);
  document.querySelector('#copy-secret').addEventListener('click', () => copyText(data.secret));
  document.querySelector('#copy-uri').addEventListener('click', () => copyText(data.otpauth_uri));
  document.querySelector('#to-login').addEventListener('click', () => renderLogin());
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Teks disalin.', 'success');
  } catch {
    toast('Gagal menyalin. Salin manual dari kotak teks.', 'error');
  }
}

/* ------------------------------------------------------------------ */
/* Schemes & Shell                                                    */
/* ------------------------------------------------------------------ */
async function loadSchemes() {
  try {
    const res = await api('/schemes', { silent401: true });
    state.schemes = res.data || [];
    syncSchemeSwitcherDom();
  } catch {
    /* biarkan kosong bila belum login */
  }
}

function syncSchemeSwitcherDom() {
  const select = document.querySelector('#scheme-switcher');
  if (!select) return;
  const options = [
    '<option value="ALL">Semua Skema (' + state.schemes.length + ')</option>',
    ...state.schemes.map(
      (s) => `<option value="${esc(s.kode)}">${esc(s.kode)} — ${esc(s.nama)}</option>`
    ),
  ];
  select.innerHTML = options.join('');
  if (state.activeScheme !== 'ALL' && !state.schemes.some((s) => s.kode === state.activeScheme)) {
    state.activeScheme = 'ALL';
  }
  select.value = state.activeScheme;
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('ukk-theme', theme);
}

function initTheme() {
  const saved = localStorage.getItem('ukk-theme');
  const preferred = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  applyTheme(saved || preferred);
}

function bindShell() {
  document.querySelector('#theme-toggle').addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
  });
  document.querySelector('#logout-btn').addEventListener('click', async () => {
    try { await api('/auth/logout', { method: 'POST' }); } catch { /* tetap keluar lokal */ }
    state.user = null;
    state.assessment = null;
    renderLogin();
  });
  document.querySelector('#sync-pill').addEventListener('click', () => flushOutbox(true));
  document.querySelector('#menu-toggle').addEventListener('click', () => {
    const open = document.body.classList.toggle('sidebar-open');
    document.querySelector('#sidebar-backdrop').classList.toggle('hidden', !open);
    document.querySelector('#menu-toggle').setAttribute('aria-expanded', String(open));
  });
  document.querySelector('#sidebar-backdrop').addEventListener('click', closeSidebar);
  document.querySelector('#sidebar-collapse').addEventListener('click', () => {
    const collapsed = document.querySelector('#app-shell').classList.toggle('collapsed');
    localStorage.setItem('ukk-sidebar-collapsed', collapsed ? '1' : '0');
  });
  if (localStorage.getItem('ukk-sidebar-collapsed') === '1') {
    document.querySelector('#app-shell').classList.add('collapsed');
  }
  document.querySelectorAll('.nav-link').forEach((link) => link.addEventListener('click', closeSidebar));

  const switcher = document.querySelector('#scheme-switcher');
  if (switcher) {
    switcher.addEventListener('change', async (e) => {
      state.activeScheme = e.target.value;
      localStorage.setItem('ukk-active-scheme', state.activeScheme);
      if (state.activeScheme !== 'ALL') {
        state.configScheme = state.activeScheme;
        localStorage.setItem('ukk-config-scheme', state.configScheme);
      }
      await refreshInstrumentVersion();
      await route();
    });
  }

  const sidebarSearch = document.querySelector('#sidebar-search');
  if (sidebarSearch) {
    sidebarSearch.addEventListener('input', (e) => {
      const q = e.target.value.trim().toLowerCase();
      document.querySelectorAll('.sidebar .nav-link').forEach((link) => {
        const text = link.textContent.toLowerCase();
        link.style.display = !q || text.includes(q) ? '' : 'none';
      });
    });
  }
}

function closeSidebar() {
  document.body.classList.remove('sidebar-open');
  document.querySelector('#sidebar-backdrop').classList.add('hidden');
  document.querySelector('#menu-toggle').setAttribute('aria-expanded', 'false');
}

function setPage(title, eyebrow = 'PORTAL ASESOR') {
  document.querySelector('#page-title').textContent = title;
  document.querySelector('#page-eyebrow').textContent = eyebrow;
  document.title = `${title} — AeroAssess`;
}

function setNav(active) {
  document.querySelectorAll('.nav-link').forEach((link) => {
    link.classList.toggle('active', link.dataset.nav === active);
  });
}

async function refreshInstrumentVersion() {
  try {
    const scheme = state.activeScheme !== 'ALL' ? state.activeScheme : state.configScheme || 'JNT-SMK';
    const instrument = await api(`/config/instrument?scheme_kode=${encodeURIComponent(scheme)}`, { silent401: true });
    state.instrument = instrument;
    document.querySelector('#instrument-version').textContent = `v${instrument.version}`;
  } catch {
    /* biarkan versi terakhir */
  }
}

async function route() {
  if (!state.user) {
    showAuth();
    return;
  }
  closeSidebar();
  if (!state.schemes.length) await loadSchemes();
  const raw = location.hash.replace(/^#\/?/, '');
  const parts = raw.split('/').filter(Boolean);
  const root = parts[0] || 'dashboard';
  setNav(root === 'assessment' ? 'schools' : root);
  try {
    if (root === 'dashboard') await renderDashboard();
    else if (root === 'schemes') await renderSchemes();
    else if (root === 'recap') await renderRecap();
    else if (root === 'schools' && parts.length === 1) await renderSchools();
    else if (root === 'schools' && parts[2] === 'results') await renderResults(Number(parts[1]));
    else if (root === 'schools') await renderSchool(Number(parts[1]));
    else if (root === 'assessment') await renderAssessment(Number(parts[1]));
    else if (root === 'config') await renderConfig();
    else if (root === 'sync') await renderSync();
    else await renderDashboard();
  } catch (error) {
    if (error.status === 401) return;
    renderError(error);
  }
  document.querySelector('#view').focus({ preventScroll: true });
}

function navigate(hash) {
  if (location.hash === hash) {
    route();
  } else {
    location.hash = hash;
  }
}

function renderError(error) {
  setPage('Terjadi kesalahan', 'PORTAL ASESOR');
  document.querySelector('#view').innerHTML = `
    <div class="card card-body empty-state">
      <strong>Tidak dapat memuat halaman</strong>
      <p>${esc(error.message || 'Kesalahan tidak diketahui.')}</p>
      <div class="copy-row" style="justify-content:center;margin-top:12px">
        <button class="btn" type="button" onclick="location.reload()">Muat ulang</button>
        <a class="btn ghost" href="#/dashboard">Ke dashboard</a>
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ */
/* Dashboard (AeroPanel Multi-Scheme Overview)                        */
/* ------------------------------------------------------------------ */
async function renderDashboard() {
  setPage('Dashboard', 'Ringkasan Multi-Skema');
  const schemeQuery = state.activeScheme !== 'ALL' ? `?scheme_kode=${encodeURIComponent(state.activeScheme)}` : '';
  const [schoolsRes, schemesRes, recapRes] = await Promise.all([
    api(`/schools${schemeQuery}`),
    api('/schemes'),
    api(`/recap/summary${schemeQuery}`),
  ]);
  state.schools = schoolsRes.data;
  state.schemes = schemesRes.data;
  syncSchemeSwitcherDom();

  const totals = recapRes.totals || { participants: 0, locked: 0, in_progress: 0, not_started: 0 };
  const outcomes = recapRes.outcomes || {};
  const totalOut = Math.max(1, totals.participants || 1);
  const pPenuh = Math.round(((outcomes.kompeten_penuh || 0) / totalOut) * 100);
  const pSub = Math.round(((outcomes.kompeten_sub || 0) / totalOut) * 100);
  const pUnit = Math.round(((outcomes.kompeten_unit || 0) / totalOut) * 100);
  const pBelum = Math.round(((outcomes.belum_kompeten || 0) / totalOut) * 100);

  const activeSchemeObj = state.schemes.find((s) => s.kode === state.activeScheme);
  const subtitleText = activeSchemeObj
    ? `Skema Aktif: ${activeSchemeObj.nama} (${activeSchemeObj.units_count} unit, ${activeSchemeObj.indicators_count} indikator, ${activeSchemeObj.sub_competencies_count} sub kompetensi)`
    : `${state.schemes.length} skema kompetensi aktif · Pengganti Google Form & Rekap Manual Google Sheet.`;

  document.querySelector('#view').innerHTML = `
    <div class="page-head">
      <div>
        <h2>Ringkasan Penilaian &amp; Kompetensi</h2>
        <p class="sub muted">${esc(subtitleText)}</p>
      </div>
      <div class="head-actions">
        <a class="btn" href="#/schemes">Kelola Skema (${state.schemes.length})</a>
        <a class="btn" href="#/recap">Rekap Otomatis &amp; Sheet</a>
        <a class="btn primary" href="#/schools">Kelola Sekolah</a>
      </div>
    </div>

    <div class="stat-grid">
      <div class="card stat-card">
        <div class="stat-card-top">
          <div>
            <div class="stat-label">Skema &amp; Institusi</div>
            <div class="stat-value">${fmtNumber(state.schools.length)}</div>
          </div>
          ${iconCircle('primary', '<path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6"/>')}
        </div>
        <div class="stat-note"><span class="badge primary">${state.schemes.length} Skema</span> Sekolah / TUK Terdaftar</div>
      </div>

      <div class="card stat-card">
        <div class="stat-card-top">
          <div>
            <div class="stat-label">Total Peserta</div>
            <div class="stat-value">${fmtNumber(totals.participants)}</div>
          </div>
          ${iconCircle('info', '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>')}
        </div>
        <div class="stat-note">Seluruh sekolah pada filter aktif</div>
      </div>

      <div class="card stat-card">
        <div class="stat-card-top">
          <div>
            <div class="stat-label">Terkunci (Final)</div>
            <div class="stat-value">${fmtNumber(totals.locked)}</div>
          </div>
          ${iconCircle('success', '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>')}
        </div>
        <div class="stat-note"><span class="badge success">${totals.participants ? Math.round((totals.locked / totals.participants) * 100) : 0}%</span> Hasil siap diekspor ke Sheet</div>
      </div>

      <div class="card stat-card">
        <div class="stat-card-top">
          <div>
            <div class="stat-label">Sedang Dinilai</div>
            <div class="stat-value">${fmtNumber(totals.in_progress)}</div>
          </div>
          ${iconCircle('warning', '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>')}
        </div>
        <div class="stat-note">Belum dikunci · ${fmtNumber(totals.not_started)} belum mulai</div>
      </div>
    </div>

    <!-- AeroPanel Segmented Analytics Bar -->
    <div class="card">
      <div class="card-head">
        <div>
          <div class="card-title">Distribusi Capaian Kompetensi Peserta</div>
          <div class="card-sub">Rekapitulasi otomatis real-time tanpa rumus manual Google Sheet.</div>
        </div>
        <a class="btn small ghost" href="#/recap">Lihat Analitik Unit &rarr;</a>
      </div>
      <div class="card-body">
        <div class="segmented-bar" role="img" aria-label="Distribusi capaian kompetensi">
          <div class="segmented-slice success" style="width:${pPenuh}%" title="Kompeten Penuh: ${outcomes.kompeten_penuh || 0}"></div>
          <div class="segmented-slice primary" style="width:${pSub}%" title="Kompeten Sub: ${outcomes.kompeten_sub || 0}"></div>
          <div class="segmented-slice info" style="width:${pUnit}%" title="Kompeten Unit: ${outcomes.kompeten_unit || 0}"></div>
          <div class="segmented-slice danger" style="width:${pBelum}%" title="Belum Kompeten: ${outcomes.belum_kompeten || 0}"></div>
        </div>
        <div class="legend-grid">
          <div class="legend-item"><span><span class="legend-dot" style="background:var(--success)"></span>Kompeten Penuh</span><strong class="tabular">${fmtNumber(outcomes.kompeten_penuh || 0)}</strong></div>
          <div class="legend-item"><span><span class="legend-dot" style="background:var(--primary)"></span>Kompeten Sub</span><strong class="tabular">${fmtNumber(outcomes.kompeten_sub || 0)}</strong></div>
          <div class="legend-item"><span><span class="legend-dot" style="background:var(--info)"></span>Kompeten Unit</span><strong class="tabular">${fmtNumber(outcomes.kompeten_unit || 0)}</strong></div>
          <div class="legend-item"><span><span class="legend-dot" style="background:var(--danger)"></span>Belum Kompeten</span><strong class="tabular">${fmtNumber(outcomes.belum_kompeten || 0)}</strong></div>
        </div>
      </div>
    </div>

    <!-- Schools Table -->
    <div class="card">
      <div class="card-head">
        <div>
          <div class="card-title">Daftar Sekolah / TUK</div>
          <div class="card-sub">Progres dihitung dari peserta yang sudah dikunci.</div>
        </div>
        <div class="toolbar">
          <a class="btn small" href="#/schools">Tambah / Kelola Sekolah</a>
        </div>
      </div>
      ${state.schools.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Kode</th><th>Skema</th><th>Nama Sekolah / Institusi</th><th>Peserta</th><th>Terkunci</th><th>Progres</th><th></th></tr></thead>
          <tbody>
            ${state.schools.map((school) => {
              const total = school.participant_count || 0;
              const locked = school.locked_count || 0;
              const percent = total ? Math.round((locked / total) * 100) : 0;
              return `<tr>
                <td><span class="mono">${esc(school.kode)}</span></td>
                <td>${schemeBadge(school.scheme_kode)}</td>
                <td><div class="row-title">${esc(school.nama)}</div><div class="row-sub">${esc(school.alamat || '—')}</div></td>
                <td class="tabular">${fmtNumber(total)}</td>
                <td class="tabular">${fmtNumber(locked)}</td>
                <td><div class="progress-line"><div class="progress"><div class="progress-bar" style="width:${percent}%"></div><span class="progress-marker"></span></div><span class="progress-num">${percent}%</span></div></td>
                <td class="actions"><a class="btn small" href="#/schools/${school.id}">Buka</a></td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>` : `<div class="empty-state"><strong>Belum ada sekolah</strong><p>Tambahkan sekolah pertama untuk mulai menilai peserta.</p></div>`}
    </div>`;
}

/* ------------------------------------------------------------------ */
/* Schemes Page (`#/schemes` — Multi-Scheme Management)               */
/* ------------------------------------------------------------------ */
async function renderSchemes() {
  setPage('Skema Asesmen', 'Multi-Skema');
  const res = await api('/schemes');
  state.schemes = res.data || [];
  syncSchemeSwitcherDom();

  document.querySelector('#view').innerHTML = `
    <div class="page-head">
      <div>
        <h2>Skema Asesmen Kompetensi</h2>
        <p class="sub muted">Kelola berbagai skema sertifikasi/uji kompetensi (SMK, Linux SysAdmin, Routing &amp; Switching, dll) dalam satu portal.</p>
      </div>
      <div class="head-actions">
        <button class="btn primary" id="add-scheme" type="button">+ Buat Skema Baru</button>
      </div>
    </div>

    <div class="scheme-grid">
      ${state.schemes.map((scheme) => {
        const isCurrent = state.activeScheme === scheme.kode;
        return `
        <div class="card scheme-card ${isCurrent ? 'active-scheme' : ''}">
          <div>
            <div class="stat-card-top">
              <div>
                ${schemeBadge(scheme.kode)}
                <h3 style="margin-top:8px">${esc(scheme.nama)}</h3>
              </div>
              <span class="badge ${scheme.aktif ? 'success' : ''}">v${esc(scheme.version)}</span>
            </div>
            <p class="muted" style="font-size:0.86rem;margin-top:6px">${esc(scheme.deskripsi || 'Skema uji kompetensi profesi / vokasi.')}</p>
            <div class="scheme-meta-pills">
              <span class="chip">${fmtNumber(scheme.units_count)} Unit</span>
              <span class="chip">${fmtNumber(scheme.indicators_count)} Indikator</span>
              <span class="chip">${fmtNumber(scheme.sub_competencies_count)} Sub Kompetensi</span>
              <span class="chip">Ambang ${fmtNumber(scheme.pass_threshold)}%</span>
              <span class="chip">${fmtNumber(scheme.schools_count)} Sekolah</span>
              <span class="chip">${fmtNumber(scheme.participants_count)} Peserta</span>
            </div>
          </div>
          <div>
            <div class="divider"></div>
            <div class="toolbar" style="justify-content:space-between">
              <div class="toolbar">
                <button class="btn small ${isCurrent ? 'success' : 'primary'}" type="button" data-select-scheme="${esc(scheme.kode)}">
                  ${isCurrent ? 'Skema Aktif' : 'Pilih Skema'}
                </button>
                <button class="btn small" type="button" data-config-scheme="${esc(scheme.kode)}">Unit &amp; Indikator</button>
              </div>
              <div class="toolbar">
                <a class="btn small ghost" href="/api/schemes/${encodeURIComponent(scheme.kode)}/export?format=xlsx" download title="Unduh Rekap XLSX Skema">XLSX</a>
                <button class="btn small ghost" type="button" data-edit-scheme="${esc(scheme.kode)}">Edit</button>
                ${scheme.kode !== 'JNT-SMK' ? `<button class="btn small danger" type="button" data-delete-scheme="${esc(scheme.kode)}">Hapus</button>` : ''}
              </div>
            </div>
          </div>
        </div>`;
      }).join('')}
    </div>`;

  document.querySelector('#add-scheme')?.addEventListener('click', () => openSchemeModal());
  document.querySelectorAll('[data-select-scheme]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      state.activeScheme = btn.dataset.selectScheme;
      state.configScheme = state.activeScheme;
      localStorage.setItem('ukk-active-scheme', state.activeScheme);
      localStorage.setItem('ukk-config-scheme', state.configScheme);
      syncSchemeSwitcherDom();
      toast(`Skema aktif diubah ke ${state.activeScheme}.`, 'success');
      await renderSchemes();
    });
  });
  document.querySelectorAll('[data-config-scheme]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.configScheme = btn.dataset.configScheme;
      localStorage.setItem('ukk-config-scheme', state.configScheme);
      navigate('#/config');
    });
  });
  document.querySelectorAll('[data-edit-scheme]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const scheme = state.schemes.find((s) => s.kode === btn.dataset.editScheme);
      if (scheme) openSchemeModal(scheme);
    });
  });
  document.querySelectorAll('[data-delete-scheme]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const kode = btn.dataset.deleteScheme;
      confirmDelete('Hapus skema asesmen?', `Skema ${kode} beserta unit yang belum dipakai akan dihapus.`, async () => {
        await api(`/schemes/${encodeURIComponent(kode)}`, { method: 'DELETE' });
        if (state.activeScheme === kode) state.activeScheme = 'ALL';
        toast(`Skema ${kode} dihapus.`, 'success');
        await loadSchemes();
        await renderSchemes();
      });
    });
  });
}

function openSchemeModal(scheme = null) {
  const editing = Boolean(scheme);
  openModal({
    title: editing ? `Edit Skema ${scheme.kode}` : 'Buat Skema Asesmen Baru',
    body: `
      <form id="scheme-form">
        <div class="form-grid">
          <div class="field">
            <label for="scheme-kode">Kode Skema</label>
            <input id="scheme-kode" name="kode" required value="${esc(scheme?.kode || '')}" ${editing ? 'disabled' : ''} placeholder="Contoh: MTCNA-01">
          </div>
          <div class="field">
            <label for="scheme-kategori">Kategori / Bidang</label>
            <input id="scheme-kategori" name="kategori" value="${esc(scheme?.kategori || 'Jaringan & Infrastruktur')}" placeholder="Jaringan & Infrastruktur">
          </div>
          <div class="field full">
            <label for="scheme-nama">Nama Skema / Jabatan Kompetensi</label>
            <input id="scheme-nama" name="nama" required value="${esc(scheme?.nama || '')}" placeholder="Contoh: Network Security Associate">
          </div>
          <div class="field">
            <label for="scheme-jenjang">Jenjang / Target</label>
            <input id="scheme-jenjang" name="jenjang" value="${esc(scheme?.jenjang || 'SMK / Profesional')}">
          </div>
          <div class="field">
            <label for="scheme-threshold">Ambang Lulus Unit (%)</label>
            <input id="scheme-threshold" name="pass_threshold" type="number" min="1" max="100" value="${esc(scheme?.pass_threshold ?? 70)}">
          </div>
          <div class="field full">
            <label for="scheme-deskripsi">Deskripsi Skema</label>
            <textarea id="scheme-deskripsi" name="deskripsi" placeholder="Ringkasan ruang lingkup uji kompetensi...">${esc(scheme?.deskripsi || '')}</textarea>
          </div>
        </div>
        <p id="scheme-error" class="error-text" role="alert"></p>
      </form>`,
    actions: [
      { label: 'Batal', className: 'ghost' },
      {
        label: editing ? 'Simpan' : 'Buat Skema',
        className: 'primary',
        onClick: async ({ close, button }) => {
          const form = document.querySelector('#scheme-form');
          const errorEl = document.querySelector('#scheme-error');
          button.disabled = true;
          errorEl.textContent = '';
          const payload = {
            nama: form.nama.value.trim(),
            kategori: form.kategori.value.trim(),
            jenjang: form.jenjang.value.trim(),
            pass_threshold: Number(form.pass_threshold.value || 70),
            deskripsi: form.deskripsi.value.trim(),
          };
          try {
            if (editing) {
              await api(`/schemes/${encodeURIComponent(scheme.kode)}`, { method: 'PATCH', body: payload });
            } else {
              await api('/schemes', {
                method: 'POST',
                body: { ...payload, kode: form.kode.value.trim().toUpperCase() },
              });
            }
            close();
            toast(editing ? 'Skema diperbarui.' : 'Skema baru ditambahkan.', 'success');
            await loadSchemes();
            await renderSchemes();
          } catch (error) {
            errorEl.textContent = error.message;
            button.disabled = false;
          }
        },
      },
    ],
  });
}

/* ------------------------------------------------------------------ */
/* Automatic Recap & Sheet Replacement (`#/recap`)                    */
/* ------------------------------------------------------------------ */
async function renderRecap() {
  setPage('Rekapitulasi & Analitik', 'Pengganti Google Sheet');
  const filterScheme = state.activeScheme !== 'ALL' ? state.activeScheme : '';
  const query = filterScheme ? `?scheme_kode=${encodeURIComponent(filterScheme)}` : '';
  const summary = await api(`/recap/summary${query}`);
  const totals = summary.totals || {};
  const outcomes = summary.outcomes || {};
  const predicates = summary.predicates || {};
  const unitAnalytics = summary.unit_analytics || [];
  const rows = summary.participant_rows || [];
  const exportScheme = filterScheme || (state.schemes[0]?.kode || 'JNT-SMK');

  document.querySelector('#view').innerHTML = `
    <div class="page-head">
      <div>
        <h2>Rekapitulasi Otomatis &amp; Analitik Asesor</h2>
        <p class="sub muted">Menggantikan rekap manual Google Sheet: kalkulasi kelulusan unit, sub-kompetensi, predikat, dan ekspor multi-tab otomatis.</p>
      </div>
      <div class="head-actions">
        <a class="btn" href="/api/schemes/${encodeURIComponent(exportScheme)}/export?format=csv" download>Unduh CSV (${esc(exportScheme)})</a>
        <a class="btn primary" href="/api/schemes/${encodeURIComponent(exportScheme)}/export?format=xlsx" download>Unduh Multi-Sheet XLSX (${esc(exportScheme)})</a>
      </div>
    </div>

    <div class="stat-grid">
      <div class="card stat-card">
        <div class="stat-card-top">
          <div><div class="stat-label">Kompeten Penuh</div><div class="stat-value">${fmtNumber(outcomes.kompeten_penuh || 0)}</div></div>
          ${iconCircle('success', '<path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/>')}
        </div>
        <div class="stat-note">Lulus seluruh unit skema</div>
      </div>
      <div class="card stat-card">
        <div class="stat-card-top">
          <div><div class="stat-label">Kompeten Sub / Unit</div><div class="stat-value">${fmtNumber((outcomes.kompeten_sub || 0) + (outcomes.kompeten_unit || 0))}</div></div>
          ${iconCircle('primary', '<path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>')}
        </div>
        <div class="stat-note">${fmtNumber(outcomes.kompeten_sub || 0)} Sub · ${fmtNumber(outcomes.kompeten_unit || 0)} Unit Parsial</div>
      </div>
      <div class="card stat-card">
        <div class="stat-card-top">
          <div><div class="stat-label">Sangat Mahir / Mahir</div><div class="stat-value">${fmtNumber((predicates['Sangat Mahir'] || 0) + (predicates['Mahir'] || 0))}</div></div>
          ${iconCircle('purple', '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>')}
        </div>
        <div class="stat-note">${fmtNumber(predicates['Sangat Mahir'] || 0)} Sangat Mahir · ${fmtNumber(predicates['Cakap'] || 0)} Cakap</div>
      </div>
      <div class="card stat-card">
        <div class="stat-card-top">
          <div><div class="stat-label">Belum Kompeten</div><div class="stat-value">${fmtNumber(outcomes.belum_kompeten || 0)}</div></div>
          ${iconCircle('danger', '<circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/>')}
        </div>
        <div class="stat-note">Total dinilai: ${fmtNumber(totals.participants || 0)} peserta</div>
      </div>
    </div>

    <!-- Unit Pass-Rate Analytics -->
    <div class="card">
      <div class="card-head">
        <div>
          <div class="card-title">Analitik Tingkat Kelulusan per Unit Kompetensi</div>
          <div class="card-sub">Membantu asesor mengidentifikasi unit kompetensi yang paling dikuasai atau paling sering gagal.</div>
        </div>
      </div>
      ${unitAnalytics.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Skema</th><th>Kode Unit</th><th>Judul Unit Kompetensi</th><th>Dinilai</th><th>Lulus</th><th>Rata-rata Skor</th><th>Pass Rate</th></tr></thead>
          <tbody>
            ${unitAnalytics.map((u) => `<tr>
              <td>${schemeBadge(u.scheme_kode)}</td>
              <td><span class="mono">${esc(u.kode)}</span></td>
              <td><div class="row-title">${esc(u.judul)}</div></td>
              <td class="tabular">${fmtNumber(u.assessed_count)}</td>
              <td class="tabular">${fmtNumber(u.passed_count)}</td>
              <td class="tabular">${fmtPercent(u.avg_percent)}</td>
              <td>
                <div class="progress-line">
                  <div class="progress"><div class="progress-bar ${u.pass_rate >= 70 ? '' : 'fail'}" style="width:${Math.min(100, u.pass_rate)}%"></div ><span class="progress-marker"></span></div>
                  <span class="progress-num">${fmtPercent(u.pass_rate)}</span>
                </div>
              </td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>` : `<div class="empty-state"><strong>Belum ada data unit yang dinilai</strong><p>Mulai penilaian peserta pada salah satu sekolah untuk melihat analitik unit.</p></div>`}
    </div>

    <!-- Master Recap Spreadsheet Table -->
    <div class="card">
      <div class="card-head">
        <div>
          <div class="card-title">Buku Rekapitulasi Peserta Lintas Sekolah</div>
          <div class="card-sub">${rows.length} baris peserta · Siap diekspor ke Excel (.xlsx) dengan proteksi Formula Injection.</div>
        </div>
      </div>
      ${rows.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Skema</th><th>Sekolah</th><th>Nomor</th><th>Nama Peserta</th><th>Kelas</th><th>Status</th><th>Unit Lulus</th><th>Rata-rata</th><th>Predikat</th><th>Hasil Akhir</th><th></th></tr></thead>
          <tbody>
            ${rows.map((r) => `<tr>
              <td>${schemeBadge(r.scheme_kode)}</td>
              <td><div class="row-title">${esc(r.school_nama)}</div><div class="row-sub mono">${esc(r.school_kode)}</div></td>
              <td class="tabular">${esc(r.nomor)}</td>
              <td><div class="row-title">${esc(r.nama)}</div></td>
              <td>${esc(r.kelas || '—')}</td>
              <td>${statusBadge(r.status)}</td>
              <td class="tabular">${r.units_passed}/${r.units_total}</td>
              <td class="tabular">${fmtPercent(r.average_percent)}</td>
              <td>${esc(r.predicate || '—')}</td>
              <td>${outcomeBadge({ outcome: r.outcome, outcome_label: r.outcome_label })}</td>
              <td class="actions">${r.assessment_id ? `<a class="btn small ghost" href="#/assessment/${r.assessment_id}">Buka</a>` : `<a class="btn small ghost" href="#/schools/${r.school_id}">Sekolah</a>`}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>` : `<div class="empty-state"><strong>Belum ada peserta terdaftar</strong><p>Tambahkan sekolah dan impor daftar peserta terlebih dahulu.</p></div>`}
    </div>`;
}

/* ------------------------------------------------------------------ */
/* Schools                                                            */
/* ------------------------------------------------------------------ */
async function renderSchools() {
  setPage('Sekolah / TUK', 'Data Induk');
  const query = state.activeScheme !== 'ALL' ? `?scheme_kode=${encodeURIComponent(state.activeScheme)}` : '';
  const data = await api(`/schools${query}`);
  state.schools = data.data;
  document.querySelector('#view').innerHTML = `
    <div class="page-head">
      <div>
        <h2>Sekolah / Tempat Uji Kompetensi (TUK)</h2>
        <p class="sub muted">Kelola sekolah, pilih skema asesmen yang diujikan, dan impor daftar peserta.</p>
      </div>
      <div class="head-actions">
        <button class="btn primary" id="add-school" type="button">Tambah sekolah</button>
      </div>
    </div>
    <div class="card">
      ${state.schools.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Kode</th><th>Skema</th><th>Nama</th><th>Alamat</th><th>Peserta</th><th>Terkunci</th><th></th></tr></thead>
          <tbody>
            ${state.schools.map((school) => `<tr>
              <td><span class="mono">${esc(school.kode)}</span></td>
              <td>${schemeBadge(school.scheme_kode)}</td>
              <td><div class="row-title">${esc(school.nama)}</div><div class="row-sub">${esc(school.kontak || '')}</div></td>
              <td>${esc(school.alamat || '—')}</td>
              <td class="tabular">${fmtNumber(school.participant_count || 0)}</td>
              <td class="tabular">${fmtNumber(school.locked_count || 0)}</td>
              <td class="actions"><a class="btn small" href="#/schools/${school.id}">Buka</a></td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>` : `<div class="empty-state"><strong>Belum ada sekolah</strong><p>Tambahkan sekolah untuk mulai mengimpor peserta.</p><button class="btn primary" id="add-school-empty" type="button">Tambah sekolah</button></div>`}
    </div>`;
  const openAdd = () => openSchoolModal();
  document.querySelector('#add-school')?.addEventListener('click', openAdd);
  document.querySelector('#add-school-empty')?.addEventListener('click', openAdd);
}

function openSchoolModal(school = null) {
  const editing = Boolean(school);
  const defaultScheme = school?.scheme_kode || (state.activeScheme !== 'ALL' ? state.activeScheme : 'JNT-SMK');
  const schemeOptions = (state.schemes.length ? state.schemes : [{ kode: 'JNT-SMK', nama: 'Junior Network Technician (UKK SMK)' }])
    .map((s) => `<option value="${esc(s.kode)}" ${s.kode === defaultScheme ? 'selected' : ''}>${esc(s.kode)} — ${esc(s.nama)}</option>`)
    .join('');

  openModal({
    title: editing ? 'Edit sekolah' : 'Tambah sekolah',
    body: `
      <form id="school-form">
        <div class="form-grid">
          <div class="field full"><label for="school-nama">Nama sekolah / institusi</label><input id="school-nama" name="nama" required value="${esc(school?.nama || '')}"></div>
          <div class="field full">
            <label for="school-scheme">Skema Asesmen</label>
            <select id="school-scheme" name="scheme_kode">${schemeOptions}</select>
          </div>
          <div class="field"><label for="school-kode">Kode (opsional)</label><input id="school-kode" name="kode" value="${esc(school?.kode || '')}" placeholder="Otomatis dari nama"></div>
          <div class="field"><label for="school-kontak">Kontak</label><input id="school-kontak" name="kontak" value="${esc(school?.kontak || '')}"></div>
          <div class="field full"><label for="school-alamat">Alamat</label><input id="school-alamat" name="alamat" value="${esc(school?.alamat || '')}"></div>
        </div>
        <p id="school-error" class="error-text" role="alert"></p>
      </form>`,
    actions: [
      { label: 'Batal', className: 'ghost' },
      {
        label: editing ? 'Simpan' : 'Tambah',
        className: 'primary',
        onClick: async ({ close, button }) => {
          const form = document.querySelector('#school-form');
          const errorEl = document.querySelector('#school-error');
          button.disabled = true;
          errorEl.textContent = '';
          const payload = {
            nama: form.nama.value.trim(),
            scheme_kode: form.scheme_kode.value,
            kode: form.kode.value.trim() || null,
            alamat: form.alamat.value.trim(),
            kontak: form.kontak.value.trim(),
          };
          try {
            if (editing) {
              await api(`/schools/${school.id}`, { method: 'PATCH', body: payload });
            } else {
              await api('/schools', { method: 'POST', body: payload });
            }
            close();
            toast(editing ? 'Sekolah diperbarui.' : 'Sekolah ditambahkan.', 'success');
            await route();
            await refreshInstrumentVersion();
          } catch (error) {
            errorEl.textContent = error.message;
            button.disabled = false;
          }
        },
      },
    ],
  });
}

async function renderSchool(schoolId) {
  setPage('Sekolah', 'Peserta');
  const data = await api(`/schools/${schoolId}/overview`);
  state.schoolData = data;
  const school = data.school;
  const stats = data.stats;
  const schemeObj = state.schemes.find((s) => s.kode === school.scheme_kode);
  const indCount = schemeObj ? schemeObj.indicators_count : 61;

  document.querySelector('#view').innerHTML = `
    <div class="page-head">
      <div>
        <a class="muted" href="#/schools">&larr; Semua sekolah</a>
        <h2>${esc(school.nama)}</h2>
        <p class="sub muted">${schemeBadge(school.scheme_kode)} · <span class="mono">${esc(school.kode)}</span>${school.alamat ? ` · ${esc(school.alamat)}` : ''}</p>
      </div>
      <div class="head-actions">
        <button class="btn" id="edit-school" type="button">Edit sekolah</button>
        <button class="btn primary" id="next-participant" type="button">Peserta berikutnya</button>
        <a class="btn ghost" href="#/schools/${school.id}/results">Hasil &amp; ekspor</a>
      </div>
    </div>
    <div class="stat-grid">
      <div class="card stat-card"><div class="stat-label">Peserta</div><div class="stat-value">${fmtNumber(stats.participants)}</div><div class="stat-note">Terdaftar</div></div>
      <div class="card stat-card"><div class="stat-label">Terkunci</div><div class="stat-value">${fmtNumber(stats.locked)}</div><div class="stat-note">${fmtPercent(stats.percent_locked)}</div></div>
      <div class="card stat-card"><div class="stat-label">Sedang dinilai</div><div class="stat-value">${fmtNumber(stats.in_progress)}</div><div class="stat-note">Belum dikunci</div></div>
      <div class="card stat-card"><div class="stat-label">Belum mulai</div><div class="stat-value">${fmtNumber(stats.not_started)}</div><div class="stat-note">Belum ada assessment</div></div>
    </div>
    <div class="card">
      <div class="card-head">
        <div><div class="card-title">Peserta</div><div class="card-sub">Skor 0–3 per indikator (${indCount} indikator pada skema ${esc(school.scheme_kode || 'JNT-SMK')}).</div></div>
        <div class="toolbar">
          <button class="btn small" id="download-template" type="button">Contoh CSV</button>
          <button class="btn small" id="import-trigger" type="button">Impor CSV</button>
          <input id="import-file" type="file" accept=".csv,text/csv" class="hidden">
          <button class="btn small primary" id="add-participant" type="button">Tambah peserta</button>
        </div>
      </div>
      ${data.participants.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Nomor</th><th>Nama</th><th>Kelas</th><th>Status</th><th>Progres</th><th>Hasil</th><th></th></tr></thead>
          <tbody>
            ${data.participants.map((participant) => `<tr>
              <td class="tabular">${esc(participant.nomor)}</td>
              <td><div class="row-title">${esc(participant.nama)}</div></td>
              <td>${esc(participant.kelas || '—')}</td>
              <td>${statusBadge(participant.status)}</td>
              <td><div class="progress-line"><div class="progress"><div class="progress-bar ${participant.status === 'locked' ? '' : 'fail'}" style="width:${Math.max(0, Math.min(100, participant.progress_percent || 0))}%"></div><span class="progress-marker"></span></div><span class="progress-num">${Number(participant.progress_percent || 0).toFixed(0)}%</span></div></td>
              <td>${outcomeBadge(participant.result)}</td>
              <td class="actions">
                <button class="btn small ${participant.status === 'in_progress' ? 'primary' : ''}" type="button" data-assess="${participant.id}">${participant.assessment_id ? 'Lanjutkan' : 'Nilai'}</button>
                ${participant.assessment_id ? `<a class="btn small ghost" href="#/schools/${school.id}/results">Hasil</a>` : ''}
              </td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>` : `<div class="empty-state"><strong>Belum ada peserta</strong><p>Tambahkan peserta satu per satu atau impor CSV dengan kolom nomor, nama, kelas.</p></div>`}
    </div>`;

  document.querySelector('#edit-school').addEventListener('click', () => openSchoolModal(school));
  document.querySelector('#add-participant').addEventListener('click', () => openParticipantModal(school.id));
  document.querySelector('#next-participant').addEventListener('click', () => nextParticipant(data.participants));
  document.querySelector('#download-template').addEventListener('click', downloadCsvTemplate);
  document.querySelector('#import-trigger').addEventListener('click', () => document.querySelector('#import-file').click());
  document.querySelector('#import-file').addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) importCsv(school.id, file);
  });
  document.querySelectorAll('[data-assess]').forEach((button) => {
    button.addEventListener('click', () => {
      const participant = data.participants.find((item) => String(item.id) === button.dataset.assess);
      if (participant) startAssessmentFor(participant);
    });
  });
}

function openParticipantModal(schoolId) {
  openModal({
    title: 'Tambah peserta',
    body: `
      <form id="participant-form">
        <div class="form-grid">
          <div class="field"><label for="participant-nomor">Nomor peserta</label><input id="participant-nomor" name="nomor" required placeholder="03"></div>
          <div class="field"><label for="participant-kelas">Kelas / Instansi</label><input id="participant-kelas" name="kelas" placeholder="XII TKJ"></div>
          <div class="field full"><label for="participant-nama">Nama</label><input id="participant-nama" name="nama" required></div>
        </div>
        <p id="participant-error" class="error-text" role="alert"></p>
      </form>`,
    actions: [
      { label: 'Batal', className: 'ghost' },
      {
        label: 'Tambah',
        className: 'primary',
        onClick: async ({ close, button }) => {
          const form = document.querySelector('#participant-form');
          const errorEl = document.querySelector('#participant-error');
          button.disabled = true;
          errorEl.textContent = '';
          try {
            await api(`/schools/${schoolId}/participants`, {
              method: 'POST',
              body: {
                nomor: form.nomor.value.trim(),
                nama: form.nama.value.trim(),
                kelas: form.kelas.value.trim(),
              },
            });
            close();
            toast('Peserta ditambahkan.', 'success');
            await route();
          } catch (error) {
            errorEl.textContent = error.message;
            button.disabled = false;
          }
        },
      },
    ],
  });
}

async function importCsv(schoolId, file) {
  const form = new FormData();
  form.append('file', file);
  try {
    const result = await api(`/schools/${schoolId}/participants/import`, { method: 'POST', body: form });
    const errors = result.errors || [];
    const duplicates = result.duplicates || [];
    const detail = [
      ...errors.map((item) => `<li>Baris ${esc(item.row)}: ${esc(item.message)}</li>`),
      ...duplicates.map((item) => `<li>${item.row ? `Baris ${esc(item.row)}: ` : ''}${esc(item.nomor)} — ${esc(item.reason)}</li>`),
    ].join('');
    openModal({
      title: 'Hasil impor',
      body: `
        <p><strong>${result.imported}</strong> peserta diimpor.</p>
        <p class="muted">${errors.length} baris error, ${duplicates.length} duplikat.</p>
        ${detail ? `<div class="divider"></div><ul class="instruction-list">${detail}</ul>` : ''}`,
      actions: [{ label: 'Tutup', className: 'primary' }],
    });
    await route();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function downloadCsvTemplate() {
  const content = '\ufeffnomor,nama,kelas\n01,Ahmad Fauzi,XII TKJ\n02,Budi Santoso,XII TKJ\n';
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'contoh-peserta.csv';
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

async function nextParticipant(participants) {
  const next = participants.find((item) => item.status === 'in_progress')
    || participants.find((item) => item.status === 'not_started')
    || null;
  if (!next) {
    toast('Semua peserta sudah dikunci.', '');
    return;
  }
  await startAssessmentFor(next);
}

async function startAssessmentFor(participant) {
  try {
    if (participant.assessment_id) {
      navigate(`#/assessment/${participant.assessment_id}`);
      return;
    }
    const data = await api('/assessments', {
      method: 'POST',
      body: { participant_id: participant.id },
    });
    navigate(`#/assessment/${data.assessment.id}`);
  } catch (error) {
    toast(error.message, 'error');
  }
}

/* ------------------------------------------------------------------ */
/* Assessment                                                         */
/* ------------------------------------------------------------------ */
async function renderAssessment(assessmentId) {
  setPage('Penilaian', 'Lembar Skor');
  const data = await api(`/assessments/${assessmentId}`);
  state.assessment = data;
  state.scores = {};
  data.units.forEach((unit) => {
    unit.indicators.forEach((indicator) => {
      state.scores[indicator.kode] = indicator.value;
    });
  });
  await mergeOutbox(assessmentId);
  state.openUnits = new Set();
  if (!data.locked) {
    const firstEmpty = data.units.find((unit) => unit.indicators.some((indicator) => state.scores[indicator.kode] == null));
    state.openUnits.add((firstEmpty || data.units[0])?.kode);
  }
  renderAssessmentView(data);
  await refreshOutboxCount();
  updateSyncPill();
}

function renderAssessmentView(data) {
  const participant = data.assessment.participant;
  const school = data.assessment.school;
  const schemeKode = data.assessment.scheme_kode || school.scheme_kode || 'JNT-SMK';
  const progress = overallProgress();
  document.querySelector('#view').innerHTML = `
    <div class="page-head">
      <div>
        <a class="muted" href="#/schools/${school.id}">&larr; ${esc(school.nama)}</a>
        <h2>${esc(participant.nama)} <span class="muted tabular">(${esc(participant.nomor)})</span></h2>
        <p class="sub muted">${schemeBadge(schemeKode)} · ${esc(participant.kelas || '—')} · Instrumen v${esc(data.assessment.instrument_version)} · ${statusBadge(data.assessment.status)}</p>
      </div>
      <div class="head-actions">
        <button class="btn" id="save-now" type="button">Sinkron sekarang</button>
        <a class="btn ghost" href="#/schools/${school.id}/results">Hasil sekolah</a>
      </div>
    </div>
    <div class="card" style="padding:16px 18px;margin-bottom:16px">
      <div class="progress-line">
        <div class="progress" style="flex:1;height:10px"><div class="progress-bar" id="overall-progress-bar" style="width:${progress.percent}%"></div><span class="progress-marker"></span></div>
        <span class="progress-num tabular" id="overall-progress-text">${progress.filled}/${progress.total} · ${progress.percent}%</span>
      </div>
    </div>
    <div class="assessment-layout">
      <div class="assessment-main" id="units-list">
        ${data.units.map((unit, index) => unitHtml(unit, index, data.locked)).join('')}
      </div>
      <aside class="card result-panel" id="result-panel"></aside>
    </div>`;
  updateResultPanel();
  bindAssessmentEvents();
}

function unitHtml(unit, index, locked) {
  const stats = computeUnitStats(unit);
  const open = state.openUnits.has(unit.kode);
  const threshold = state.assessment?.thresholds?.unit_pass_percent ?? 70;
  return `
    <details class="unit-card card ${open ? 'open' : ''}" data-unit="${esc(unit.kode)}" ${open ? 'open' : ''}>
      <summary class="unit-head" data-toggle-unit="${esc(unit.kode)}" aria-expanded="${open}">
        <span class="unit-index tabular">${String(index + 1).padStart(2, '0')}</span>
        <div class="unit-head-main">
          <span class="unit-code">${esc(unit.kode)}</span>
          <div class="unit-title">${esc(unit.judul)}</div>
        </div>
        <div class="unit-head-metrics">
          <div class="progress"><div class="progress-bar ${stats.passed ? '' : 'fail'}" style="width:${stats.percent}%"></div><span class="progress-marker"></span></div>
          <span class="unit-percent">${stats.percent.toFixed(2)}%</span>
          <span class="badge ${stats.passed ? 'success' : 'danger'}">${stats.passed ? 'Lulus' : 'Belum'}</span>
        </div>
      </summary>
      <div class="unit-body">
        <div class="unit-summary">
          <span>Terisi <strong>${stats.filled}/${unit.indicators.length}</strong></span>
          <span>Kosong <strong>${stats.empty.length}</strong></span>
          <span>Skor <strong>${stats.total}</strong> / ${stats.max}</span>
          <span>Ambang lulus <strong>${threshold}%</strong></span>
        </div>
        ${unit.indicators.map((indicator) => indicatorHtml(indicator, locked)).join('')}
      </div>
    </details>`;
}

function indicatorHtml(indicator, locked) {
  const value = state.scores[indicator.kode];
  const sync = state.failedKeys.has(indicator.kode) ? 'failed' : state.pendingKeys.has(indicator.kode) ? 'pending' : 'synced';
  const syncTitle = sync === 'failed' ? 'Gagal sinkron' : sync === 'pending' ? 'Menunggu sinkron' : 'Tersinkron';
  return `
    <div class="indicator" data-indicator="${esc(indicator.kode)}">
      <div class="indicator-top">
        <div class="indicator-text">
          <span class="indicator-code">${esc(indicator.kode)}</span>
          ${indicator.is_proposed ? '<span class="proposed-badge">Usulan — verifikasi</span>' : ''}
          <p>${esc(indicator.teks)}</p>
        </div>
        <div class="score-group" role="group" aria-label="Skor ${esc(indicator.kode)}">
          ${[0, 1, 2, 3].map((score) => `<button class="score-btn ${value === score ? 'active' : ''}" type="button" data-score="${esc(indicator.kode)}" data-value="${score}" aria-pressed="${value === score}" ${locked ? 'disabled' : ''}>${score}</button>`).join('')}
        </div>
      </div>
      <div class="indicator-foot">
        <span class="sync-dot ${sync}" data-sync="${esc(indicator.kode)}" title="${syncTitle}"></span>
        <input class="note-input" data-note="${esc(indicator.kode)}" value="${esc(indicator.note || '')}" placeholder="Catatan indikator (opsional)" aria-label="Catatan ${esc(indicator.kode)}" ${locked ? 'disabled' : ''}>
      </div>
    </div>`;
}

function bindAssessmentEvents() {
  const view = document.querySelector('#view');
  view.addEventListener('click', async (event) => {
    const scoreButton = event.target.closest('[data-score]');
    if (scoreButton && !scoreButton.disabled) {
      setScore(scoreButton.dataset.score, Number(scoreButton.dataset.value));
      return;
    }
    if (event.target.closest('#save-now')) {
      await flushOutbox(true);
      return;
    }
    if (event.target.closest('[data-copy-statement]')) {
      const panel = document.querySelector('#result-panel');
      const statement = panel.querySelector('[data-statement-text]')?.textContent || '';
      await copyText(statement);
      return;
    }
    if (event.target.closest('[data-lock]')) {
      openLockModal();
      return;
    }
    if (event.target.closest('[data-unlock]')) {
      openUnlockModal();
    }
  });

  view.addEventListener('toggle', (event) => {
    const details = event.target.closest('details[data-unit]');
    if (!details) return;
    const kode = details.dataset.unit;
    const open = details.open;
    if (open) state.openUnits.add(kode); else state.openUnits.delete(kode);
  });

  view.addEventListener('input', (event) => {
    const input = event.target.closest('[data-note]');
    if (!input) return;
    const kode = input.dataset.note;
    clearTimeout(state.noteTimers[kode]);
    state.noteTimers[kode] = setTimeout(() => {
      queueScore(kode, state.scores[kode], input.value);
    }, 500);
  });
}

function computeUnitStats(unit) {
  let total = 0;
  let filled = 0;
  const empty = [];
  unit.indicators.forEach((indicator) => {
    const value = state.scores[indicator.kode];
    if (value === null || value === undefined) {
      empty.push(indicator.kode);
    } else {
      total += value;
      filled += 1;
    }
  });
  const n = unit.indicators.length;
  const percent = n ? Math.round((total / (3 * n)) * 10000) / 100 : 0;
  const threshold = Number(state.assessment?.thresholds?.unit_pass_percent ?? 70);
  const passed = n > 0 && (threshold === 70 ? total * 10 >= 21 * n : percent >= threshold);
  return {
    total,
    max: 3 * n,
    percent,
    passed,
    filled,
    empty,
  };
}

function overallProgress() {
  if (!state.assessment) return { filled: 0, total: 0, percent: 0 };
  let filled = 0;
  let total = 0;
  state.assessment.units.forEach((unit) => {
    unit.indicators.forEach((indicator) => {
      total += 1;
      if (state.scores[indicator.kode] !== null && state.scores[indicator.kode] !== undefined) filled += 1;
    });
  });
  return { filled, total, percent: total ? Math.round((filled / total) * 10000) / 100 : 0 };
}

function predicateFor(average) {
  if (average == null) return null;
  const thresholds = state.assessment?.thresholds || {};
  if (average >= (thresholds.predicate_sangat_mahir ?? 90)) return 'Sangat Mahir';
  if (average >= (thresholds.predicate_mahir ?? 80)) return 'Mahir';
  if (average >= (thresholds.predicate_cakap ?? 70)) return 'Cakap';
  return 'Tidak Memenuhi';
}

function computePreview() {
  const units = state.assessment.units.map((unit, index) => ({
    ...unit,
    ...computeUnitStats(unit),
    urutan: unit.urutan ?? index + 1,
  }));
  const byCode = Object.fromEntries(units.map((unit) => [unit.kode, unit]));
  const passed = units.filter((unit) => unit.passed);
  const subs = (state.assessment.sub_competencies || []).map((sub) => {
    const codes = sub.unit_kodes || [];
    const members = codes.map((code) => byCode[code]).filter(Boolean);
    const fulfilled = codes.length > 0 && members.length === codes.length && members.every((member) => member.passed);
    const average = members.length
      ? Math.round((members.reduce((sum, member) => sum + member.percent, 0) / members.length) * 100) / 100
      : 0;
    return { ...sub, fulfilled, average_percent: average };
  });
  subs.sort((a, b) => (b.average_percent - a.average_percent) || ((a.urutan || 0) - (b.urutan || 0)));
  const fulfilledSubs = subs.filter((sub) => sub.fulfilled);
  const allPassed = units.length > 0 && units.every((unit) => unit.passed);
  let outcome;
  let selectedSub = null;
  if (allPassed) outcome = 'kompeten_penuh';
  else if (fulfilledSubs.length) { outcome = 'kompeten_sub'; selectedSub = fulfilledSubs[0]; }
  else if (passed.length) outcome = 'kompeten_unit';
  else outcome = 'belum_kompeten';

  const average = passed.length
    ? Math.round((passed.reduce((sum, unit) => sum + unit.percent, 0) / passed.length) * 100) / 100
    : null;
  const predicate = predicateFor(average);
  const labels = {
    kompeten_penuh: 'Kompeten Penuh',
    kompeten_sub: 'Kompeten pada Sub Kompetensi',
    kompeten_unit: 'Kompeten pada Unit',
    belum_kompeten: 'Belum Kompeten',
  };
  const participant = state.assessment.assessment.participant;
  const schemeNama = state.assessment.scheme?.nama || 'Junior Network Technician';
  const peserta = `${participant.nama} (${participant.nomor})`;
  let statement;
  if (outcome === 'kompeten_penuh') {
    statement = `Peserta ${peserta} dinyatakan kompeten sebagai ${schemeNama} dengan predikat ${predicate}.`;
  } else if (outcome === 'kompeten_sub' && selectedSub) {
    statement = `Peserta ${peserta} dinyatakan kompeten pada sub kompetensi ${selectedSub.judul} dengan predikat ${predicate}.`;
  } else if (outcome === 'kompeten_unit') {
    statement = `Peserta ${peserta} dinyatakan kompeten pada unit ${passed.map((unit) => unit.kode).join(', ')} dengan predikat ${predicate}.`;
  } else {
    statement = `Peserta ${peserta} dinyatakan belum kompeten.`;
  }
  const emptyIndicators = units.flatMap((unit) => unit.empty);
  return {
    outcome,
    outcome_label: labels[outcome],
    predicate,
    average_percent: average,
    unit_passed: passed.map((unit) => unit.kode),
    unit_failed: units.filter((unit) => !unit.passed).map((unit) => unit.kode),
    unit_results: units,
    sub_competencies: subs,
    sub_fulfilled: fulfilledSubs,
    selected_sub: selectedSub,
    statement,
    empty_count: emptyIndicators.length,
    empty_indicators: emptyIndicators,
  };
}

function updateResultPanel() {
  const panel = document.querySelector('#result-panel');
  if (!panel || !state.assessment) return;
  const result = state.assessment.locked ? state.assessment.result : computePreview();
  const locked = state.assessment.locked;
  const selected = result.selected_sub ? `Sub: ${result.selected_sub.judul}` : '';
  panel.innerHTML = `
    <div class="panel-label">${locked ? 'Hasil final' : 'Hasil sementara'}</div>
    <div class="outcome">${esc(result.outcome_label)}</div>
    <div class="predicate-line">${result.predicate ? `Predikat <strong>${esc(result.predicate)}</strong>` : 'Predikat belum ada'}</div>
    <div class="avg-line">Rata-rata unit lulus: ${result.average_percent == null ? '—' : fmtPercent(result.average_percent)}</div>
    ${selected ? `<div class="avg-line">${esc(selected)}</div>` : ''}
    <div class="statement-box"><p data-statement-text>${esc(result.statement)}</p></div>
    <div class="copy-row"><button class="btn small" type="button" data-copy-statement>Salin pernyataan</button></div>
    <div class="empty-info">Indikator kosong: <strong>${result.empty_count}</strong>${result.empty_count ? ' (dihitung 0)' : ''}</div>
    ${locked ? `<div class="empty-info">Dikunci: ${fmtDateTime(state.assessment.assessment.locked_at)}</div>` : ''}
    <div class="result-actions">
      ${locked
        ? `<button class="btn wide" type="button" data-unlock>Buka kunci</button>`
        : `<button class="btn primary wide" type="button" data-lock>Kunci penilaian</button>`}
    </div>`;
}

function updateUnitDom(kode) {
  const unit = state.assessment.units.find((item) => item.kode === kode);
  if (!unit) return;
  const stats = computeUnitStats(unit);
  const card = document.querySelector(`[data-unit="${kode}"]`);
  if (!card) return;
  const threshold = state.assessment?.thresholds?.unit_pass_percent ?? 70;
  const metrics = card.querySelector('.unit-head-metrics');
  metrics.innerHTML = `
    <div class="progress"><div class="progress-bar ${stats.passed ? '' : 'fail'}" style="width:${stats.percent}%"></div><span class="progress-marker"></span></div>
    <span class="unit-percent">${stats.percent.toFixed(2)}%</span>
    <span class="badge ${stats.passed ? 'success' : 'danger'}">${stats.passed ? 'Lulus' : 'Belum'}</span>`;
  const summary = card.querySelector('.unit-summary');
  summary.innerHTML = `
    <span>Terisi <strong>${stats.filled}/${unit.indicators.length}</strong></span>
    <span>Kosong <strong>${stats.empty.length}</strong></span>
    <span>Skor <strong>${stats.total}</strong> / ${stats.max}</span>
    <span>Ambang lulus <strong>${threshold}%</strong></span>`;
}

function updateProgressHeader() {
  const progress = overallProgress();
  const bar = document.querySelector('#overall-progress-bar');
  const text = document.querySelector('#overall-progress-text');
  if (bar) bar.style.width = `${progress.percent}%`;
  if (text) text.textContent = `${progress.filled}/${progress.total} · ${progress.percent}%`;
}

function setScore(kode, value) {
  if (!state.assessment || state.assessment.locked) return;
  state.scores[kode] = value;
  const indicator = document.querySelector(`[data-indicator="${kode}"]`);
  if (indicator) {
    indicator.querySelectorAll('[data-score]').forEach((button) => {
      const active = Number(button.dataset.value) === value;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
  }
  const unit = state.assessment.units.find((item) => item.indicators.some((ind) => ind.kode === kode));
  if (unit) updateUnitDom(unit.kode);
  updateProgressHeader();
  updateResultPanel();
  const noteInput = document.querySelector(`[data-note="${kode}"]`);
  queueScore(kode, value, noteInput?.value || '');
}

function queueScore(kode, value, note) {
  if (!state.assessment || state.assessment.locked) return;
  const item = {
    key: `${state.assessment.assessment.id}:${kode}`,
    assessment_id: state.assessment.assessment.id,
    indicator_kode: kode,
    value,
    note: note || '',
    ts: new Date().toISOString(),
    status: 'pending',
  };
  state.pendingKeys.add(kode);
  state.failedKeys.delete(kode);
  updateSyncDot(kode);
  outboxPut(item).then(async () => {
    await refreshOutboxCount();
    updateSyncPill();
  });
  clearTimeout(state.flushTimer);
  state.flushTimer = setTimeout(() => flushOutbox(), 700);
}

function updateSyncDot(kode) {
  const dot = document.querySelector(`[data-sync="${kode}"]`);
  if (!dot) return;
  if (state.failedKeys.has(kode)) {
    dot.className = 'sync-dot failed';
    dot.title = 'Gagal sinkron';
  } else if (state.pendingKeys.has(kode)) {
    dot.className = 'sync-dot pending';
    dot.title = 'Menunggu sinkron';
  } else {
    dot.className = 'sync-dot synced';
    dot.title = 'Tersinkron';
  }
}

async function mergeOutbox(assessmentId) {
  state.pendingKeys = new Set();
  state.failedKeys = new Set();
  const items = (await outboxAll()).filter((item) => item.assessment_id === assessmentId);
  items.forEach((item) => {
    state.scores[item.indicator_kode] = item.value;
    if (item.status === 'failed') state.failedKeys.add(item.indicator_kode);
    else state.pendingKeys.add(item.indicator_kode);
  });
}

/* ------------------------------------------------------------------ */
/* Offline queue                                                      */
/* ------------------------------------------------------------------ */
async function refreshOutboxCount() {
  const items = await outboxAll();
  state.outboxCount = items.length;
}

function updateSyncPill() {
  const pill = document.querySelector('#sync-pill');
  const text = document.querySelector('#sync-text');
  if (!pill || !text) return;
  pill.classList.remove('pending', 'failed', 'offline');
  if (state.offline) {
    pill.classList.add('offline');
    text.textContent = 'Offline';
    return;
  }
  if (state.outboxCount > 0) {
    const hasFailed = state.failedKeys.size > 0;
    pill.classList.add(hasFailed ? 'failed' : 'pending');
    if (hasFailed) {
      text.textContent = `${state.failedKeys.size} gagal, ${state.outboxCount - state.failedKeys.size} pending`;
    } else {
      text.textContent = `${state.outboxCount} belum sinkron`;
    }
  } else {
    text.textContent = 'Tersinkron';
  }
}

async function flushOutbox(manual = false) {
  if (state.flushing) return;
  if (!navigator.onLine) {
    setOffline(true);
    if (manual) toast('Masih offline. Perubahan tersimpan di perangkat.', '');
    return;
  }
  const items = await outboxAll();
  await refreshOutboxCount();
  if (!items.length) {
    updateSyncPill();
    if (manual) toast('Semua perubahan sudah tersinkron.', 'success');
    return;
  }
  state.flushing = true;
  updateSyncPill();
  const groups = {};
  items.forEach((item) => {
    if (!groups[item.assessment_id]) groups[item.assessment_id] = [];
    groups[item.assessment_id].push(item);
  });

  let failedTotal = 0;
  for (const [assessmentId, group] of Object.entries(groups)) {
    try {
      const payload = group.map((item) => ({
        assessment_id: Number(assessmentId),
        indicator_kode: item.indicator_kode,
        value: item.value,
        note: item.note,
        client_ts: item.ts,
      }));
      const result = await api('/sync/scores', { method: 'POST', body: { items: payload } });
      const failedCodes = new Set((result.failed || []).map((item) => item.indicator_kode));
      const deleteKeys = [];
      group.forEach((item) => {
        if (failedCodes.has(item.indicator_kode)) {
          failedTotal += 1;
          state.failedKeys.add(item.indicator_kode);
          outboxPut({ ...item, status: 'failed' });
        } else {
          deleteKeys.push(item.key);
          state.pendingKeys.delete(item.indicator_kode);
          state.failedKeys.delete(item.indicator_kode);
        }
        updateSyncDot(item.indicator_kode);
      });
      await outboxDelete(deleteKeys);
    } catch (error) {
      failedTotal += group.length;
      group.forEach((item) => {
        state.failedKeys.add(item.indicator_kode);
        updateSyncDot(item.indicator_kode);
      });
      if (manual) toast(error.message, 'error');
    }
  }
  state.flushing = false;
  await refreshOutboxCount();
  updateSyncPill();
  if (manual) {
    if (failedTotal) toast(`${failedTotal} perubahan belum tersinkron.`, 'error');
    else toast('Perubahan tersinkron.', 'success');
  }
}

function setOffline(offline) {
  state.offline = offline;
  document.querySelector('#offline-banner').classList.toggle('hidden', !offline);
  updateSyncPill();
}

/* ------------------------------------------------------------------ */
/* Lock / unlock                                                      */
/* ------------------------------------------------------------------ */
function openLockModal() {
  const preview = computePreview();
  const empty = preview.empty_indicators;
  openModal({
    title: 'Kunci penilaian',
    body: `
      ${empty.length ? `
        <div class="warning-box">
          <strong>${empty.length} indikator masih kosong.</strong>
          <p style="margin-top:4px">Indikator kosong dihitung 0. Centang konfirmasi untuk tetap mengunci.</p>
          <p class="mono" style="margin-top:8px">${esc(empty.slice(0, 8).join(', '))}${empty.length > 8 ? ' …' : ''}</p>
        </div>
        <label class="checkbox-row" style="margin-top:12px">
          <input type="checkbox" id="confirm-empty">
          <span>Saya mengonfirmasi indikator kosong dihitung 0 dan hasil dikunci.</span>
        </label>` : `
        <p>Semua indikator sudah terisi. Setelah dikunci, skor tidak dapat diubah sampai dibuka kembali.</p>`}
      <p class="hint" style="margin-top:12px">Perubahan yang belum tersinkron akan dicoba dikirim sebelum kunci.</p>`,
    actions: [
      { label: 'Batal', className: 'ghost' },
      {
        label: 'Kunci',
        className: 'primary',
        onClick: async ({ close, button }) => {
          const confirmBox = document.querySelector('#confirm-empty');
          if (empty.length && !confirmBox?.checked) {
            toast('Centang konfirmasi indikator kosong terlebih dahulu.', 'error');
            return;
          }
          button.disabled = true;
          try {
            await flushOutbox();
            const result = await api(`/assessments/${state.assessment.assessment.id}/lock`, {
              method: 'POST',
              body: { confirm_empty: Boolean(empty.length) },
            });
            close();
            toast(`Dinilai: ${result.result.outcome_label}.`, 'success');
            await renderAssessment(state.assessment.assessment.id);
            await refreshInstrumentVersion();
          } catch (error) {
            toast(error.message, 'error');
            button.disabled = false;
          }
        },
      },
    ],
  });
}

function openUnlockModal() {
  openModal({
    title: 'Buka kunci penilaian',
    body: `
      <p class="muted">Buka kunci hanya untuk perbaikan. Alasan wajib diisi minimal 10 karakter dan dicatat di audit log.</p>
      <div class="field" style="margin-top:14px">
        <label for="unlock-reason">Alasan</label>
        <textarea id="unlock-reason" maxlength="300" placeholder="Contoh: salah input unit 5"></textarea>
        <div class="char-count" style="display:flex;align-items:center;gap:8px;margin-top:6px">
          <span id="unlock-len" style="font-variant-numeric:tabular-nums">0</span>/10
        </div>
        <div class="hint"><span id="reason-count">0</span>/300</div>
      </div>`,
    actions: [
      { label: 'Batal', className: 'ghost' },
      {
        label: 'Buka kunci',
        className: 'danger',
        onClick: async ({ close, button }) => {
          const reason = document.querySelector('#unlock-reason').value.trim();
          if (reason.length < 10) {
            toast('Alasan minimal 10 karakter.', 'error');
            return;
          }
          button.disabled = true;
          try {
            await api(`/assessments/${state.assessment.assessment.id}/unlock`, {
              method: 'POST',
              body: { reason },
            });
            close();
            toast('Penilaian dibuka kembali.', 'success');
            await renderAssessment(state.assessment.assessment.id);
          } catch (error) {
            toast(error.message, 'error');
            button.disabled = false;
          }
        },
      },
    ],
  });
}

/* ------------------------------------------------------------------ */
/* Results                                                            */
/* ------------------------------------------------------------------ */
async function renderResults(schoolId) {
  setPage('Hasil', 'Rekap Sekolah');
  const [school, results] = await Promise.all([
    api(`/schools/${schoolId}`),
    api(`/schools/${schoolId}/results`),
  ]);
  const rows = results.data;
  const schemeObj = state.schemes.find((s) => s.kode === school.scheme_kode);
  const totalUnits = schemeObj ? schemeObj.units_count : 13;

  document.querySelector('#view').innerHTML = `
    <div class="page-head">
      <div>
        <a class="muted" href="#/schools/${school.id}">&larr; ${esc(school.nama)}</a>
        <h2>Hasil &amp; ekspor</h2>
        <p class="sub muted">${schemeBadge(school.scheme_kode)} · Rekap per peserta. Ekspor CSV UTF-8 atau XLSX.</p>
      </div>
      <div class="head-actions">
        <a class="btn" href="/api/schools/${school.id}/export?format=csv" download>Unduh CSV</a>
        <a class="btn primary" href="/api/schools/${school.id}/export?format=xlsx" download>Unduh XLSX</a>
      </div>
    </div>
    <div class="card">
      <div class="card-head">
        <div><div class="card-title">Rekap peserta</div><div class="card-sub">${rows.length} peserta · dibuat ${fmtDateTime(results.generated_at)}</div></div>
        <div class="filters">
          <label class="muted" for="result-filter">Status</label>
          <select id="result-filter" class="select-sm">
            <option value="all">Semua</option>
            <option value="locked">Terkunci</option>
            <option value="in_progress">Sedang dinilai</option>
          </select>
        </div>
      </div>
      ${rows.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Nomor</th><th>Nama</th><th>Kelas</th><th>Status</th><th>Unit lulus</th><th>Predikat</th><th>Hasil</th><th>Pernyataan</th><th>Dikunci</th><th></th></tr></thead>
          <tbody>
            ${rows.map((row) => {
              const result = row.result || {};
              const unitTotal = result.unit_results ? result.unit_results.length : totalUnits;
              return `<tr>
                <td class="tabular">${esc(row.participant.nomor)}</td>
                <td><div class="row-title">${esc(row.participant.nama)}</div></td>
                <td>${esc(row.participant.kelas || '—')}</td>
                <td>${statusBadge(row.status)}</td>
                <td class="tabular">${result.unit_passed ? result.unit_passed.length : 0}/${unitTotal}</td>
                <td>${esc(result.predicate || '—')}</td>
                <td>${outcomeBadge(row.result)}</td>
                <td><div class="row-sub" style="max-width:360px">${esc(result.statement || '—')}</div></td>
                <td class="nowrap">${fmtDateTime(row.locked_at)}</td>
                <td class="actions">${row.assessment_id ? `<a class="btn small ghost" href="#/assessment/${row.assessment_id}">Buka</a>` : ''}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>` : `<div class="empty-state"><strong>Belum ada hasil</strong><p>Mulai penilaian peserta terlebih dahulu.</p></div>`}
    </div>`;
  document.querySelector('#result-filter').value = 'all';
  document.querySelector('#result-filter').addEventListener('change', async (event) => {
    const filter = event.target.value;
    try {
      const filtered = await api(`/schools/${schoolId}/results?status=${encodeURIComponent(filter)}`);
      renderResultsTable(filtered.data, totalUnits);
    } catch (error) {
      toast(error.message, 'error');
    }
  });
}

function renderResultsTable(rows, totalUnits = 13) {
  const table = document.querySelector('.card .table-wrap');
  if (!table) return;
  if (!rows.length) {
    table.outerHTML = `<div class="empty-state"><strong>Tidak ada data</strong><p>Tidak ada peserta dengan status ini.</p></div>`;
    return;
  }
  const body = rows.map((row) => {
    const result = row.result || {};
    const unitTotal = result.unit_results ? result.unit_results.length : totalUnits;
    return `<tr>
      <td class="tabular">${esc(row.participant.nomor)}</td>
      <td><div class="row-title">${esc(row.participant.nama)}</div></td>
      <td>${esc(row.participant.kelas || '—')}</td>
      <td>${statusBadge(row.status)}</td>
      <td class="tabular">${result.unit_passed ? result.unit_passed.length : 0}/${unitTotal}</td>
      <td>${esc(result.predicate || '—')}</td>
      <td>${outcomeBadge(row.result)}</td>
      <td><div class="row-sub" style="max-width:360px">${esc(result.statement || '—')}</div></td>
      <td class="nowrap">${fmtDateTime(row.locked_at)}</td>
      <td class="actions">${row.assessment_id ? `<a class="btn small ghost" href="#/assessment/${row.assessment_id}">Buka</a>` : ''}</td>
    </tr>`;
  }).join('');
  table.querySelector('tbody').innerHTML = body;
}

/* ------------------------------------------------------------------ */
/* Config (`#/config` — Scheme-Aware Instrument Editor)               */
/* ------------------------------------------------------------------ */
async function renderConfig() {
  setPage('Instrumen & Unit', 'Konfigurasi Skema');
  if (state.activeScheme !== 'ALL') {
    state.configScheme = state.activeScheme;
  }
  const schemeKode = state.configScheme || 'JNT-SMK';
  const [instrument, units, subs] = await Promise.all([
    api(`/config/instrument?scheme_kode=${encodeURIComponent(schemeKode)}`),
    api(`/config/units?scheme_kode=${encodeURIComponent(schemeKode)}`),
    api(`/config/sub-competencies?scheme_kode=${encodeURIComponent(schemeKode)}`),
  ]);
  state.instrument = instrument;
  state.configUnits = units.data;
  document.querySelector('#instrument-version').textContent = `v${instrument.version}`;

  const schemeOptions = state.schemes
    .map((s) => `<option value="${esc(s.kode)}" ${s.kode === schemeKode ? 'selected' : ''}>${esc(s.kode)} — ${esc(s.nama)}</option>`)
    .join('');

  const proposed = instrument.proposed_indicators || [];
  document.querySelector('#view').innerHTML = `
    <div class="page-head">
      <div>
        <h2>Instrumen penilaian</h2>
        <p class="sub muted">Skema <strong>${esc(schemeKode)}</strong> · Versi ${esc(instrument.version)} · ${instrument.units_count} unit · ${instrument.indicators_count} indikator · ${instrument.sub_competencies_count} sub kompetensi</p>
      </div>
      <div class="head-actions">
        <select id="config-scheme-select" class="select-sm" aria-label="Pilih skema instrumen">${schemeOptions}</select>
        <button class="btn" id="add-unit" type="button">Tambah unit</button>
        <button class="btn primary" id="add-sub" type="button">Tambah sub kompetensi</button>
      </div>
    </div>
    <div class="card card-body" style="margin-bottom:16px">
      <div class="toolbar">
        ${schemeBadge(schemeKode)}
        <span class="badge primary">Versi ${esc(instrument.version)}</span>
        <span class="badge ${instrument.proposed_count ? 'warning' : 'success'}">${instrument.proposed_count} teks usulan</span>
        <span class="muted">Diperbarui ${fmtDateTime(instrument.updated_at)}</span>
      </div>
      <p class="hint" style="margin-top:10px">${esc(instrument.note)}</p>
      ${proposed.length ? `<div class="divider"></div><div class="card-sub" style="margin-bottom:6px">Indikator usulan</div><ul class="instruction-list">${proposed.map((item) => `<li><span class="mono">${esc(item.kode)}</span> — ${esc(item.teks)}</li>`).join('')}</ul>` : ''}
    </div>
    <div class="card">
      <div class="card-head"><div><div class="card-title">Unit &amp; indikator (${esc(schemeKode)})</div><div class="card-sub">Perubahan struktur menaikkan versi instrumen. Assessment lama memakai snapshot versi saat dimulai.</div></div></div>
      <div class="card-body config-block">
        ${units.data.length ? units.data.map((unit) => configUnitHtml(unit)).join('') : '<div class="empty-state"><strong>Belum ada unit pada skema ini</strong><p>Tambahkan unit pertama untuk mulai menyusun indikator penilaian.</p></div>'}
      </div>
    </div>
    <div class="card">
      <div class="card-head"><div><div class="card-title">Sub kompetensi (${esc(schemeKode)})</div><div class="card-sub">Satu unit boleh menjadi penyusun lebih dari satu sub kompetensi.</div></div></div>
      <div class="card-body">
        ${subs.data.length ? subs.data.map((sub) => configSubHtml(sub)).join('') : '<div class="empty-state"><strong>Belum ada sub kompetensi</strong><p>Tambahkan klaster / sub kompetensi untuk skema ini.</p></div>'}
      </div>
    </div>`;

  document.querySelector('#config-scheme-select')?.addEventListener('change', async (e) => {
    state.configScheme = e.target.value;
    localStorage.setItem('ukk-config-scheme', state.configScheme);
    await renderConfig();
  });
  document.querySelector('#add-unit').addEventListener('click', () => openUnitModal());
  document.querySelector('#add-sub').addEventListener('click', () => openSubModal());
  bindConfigEvents();
}

function configUnitHtml(unit) {
  return `
    <div class="config-unit" data-config-unit="${esc(unit.kode)}">
      <div class="config-unit-head">
        <div>
          <span class="unit-code">${esc(unit.kode)}</span>
          <div class="unit-title">${esc(unit.judul)}</div>
        </div>
        <div class="config-unit-meta">
          <span class="badge ${unit.aktif ? 'success' : ''}">${unit.aktif ? 'Aktif' : 'Nonaktif'}</span>
          <span class="badge plain">${unit.indicator_count} indikator</span>
          <button class="btn small" type="button" data-edit-unit="${esc(unit.kode)}">Edit</button>
          <button class="btn small ghost" type="button" data-add-indicator="${esc(unit.kode)}">Tambah indikator</button>
          <button class="btn small danger" type="button" data-delete-unit="${esc(unit.kode)}">Hapus</button>
        </div>
      </div>
      <div class="config-indicators">
        ${unit.indicators.length ? unit.indicators.map((indicator) => `
          <div class="config-indicator">
            <span class="kode">${esc(indicator.kode)}</span>
            <div class="txt">${esc(indicator.teks)}${indicator.is_proposed ? '<span class="proposed-badge">Usulan — verifikasi</span>' : ''}</div>
            <div class="toolbar">
              <button class="btn small" type="button" data-edit-indicator="${esc(indicator.kode)}">Edit</button>
              <button class="btn small danger" type="button" data-delete-indicator="${esc(indicator.kode)}">Hapus</button>
            </div>
          </div>`).join('') : '<div class="empty-state" style="padding:18px"><p>Belum ada indikator.</p></div>'}
      </div>
    </div>`;
}

function configSubHtml(sub) {
  return `
    <div class="sub-card">
      <div class="sub-card-head">
        <div class="grow">
          <span class="unit-code">${esc(sub.kode)}</span>
          <div class="unit-title">${esc(sub.judul)}</div>
          <div class="chips">${(sub.unit_kodes || []).map((code) => `<span class="chip">${esc(code)}</span>`).join('')}</div>
        </div>
        <div class="toolbar">
          <button class="btn small" type="button" data-edit-sub="${esc(sub.kode)}">Edit</button>
          <button class="btn small danger" type="button" data-delete-sub="${esc(sub.kode)}">Hapus</button>
        </div>
      </div>
    </div>`;
}

function bindConfigEvents() {
  const view = document.querySelector('#view');
  view.querySelectorAll('[data-edit-unit]').forEach((button) => button.addEventListener('click', () => {
    const unit = state.configUnits.find((item) => item.kode === button.dataset.editUnit);
    if (unit) openUnitModal(unit);
  }));
  view.querySelectorAll('[data-delete-unit]').forEach((button) => button.addEventListener('click', () => {
    confirmDelete('Hapus unit?', `Unit ${button.dataset.deleteUnit} akan dihapus dari instrumen aktif.`, async () => {
      await api(`/config/units/${encodeURIComponent(button.dataset.deleteUnit)}`, { method: 'DELETE' });
      toast('Unit dihapus.', 'success');
      await renderConfig();
      await refreshInstrumentVersion();
    });
  }));
  view.querySelectorAll('[data-add-indicator]').forEach((button) => button.addEventListener('click', () => openIndicatorModal(button.dataset.addIndicator)));
  view.querySelectorAll('[data-edit-indicator]').forEach((button) => button.addEventListener('click', () => {
    for (const unit of state.configUnits) {
      const indicator = unit.indicators.find((item) => item.kode === button.dataset.editIndicator);
      if (indicator) { openIndicatorModal(unit.kode, indicator); return; }
    }
  }));
  view.querySelectorAll('[data-delete-indicator]').forEach((button) => button.addEventListener('click', () => {
    confirmDelete('Hapus indikator?', `Indikator ${button.dataset.deleteIndicator} akan dihapus.`, async () => {
      await api(`/config/indicators/${encodeURIComponent(button.dataset.deleteIndicator)}`, { method: 'DELETE' });
      toast('Indikator dihapus.', 'success');
      await renderConfig();
      await refreshInstrumentVersion();
    });
  }));
  view.querySelectorAll('[data-edit-sub]').forEach((button) => button.addEventListener('click', async () => {
    const subs = await api(`/config/sub-competencies?scheme_kode=${encodeURIComponent(state.configScheme || 'JNT-SMK')}`);
    const sub = subs.data.find((item) => item.kode === button.dataset.editSub);
    if (sub) openSubModal(sub);
  }));
  view.querySelectorAll('[data-delete-sub]').forEach((button) => button.addEventListener('click', () => {
    confirmDelete('Hapus sub kompetensi?', `Sub kompetensi ${button.dataset.deleteSub} akan dihapus.`, async () => {
      await api(`/config/sub-competencies/${encodeURIComponent(button.dataset.deleteSub)}`, { method: 'DELETE' });
      toast('Sub kompetensi dihapus.', 'success');
      await renderConfig();
      await refreshInstrumentVersion();
    });
  }));
}

function confirmDelete(title, message, action) {
  openModal({
    title,
    body: `<p>${esc(message)}</p><p class="hint" style="margin-top:8px">Tindakan ini tidak dapat dibatalkan.</p>`,
    actions: [
      { label: 'Batal', className: 'ghost' },
      {
        label: 'Hapus',
        className: 'danger',
        onClick: async ({ close, button }) => {
          button.disabled = true;
          try {
            await action();
            close();
          } catch (error) {
            toast(error.message, 'error');
            button.disabled = false;
          }
        },
      },
    ],
  });
}

function openUnitModal(unit = null) {
  const editing = Boolean(unit);
  const schemeKode = unit?.scheme_kode || state.configScheme || 'JNT-SMK';
  openModal({
    title: editing ? 'Edit unit' : `Tambah unit (${schemeKode})`,
    body: `
      <form id="unit-form">
        <div class="field"><label for="unit-kode">Kode unit</label><input id="unit-kode" name="kode" required value="${esc(unit?.kode || '')}" ${editing ? 'disabled' : ''} placeholder="J.611000.xxx.01 / .02"></div>
        <div class="field"><label for="unit-judul">Judul</label><input id="unit-judul" name="judul" required value="${esc(unit?.judul || '')}"></div>
        <div class="form-grid">
          <div class="field"><label for="unit-urutan">Urutan</label><input id="unit-urutan" name="urutan" type="number" min="1" value="${esc(unit?.urutan || '')}"></div>
          <div class="field" style="justify-content:flex-end"><label class="checkbox-row" style="border:0;padding:0;background:transparent"><input type="checkbox" name="aktif" ${unit?.aktif !== 0 ? 'checked' : ''}> Aktif</label></div>
        </div>
        <p id="unit-error" class="error-text" role="alert"></p>
      </form>`,
    actions: [
      { label: 'Batal', className: 'ghost' },
      {
        label: editing ? 'Simpan' : 'Tambah',
        className: 'primary',
        onClick: async ({ close, button }) => {
          const form = document.querySelector('#unit-form');
          const errorEl = document.querySelector('#unit-error');
          button.disabled = true;
          errorEl.textContent = '';
          const payload = {
            judul: form.judul.value.trim(),
            urutan: form.urutan.value ? Number(form.urutan.value) : null,
            aktif: form.aktif.checked,
            scheme_kode: schemeKode,
          };
          try {
            if (editing) {
              await api(`/config/units/${encodeURIComponent(unit.kode)}`, { method: 'PATCH', body: payload });
            } else {
              await api('/config/units', { method: 'POST', body: { ...payload, kode: form.kode.value.trim() } });
            }
            close();
            toast(editing ? 'Unit diperbarui.' : 'Unit ditambahkan.', 'success');
            await renderConfig();
            await refreshInstrumentVersion();
          } catch (error) {
            errorEl.textContent = error.message;
            button.disabled = false;
          }
        },
      },
    ],
  });
}

function openIndicatorModal(unitKode, indicator = null) {
  const editing = Boolean(indicator);
  openModal({
    title: editing ? 'Edit indikator' : 'Tambah indikator',
    body: `
      <form id="indicator-form">
        <div class="field"><label for="indicator-kode">Kode indikator</label><input id="indicator-kode" name="kode" value="${esc(indicator?.kode || '')}" ${editing ? 'disabled' : ''} placeholder="Otomatis IND-0xx"></div>
        <div class="field"><label for="indicator-teks">Teks indikator</label><textarea id="indicator-teks" name="teks" required>${esc(indicator?.teks || '')}</textarea></div>
        <div class="form-grid">
          <div class="field"><label for="indicator-urutan">Urutan</label><input id="indicator-urutan" name="urutan" type="number" min="1" value="${esc(indicator?.urutan || '')}"></div>
          <div class="field" style="justify-content:flex-end">
            <label class="checkbox-row" style="border:0;padding:0;background:transparent"><input type="checkbox" name="aktif" ${indicator?.aktif !== 0 ? 'checked' : ''}> Aktif</label>
            ${editing ? '' : `<label class="checkbox-row" style="border:0;padding:0;background:transparent;margin-top:6px"><input type="checkbox" name="usulan"> Teks usulan (perlu verifikasi)</label>`}
          </div>
        </div>
        <p id="indicator-error" class="error-text" role="alert"></p>
      </form>`,
    actions: [
      { label: 'Batal', className: 'ghost' },
      {
        label: editing ? 'Simpan' : 'Tambah',
        className: 'primary',
        onClick: async ({ close, button }) => {
          const form = document.querySelector('#indicator-form');
          const errorEl = document.querySelector('#indicator-error');
          button.disabled = true;
          errorEl.textContent = '';
          const payload = {
            teks: form.teks.value.trim(),
            urutan: form.urutan.value ? Number(form.urutan.value) : null,
            aktif: form.aktif.checked,
          };
          try {
            if (editing) {
              await api(`/config/indicators/${encodeURIComponent(indicator.kode)}`, { method: 'PATCH', body: payload });
            } else {
              if (form.usulan.checked) payload.is_proposed = true;
              if (form.kode.value.trim()) payload.kode = form.kode.value.trim();
              await api(`/config/units/${encodeURIComponent(unitKode)}/indicators`, { method: 'POST', body: payload });
            }
            close();
            toast(editing ? 'Indikator diperbarui.' : 'Indikator ditambahkan.', 'success');
            await renderConfig();
            await refreshInstrumentVersion();
          } catch (error) {
            errorEl.textContent = error.message;
            button.disabled = false;
          }
        },
      },
    ],
  });
}

async function openSubModal(sub = null) {
  const editing = Boolean(sub);
  const schemeKode = sub?.scheme_kode || state.configScheme || 'JNT-SMK';
  if (!state.configUnits.length) {
    state.configUnits = (await api(`/config/units?scheme_kode=${encodeURIComponent(schemeKode)}`)).data;
  }
  const selected = new Set(sub?.unit_kodes || []);
  openModal({
    title: editing ? 'Edit sub kompetensi' : `Tambah sub kompetensi (${schemeKode})`,
    body: `
      <form id="sub-form">
        <div class="form-grid">
          <div class="field"><label for="sub-kode">Kode</label><input id="sub-kode" name="kode" required value="${esc(sub?.kode || '')}" ${editing ? 'disabled' : ''} placeholder="SK-06"></div>
          <div class="field"><label for="sub-urutan">Urutan</label><input id="sub-urutan" name="urutan" type="number" min="1" required value="${esc(sub?.urutan || '')}"></div>
        </div>
        <div class="field"><label for="sub-judul">Judul sub kompetensi</label><input id="sub-judul" name="judul" required value="${esc(sub?.judul || '')}"></div>
        <div class="field"><label>Unit penyusun</label><div class="card" style="padding:8px;max-height:260px;overflow:auto">
          ${state.configUnits.map((unit) => `<label class="checkbox-row" style="border:0;background:transparent;padding:7px 8px"><input type="checkbox" name="unit" value="${esc(unit.kode)}" ${selected.has(unit.kode) ? 'checked' : ''}><span><span class="mono">${esc(unit.kode)}</span> ${esc(unit.judul)}</span></label>`).join('')}
        </div></div>
        <p id="sub-error" class="error-text" role="alert"></p>
      </form>`,
    actions: [
      { label: 'Batal', className: 'ghost' },
      {
        label: editing ? 'Simpan' : 'Tambah',
        className: 'primary',
        onClick: async ({ close, button }) => {
          const form = document.querySelector('#sub-form');
          const errorEl = document.querySelector('#sub-error');
          const unitKodes = [...form.querySelectorAll('input[name="unit"]:checked')].map((item) => item.value);
          button.disabled = true;
          errorEl.textContent = '';
          const payload = {
            judul: form.judul.value.trim(),
            urutan: form.urutan.value ? Number(form.urutan.value) : null,
            unit_kodes: unitKodes,
            scheme_kode: schemeKode,
          };
          try {
            if (editing) {
              await api(`/config/sub-competencies/${encodeURIComponent(sub.kode)}`, { method: 'PATCH', body: payload });
            } else {
              await api('/config/sub-competencies', {
                method: 'POST',
                body: { ...payload, kode: form.kode.value.trim(), urutan: Number(form.urutan.value) },
              });
            }
            close();
            toast(editing ? 'Sub kompetensi diperbarui.' : 'Sub kompetensi ditambahkan.', 'success');
            await renderConfig();
            await refreshInstrumentVersion();
          } catch (error) {
            errorEl.textContent = error.message;
            button.disabled = false;
          }
        },
      },
    ],
  });
}

/* ------------------------------------------------------------------ */
/* Sync & backup                                                      */
/* ------------------------------------------------------------------ */
async function renderSync() {
  setPage('Sinkron & Backup', 'Operasional');
  const [status, backups] = await Promise.all([
    api('/sync/status'),
    api('/admin/backups'),
  ]);
  const sheetsInfo = status.sheets || {};
  document.querySelector('#view').innerHTML = `
    <div class="page-head">
      <div>
        <h2>Sinkron &amp; backup</h2>
        <p class="sub muted">Antrean offline, Google Sheets satu arah, dan backup SQLite terproteksi (0600).</p>
      </div>
      <div class="head-actions">
        <button class="btn" id="flush-now" type="button">Sinkron perubahan</button>
        <button class="btn" id="refresh-sync" type="button">Muat ulang status</button>
      </div>
    </div>
    <div class="sync-grid">
      <div class="card">
        <div class="card-head"><div><div class="card-title">Google Sheets</div><div class="card-sub">Satu arah, tab per sekolah.</div></div><span class="badge ${sheetsInfo.status === 'enabled' ? 'success' : 'warning'}">${esc(sheetsInfo.status || 'disabled')}</span></div>
        <div class="card-body">
          ${sheetsInfo.enabled
            ? '<p class="hint">Kredensial terdeteksi. Sinkron manual akan menulis hasil per sekolah ke tab masing-masing.</p>'
            : `<div class="warning-box"><strong>Sheets nonaktif.</strong><p style="margin-top:4px">${esc(sheetsInfo.reason || 'Set GOOGLE_SERVICE_ACCOUNT_JSON dan GOOGLE_SHEETS_ID untuk mengaktifkan.')}</p></div>`}
          <div class="detail-list" style="margin-top:14px">
            <dt>Terakhir sync skor</dt><dd>${fmtDateTime(status.last_scores_sync)}</dd>
            <dt>Terakhir sync Sheets</dt><dd>${fmtDateTime(status.last_sheets_sync)}</dd>
            <dt>Skor pending</dt><dd>${fmtNumber(status.pending_scores)}</dd>
            <dt>Outbox Sheets</dt><dd>${fmtNumber(status.pending_sheets)}</dd>
          </div>
          <div class="copy-row">
            <button class="btn ${sheetsInfo.enabled ? 'primary' : ''}" id="sync-sheets" type="button" ${sheetsInfo.enabled ? '' : 'disabled'}>Sinkron sekarang</button>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-head"><div><div class="card-title">Backup</div><div class="card-sub">SQLite backup API, retensi 30 hari.</div></div><span class="badge">${backups.backups.length} file</span></div>
        <div class="card-body">
          <p class="hint">BACKUP_DIR: ${status.backup_dir_configured ? 'diset via env' : 'default ./backups'}</p>
          <div class="copy-row"><button class="btn primary" id="backup-now" type="button">Backup sekarang</button></div>
          <div class="divider"></div>
          ${backups.backups.length ? `<div class="table-wrap"><table><thead><tr><th>File</th><th>Ukuran</th><th>Dibuat</th></tr></thead><tbody>
            ${backups.backups.map((item) => `<tr><td><span class="mono">${esc(item.filename)}</span></td><td class="tabular">${fmtNumber(item.size_bytes)} B</td><td>${fmtDateTime(item.created_at)}</td></tr>`).join('')}
          </tbody></table></div>` : '<p class="muted">Belum ada backup.</p>'}
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><div><div class="card-title">Antrean gagal</div><div class="card-sub">Item yang perlu diperiksa ulang.</div></div></div>
      <div class="card-body">
        ${status.failed_items.length ? `<div class="table-wrap"><table><thead><tr><th>Key</th><th>Tipe</th><th>Retry</th><th>Error</th><th>Waktu</th></tr></thead><tbody>
          ${status.failed_items.map((item) => `<tr><td><span class="mono">${esc(item.idempotency_key)}</span></td><td><span class="badge">${esc(item.payload_type)}</span></td><td class="tabular">${fmtNumber(item.retry_count)}</td><td>${esc(item.last_error || '—')}</td><td>${fmtDateTime(item.created_at)}</td></tr>`).join('')}
        </tbody></table></div>` : '<p class="muted">Tidak ada item gagal.</p>'}
      </div>
    </div>`;
  document.querySelector('#flush-now').addEventListener('click', () => flushOutbox(true));
  document.querySelector('#refresh-sync').addEventListener('click', () => renderSync());
  document.querySelector('#sync-sheets').addEventListener('click', async () => {
    try {
      const result = await api('/sync/sheets', { method: 'POST', body: {} });
      if (result.status === 'disabled') toast(result.message || 'Sheets nonaktif.', '');
      else toast(`Sheets tersinkron: ${result.synced_schools} sekolah.`, 'success');
      await renderSync();
    } catch (error) {
      toast(error.message, 'error');
    }
  });
  document.querySelector('#backup-now').addEventListener('click', async () => {
    try {
      const result = await api('/admin/backup', { method: 'POST', body: {} });
      toast(`Backup dibuat: ${result.filename}`, 'success');
      await renderSync();
    } catch (error) {
      toast(error.message, 'error');
    }
  });
}

/* ------------------------------------------------------------------ */
/* Service worker & init                                              */
/* ------------------------------------------------------------------ */
function registerServiceWorker() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      /* dev tanpa HTTPS tetap berjalan tanpa cache */
    });
  }
}

async function init() {
  initTheme();
  bindShell();
  registerServiceWorker();
  setOffline(!navigator.onLine);
  window.addEventListener('hashchange', route);
  window.addEventListener('offline', () => setOffline(true));
  window.addEventListener('online', () => {
    setOffline(false);
    flushOutbox();
  });
  setInterval(() => {
    if (navigator.onLine) flushOutbox();
  }, 15000);
  try {
    await bootAuth();
    await refreshOutboxCount();
    updateSyncPill();
  } catch (error) {
    showAuth();
    renderLogin(error.message);
  }
}

init();
