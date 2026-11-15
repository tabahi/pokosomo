// Advanced: terminal drawer (xterm.js) running inside the project folder.
import { $, api, esc, h, icon, on, toast } from './util.js';
import { state } from './state.js';

let drawer = null;
const sessions = new Map(); // id -> { id, title, term, fit, ws, el }
let active = null;

export function initTerminals(container) {
  drawer = container;
  for (const s of sessions.values()) { try { s.ws?.close(); s.term?.dispose(); } catch { /* ignore */ } }
  sessions.clear();
  active = null;
  drawer.innerHTML = `
    <div class="term-bar">
      <div class="term-tabs" id="termTabs"></div>
      <div class="spacer"></div>
      <button class="btn btn-sm btn-ghost" data-cmd="/bin/bash" data-title="Shell">${icon('SquareTerminal')}Shell</button>
      <button class="btn btn-sm btn-ghost" data-cmd="claude" data-title="Claude Code">${icon('Bot')}Claude Code</button>
      <button class="btn btn-sm btn-ghost" data-cmd="agy" data-title="Antigravity">${icon('Rocket')}Antigravity</button>
      <button class="btn btn-sm btn-ghost" data-cmd="codex" data-title="Codex">${icon('Code')}Codex</button>
      <button class="icon-btn" id="termHide" title="Hide terminal">${icon('ChevronDown')}</button>
    </div>
    <div class="term-views" id="termViews"><div class="term-empty hint">Start a shell or an agent. It runs inside this project's folder.</div></div>`;
  drawer.querySelectorAll('[data-cmd]').forEach(b => { b.onclick = () => createSession(b.dataset.cmd, b.dataset.title); });
  $('#termHide', drawer).onclick = () => toggleTerminalDrawer(false);
}

export async function toggleTerminalDrawer(show) {
  if (!drawer) return;
  const willShow = show ?? drawer.classList.contains('hidden');
  drawer.classList.toggle('hidden', !willShow);
  if (willShow) {
    if (!sessions.size) await attachExisting();
    setTimeout(fitActive, 50);
  }
}

async function attachExisting() {
  try {
    const list = await api(`/api/terminals?project=${encodeURIComponent(state.project)}`);
    for (const s of list) if (s.is_alive) mount(s.session_id, s.title);
    if (sessions.size) activate([...sessions.keys()].pop());
  } catch { /* ignore */ }
}

async function createSession(command, title) {
  if (!window.Terminal) return toast('Terminal library not loaded', 'error');
  try {
    const s = await api('/api/terminals', { method: 'POST', body: { project: state.project, command, title, cols: 100, rows: 24 } });
    mount(s.session_id, s.title);
    activate(s.session_id);
  } catch (e) { toast(e.message, 'error'); }
}

function mount(id, title) {
  $('.term-empty', drawer)?.remove();
  const el = h(`<div class="term-view hidden"></div>`);
  $('#termViews', drawer).append(el);
  const term = new window.Terminal({
    cursorBlink: true, fontSize: 13, scrollback: 5000, allowProposedApi: true,
    fontFamily: 'ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace',
    theme: { background: '#16181d', foreground: '#e6e6e6' },
  });
  const fit = new window.FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(el);
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/terminal/${id}`);
  ws.binaryType = 'arraybuffer';
  ws.onmessage = ev => term.write(typeof ev.data === 'string' ? ev.data : new Uint8Array(ev.data));
  ws.onopen = () => fitActive();
  term.onData(d => { if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'input', data: d })); });
  sessions.set(id, { id, title, term, fit, ws, el });
  renderTabs();
}

function activate(id) {
  active = id;
  for (const s of sessions.values()) s.el.classList.toggle('hidden', s.id !== id);
  renderTabs();
  setTimeout(() => { fitActive(); sessions.get(id)?.term.focus(); }, 30);
}

function renderTabs() {
  const tabs = $('#termTabs', drawer);
  tabs.innerHTML = '';
  for (const s of sessions.values()) {
    const t = h(`<div class="term-tab ${s.id === active ? 'active' : ''}"><span>${esc(s.title)}</span><button class="icon-btn" title="Close">${icon('X')}</button></div>`);
    t.onclick = e => { if (!e.target.closest('button')) activate(s.id); };
    $('button', t).onclick = () => closeSession(s.id);
    tabs.append(t);
  }
}

function closeSession(id) {
  const s = sessions.get(id);
  if (!s) return;
  try { s.ws.close(); s.term.dispose(); } catch { /* ignore */ }
  s.el.remove();
  sessions.delete(id);
  api(`/api/terminals/${id}`, { method: 'DELETE' }).catch(() => {});
  if (active === id) { const next = [...sessions.keys()].pop(); if (next) activate(next); else active = null; }
  renderTabs();
}

function fitActive() {
  const s = active && sessions.get(active);
  if (!s || drawer.classList.contains('hidden')) return;
  try {
    s.fit.fit();
    if (s.ws.readyState === 1) s.ws.send(JSON.stringify({ type: 'resize', cols: s.term.cols, rows: s.term.rows }));
  } catch { /* ignore */ }
}

window.addEventListener('resize', fitActive);
on('layout-changed', fitActive);
