// Right panel: the AI assistant chat.
import { $, P, ago, api, confirmDialog, emit, esc, h, icon, md, on, openMenu, toast } from './util.js';
import { pref, setPref, state } from './state.js';
import { uploadFiles } from './files.js';

let panel = null;
let chat = null;        // full chat object
let ws = null;
let wsChatId = null;
let pingTimer = null;
let includeContext = true;
const openGroups = new Set();
const closedGroups = new Set();
const openSteps = new Set();

const STEP_ICON = {
  read: 'BookOpen', write: 'FilePlus', edit: 'FilePen', run: 'Play', search: 'Search',
  web: 'Globe', plan: 'ListTodo', agent: 'Bot', other: 'Wrench',
};

export async function initChat(container) {
  panel = container;
  chat = null;
  closeSocket();
  panel.innerHTML = `
    <div class="panel-head chat-head">
      ${icon('Sparkles', 'accent')}<h2>Assistant</h2>
      <button class="chat-picker" id="chatPicker" title="Earlier chats">${icon('History')}<span class="chat-title">New chat</span>${icon('ChevronDown')}</button>
      <div class="spacer"></div>
      <button class="btn btn-sm btn-soft" id="btnNewChat" title="Start a new conversation">${icon('SquarePen')}<span class="hide-md">New chat</span></button>
    </div>
    <div class="messages" id="messages"></div>
    <div class="composer" id="composer">
      <div class="context-chip hidden" id="ctxChip"></div>
      <textarea id="chatInput" rows="2" placeholder="Ask anything about this project…"></textarea>
      <div class="composer-row">
        <button class="icon-btn" id="btnAttach" title="Attach files (they're added to the project)">${icon('Paperclip')}</button>
        <input type="file" id="attachInput" multiple hidden>
        <span class="hint hide-md">Enter to send · Shift+Enter for a new line</span>
        <div class="spacer"></div>
        <button class="btn btn-danger btn-sm hidden" id="btnStop">${icon('Square')}Stop</button>
        <button class="btn btn-primary btn-sm" id="btnSend">${icon('SendHorizontal')}Send</button>
      </div>
    </div>`;

  const input = $('#chatInput', panel);
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  });
  $('#btnSend', panel).onclick = () => send();
  $('#btnStop', panel).onclick = stop;
  $('#btnNewChat', panel).onclick = newChat;
  $('#chatPicker', panel).onclick = e => pickChat(e.currentTarget);
  const attach = $('#attachInput', panel);
  $('#btnAttach', panel).onclick = () => attach.click();
  attach.onchange = async () => { await attachFiles(attach.files); attach.value = ''; };
  panel.addEventListener('dragover', e => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); panel.classList.add('dropping'); } });
  panel.addEventListener('dragleave', e => { if (!panel.contains(e.relatedTarget)) panel.classList.remove('dropping'); });
  panel.addEventListener('drop', async e => {
    panel.classList.remove('dropping');
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    await attachFiles(e.dataTransfer.files);
  });
  $('#messages', panel).addEventListener('click', onMessagesClick);

  updateContextChip();
  renderMessages();

  try {
    const chats = await api(`${P(state.project)}/chats`);
    const last = pref(`chat:${state.project}`, null);
    const pick = chats.find(c => c.id === last) || chats[0];
    if (pick) await loadChat(pick.id);
  } catch (e) { toast(e.message, 'error'); }
}

// ------------------------------------------------------------------ events from other panels
on('ask', ({ text, send: now }) => {
  if (!panel?.isConnected) return;
  const input = $('#chatInput', panel);
  if (now) { send(text); return; }
  input.value = text || input.value;
  autosize();
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
});
on('file-opened', () => { includeContext = true; updateContextChip(); });
on('tree-updated', () => { if (panel?.isConnected) linkifyPaths($('#messages', panel)); });

function updateContextChip() {
  const chip = panel && $('#ctxChip', panel);
  if (!chip) return;
  if (!state.openFile) { chip.classList.add('hidden'); return; }
  chip.classList.remove('hidden');
  chip.classList.toggle('off', !includeContext);
  chip.innerHTML = includeContext
    ? `${icon('Eye')}<span>The assistant can see you have <b>${esc(state.openFile.split('/').pop())}</b> open</span><button class="icon-btn" title="Don't mention it">${icon('X')}</button>`
    : `${icon('EyeOff')}<span>Not mentioning the open file</span><button class="icon-btn" title="Mention it">${icon('Undo2')}</button>`;
  $('button', chip).onclick = () => { includeContext = !includeContext; updateContextChip(); };
}

