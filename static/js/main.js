import { $, api, ago, confirmDialog, customDialog, emit, esc, h, icon, on, openMenu, promptDialog, toast } from './util.js';
import { pref, setAdvanced, setPref, state } from './state.js';
import { initFiles } from './files.js';
import { initViewer, openFile, closeFile } from './viewer.js';
import { initChat } from './chat.js';
import { initTerminals, toggleTerminalDrawer } from './terminal.js';

const app = $('#app');

// ======================================================================= routing
function parseHash() {
  const hash = location.hash.slice(1) || '/';
  const m = hash.match(/^\/p\/([^/]+)(?:\/f\/(.+))?$/);
  if (!m) return { view: 'home' };
  return { view: 'project', project: decodeURIComponent(m[1]), file: m[2] ? decodeURIComponent(m[2]) : null };
}

export function fileHash(project, path) {
  return `#/p/${encodeURIComponent(project)}` + (path ? `/f/${encodeURIComponent(path)}` : '');
}

async function route() {
  const r = parseHash();
  if (r.view === 'home') return showHome();
  if (state.project !== r.project || !$('.project-shell')) await showProject(r.project);
  if (r.file && r.file !== state.openFile) openFile(r.file);
  if (!r.file && state.openFile) closeFile();
}
window.addEventListener('hashchange', route);
on('open-file', ({ path }) => { location.hash = fileHash(state.project, path); });
on('close-file', () => { location.hash = fileHash(state.project, null); });
on('show-tab', tab => { const s = $('.project-shell'); if (s) s.dataset.mobileTab = tab; });

// ======================================================================= home
async function showHome() {
  state.project = null;
  state.openFile = null;
  document.title = 'Pokosomo Studio';
  app.innerHTML = `
    <div class="home">
      <header class="topbar">
        <div class="brand">${icon('FlaskConical')}<span>Pokosomo <b>Studio</b></span></div>
        <div class="spacer"></div>
        <button class="btn btn-ghost" id="btnSettings" title="Settings">${icon('Settings')}<span class="hide-sm">Settings</span></button>
        <button class="btn btn-ghost" id="btnSignOut" title="Sign out">${icon('LogOut')}<span class="hide-sm">Sign out</span></button>
      </header>
      <main class="home-main">
        <h1>Your projects</h1>
        <p class="lead">Each project is a folder for one piece of work — its papers, data, notes and results.
          The assistant only works inside the project you open.</p>
        <div class="project-grid" id="projectGrid"><div class="muted">Loading…</div></div>
      </main>
    </div>`;
  $('#btnSettings').onclick = openSettings;
  $('#btnSignOut').onclick = signOut;
  let projects = [];
  try { projects = await api('/api/projects'); } catch (e) { toast(e.message, 'error'); }
  const grid = $('#projectGrid');
  grid.innerHTML = '';
  const newCard = h(`<button class="project-card new">${icon('Plus')}<span>New project</span></button>`);
  newCard.onclick = newProject;
  grid.append(newCard);
  for (const p of projects) {
    const card = h(`
      <div class="project-card" tabindex="0" role="link">
        <div class="pc-icon">${icon('FolderOpen')}</div>
        <div class="pc-body">
          <div class="pc-name">${esc(p.name)}</div>
          <div class="pc-meta">${p.file_count} file${p.file_count === 1 ? '' : 's'} · edited ${ago(p.modified)}</div>
        </div>
        <button class="icon-btn pc-menu" title="More">${icon('more')}</button>
      </div>`);
    const open = () => { location.hash = fileHash(p.name); };
    card.onclick = e => { if (!e.target.closest('.pc-menu')) open(); };
    card.onkeydown = e => { if (e.key === 'Enter') open(); };
    $('.pc-menu', card).onclick = e => {
      e.stopPropagation();
      openMenu(e.currentTarget, [
        { label: 'Open', icon: 'FolderOpen', onClick: open },
        { label: 'Rename', icon: 'Pencil', onClick: () => renameProject(p.name) },
        '-',
        { label: 'Delete', icon: 'Trash2', danger: true, onClick: () => deleteProject(p.name) },
      ]);
    };
    grid.append(card);
  }
}

async function newProject() {
  const name = await promptDialog({ title: 'New project', label: 'Project name', placeholder: 'e.g. Biofilm assay 2026', okText: 'Create' });
  if (!name) return;
  try {
    const p = await api('/api/projects', { method: 'POST', body: { name } });
    location.hash = fileHash(p.name);
  } catch (e) { toast(e.message, 'error'); }
}

