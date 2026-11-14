// Left panel: the project's files.
import { $, P, api, confirmDialog, debounce, downloadUrl, emit, esc, fileIcon, fileType, h, icon, on, openMenu, promptDialog, rawUrl, toast } from './util.js';
import { pref, setPref, state } from './state.js';

let root = null;        // panel element
let expanded = new Set();

const DRAG_TYPE = 'application/x-pokosomo-path';

export async function initFiles(container) {
  root = container;
  expanded = new Set(pref(`expanded:${state.project}`, []));
  root.innerHTML = `
    <div class="panel-head">
      <h2>Files</h2>
      <div class="spacer"></div>
      <button class="btn btn-sm btn-soft" id="btnNew" title="Create a note or folder">${icon('Plus')}New</button>
      <button class="btn btn-sm btn-soft" id="btnUpload" title="Add files from your computer">${icon('Upload')}Add files</button>
      <input type="file" id="fileInput" multiple hidden>
    </div>
    <div class="tree" id="tree" role="tree"></div>
    <div class="files-foot hint" id="filesFoot">Tip: drag files from your computer onto this panel.</div>
    <div class="drop-overlay">${icon('Upload')}<div>Drop to add to <b id="dropTarget">the project</b></div></div>`;

  $('#btnNew', root).onclick = e => openMenu(e.currentTarget, [
    { label: 'New note', icon: 'NotebookPen', onClick: () => newNote(state.currentDir) },
    { label: 'New folder', icon: 'FolderPlus', onClick: () => newFolder(state.currentDir) },
  ]);
  const input = $('#fileInput', root);
  $('#btnUpload', root).onclick = () => input.click();
  input.onchange = () => { if (input.files.length) uploadFiles(input.files, state.currentDir); input.value = ''; };

  // Drag & drop from the computer anywhere on the panel
  let depth = 0;
  root.addEventListener('dragenter', e => {
    if (!e.dataTransfer.types.includes('Files')) return;
    depth++;
    root.classList.add('dropping');
    $('#dropTarget', root).textContent = state.currentDir ? `“${state.currentDir}”` : 'the project';
  });
  root.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; root.classList.remove('dropping'); } });
  root.addEventListener('dragover', e => { e.preventDefault(); });
  root.addEventListener('drop', e => {
    e.preventDefault();
    depth = 0;
    root.classList.remove('dropping');
    if (e.dataTransfer.files.length && !e.target.closest('.tree-row.dir')) uploadFiles(e.dataTransfer.files, state.currentDir);
  });

  await refreshTree();
}

const refreshSoon = debounce(() => refreshTree(), 400);
on('files-changed', () => refreshSoon());
window.addEventListener('focus', () => { if (root?.isConnected) refreshSoon(); });

export async function refreshTree() {
  if (!state.project) return;
  try {
    state.tree = await api(`${P(state.project)}/tree`);
  } catch (e) {
    if (e.status === 404) { toast('This project no longer exists.', 'error'); location.hash = '#/'; }
    return;
  }
  state.paths = new Set();
  (function walk(n) { if (n.type === 'file') state.paths.add(n.path); (n.children || []).forEach(walk); })(state.tree);
  render();
  emit('tree-updated');
}

function render() {
  const tree = $('#tree', root);
  if (!tree) return;
  tree.innerHTML = '';
  const kids = state.tree?.children || [];
  if (!kids.length) {
    tree.append(h(`<div class="tree-empty">
      ${icon('FolderOpen')}
      <p>No files yet.</p>
      <p class="hint">Add PDFs, Word files or data with <b>Add files</b>, or start a <b>New → note</b>.</p></div>`));
  }
  const rootRow = h(`<div class="tree-row dir root-row ${state.currentDir === '' ? 'current' : ''}" data-path="">${icon('House')}<span class="name">Project folder</span></div>`);
  rootRow.onclick = () => { state.currentDir = ''; render(); };
  wireDrop(rootRow, '');
  if (kids.length) tree.append(rootRow);
  for (const c of kids) renderNode(c, tree, 0);
}