function autosize() {
  const input = $('#chatInput', panel);
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
}

async function attachFiles(fileList) {
  const files = await uploadFiles(fileList, state.currentDir, { open: false });
  if (!files.length) return;
  const input = $('#chatInput', panel);
  const list = files.map(f => `\`${f.path}\``).join(', ');
  input.value = `${input.value ? input.value.trimEnd() + '\n' : ''}I've added ${files.length === 1 ? 'the file' : 'these files'}: ${list}\n`;
  autosize();
  input.focus();
}

// ------------------------------------------------------------------ chat lifecycle
async function loadChat(id) {
  try {
    chat = await api(`${P(state.project)}/chats/${id}`);
  } catch {
    chat = null;
    renderMessages();
    return;
  }
  setPref(`chat:${state.project}`, id);
  renderMessages(true);
  connect(id);
}

async function newChat() {
  if (chat && !chat.messages.length) { $('#chatInput', panel).focus(); return; }
  closeSocket();
  chat = null;
  setPref(`chat:${state.project}`, null);
  renderMessages();
  $('#chatInput', panel).focus();
}

async function pickChat(anchor) {
  let chats = [];
  try { chats = await api(`${P(state.project)}/chats`); } catch (e) { return toast(e.message, 'error'); }
  const items = chats.slice(0, 25).map(c => ({
    label: `${c.title || 'New chat'} · ${ago(c.updated)}${c.running ? ' · working…' : ''}`,
    icon: c.id === chat?.id ? 'Check' : 'MessageCircle',
    onClick: () => { closeSocket(); loadChat(c.id); },
  }));
  if (!items.length) items.push({ label: 'No earlier chats yet', icon: 'Info', onClick: () => {} });
  openMenu(anchor, [
    { label: 'New chat', icon: 'SquarePen', onClick: newChat },
    '-',
    ...items,
    chat?.messages.length && '-',
    chat?.messages.length && { label: 'Delete this chat', icon: 'Trash2', danger: true, onClick: deleteChat },
  ]);
}

async function deleteChat() {
  if (!chat) return;
  if (!await confirmDialog({ title: 'Delete this chat?', message: 'The conversation is removed. Files the assistant made stay in the project.', okText: 'Delete', danger: true })) return;
  try {
    await api(`${P(state.project)}/chats/${chat.id}`, { method: 'DELETE' });
    closeSocket();
    chat = null;
    renderMessages();
  } catch (e) { toast(e.message, 'error'); }
}

async function send(textArg) {
  const input = $('#chatInput', panel);
  const text = (textArg ?? input.value).trim();
  if (!text) return;
  if (chat?.running) { toast('The assistant is still working. Wait, or press Stop.', 'info'); return; }
  const btn = $('#btnSend', panel);
  btn.disabled = true;
  try {
    if (!chat) {
      chat = await api(`${P(state.project)}/chats`, { method: 'POST' });
      setPref(`chat:${state.project}`, chat.id);
      connect(chat.id);
    }
    const body = { text, open_file: includeContext ? state.openFile : null };
    if (textArg === undefined) { input.value = ''; autosize(); }
    chat = await api(`${P(state.project)}/chats/${chat.id}/send`, { method: 'POST', body });
    renderMessages(true);
  } catch (e) {
    toast(e.message, 'error', 5000);
    if (textArg === undefined && !input.value) input.value = text;
  } finally { btn.disabled = false; }
}

async function stop() {
  if (!chat) return;
  await api(`${P(state.project)}/chats/${chat.id}/stop`, { method: 'POST' }).catch(() => {});
}

// ------------------------------------------------------------------ websocket
function connect(id) {
  if (wsChatId === id && ws && ws.readyState <= 1) return;
  closeSocket();
  wsChatId = id;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const sock = new WebSocket(`${proto}://${location.host}/ws/projects/${encodeURIComponent(state.project)}/chats/${id}`);
  ws = sock;
  sock.onmessage = ev => {
    if (ws !== sock) return;
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    if (m.type === 'chat') {
      // a snapshot taken before our last send can arrive late; never go backwards
      if (chat && chat.id === m.chat.id && m.chat.messages.length < chat.messages.length) return;
      chat = m.chat;
      renderMessages(true);
    }
    else if (m.type === 'update' && chat) {
      const i = chat.messages.findIndex(x => x.id === m.message.id);
      if (i >= 0) chat.messages[i] = m.message; else chat.messages.push(m.message);
      chat.running = m.message.status === 'running';
      renderMessage(m.message);
      updateRunning();
    } else if (m.type === 'run_end' && chat) {
      chat.running = false;
      updateRunning();
      if (m.status === 'done' && document.hidden) document.title = `✓ ${state.project} · Pokosomo Studio`;
    } else if (m.type === 'files_changed') emit('files-changed');
  };
  sock.onclose = () => {
    if (ws !== sock) return;
    ws = null;
    clearInterval(pingTimer);
    // reconnect while this chat is still on screen
    setTimeout(() => { if (panel?.isConnected && chat?.id === id && wsChatId === id) { wsChatId = null; loadChat(id); } }, 2000);
  };
  clearInterval(pingTimer);
  pingTimer = setInterval(() => { if (sock.readyState === 1) sock.send('ping'); }, 25000);
}

