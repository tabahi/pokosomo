// Center panel: shows / edits the open file. Notes get a friendly editor with "Make PDF".
import { $, P, api, ago, confirmDialog, customDialog, debounce, downloadUrl, emit, esc, ext, fileIcon, fileType, h, icon, md, on, openMenu, rawUrl, size, toast, TYPE_LABEL } from './util.js';
import { pref, setPref, state } from './state.js';
import { importAsNote, newNote, uploadFiles } from './files.js';

let panel = null;
let current = null;   // { path, dispose(), flush(), onExternalChange() }
let openSeq = 0;

export function initViewer(container) {
  panel = container;
  current = null;
  showWelcome();
}

on('tree-updated', () => {
  if (!panel?.isConnected) return;
  if (!state.openFile) return showWelcome();
  current?.onExternalChange?.();
});

export async function closeFile() {
  await current?.flush?.();
  current?.dispose?.();
  current = null;
  state.openFile = null;
  emit('file-opened', { path: null });
  showWelcome();
}

export async function openFile(path) {
  const seq = ++openSeq;
  await current?.flush?.();
  if (seq !== openSeq) return;
  current?.dispose?.();
  current = null;
  state.openFile = path;
  emit('file-opened', { path });
  const name = path.split('/').pop();
  const folder = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
  const type = fileType(name);
  const e = ext(name);

  panel.innerHTML = `
    <div class="doc">
      <div class="doc-head">
        <div class="doc-title">${fileIcon(name)}<div class="doc-name"><span class="name">${esc(name)}</span>${folder ? `<span class="folder">${esc(folder)}</span>` : ''}</div></div>
        <div class="spacer"></div>
        <div class="doc-actions"></div>
        <button class="icon-btn" data-act="close" title="Close">${icon('X')}</button>
      </div>
      <div class="doc-body"></div>
    </div>`;
  $('[data-act=close]', panel).onclick = () => emit('close-file');
  const ctx = { path, name, folder, type, ext: e, actions: $('.doc-actions', panel), body: $('.doc-body', panel) };

  try {
    if (type === 'note' || e === 'tex') current = await textEditor(ctx, { markdown: type === 'note', pdf: true, word: type === 'note' });
    else if (type === 'code' || e === 'bib' || e === 'cls' || e === 'sty') current = await textEditor(ctx, { markdown: false, pdf: false, word: false });
    else if (type === 'pdf') current = pdfView(ctx);
    else if (type === 'image') current = imageView(ctx);
    else if (type === 'table') current = await tableView(ctx);
    else if (type === 'word' || type === 'slides') current = await officeView(ctx);
    else current = otherView(ctx);
  } catch (err) {
    ctx.body.innerHTML = `<div class="doc-message">${icon('alert', 'warn big')}<p>${esc(err.message)}</p>
      <button class="btn btn-soft" id="dl">${icon('Download')}Download instead</button></div>`;
    $('#dl', ctx.body).onclick = () => downloadUrl(rawUrl(state.project, path, true));
  }
  if (seq !== openSeq) current?.dispose?.();
}

// ====================================================================== shared bits
function askButton(ctx, label, text) {
  const b = h(`<button class="btn btn-sm btn-soft">${icon('Sparkles')}<span class="hide-md">${esc(label)}</span></button>`);
  b.title = label;
  b.onclick = () => { emit('ask', { text }); emit('show-tab', 'chat'); };
  ctx.actions.append(b);
}
function downloadButton(ctx) {
  const b = h(`<button class="btn btn-sm btn-ghost" title="Download to your computer">${icon('Download')}<span class="hide-md">Download</span></button>`);
  b.onclick = () => downloadUrl(rawUrl(state.project, ctx.path, true));
  ctx.actions.append(b);
}
function siblingPath(path, newExt) {
  return path.replace(/\.[^./]+$/, '') + '.' + newExt;
}