function renderNode(node, parent, depth) {
  const isDir = node.type === 'dir';
  const open = isDir && expanded.has(node.path);
  const row = h(`
    <div class="tree-row ${isDir ? 'dir' : 'file'} ${state.openFile === node.path ? 'active' : ''} ${isDir && state.currentDir === node.path ? 'current' : ''}"
         style="--depth:${depth}" data-path="${esc(node.path)}" draggable="true" role="treeitem" tabindex="0" title="${esc(node.name)}">
      <span class="chev">${isDir ? icon(open ? 'ChevronDown' : 'ChevronRight') : ''}</span>
      ${fileIcon(node.name, isDir, open)}
      <span class="name">${esc(node.name)}</span>
      <button class="icon-btn row-menu" title="More">${icon('more')}</button>
    </div>`);
  row.onclick = e => {
    if (e.target.closest('.row-menu')) return;
    if (isDir) {
      if (open) expanded.delete(node.path); else expanded.add(node.path);
      setPref(`expanded:${state.project}`, [...expanded]);
      state.currentDir = node.path;
      render();
    } else {
      state.currentDir = node.path.includes('/') ? node.path.slice(0, node.path.lastIndexOf('/')) : '';
      emit('open-file', { path: node.path });
      emit('show-tab', 'doc');
    }
  };
  row.onkeydown = e => { if (e.key === 'Enter') row.click(); };
  $('.row-menu', row).onclick = e => { e.stopPropagation(); itemMenu(e.currentTarget, node); };
  row.oncontextmenu = e => { e.preventDefault(); itemMenu(row, node); };
  row.addEventListener('dragstart', e => {
    e.dataTransfer.setData(DRAG_TYPE, node.path);
    e.dataTransfer.effectAllowed = 'move';
  });
  if (isDir) wireDrop(row, node.path);
  parent.append(row);
  if (open) for (const c of node.children || []) renderNode(c, parent, depth + 1);
}

function wireDrop(row, dirPath) {
  row.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); row.classList.add('drop-here'); });
  row.addEventListener('dragleave', () => row.classList.remove('drop-here'));
  row.addEventListener('drop', async e => {
    e.preventDefault();
    e.stopPropagation();
    row.classList.remove('drop-here');
    root.classList.remove('dropping');
    const moving = e.dataTransfer.getData(DRAG_TYPE);
    if (moving) {
      if (moving === dirPath) return;
      try {
        const r = await api(`${P(state.project)}/move`, { method: 'POST', body: { path: moving, dest_dir: dirPath } });
        if (state.openFile === moving) emit('open-file', { path: r.path });
        expanded.add(dirPath);
        await refreshTree();
      } catch (err) { toast(err.message, 'error'); }
    } else if (e.dataTransfer.files.length) {
      uploadFiles(e.dataTransfer.files, dirPath);
    }
  });
}

function itemMenu(anchor, node) {
  const isDir = node.type === 'dir';
  const t = fileType(node.name);
  openMenu(anchor, [
    !isDir && { label: 'Open', icon: 'Eye', onClick: () => emit('open-file', { path: node.path }) },
    isDir && { label: 'New note here', icon: 'NotebookPen', onClick: () => newNote(node.path) },
    isDir && { label: 'New folder here', icon: 'FolderPlus', onClick: () => newFolder(node.path) },
    t === 'word' && { label: 'Turn into editable note', icon: 'NotebookPen', onClick: () => importAsNote(node.path) },
    { label: isDir ? 'Ask assistant about this folder' : 'Ask assistant about this', icon: 'Sparkles',
      onClick: () => { emit('ask', { text: `About ${isDir ? 'the folder' : ''} \`${node.path}\`: ` }); emit('show-tab', 'chat'); } },
    '-',
    { label: 'Rename', icon: 'Pencil', onClick: () => renameItem(node) },
    !isDir && { label: 'Download', icon: 'Download', onClick: () => downloadUrl(rawUrl(state.project, node.path, true)) },
    '-',
    { label: 'Delete', icon: 'Trash2', danger: true, onClick: () => deleteItem(node) },
  ]);
}