function closeSocket() {
  clearInterval(pingTimer);
  const s = ws;
  ws = null;
  wsChatId = null;
  try { s?.close(); } catch { /* ignore */ }
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden && state.project) document.title = `${state.project} · Pokosomo Studio`;
});

// ------------------------------------------------------------------ rendering
function updateRunning() {
  if (!panel) return;
  const running = !!chat?.running;
  $('#btnStop', panel).classList.toggle('hidden', !running);
  $('#btnSend', panel).classList.toggle('hidden', running);
  $('.chat-title', panel).textContent = chat?.title || 'New chat';
}

function renderMessages(scrollToEnd = false) {
  const box = $('#messages', panel);
  if (!box) return;
  updateRunning();
  if (!chat || !chat.messages.length) {
    box.innerHTML = `
      <div class="chat-empty">
        <div class="chat-empty-icon">${icon('Sparkles')}</div>
        <h3>How can I help?</h3>
        <p>I can read your PDFs and Word files, analyse data, make figures, and write or edit notes — all inside <b>${esc(state.project)}</b>.</p>
        <div class="chips">
          <button class="chip">What's in this project?</button>
          <button class="chip">Summarize my newest PDF</button>
          <button class="chip">Make a figure from my data</button>
        </div>
        <p class="hint">Everything I make is saved as files you can see on the left.</p>
      </div>`;
    box.querySelectorAll('.chip').forEach(c => { c.onclick = () => { $('#chatInput', panel).value = c.textContent; autosize(); $('#chatInput', panel).focus(); }; });
    return;
  }
  box.innerHTML = '';
  for (const m of chat.messages) box.append(messageEl(m));
  linkifyPaths(box);
  if (scrollToEnd) box.scrollTop = box.scrollHeight;
}

function renderMessage(m) {
  const box = $('#messages', panel);
  if (!box) return;
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  const old = box.querySelector(`[data-mid="${m.id}"]`);
  const el = messageEl(m);
  if (old) old.replaceWith(el);
  else { box.querySelector('.chat-empty')?.remove(); box.append(el); }
  linkifyPaths(el);
  if (nearBottom) box.scrollTop = box.scrollHeight;
}

function messageEl(m) {
  if (m.role === 'user') {
    return h(`<div class="msg user" data-mid="${m.id}"><div class="bubble">${esc(m.text)}</div>
      ${m.open_file ? `<div class="msg-meta">${icon('Eye')}with ${esc(m.open_file.split('/').pop())} open</div>` : ''}</div>`);
  }
  const el = h(`<div class="msg assistant" data-mid="${m.id}"><div class="msg-body"></div></div>`);
  const body = $('.msg-body', el);
  // group consecutive tool parts
  const groups = [];
  for (const p of m.parts || []) {
    const last = groups[groups.length - 1];
    if (p.type === 'tool') {
      if (last?.type === 'tools') last.items.push(p);
      else groups.push({ type: 'tools', items: [p] });
    } else if (p.type === 'text' && p.text.trim()) groups.push(p);
  }
  const running = m.status === 'running';
  groups.forEach((g, gi) => {
    if (g.type === 'text') { body.append(h(`<div class="md-text">${md(g.text)}</div>`)); return; }
    const key = `${m.id}:${gi}`;
    const isLast = gi === groups.length - 1;
    const active = running && isLast;
    const open = openGroups.has(key) || (active && !closedGroups.has(key));
    const lastStep = g.items[g.items.length - 1];
    const anyErr = g.items.some(s => s.status === 'error');
    const summaryIcon = active ? icon('spinner', 'spin') : anyErr ? icon('alert', 'warn') : icon('CircleCheck', 'ok');
    const label = active || g.items.length === 1 ? lastStep.label
      : `${g.items.length} steps — last: ${(lastStep.label || '').replace(/^./, c => c.toLowerCase())}`;
    const det = h(`<details class="steps" data-key="${key}" ${open ? 'open' : ''}>
      <summary>${summaryIcon}<span class="steps-label">${esc(label)}</span><span class="steps-count">${g.items.length}</span>${icon('ChevronDown', 'chev')}</summary>
      <div class="step-list"></div></details>`);
    det.addEventListener('toggle', () => {
      if (det.open) { openGroups.add(key); closedGroups.delete(key); } else { openGroups.delete(key); closedGroups.add(key); }
    });
    const list = $('.step-list', det);
    for (const s of g.items) list.append(stepEl(s));
    body.append(det);
  });
  if (running) {
    body.append(h(`<div class="working">${icon('spinner', 'spin')}<span>${m.thinking ? 'Thinking…' : groups.length ? 'Working…' : 'Starting…'}</span></div>`));
  }
  if (m.status === 'error') {
    const err = h(`<div class="msg-error">${icon('alert')}<div><b>Something went wrong.</b><div class="err-msg">${esc(m.error || '')}</div>
      <button class="btn btn-sm btn-soft retry">${icon('RotateCcw')}Try again</button></div></div>`);
    $('.retry', err).onclick = () => {
      const idx = chat.messages.findIndex(x => x.id === m.id);
      const prev = chat.messages.slice(0, idx).reverse().find(x => x.role === 'user');
      if (prev) send(prev.text);
    };
    body.append(err);
  } else if (m.status === 'stopped') {
    body.append(h(`<div class="msg-stopped">${icon('CircleStop')}${esc(m.error || 'Stopped.')}</div>`));
  }
  return el;
}

