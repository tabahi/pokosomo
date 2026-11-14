// Shared helpers: API calls, icons, dialogs, menus, toasts, safe markdown.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function h(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

// ------------------------------------------------------------------ API
export async function api(path, { method = 'GET', body, form, signal } = {}) {
  const opts = { method, headers: {}, signal };
  if (body !== undefined) {
    opts.headers['content-type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (form) opts.body = form;
  const res = await fetch(path, opts);
  if (res.status === 401) {
    location.href = '/login';
    throw new Error('Signed out');
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const d = data?.detail;
    const msg = typeof d === 'string' ? d : d?.message || res.statusText || 'Request failed';
    const err = new Error(msg);
    err.status = res.status;
    err.data = d;
    throw err;
  }
  return data;
}

export const P = name => `/api/projects/${encodeURIComponent(name)}`;
export const rawUrl = (project, path, download = false) =>
  `${P(project)}/raw?path=${encodeURIComponent(path)}${download ? '&download=1' : ''}&t=${Date.now()}`;

// ------------------------------------------------------------------ icons (lucide)
const ICON_ALIASES = { more: 'Ellipsis', spinner: 'LoaderCircle', alert: 'CircleAlert' };
export function icon(name, cls = '') {
  const key = ICON_ALIASES[name] || name;
  const node = window.lucide?.icons?.[key];
  if (!node) return '';
  const inner = node.map(([tag, attrs]) =>
    `<${tag} ${Object.entries(attrs).map(([k, v]) => `${k}="${esc(v)}"`).join(' ')}/>`).join('');
  return `<svg class="icon ${cls}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
}

// ------------------------------------------------------------------ file types
const EXT_TYPES = {
  note: ['md', 'markdown', 'txt'],
  pdf: ['pdf'],
  word: ['docx', 'doc', 'odt', 'rtf'],
  slides: ['pptx', 'ppt', 'odp'],
  table: ['csv', 'tsv', 'xlsx', 'xls', 'ods'],
  image: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'tif', 'tiff'],
  tex: ['tex', 'bib', 'cls', 'sty'],
  code: ['py', 'r', 'ipynb', 'js', 'json', 'yaml', 'yml', 'sh', 'html', 'css', 'xml', 'toml', 'log', 'ini', 'cfg', 'fasta', 'fa', 'fastq', 'gb', 'gbk', 'nwk', 'tre'],
};
export function fileType(name) {
  const ext = (name.split('.').pop() || '').toLowerCase();
  if (!name.includes('.')) return 'other';
  for (const [t, exts] of Object.entries(EXT_TYPES)) if (exts.includes(ext)) return t;
  return 'other';
}
export const ext = name => (name.includes('.') ? name.split('.').pop().toLowerCase() : '');

const TYPE_ICON = {
  note: ['NotebookPen', 'c-note'], pdf: ['FileText', 'c-pdf'], word: ['FileText', 'c-word'],
  slides: ['Presentation', 'c-slides'], table: ['Sheet', 'c-table'], image: ['Image', 'c-image'],
  tex: ['Sigma', 'c-tex'], code: ['FileCode', 'c-code'], other: ['File', 'c-other'],
};
export function fileIcon(name, isDir = false, open = false) {
  if (isDir) return icon(open ? 'FolderOpen' : 'Folder', 'c-folder');
  const [n, c] = TYPE_ICON[fileType(name)];
  return icon(n, c);
}
export const TYPE_LABEL = {
  note: 'Note', pdf: 'PDF', word: 'Word document', slides: 'Presentation', table: 'Table',
  image: 'Image', tex: 'LaTeX', code: 'Code / text', other: 'File',
};

// ------------------------------------------------------------------ time & size
export function ago(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} days ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}
export function size(n) {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

// ------------------------------------------------------------------ markdown (sanitized)
const ALLOWED_PROTOCOLS = /^(https?:|mailto:|#|\/|\.|[^:]*$)/i;
export function sanitize(html) {
  const t = document.createElement('template');
  t.innerHTML = html;
  t.content.querySelectorAll('script,style,iframe,object,embed,form,input,button,textarea,select,link,meta,base').forEach(n => n.remove());
  t.content.querySelectorAll('*').forEach(el => {
    for (const a of [...el.attributes]) {
      const n = a.name.toLowerCase();
      if (n.startsWith('on') || n === 'style' || n === 'srcdoc' || n === 'formaction') el.removeAttribute(a.name);
      else if ((n === 'href' || n === 'src' || n === 'xlink:href') && !ALLOWED_PROTOCOLS.test(a.value.trim())) el.removeAttribute(a.name);
    }
    if (el.tagName === 'A') { el.setAttribute('target', '_blank'); el.setAttribute('rel', 'noopener noreferrer'); }
  });
  return t.innerHTML;
}
export function md(text) {
  if (!window.marked) return esc(text).replace(/\n/g, '<br>');
  return sanitize(window.marked.parse(text || '', { gfm: true, breaks: false }));
}

// ------------------------------------------------------------------ toasts
export function toast(msg, kind = 'info', ms = 3500) {
  let box = $('#toasts');
  if (!box) { box = h('<div id="toasts" role="status" aria-live="polite"></div>'); document.body.append(box); }
  const el = h(`<div class="toast toast-${kind}">${icon(kind === 'error' ? 'alert' : kind === 'ok' ? 'Check' : 'Info')}<span>${esc(msg)}</span></div>`);
  box.append(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 300); }, ms);
}

// ------------------------------------------------------------------ dialogs
function dialogShell(inner, { wide = false } = {}) {
  const d = h(`<dialog class="dlg ${wide ? 'dlg-wide' : ''}">${inner}</dialog>`);
  document.body.append(d);
  d.addEventListener('close', () => setTimeout(() => d.remove(), 50));
  d.showModal();
  return d;
}

export function promptDialog({ title, label = '', value = '', okText = 'OK', placeholder = '', hint = '' }) {
  return new Promise(resolve => {
    const d = dialogShell(`
      <form method="dialog">
        <h3>${esc(title)}</h3>
        ${label ? `<label class="field-label">${esc(label)}</label>` : ''}
        <input class="input" name="v" value="${esc(value)}" placeholder="${esc(placeholder)}" autocomplete="off" required>
        ${hint ? `<p class="hint">${esc(hint)}</p>` : ''}
        <div class="dlg-actions">
          <button type="button" class="btn btn-ghost" data-cancel>Cancel</button>
          <button class="btn btn-primary" value="ok">${esc(okText)}</button>
        </div>
      </form>`);
    const input = $('input', d);
    input.focus();
    const dot = value.lastIndexOf('.');
    input.setSelectionRange(0, dot > 0 ? dot : value.length);
    $('[data-cancel]', d).onclick = () => { d.close(); resolve(null); };
    d.addEventListener('cancel', () => resolve(null));
    $('form', d).addEventListener('submit', () => resolve(input.value.trim() || null));
  });
}

export function confirmDialog({ title, message = '', okText = 'OK', danger = false }) {
  return new Promise(resolve => {
    const d = dialogShell(`
      <form method="dialog">
        <h3>${esc(title)}</h3>
        ${message ? `<p>${esc(message)}</p>` : ''}
        <div class="dlg-actions">
          <button type="button" class="btn btn-ghost" data-cancel>Cancel</button>
          <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" value="ok">${esc(okText)}</button>
        </div>
      </form>`);
    $('[data-cancel]', d).onclick = () => { d.close(); resolve(false); };
    d.addEventListener('cancel', () => resolve(false));
    $('form', d).addEventListener('submit', () => resolve(true));
    $('.btn-primary, .btn-danger', d).focus();
  });
}

export function customDialog(innerHtml, opts) {
  return dialogShell(innerHtml, opts);
}

// ------------------------------------------------------------------ popup menu
let openMenuEl = null;
export function closeMenu() { openMenuEl?.remove(); openMenuEl = null; }
document.addEventListener('pointerdown', e => { if (openMenuEl && !openMenuEl.contains(e.target)) closeMenu(); }, true);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });
window.addEventListener('resize', closeMenu);

export function openMenu(anchor, items) {
  closeMenu();
  const m = h(`<div class="menu" role="menu"></div>`);
  for (const it of items) {
    if (it === '-') { m.append(h('<div class="menu-sep"></div>')); continue; }
    if (!it) continue;
    const b = h(`<button class="menu-item ${it.danger ? 'danger' : ''}" role="menuitem">${icon(it.icon || 'Dot')}<span>${esc(it.label)}</span></button>`);
    b.onclick = () => { closeMenu(); it.onClick(); };
    m.append(b);
  }
  document.body.append(m);
  const r = anchor.getBoundingClientRect();
  const mw = m.offsetWidth, mh = m.offsetHeight;
  let left = Math.min(r.left, window.innerWidth - mw - 8);
  let top = r.bottom + 4;
  if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 4);
  m.style.left = `${Math.max(8, left)}px`;
  m.style.top = `${top}px`;
  openMenuEl = m;
  m.querySelector('button')?.focus();
}

// ------------------------------------------------------------------ misc
export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function downloadUrl(url) {
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  document.body.append(a);
  a.click();
  a.remove();
}

// Tiny event bus between panels
const bus = new EventTarget();
export const on = (type, fn) => bus.addEventListener(type, e => fn(e.detail));
export const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));