// ------------------------------------------------------------------ actions
function joinPath(dir, name) { return dir ? `${dir}/${name}` : name; }

export async function newNote(dir = '') {
  let name = await promptDialog({ title: 'New note', label: 'Name', value: 'Untitled note', okText: 'Create',
    hint: dir ? `It will be created in “${dir}”.` : '' });
  if (!name) return;
  if (!/\.(md|markdown|txt|tex)$/i.test(name)) name += '.md';
  const title = name.replace(/\.(md|markdown|txt)$/i, '');
  const today = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
  const content = name.endsWith('.md')
    ? `---\ntitle: "${title.replace(/"/g, "'")}"\ndate: "${today}"\n---\n\n` : '';
  try {
    const r = await api(`${P(state.project)}/create`, { method: 'POST', body: { path: joinPath(dir, name), kind: 'file', content } });
    if (dir) expanded.add(dir);
    await refreshTree();
    emit('open-file', { path: r.path });
  } catch (e) { toast(e.message, 'error'); }
}

async function newFolder(dir = '') {
  const name = await promptDialog({ title: 'New folder', label: 'Name', placeholder: 'e.g. Papers', okText: 'Create' });
  if (!name) return;
  try {
    const r = await api(`${P(state.project)}/create`, { method: 'POST', body: { path: joinPath(dir, name), kind: 'dir' } });
    expanded.add(r.path);
    if (dir) expanded.add(dir);
    state.currentDir = r.path;
    await refreshTree();
  } catch (e) { toast(e.message, 'error'); }
}

async function renameItem(node) {
  const name = await promptDialog({ title: 'Rename', value: node.name, okText: 'Rename' });
  if (!name || name === node.name) return;
  try {
    const r = await api(`${P(state.project)}/rename-item`, { method: 'POST', body: { path: node.path, new_name: name } });
    await refreshTree();
    if (state.openFile === node.path) emit('open-file', { path: r.path });
  } catch (e) { toast(e.message, 'error'); }
}

async function deleteItem(node) {
  const ok = await confirmDialog({
    title: `Delete “${node.name}”?`,
    message: node.type === 'dir' ? 'The folder and everything in it will be moved to the trash.' : 'The file will be moved to the trash.',
    okText: 'Delete', danger: true,
  });
  if (!ok) return;
  try {
    await api(`${P(state.project)}/item?path=${encodeURIComponent(node.path)}`, { method: 'DELETE' });
    if (state.openFile && (state.openFile === node.path || state.openFile.startsWith(node.path + '/'))) emit('close-file');
    if (state.currentDir === node.path) state.currentDir = '';
    await refreshTree();
  } catch (e) { toast(e.message, 'error'); }
}

export async function importAsNote(path) {
  toast('Converting to an editable note…');
  try {
    const r = await api(`${P(state.project)}/import`, { method: 'POST', body: { path } });
    await refreshTree();
    emit('open-file', { path: r.path });
    toast('Done — this is an editable copy. The original is unchanged.', 'ok', 5000);
  } catch (e) { toast(e.message, 'error', 6000); }
}

export async function uploadFiles(fileList, dir = '', { open = true } = {}) {
  const files = [...fileList];
  if (!files.length) return [];
  const form = new FormData();
  form.append('dir', dir);
  files.forEach(f => form.append('files', f, f.name));
  const label = files.length === 1 ? `“${files[0].name}”` : `${files.length} files`;
  toast(`Uploading ${label}…`);
  try {
    const r = await api(`${P(state.project)}/upload`, { method: 'POST', form });
    if (dir) expanded.add(dir);
    await refreshTree();
    toast(`Added ${label}`, 'ok');
    if (open && r.files.length === 1) emit('open-file', { path: r.files[0].path });
    return r.files;
  } catch (e) {
    toast(`Upload failed: ${e.message}`, 'error');
    return [];
  }
}

on('file-opened', () => render());