function stepEl(s) {
  const open = openSteps.has(s.id);
  const st = s.status === 'running' ? icon('spinner', 'spin') : s.status === 'error' ? icon('alert', 'warn') : '';
  const hasDetail = s.detail || s.output || s.todos;
  const el = h(`<div class="step ${s.status} ${open ? 'open' : ''}" data-sid="${esc(s.id)}">
    <div class="step-row ${hasDetail ? 'clickable' : ''}">${icon(STEP_ICON[s.kind] || 'Wrench', 'step-icon')}
      <span class="step-label">${esc(s.label || s.name || 'Step')}</span>
      ${s.file && state.paths.has(s.file) ? `<button class="link-btn" data-open="${esc(s.file)}">Open</button>` : ''}${st}</div>
  </div>`);
  if (hasDetail && open) el.append(stepDetail(s));
  return el;
}

function stepDetail(s) {
  const d = h('<div class="step-detail"></div>');
  if (s.todos) {
    d.append(h(`<ul class="todos">${s.todos.map(t => `<li class="${esc(t.status)}">${icon(t.status === 'completed' ? 'SquareCheck' : t.status === 'in_progress' ? 'SquareDot' : 'Square')}${esc(t.text)}</li>`).join('')}</ul>`));
  }
  if (s.detail) d.append(h(`<pre class="step-pre">${esc(s.detail)}</pre>`));
  if (s.output) d.append(h(`<div class="step-out-label">Result</div>`), h(`<pre class="step-pre out">${esc(s.output)}</pre>`));
  return d;
}

function onMessagesClick(e) {
  const openBtn = e.target.closest('[data-open]');
  if (openBtn) { e.preventDefault(); emit('open-file', { path: openBtn.dataset.open }); emit('show-tab', 'doc'); return; }
  const row = e.target.closest('.step-row.clickable');
  if (row) {
    const stepNode = row.parentElement;
    const id = stepNode.dataset.sid;
    const msgId = stepNode.closest('[data-mid]').dataset.mid;
    const m = chat?.messages.find(x => x.id === msgId);
    const s = m?.parts.find(p => p.id === id);
    if (!s) return;
    if (openSteps.has(id)) { openSteps.delete(id); stepNode.classList.remove('open'); stepNode.querySelector('.step-detail')?.remove(); }
    else { openSteps.add(id); stepNode.classList.add('open'); stepNode.append(stepDetail(s)); }
  }
}

// Turn `path/in/project.ext` mentions in replies into clickable links.
function linkifyPaths(root) {
  if (!root) return;
  root.querySelectorAll('.md-text code').forEach(c => {
    if (c.closest('pre') || c.dataset.linked) return;
    const t = c.textContent.trim().replace(/^\.\//, '');
    if (state.paths.has(t)) {
      c.dataset.linked = '1';
      const b = h(`<button class="file-link" data-open="${esc(t)}" title="Open ${esc(t)}">${icon('FileSymlink')}</button>`);
      b.append(c.cloneNode(true));
      c.replaceWith(b);
    }
  });
}
