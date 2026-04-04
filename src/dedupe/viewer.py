"""Local HTTP server for browsing a dedupe plan in the browser."""

import json
import mimetypes
import os
import subprocess
import tempfile
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .planner import read_plan

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.tiff', '.gif', '.webp', '.bmp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.mpeg', '.mpg', '.avi'}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dedupe Plan Viewer</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 13px;
  background: #111;
  color: #ddd;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
#header {
  background: #0d0d0d;
  border-bottom: 1px solid #2a2a2a;
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
#header h1 { font-size: 14px; font-weight: 600; color: #fff; }
.subtitle { color: #555; font-size: 12px; }
#search {
  margin-left: auto;
  background: #1e1e1e;
  border: 1px solid #333;
  border-radius: 4px;
  padding: 4px 10px;
  color: #ddd;
  font-size: 12px;
  width: 200px;
  outline: none;
}
#search:focus { border-color: #556; }
#search::placeholder { color: #444; }
#layout { display: flex; flex: 1; overflow: hidden; }
#sidebar {
  width: 260px;
  flex-shrink: 0;
  background: #161616;
  border-right: 1px solid #222;
  overflow-y: auto;
  padding: 6px 0;
}
.tree-node { user-select: none; }
.tree-folder {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  cursor: pointer;
  border-radius: 3px;
  margin: 0 4px;
  color: #888;
}
.tree-folder:hover { background: #222; color: #ccc; }
.arrow { display: inline-block; transition: transform 0.12s; font-size: 9px; color: #444; }
.arrow.open { transform: rotate(90deg); }
.tree-folder .folder-icon { font-size: 12px; }
.tree-folder .fname { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tree-folder .fcount { font-size: 10px; color: #444; }
.tree-children { padding-left: 14px; }
.tree-children.hidden { display: none; }
.tree-file {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  cursor: pointer;
  border-radius: 3px;
  margin: 0 4px;
  color: #777;
}
.tree-file:hover { background: #1e1e1e; color: #ccc; }
.tree-file.selected { background: #1e2d1e; color: #6ab06a; }
.tree-file .file-icon { font-size: 11px; }
.tree-file .fname { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.done-badge { font-size: 10px; color: #3a8; }
#content { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: #0e0e0e; }
#welcome { flex: 1; display: flex; align-items: center; justify-content: center; color: #333; font-size: 14px; }
#detail { flex: 1; display: flex; overflow: hidden; }
#preview-panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0a0a0a;
  overflow: hidden;
}
#preview { max-width: 100%; max-height: 100%; object-fit: contain; display: none; }
#no-preview { font-size: 56px; }
#meta-panel {
  width: 300px;
  flex-shrink: 0;
  border-left: 1px solid #1e1e1e;
  overflow-y: auto;
  padding: 16px;
  background: #141414;
}
.meta-filename { font-size: 14px; font-weight: 600; color: #eee; margin-bottom: 3px; word-break: break-all; }
.meta-dest { font-size: 11px; color: #444; margin-bottom: 10px; word-break: break-all; font-family: monospace; }
.badge-done {
  display: inline-block;
  background: #142214;
  color: #3a8;
  border: 1px solid #1e401e;
  border-radius: 3px;
  padding: 2px 7px;
  font-size: 11px;
  margin-bottom: 12px;
}
.section-title {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: #444;
  margin: 14px 0 6px;
}
.meta-row { display: flex; gap: 6px; margin-bottom: 5px; font-size: 12px; }
.meta-key { color: #555; flex-shrink: 0; width: 76px; }
.meta-val { color: #bbb; flex: 1; word-break: break-all; }
.meta-val.mono { font-family: monospace; font-size: 11px; }
.path-item {
  font-family: monospace;
  font-size: 11px;
  padding: 4px 7px;
  border-radius: 3px;
  margin-bottom: 4px;
  word-break: break-all;
  background: #0d0d0d;
}
.path-item.source { color: #6ab06a; border-left: 2px solid #2a5a2a; }
.path-item.done   { color: #3a8;    border-left: 2px solid #1a5a3a; }
.path-item.dup    { color: #666;    border-left: 2px solid #2a2a2a; }
#stats-bar {
  background: #0d0d0d;
  border-top: 1px solid #1e1e1e;
  padding: 4px 16px;
  font-size: 11px;
  color: #444;
  display: flex;
  gap: 20px;
  flex-shrink: 0;
}
.stat span { color: #666; }
</style>
</head>
<body>
<div id="header">
  <h1>&#128193; Dedupe Plan Viewer</h1>
  <span class="subtitle" id="subtitle"></span>
  <input id="search" type="text" placeholder="Filter files\u2026" oninput="filterTree(this.value)">
</div>
<div id="layout">
  <div id="sidebar"><div id="tree"></div></div>
  <div id="content">
    <div id="welcome">&larr; Select a file from the tree</div>
    <div id="detail" style="display:none">
      <div id="preview-panel">
        <img id="preview" alt="preview">
        <video id="video-preview" controls style="display:none;max-width:100%;max-height:100%"></video>
        <div id="no-preview"></div>
      </div>
      <div id="meta-panel">
        <div class="meta-filename" id="mf"></div>
        <div class="meta-dest" id="md"></div>
        <div id="mbadge"></div>
        <div class="section-title">Metadata</div>
        <div id="mfields"></div>
        <div class="section-title">Sources</div>
        <div id="msources"></div>
      </div>
    </div>
  </div>
</div>
<div id="stats-bar">
  <span class="stat">Files: <span id="s-total">&ndash;</span></span>
  <span class="stat">Already at dest: <span id="s-done">&ndash;</span></span>
  <span class="stat">Duplicates: <span id="s-dups">&ndash;</span></span>
</div>
<script>
let allEntries = [];
let selectedDest = null;

async function init() {
  const data = await fetch('/api/plan').then(r => r.json());
  allEntries = data.entries;
  document.getElementById('subtitle').textContent =
    (data.sources || []).length + ' source' + ((data.sources||[]).length !== 1 ? 's' : '');
  const done = allEntries.filter(e => e.already_at_dest).length;
  const dups = allEntries.reduce((n, e) => n + (e.duplicates ? e.duplicates.length : 0), 0);
  document.getElementById('s-total').textContent = allEntries.length;
  document.getElementById('s-done').textContent = done;
  document.getElementById('s-dups').textContent = dups;
  renderTree(allEntries);
}

function buildTree(entries) {
  const root = { _folders: {}, _files: [] };
  for (const e of entries) {
    const parts = e.dest.split('/');
    let node = root;
    for (let i = 0; i < parts.length - 1; i++) {
      node._folders[parts[i]] = node._folders[parts[i]] || { _folders: {}, _files: [] };
      node = node._folders[parts[i]];
    }
    node._files.push(e);
  }
  return root;
}

function countFiles(node) {
  let n = node._files.length;
  for (const c of Object.values(node._folders)) n += countFiles(c);
  return n;
}

function renderTree(entries) {
  const container = document.getElementById('tree');
  container.innerHTML = '';
  renderNode(buildTree(entries), container, 0);
}

function renderNode(node, container, depth) {
  const pad = 8 + depth * 14;
  for (const [name, child] of Object.entries(node._folders).sort()) {
    const wrap = document.createElement('div');
    wrap.className = 'tree-node';
    const hdr = document.createElement('div');
    hdr.className = 'tree-folder';
    hdr.style.paddingLeft = pad + 'px';
    hdr.innerHTML =
      '<span class="arrow open">\u25b6</span>' +
      '<span class="folder-icon">\U0001F4C1</span>' +
      '<span class="fname">' + esc(name) + '</span>' +
      '<span class="fcount">' + countFiles(child) + '</span>';
    const kids = document.createElement('div');
    kids.className = 'tree-children';
    hdr.addEventListener('click', () => {
      kids.classList.toggle('hidden');
      hdr.querySelector('.arrow').classList.toggle('open');
    });
    wrap.appendChild(hdr);
    wrap.appendChild(kids);
    container.appendChild(wrap);
    renderNode(child, kids, depth + 1);
  }
  for (const entry of node._files) {
    const filename = entry.dest.split('/').pop();
    const el = document.createElement('div');
    el.className = 'tree-file' + (entry.dest === selectedDest ? ' selected' : '');
    el.style.paddingLeft = pad + 'px';
    el.dataset.dest = entry.dest;
    const icon = entry._type === 'video' ? '\U0001F3AC' : '\U0001F5BC\uFE0F';
    el.innerHTML =
      '<span class="file-icon">' + icon + '</span>' +
      '<span class="fname">' + esc(filename) + '</span>' +
      (entry.already_at_dest ? '<span class="done-badge">\u2713</span>' : '');
    el.addEventListener('click', () => select(entry, el));
    container.appendChild(el);
  }
}

function select(entry, el) {
  document.querySelectorAll('.tree-file.selected').forEach(e => e.classList.remove('selected'));
  el.classList.add('selected');
  selectedDest = entry.dest;
  showDetail(entry);
}

function showDetail(e) {
  document.getElementById('welcome').style.display = 'none';
  document.getElementById('detail').style.display = 'flex';

  const filename = e.dest.split('/').pop();
  document.getElementById('mf').textContent = filename;
  document.getElementById('md').textContent = e.dest;
  document.getElementById('mbadge').innerHTML = e.already_at_dest
    ? '<div class="badge-done">\u2713 Already at destination</div>' : '';

  // Preview
  const img = document.getElementById('preview');
  const vid = document.getElementById('video-preview');
  const nop = document.getElementById('no-preview');
  img.style.display = 'none';
  vid.style.display = 'none';
  nop.textContent = '';
  const mediaUrl = '/api/image?path=' + encodeURIComponent(e.best);
  if (e._type === 'video') {
    vid.style.display = 'block';
    vid.src = mediaUrl;
    vid.onerror = () => { vid.style.display = 'none'; nop.textContent = '\u26A0\uFE0F'; };
  } else {
    img.style.display = 'block';
    img.src = mediaUrl;
    img.onerror = () => { img.style.display = 'none'; nop.textContent = '\u26A0\uFE0F'; };
  }

  // Metadata rows
  const mf = document.getElementById('mfields');
  mf.innerHTML = '';
  const row = (k, v, mono) => {
    if (v == null || v === '') return;
    mf.innerHTML += '<div class="meta-row"><span class="meta-key">' + esc(k) + '</span>'
      + '<span class="meta-val' + (mono ? ' mono' : '') + '">' + esc(v) + '</span></div>';
  };
  row('Type', e._type);
  if (e._camera && e._camera !== 'unknown') row('Camera', e._camera);
  if (e.dimensions) {
    const [w, h] = e.dimensions.split('x');
    row('Dimensions', w + ' \u00d7 ' + h + ' px');
  }
  if (e.duration != null) {
    const d = e.duration;
    row('Duration', d >= 60 ? Math.floor(d/60) + 'm ' + Math.round(d%60) + 's' : d.toFixed(1) + 's');
  }
  if (e.original_date) {
    row('Date', e.original_date.replace('T',' ') + (e.date_source ? ' (' + e.date_source + ')' : ''));
  }
  if (e.hash) row('Hash', e.hash.substring(0, 16) + '\u2026', true);
  if (e.latitude != null && e.longitude != null) {
    const lat = e.latitude.toFixed(5), lon = e.longitude.toFixed(5);
    const url = 'https://maps.apple.com/?ll=' + lat + ',' + lon + '&q=Photo';
    mf.innerHTML += '<div class="meta-row"><span class="meta-key">Location</span>'
      + '<span class="meta-val mono"><a href="' + url + '" target="_blank" style="color:#4a9;text-decoration:none">'
      + lat + ', ' + lon + ' \u2197</a></span></div>';
  }

  // Sources
  const ms = document.getElementById('msources');
  ms.innerHTML = '';
  const pathEl = (p, cls) => {
    ms.innerHTML += '<div class="path-item ' + cls + '" title="' + esc(p) + '">' + esc(p) + '</div>';
  };
  pathEl(e.best, e.already_at_dest ? 'done' : 'source');
  if (e.duplicates && e.duplicates.length) {
    ms.innerHTML += '<div class="section-title" style="margin-top:8px">Duplicates (' + e.duplicates.length + ')</div>';
    e.duplicates.forEach(d => pathEl(d, 'dup'));
  }
}

function filterTree(q) {
  q = q.toLowerCase().trim();
  renderTree(q ? allEntries.filter(e => e.dest.toLowerCase().includes(q)) : allEntries);
  if (selectedDest) {
    const el = document.querySelector('[data-dest="' + selectedDest + '"]');
    if (el) el.classList.add('selected');
  }
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

init().catch(console.error);
</script>
</body>
</html>
"""


def _flatten_entries(plan: dict) -> list[dict]:
    entries = []
    for file_type, camera_groups in plan.get("files", {}).items():
        for camera, group_entries in camera_groups.items():
            for entry in group_entries:
                entries.append({**entry, "_type": file_type, "_camera": camera})
    return entries


def _heic_to_jpeg(path: str) -> bytes | None:
    """Convert HEIC to JPEG in memory using sips. Original file is never modified."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp_path = tmp.name
        result = subprocess.run(
            ['sips', '-s', 'format', 'jpeg', path, '--out', tmp_path],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0:
            return Path(tmp_path).read_bytes()
    except Exception:
        pass
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return None


def serve(plan_path: str, port: int = 8421) -> None:
    plan = read_plan(plan_path)
    entries = _flatten_entries(plan)
    plan_json = json.dumps({"entries": entries, "sources": plan.get("sources", [])})

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # suppress per-request logs

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                self._send(_HTML.encode(), "text/html; charset=utf-8")
            elif parsed.path == "/api/plan":
                self._send(plan_json.encode(), "application/json")
            elif parsed.path == "/api/image":
                params = urllib.parse.parse_qs(parsed.query)
                self._serve_image(params.get("path", [""])[0])
            else:
                self.send_error(404)

        def _send(self, data: bytes, content_type: str):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)

        def _serve_image(self, path: str):
            p = Path(path)
            if not p.exists() or not p.is_file() or p.suffix.lower() not in MEDIA_EXTENSIONS:
                self.send_error(404)
                return
            if p.suffix.lower() in {'.heic', '.heif'}:
                data = _heic_to_jpeg(path)
                if data:
                    self._send(data, "image/jpeg")
                    return
                self.send_error(415)
                return
            mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
            data = p.read_bytes()
            self._send(data, mime)

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Plan viewer running at {url}  (Ctrl+C to stop)")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
