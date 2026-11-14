// Shared, mutable app state.
export const state = {
  project: null,        // current project name
  tree: null,           // file tree of the current project
  paths: new Set(),     // all file paths in the project (for linking)
  openFile: null,       // path of the file shown in the document panel
  currentDir: '',       // folder used for "new note", uploads
  advanced: (() => { try { return localStorage.getItem('pk.advanced') === '1'; } catch { return false; } })(),
};

export function setAdvanced(v) {
  state.advanced = v;
  try { localStorage.setItem('pk.advanced', v ? '1' : '0'); } catch { /* ignore */ }
}

export function pref(key, fallback) {
  try { const v = localStorage.getItem('pk.' + key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
}
export function setPref(key, value) {
  try { localStorage.setItem('pk.' + key, JSON.stringify(value)); } catch { /* ignore */ }
}