async function renameProject(name) {
  const n = await promptDialog({ title: 'Rename project', value: name, okText: 'Rename' });
  if (!n || n === name) return;
  try { await api(`/api/projects/${encodeURIComponent(name)}/rename`, { method: 'POST', body: { name: n } }); showHome(); }
  catch (e) { toast(e.message, 'error'); }
}

async function deleteProject(name) {
  const ok = await confirmDialog({ title: `Delete “${name}”?`, message: 'The project and all its files will be moved to the trash on the server. Ask your brother if you need it back.', okText: 'Delete project', danger: true });
  if (!ok) return;
  try { await api(`/api/projects/${encodeURIComponent(name)}`, { method: 'DELETE' }); toast('Project deleted', 'ok'); showHome(); }
  catch (e) { toast(e.message, 'error'); }
}

// ======================================================================= project
async function showProject(name) {
  state.project = name;
  state.openFile = null;
  state.currentDir = '';
  document.title = `${name} · Pokosomo Studio`;
  app.innerHTML = `
    <div class="project-shell" data-mobile-tab="doc">
      <header class="topbar">
        <a class="btn btn-ghost" href="#/" title="All projects">${icon('ArrowLeft')}<span class="hide-sm">Projects</span></a>
        <div class="proj-title">${icon('FolderOpen')}<span>${esc(name)}</span></div>
        <div class="spacer"></div>
        <button class="btn btn-ghost ${state.advanced ? '' : 'hidden'}" id="btnTerminal" title="Terminal (advanced)">${icon('SquareTerminal')}<span class="hide-sm">Terminal</span></button>
        <button class="btn btn-ghost" id="btnSettings" title="Settings">${icon('Settings')}</button>
        <button class="btn btn-ghost" id="btnSignOut" title="Sign out">${icon('LogOut')}</button>
      </header>
      <div class="workspace" id="workspace">
        <aside class="panel files-panel" id="filesPanel"></aside>
        <main class="panel doc-panel" id="docPanel"></main>
        <div class="resizer" id="chatResizer" title="Drag to resize"></div>
        <section class="panel chat-panel" id="chatPanel"></section>
      </div>
      <div class="terminal-drawer hidden" id="terminalDrawer"></div>
      <nav class="mobile-tabs">
        <button data-tab="files">${icon('Folder')}<span>Files</span></button>
        <button data-tab="doc">${icon('FileText')}<span>Document</span></button>
        <button data-tab="chat">${icon('Sparkles')}<span>Assistant</span></button>
      </nav>
    </div>`;
  $('#btnSettings').onclick = openSettings;
  $('#btnSignOut').onclick = signOut;
  $('#btnTerminal').onclick = () => toggleTerminalDrawer();

  const shell = $('.project-shell');
  shell.querySelectorAll('.mobile-tabs button').forEach(b => {
    b.onclick = () => { shell.dataset.mobileTab = b.dataset.tab; };
  });

  // Resizable assistant panel
  const ws = $('#workspace');
  ws.style.setProperty('--chat-w', `${pref('chatWidth', 420)}px`);
  const rz = $('#chatResizer');
  rz.addEventListener('pointerdown', e => {
    e.preventDefault();
    rz.setPointerCapture(e.pointerId);
    document.body.classList.add('resizing');
    const move = ev => {
      const w = Math.min(Math.max(window.innerWidth - ev.clientX, 320), Math.min(900, window.innerWidth - 520));
      ws.style.setProperty('--chat-w', `${w}px`);
    };
    const up = ev => {
      rz.removeEventListener('pointermove', move);
      rz.removeEventListener('pointerup', up);
      document.body.classList.remove('resizing');
      setPref('chatWidth', parseInt(getComputedStyle(ws).getPropertyValue('--chat-w')));
      emit('layout-changed');
    };
    rz.addEventListener('pointermove', move);
    rz.addEventListener('pointerup', up);
  });

  initViewer($('#docPanel'));
  await initFiles($('#filesPanel'));
  initChat($('#chatPanel'));
  initTerminals($('#terminalDrawer'));
}