// ====================================================================== welcome
function showWelcome() {
  if (!panel) return;
  const files = [];
  (function walk(n) { if (n.type === 'file') files.push(n); (n.children || []).forEach(walk); })(state.tree || {});
  files.sort((a, b) => b.modified - a.modified);
  const ideas = [
    'Summarize the PDFs in this project into a short note with the key findings of each paper.',
    'I added my data spreadsheet. Compare the groups with the right statistical test and make a publication-quality figure.',
    'Turn my notes into a draft Methods section.',
    'Check the spelling and grammar of my Word document and save a corrected copy.',
  ];
  panel.innerHTML = `
    <div class="welcome">
      <h1>${esc(state.project || '')}</h1>
      <p class="lead">Open a file on the left, or start with one of these:</p>
      <div class="start-cards">
        <button class="start-card" data-go="note">${icon('NotebookPen')}<b>Write a note</b><span>Type notes and turn them into a clean PDF.</span></button>
        <button class="start-card" data-go="upload">${icon('Upload')}<b>Add files</b><span>PDFs, Word files, spreadsheets, images…</span></button>
        <button class="start-card" data-go="ask">${icon('Sparkles')}<b>Ask the assistant</b><span>It can read, analyse and write files here.</span></button>
      </div>
      <h3>Things you can ask</h3>
      <div class="ideas">${ideas.map(t => `<button class="idea">${icon('MessageCircle')}<span>${esc(t)}</span></button>`).join('')}</div>
      ${files.length ? `<h3>Recent files</h3><div class="recent">${files.slice(0, 8).map(f => `
        <button class="recent-item" data-path="${esc(f.path)}">${fileIcon(f.name)}<span class="name">${esc(f.path)}</span><span class="muted">${ago(f.modified)}</span></button>`).join('')}</div>` : ''}
      <input type="file" id="welcomeUpload" multiple hidden>
    </div>`;
  const up = $('#welcomeUpload', panel);
  up.onchange = () => { if (up.files.length) uploadFiles(up.files, state.currentDir); up.value = ''; };
  panel.querySelectorAll('[data-go]').forEach(b => {
    b.onclick = () => {
      if (b.dataset.go === 'note') newNote(state.currentDir);
      else if (b.dataset.go === 'upload') up.click();
      else { emit('ask', { text: '' }); emit('show-tab', 'chat'); }
    };
  });
  panel.querySelectorAll('.idea').forEach(b => { b.onclick = () => { emit('ask', { text: b.textContent.trim() }); emit('show-tab', 'chat'); }; });
  panel.querySelectorAll('.recent-item').forEach(b => { b.onclick = () => emit('open-file', { path: b.dataset.path }); });
}