// ======================================================================= settings
async function openSettings() {
  const d = customDialog(`
    <div class="settings">
      <div class="dlg-head"><h3>Settings</h3><button class="icon-btn" data-close title="Close">${icon('X')}</button></div>
      <section>
        <h4>Assistant</h4>
        <p class="hint">Which AI does the work. Changes apply to new chats.</p>
        <label class="radio"><input type="radio" name="engine" value="claude"> <span><b>Claude</b> (recommended)</span></label>
        <div class="sub" data-for="claude"><select class="input" id="claudeModel"></select></div>
        <label class="radio"><input type="radio" name="engine" value="agy"> <span><b>Antigravity</b> (Gemini and others)</span></label>
        <div class="sub" data-for="agy"><select class="input" id="agyModel"></select></div>
        <label class="radio"><input type="radio" name="engine" value="codex"> <span><b>OpenAI Codex</b></span></label>
        <div class="sub" data-for="codex"><input class="input" id="codexModel" placeholder="Model (optional; uses Codex default)"></div>
      </section>
      <section>
        <h4>Accounts</h4>
        <div id="accounts" class="muted">Checking…</div>
      </section>
      <section>
        <h4>Advanced</h4>
        <label class="switch"><input type="checkbox" id="advToggle"> <span>Show the terminal (for technical users)</span></label>
      </section>
      <section>
        <h4>Security</h4>
        <button class="btn btn-ghost" id="btnLogoutAll">${icon('ShieldOff')}Sign out on all devices</button>
      </section>
    </div>`, { wide: true });
  $('[data-close]', d).onclick = () => d.close();
  const adv = $('#advToggle', d);
  adv.checked = state.advanced;
  adv.onchange = () => {
    setAdvanced(adv.checked);
    $('#btnTerminal')?.classList.toggle('hidden', !adv.checked);
  };
  $('#btnLogoutAll', d).onclick = async () => {
    if (!await confirmDialog({ title: 'Sign out everywhere?', message: 'All browsers, including this one, will need the password and code again.', okText: 'Sign out everywhere', danger: true })) return;
    await api('/api/auth/logout-all', { method: 'POST' }).catch(() => {});
    location.href = '/login';
  };

  try {
    const { settings, claude_models } = await api('/api/settings');
    const cm = $('#claudeModel', d);
    const codexModel = $('#codexModel', d);
    cm.innerHTML = claude_models.map(m => `<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('');
    cm.value = settings.claude_model;
    codexModel.value = settings.codex_model || '';
    d.querySelectorAll('input[name=engine]').forEach(r => { r.checked = r.value === settings.engine; });
    const save = async () => {
      const body = {
        engine: d.querySelector('input[name=engine]:checked')?.value || 'claude',
        claude_model: cm.value,
        agy_model: $('#agyModel', d).value || settings.agy_model,
        codex_model: codexModel.value.trim(),
      };
      try { await api('/api/settings', { method: 'PUT', body }); toast('Saved — new chats will use this', 'ok', 2000); }
      catch (e) { toast(e.message, 'error'); }
    };
    d.querySelectorAll('input[name=engine]').forEach(r => { r.onchange = save; });
    cm.onchange = save;
    codexModel.onchange = save;

    const agents = await api('/api/agents');
    const am = $('#agyModel', d);
    am.innerHTML = (agents.agy?.models || []).map(m => `<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('');
    am.value = settings.agy_model;
    am.onchange = save;
    const c = agents.claude || {};
    const cAuth = c.auth || {};
    const codex = agents.codex || {};
    $('#accounts', d).innerHTML = `
      <div class="account-row">${icon(cAuth.loggedIn ? 'CircleCheck' : 'CircleAlert', cAuth.loggedIn ? 'ok' : 'warn')}
        <div><b>Claude</b> — ${c.installed ? (cAuth.loggedIn ? `signed in${cAuth.subscriptionType ? ` (${esc(cAuth.subscriptionType)} plan)` : ''}` : 'not signed in') : 'not installed'}</div></div>
      <div class="account-row">${icon(agents.agy?.authenticated ? 'CircleCheck' : 'CircleAlert', agents.agy?.authenticated ? 'ok' : 'warn')}
        <div><b>Antigravity</b> — ${agents.agy?.installed ? (agents.agy.authenticated ? 'signed in' : 'not signed in') : 'not installed'}</div></div>
      <div class="account-row">${icon(codex.authenticated ? 'CircleCheck' : 'CircleAlert', codex.authenticated ? 'ok' : 'warn')}
        <div><b>OpenAI Codex</b> — ${codex.installed ? (codex.authenticated ? 'signed in' : 'not signed in') : 'not installed'}</div></div>
      <p class="hint">To sign in, use the included setup shortcut on Windows, or run <code>claude auth login</code>, <code>codex login</code>, or <code>agy</code> in the server terminal.</p>`;
  } catch (e) {
    $('#accounts', d).textContent = e.message;
  }
}

async function signOut() {
  await api('/api/auth/logout', { method: 'POST' }).catch(() => {});
  location.href = '/login';
}

route();