// ====================================================================== text / note editor
async function textEditor(ctx, { markdown, pdf, word }) {
  const file = await api(`${P(state.project)}/file?path=${encodeURIComponent(ctx.path)}`);
  let mtime = file.mtime;
  let dirty = false;
  let saving = null;
  let disposed = false;

  // ---- header actions
  const status = h(`<span class="save-state" title="Your changes are saved automatically">${icon('Check')}Saved</span>`);
  ctx.actions.append(status);
  let previewBtn = null;
  if (markdown) {
    previewBtn = h(`<button class="btn btn-sm btn-ghost" title="See the formatted text">${icon('Eye')}<span class="hide-md">Preview</span></button>`);
    ctx.actions.append(previewBtn);
  }
  let pdfBtn = null;
  if (pdf) {
    pdfBtn = h(`<button class="btn btn-sm btn-primary" title="Create a typeset PDF from this ${markdown ? 'note' : 'file'}">${icon('FileDown')}<span>Make PDF</span></button>`);
    ctx.actions.append(pdfBtn);
  }
  const more = h(`<button class="icon-btn" title="More">${icon('more')}</button>`);
  ctx.actions.append(more);

  // ---- body
  ctx.body.innerHTML = `
    ${markdown ? `<div class="md-toolbar" role="toolbar"></div>` : ''}
    <div class="build-error hidden"></div>
    <div class="split">
      <div class="editor-pane ${markdown ? 'md' : 'plain'}">
        ${markdown ? `<div class="doc-meta">
          <input class="meta-title" data-k="title" placeholder="Title" aria-label="Title" title="Title — shown at the top of the PDF">
          <div class="meta-row"><input data-k="author" placeholder="Author" aria-label="Author"><input data-k="date" placeholder="Date" aria-label="Date"></div>
        </div>` : ''}
        <textarea spellcheck="${markdown}"></textarea></div>
      <div class="pdf-pane hidden">
        <div class="pdf-pane-head">${icon('FileText')}<span class="pdf-label">PDF</span><div class="spacer"></div>
          <button class="icon-btn" data-pdf="open" title="Open the PDF on its own">${icon('ExternalLink')}</button>
          <button class="icon-btn" data-pdf="download" title="Download PDF">${icon('Download')}</button>
          <button class="icon-btn" data-pdf="close" title="Hide PDF">${icon('X')}</button></div>
        <iframe title="PDF preview"></iframe>
      </div>
    </div>`;
  const ta = $('textarea', ctx.body);
  // Notes: the YAML header (title/author/date) is edited through the fields above the text.
  let fm = markdown ? splitFrontMatter(file.content) : null;
  const metaInputs = markdown ? [...ctx.body.querySelectorAll('.doc-meta input')] : [];
  const fillMeta = () => metaInputs.forEach(inp => {
    inp.value = fm.fields[inp.dataset.k] || '';
    inp.classList.toggle('hidden', !fm.simple.has(inp.dataset.k));
  });
  if (fm) fillMeta();
  ta.value = fm ? fm.body : file.content;
  const pdfPane = $('.pdf-pane', ctx.body);
  const errBox = $('.build-error', ctx.body);

  let mde = null;
  if (markdown && window.EasyMDE) {
    mde = new window.EasyMDE({
      element: ta, autoDownloadFontAwesome: false, toolbar: false, status: false,
      spellChecker: false, nativeSpellcheck: true, inputStyle: 'contenteditable',
      previewRender: t => { const tt = $('.meta-title', ctx.body)?.value.trim(); return md((tt ? `# ${tt}\n\n` : '') + t); },
      placeholder: 'Start writing…',
      unorderedListStyle: '-', tabSize: 2, autofocus: false, minHeight: '200px',
      renderingConfig: { codeSyntaxHighlighting: false },
      shortcuts: { togglePreview: null, toggleSideBySide: null, toggleFullScreen: null },
    });
    buildMdToolbar($('.md-toolbar', ctx.body), mde, ctx);
  }
  const bodyValue = () => (mde ? mde.value() : ta.value);
  const getValue = () => {
    if (!fm) return bodyValue();
    metaInputs.forEach(inp => { fm.fields[inp.dataset.k] = inp.value; });
    return joinFrontMatter(fm, bodyValue());
  };
  const setValue = v => {
    if (markdown) { fm = splitFrontMatter(v); fillMeta(); v = fm.body; }
    if (mde) mde.value(v); else ta.value = v;
  };

  // ---- saving
  const setStatus = s => {
    const map = {
      saved: [icon('Check'), 'Saved', ''], saving: [icon('spinner', 'spin'), 'Saving…', ''],
      editing: [icon('Pencil'), 'Editing…', ''], error: [icon('alert'), 'Not saved', 'err'],
    };
    const [ic, label, cls] = map[s];
    status.innerHTML = `${ic}${label}`;
    status.className = `save-state ${cls}`;
  };
  async function save(force = false) {
    if (!dirty && !force) return;
    if (saving) { await saving; if (!dirty) return; }
    const content = getValue();
    setStatus('saving');
    saving = (async () => {
      try {
        const r = await api(`${P(state.project)}/file`, { method: 'PUT', body: { path: ctx.path, content, expected_mtime: force ? null : mtime } });
        mtime = r.mtime;
        if (getValue() === content) { dirty = false; setStatus('saved'); }
      } catch (e) {
        if (e.status === 409) await resolveConflict();
        else { setStatus('error'); toast(`Couldn't save: ${e.message}`, 'error'); }
      } finally { saving = null; }
    })();
    await saving;
  }
  async function resolveConflict() {
    const keepMine = await confirmDialog({
      title: 'This file was changed by someone else',
      message: 'The assistant (or another window) changed this file while you were editing. Keep your version (overwrites theirs), or cancel to load their version?',
      okText: 'Keep my version',
    });
    if (keepMine) { saving = null; dirty = true; await saveForce(); }
    else await reload();
  }
  async function saveForce() {
    const r = await api(`${P(state.project)}/file`, { method: 'PUT', body: { path: ctx.path, content: getValue() } });
    mtime = r.mtime; dirty = false; setStatus('saved');
  }
  async function reload() {
    const f = await api(`${P(state.project)}/file?path=${encodeURIComponent(ctx.path)}`);
    mtime = f.mtime;
    const pos = mde?.codemirror.getCursor();
    setValue(f.content);
    if (pos) mde.codemirror.setCursor(pos);
    dirty = false;
    setStatus('saved');
  }
  const autosave = debounce(() => save(), 1200);
  const onInput = () => { dirty = true; setStatus('editing'); autosave(); };
  if (mde) mde.codemirror.on('change', (_cm, change) => { if (change.origin !== 'setValue') onInput(); });
  else ta.addEventListener('input', onInput);
  metaInputs.forEach(inp => inp.addEventListener('input', onInput));
  const keyHandler = e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
  };
  document.addEventListener('keydown', keyHandler);
  const beforeUnload = e => { if (dirty) { save(); e.preventDefault(); e.returnValue = ''; } };
  window.addEventListener('beforeunload', beforeUnload);

  // ---- preview
  if (previewBtn) previewBtn.onclick = () => {
    window.EasyMDE.togglePreview(mde);
    const on = mde.isPreviewActive();
    previewBtn.classList.toggle('active', on);
    previewBtn.innerHTML = on ? `${icon('Pencil')}<span class="hide-md">Edit</span>` : `${icon('Eye')}<span class="hide-md">Preview</span>`;
  };

  // ---- PDF pane
  const pdfPath = siblingPath(ctx.path, 'pdf');
  const showPdf = (show = true) => {
    pdfPane.classList.toggle('hidden', !show);
    $('.split', ctx.body).classList.toggle('with-pdf', show);
    if (show) {
      $('iframe', pdfPane).src = rawUrl(state.project, pdfPath) + '#view=FitH';
      $('.pdf-label', pdfPane).textContent = pdfPath.split('/').pop();
    } else $('iframe', pdfPane).removeAttribute('src');
    setPref('pdfPane', show);
  };
  $('[data-pdf=close]', pdfPane).onclick = () => showPdf(false);
  $('[data-pdf=open]', pdfPane).onclick = () => window.open(rawUrl(state.project, pdfPath), '_blank', 'noopener');
  $('[data-pdf=download]', pdfPane).onclick = () => downloadUrl(rawUrl(state.project, pdfPath, true));
  if (pdf && state.paths.has(pdfPath) && pref('pdfPane', true) && window.innerWidth > 1100) showPdf(true);

  async function build(format) {
    await save();
    errBox.classList.add('hidden');
    const btn = format === 'pdf' ? pdfBtn : null;
    const old = btn?.innerHTML;
    if (btn) { btn.disabled = true; btn.innerHTML = `${icon('spinner', 'spin')}<span>Making PDF…</span>`; }
    else toast('Making the Word document…');
    try {
      const r = await api(`${P(state.project)}/export`, { method: 'POST', body: { path: ctx.path, format } });
      emit('files-changed');
      if (format === 'pdf') { pdfPane.dataset.mtime = String(r.mtime); showPdf(true); toast('PDF ready', 'ok', 2000); }
      else { toast(`Saved as ${r.path}`, 'ok', 5000); downloadUrl(rawUrl(state.project, r.path, true)); }
    } catch (e) {
      errBox.innerHTML = `
        <div class="err-main">${icon('alert')}<div><b>The ${format === 'pdf' ? 'PDF' : 'Word file'} couldn't be made.</b>
          <div class="err-msg">${esc(e.message)}</div></div></div>
        <div class="err-actions">
          <button class="btn btn-sm btn-primary" data-e="fix">${icon('Sparkles')}Ask the assistant to fix it</button>
          ${e.data?.log ? `<button class="btn btn-sm btn-ghost" data-e="log">Show details</button>` : ''}
          <button class="icon-btn" data-e="x" title="Dismiss">${icon('X')}</button></div>
        <pre class="err-log hidden">${esc(e.data?.log || '')}</pre>`;
      errBox.classList.remove('hidden');
      $('[data-e=x]', errBox).onclick = () => errBox.classList.add('hidden');
      const lb = $('[data-e=log]', errBox);
      if (lb) lb.onclick = () => $('.err-log', errBox).classList.toggle('hidden');
      $('[data-e=fix]', errBox).onclick = () => {
        emit('ask', { send: true, text: `When I press "Make ${format === 'pdf' ? 'PDF' : 'Word'}" on \`${ctx.path}\`, it fails with this error:\n\n${e.message}\n\nPlease fix the file so it converts, without changing its content more than needed, then make the ${format === 'pdf' ? 'PDF' : 'Word file'} again.` });
        emit('show-tab', 'chat');
      };
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = old; }
    }
  }
  if (pdfBtn) pdfBtn.onclick = () => build('pdf');

  more.onclick = () => openMenu(more, [
    pdf && state.paths.has(pdfPath) && { label: 'Show the PDF', icon: 'FileText', onClick: () => showPdf(true) },
    word && { label: 'Make a Word document', icon: 'FileType', onClick: () => build('docx') },
    markdown && { label: 'Ask assistant to proofread', icon: 'SpellCheck', onClick: () => { emit('ask', { text: `Please proofread \`${ctx.path}\` (spelling, grammar, clarity). Edit the file directly and tell me what you changed.`, send: false }); emit('show-tab', 'chat'); } },
    markdown && { label: 'Formatting help', icon: 'CircleHelp', onClick: formattingHelp },
    '-',
    { label: 'Download', icon: 'Download', onClick: () => downloadUrl(rawUrl(state.project, ctx.path, true)) },
  ]);

  // ---- external changes (e.g. the assistant edited this file)
  async function onExternalChange() {
    if (disposed) return;
    if (!state.paths.has(ctx.path)) return;
    try {
      const st = await api(`${P(state.project)}/stat?path=${encodeURIComponent(ctx.path)}`);
      if (Math.abs(st.mtime - mtime) > 0.001 && !dirty && !saving) {
        await reload();
        toast(`“${ctx.name}” was updated`, 'info', 2500);
      }
      if (pdf && !pdfPane.classList.contains('hidden')) {
        // refresh PDF if it was rebuilt by the assistant
        const ps = await api(`${P(state.project)}/stat?path=${encodeURIComponent(pdfPath)}`).catch(() => null);
        if (ps && String(ps.mtime) !== pdfPane.dataset.mtime) {
          if (pdfPane.dataset.mtime) $('iframe', pdfPane).src = rawUrl(state.project, pdfPath) + '#view=FitH';
          pdfPane.dataset.mtime = String(ps.mtime);
        }
      }
    } catch { /* file may have been removed */ }
  }

  return {
    flush: () => save(),
    onExternalChange,
    dispose() {
      disposed = true;
      document.removeEventListener('keydown', keyHandler);
      window.removeEventListener('beforeunload', beforeUnload);
      mde?.toTextArea();
    },
  };
}

// ---- YAML header <-> simple fields. Only one-line title/author/date values become fields;
// anything else (lists, bibliography:, header-includes:, ...) is kept exactly as written.
const META_KEYS = ['title', 'author', 'date'];
function unquote(v) {
  if (v.startsWith('"') && v.endsWith('"') && v.length > 1) { try { return JSON.parse(v); } catch { return v.slice(1, -1); } }
  if (v.startsWith("'") && v.endsWith("'") && v.length > 1) return v.slice(1, -1).replace(/''/g, "'");
  return v;
}
function splitFrontMatter(text) {
  const fields = { title: '', author: '', date: '' };
  const m = text.match(/^---[ \t]*\r?\n([\s\S]*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/);
  if (!m) return { fields, rest: [], simple: new Set(META_KEYS), body: text };
  const lines = m[1].split(/\r?\n/);
  const rest = [];
  const simple = new Set();
  lines.forEach((line, i) => {
    const km = line.match(/^(title|author|date):[ \t]*(.*)$/);
    const next = lines[i + 1] ?? '';
    const val = km ? km[2].trim() : '';
    if (km && !/^[|>[{&*!]/.test(val) && !/^([ \t]|- )/.test(next)) { fields[km[1]] = unquote(val); simple.add(km[1]); }
    else rest.push(line);
  });
  for (const k of META_KEYS) if (!rest.some(l => l.startsWith(k + ':'))) simple.add(k);
  return { fields, rest, simple, body: text.slice(m[0].length).replace(/^\r?\n/, '') };
}
function joinFrontMatter(fm, body) {
  const lines = META_KEYS.filter(k => fm.simple.has(k) && fm.fields[k].trim())
    .map(k => `${k}: ${JSON.stringify(fm.fields[k].trim())}`);
  lines.push(...fm.rest);
  if (!lines.some(l => l.trim())) return body;
  return `---\n${lines.join('\n')}\n---\n\n${body}`;
}

function buildMdToolbar(bar, mde, ctx) {
  const E = window.EasyMDE;
  const cm = mde.codemirror;
  const insert = (before, after = '', placeholder = '') => {
    const sel = cm.getSelection() || placeholder;
    cm.replaceSelection(before + sel + after);
    if (!cm.getSelection() && placeholder) {
      const c = cm.getCursor();
      cm.setSelection({ line: c.line, ch: c.ch - after.length - placeholder.length }, { line: c.line, ch: c.ch - after.length });
    }
    cm.focus();
  };
  const items = [
    ['Heading1', 'Big heading', () => E.toggleHeading1(mde)],
    ['Heading2', 'Smaller heading', () => E.toggleHeading2(mde)],
    '|',
    ['Bold', 'Bold (Ctrl+B)', () => E.toggleBold(mde)],
    ['Italic', 'Italic (Ctrl+I) — e.g. species names', () => E.toggleItalic(mde)],
    ['Superscript', 'Superscript (e.g. 10^6^)', () => insert('^', '^', '2')],
    ['Subscript', 'Subscript (e.g. H~2~O)', () => insert('~', '~', '2')],
    '|',
    ['List', 'Bullet list', () => E.toggleUnorderedList(mde)],
    ['ListOrdered', 'Numbered list', () => E.toggleOrderedList(mde)],
    ['TextQuote', 'Quote', () => E.toggleBlockquote(mde)],
    '|',
    ['Table', 'Insert table', () => insert('\n\n| Column 1 | Column 2 | Column 3 |\n|---|---|---|\n| | | |\n| | | |\n\n')],
    ['Image', 'Insert picture', e => imageMenu(e.currentTarget, cm, ctx)],
    ['Link', 'Insert link', () => E.drawLink(mde)],
    ['Sigma', 'Insert formula (LaTeX math)', () => insert('$', '$', 'x^2')],
    ['Minus', 'Page break (PDF)', () => insert('\n\n\\newpage\n\n')],
    '|',
    ['Undo2', 'Undo', () => E.undo(mde)],
    ['Redo2', 'Redo', () => E.redo(mde)],
  ];
  for (const it of items) {
    if (it === '|') { bar.append(h('<span class="tb-sep"></span>')); continue; }
    const [ic, title, fn] = it;
    const b = h(`<button class="tb-btn" title="${esc(title)}" aria-label="${esc(title)}">${icon(ic)}</button>`);
    b.onmousedown = e => e.preventDefault(); // keep editor selection
    b.onclick = fn;
    bar.append(b);
  }
}

function imageMenu(anchor, cm, ctx) {
  const noteDir = ctx.folder;
  const rel = p => {
    if (!noteDir) return p;
    if (p.startsWith(noteDir + '/')) return p.slice(noteDir.length + 1);
    return '../'.repeat(noteDir.split('/').length) + p;
  };
  const insertImg = p => {
    const cap = p.split('/').pop().replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
    cm.replaceSelection(`\n\n![${cap}](<${rel(p)}>){ width=80% }\n\n`);
    cm.focus();
  };
  const imgs = [...state.paths].filter(p => fileType(p) === 'image' && !/\.(tiff?|bmp)$/i.test(p)).slice(0, 15);
  openMenu(anchor, [
    { label: 'Upload a picture…', icon: 'Upload', onClick: () => {
      const inp = h('<input type="file" accept="image/*" hidden>');
      document.body.append(inp);
      inp.onchange = async () => {
        const dir = noteDir ? `${noteDir}/images` : 'images';
        const files = await uploadFiles(inp.files, dir, { open: false });
        inp.remove();
        if (files[0]) insertImg(files[0].path);
      };
      inp.click();
    } },
    imgs.length && '-',
    ...imgs.map(p => ({ label: p, icon: 'Image', onClick: () => insertImg(p) })),
  ]);
}

function formattingHelp() {
  {
    const d = customDialog(`
      <div class="help">
        <div class="dlg-head"><h3>Formatting cheat-sheet</h3><button class="icon-btn" data-close>${icon('X')}</button></div>
        <p class="hint">You can use the toolbar buttons, or type these directly. They become proper formatting in the PDF.</p>
        <table class="cheat">
          <tr><td><code># Heading</code></td><td>Big heading (<code>##</code> smaller)</td></tr>
          <tr><td><code>**bold**</code> · <code>*italic*</code></td><td><b>bold</b> · <i>italic</i></td></tr>
          <tr><td><code>H~2~O</code> · <code>10^6^</code></td><td>H<sub>2</sub>O · 10<sup>6</sup></td></tr>
          <tr><td><code>- item</code></td><td>Bullet list (<code>1.</code> for numbered)</td></tr>
          <tr><td><code>$p &lt; 0.05$</code></td><td>Math / formulas (LaTeX)</td></tr>
          <tr><td><code>\\SI{37}{\\celsius}</code></td><td>Units, nicely spaced (PDF only)</td></tr>
          <tr><td><code>\\ce{NaCl}</code></td><td>Chemical formulas (PDF only)</td></tr>
          <tr><td><code>[@smith2020]</code></td><td>Citation — needs a <code>references.bib</code> file next to the note</td></tr>
          <tr><td><code>\\newpage</code></td><td>Start a new page in the PDF</td></tr>
          <tr><td>The lines between <code>---</code> at the top</td><td>Title, author and date of the PDF</td></tr>
        </table>
      </div>`, { wide: true });
    $('[data-close]', d).onclick = () => d.close();
  }
}

// ====================================================================== PDF
function pdfView(ctx) {
  const notePath = siblingPath(ctx.path, 'md');
  if (state.paths.has(notePath)) {
    const b = h(`<button class="btn btn-sm btn-soft" title="Edit the note this PDF was made from">${icon('NotebookPen')}<span class="hide-md">Edit note</span></button>`);
    b.onclick = () => emit('open-file', { path: notePath });
    ctx.actions.append(b);
  }
  askButton(ctx, 'Summarize', `Please read \`${ctx.path}\` and write a short summary note (key question, methods, main findings, limitations) as a new Markdown file.`);
  downloadButton(ctx);
  const open = h(`<button class="icon-btn" title="Open in a new tab">${icon('ExternalLink')}</button>`);
  open.onclick = () => window.open(rawUrl(state.project, ctx.path), '_blank', 'noopener');
  ctx.actions.append(open);
  ctx.body.innerHTML = `<iframe class="full-frame" title="${esc(ctx.name)}" src="${rawUrl(state.project, ctx.path)}"></iframe>`;
  let shownMtime = null;
  return {
    async onExternalChange() {
      const st = await api(`${P(state.project)}/stat?path=${encodeURIComponent(ctx.path)}`).catch(() => null);
      if (st && shownMtime !== null && st.mtime !== shownMtime) $('iframe', ctx.body).src = rawUrl(state.project, ctx.path);
      if (st) shownMtime = st.mtime;
    },
  };
}

// ====================================================================== image
function imageView(ctx) {
  downloadButton(ctx);
  ctx.body.innerHTML = `<div class="image-view"><img alt="${esc(ctx.name)}" src="${rawUrl(state.project, ctx.path)}"></div>`;
  return {};
}

// ====================================================================== tables
async function tableView(ctx, sheet = null) {
  if (!sheet) {
    askButton(ctx, 'Analyse', `Please look at the data in \`${ctx.path}\`. Describe what it contains, then suggest (but don't run yet) the analyses that make sense for it.`);
    downloadButton(ctx);
  }
  ctx.body.innerHTML = `<div class="doc-message">${icon('spinner', 'spin big')}<p>Loading table…</p></div>`;
  const t = await api(`${P(state.project)}/table?path=${encodeURIComponent(ctx.path)}${sheet ? `&sheet=${encodeURIComponent(sheet)}` : ''}`);
  ctx.body.innerHTML = `
    ${t.sheets && t.sheets.length > 1 ? `<div class="sheet-tabs">${t.sheets.map(s => `<button class="sheet-tab ${s === t.sheet ? 'active' : ''}">${esc(s)}</button>`).join('')}</div>` : ''}
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th class="rownum">#</th>${t.columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead>
      <tbody>${t.rows.map((r, i) => `<tr><td class="rownum">${i + 1}</td>${r.map(v => `<td>${v === null ? '<span class="na">—</span>' : esc(v)}</td>`).join('')}</tr>`).join('')}</tbody>
    </table></div>
    <div class="table-foot hint">${t.truncated ? `Showing the first ${t.rows.length} rows${t.total_rows ? ` of ${t.total_rows}` : ''}.` : `${t.rows.length} rows`} · ${t.columns.length} columns · This is a preview; ask the assistant to change or analyse the data.</div>`;
  ctx.body.querySelectorAll('.sheet-tab').forEach(b => { b.onclick = () => tableView(ctx, b.textContent); });
  return {};
}

// ====================================================================== Word / PowerPoint
async function officeView(ctx) {
  if (['docx', 'odt', 'rtf'].includes(ctx.ext)) {
    const b = h(`<button class="btn btn-sm btn-soft" title="Make an editable copy as a note">${icon('NotebookPen')}<span class="hide-md">Edit as note</span></button>`);
    b.onclick = () => importAsNote(ctx.path);
    ctx.actions.append(b);
  }
  askButton(ctx, 'Ask about it', `About \`${ctx.path}\`: `);
  downloadButton(ctx);
  ctx.body.innerHTML = `<div class="doc-message">${icon('spinner', 'spin big')}<p>Preparing a preview…</p><p class="hint">The first time can take a few seconds.</p></div>`;
  const url = `${P(state.project)}/preview-pdf?path=${encodeURIComponent(ctx.path)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('A preview of this document could not be created.');
  if (state.openFile !== ctx.path) return {};
  ctx.body.innerHTML = `<iframe class="full-frame" title="${esc(ctx.name)}" src="${url}"></iframe>`;
  return {};
}

// ====================================================================== other
function otherView(ctx) {
  downloadButton(ctx);
  const node = findNode(ctx.path);
  ctx.body.innerHTML = `<div class="doc-message">${fileIcon(ctx.name).replace('class="icon', 'class="icon big')}
    <p><b>${esc(ctx.name)}</b></p><p class="hint">${esc(TYPE_LABEL[ctx.type])}${node?.size != null ? ` · ${size(node.size)}` : ''} — no preview for this kind of file.</p>
    <button class="btn btn-soft" id="askOther">${icon('Sparkles')}Ask the assistant about it</button></div>`;
  $('#askOther', ctx.body).onclick = () => { emit('ask', { text: `About \`${ctx.path}\`: ` }); emit('show-tab', 'chat'); };
  return {};
}

function findNode(path) {
  let found = null;
  (function walk(n) { if (n.path === path) found = n; (n.children || []).forEach(walk); })(state.tree || {});
  return found;
}
