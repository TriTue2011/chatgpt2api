"""Studio HTML page — served directly by FastAPI at GET /studio.

Plain HTML + CSS + vanilla JS, no build step required.
"""

STUDIO_HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VN MCP Hub — Studio</title>
<style>
  :root { --bg: #0f172a; --card: #1e293b; --border: #334155; --text: #e2e8f0;
          --muted: #94a3b8; --accent: #3b82f6; --danger: #ef4444; --ok: #22c55e; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--text);
         padding: 2rem; max-width: 960px; margin: 0 auto; }
  h1 { font-size: 1.5rem; margin-bottom: .5rem; }
  .sub { color: var(--muted); margin-bottom: 2rem; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
          padding: 1.5rem; margin-bottom: 1.5rem; }
  .card h2 { font-size: 1.1rem; margin-bottom: 1rem; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: .5rem; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; font-size: .85rem; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: .75rem; }
  .badge-ok { background: var(--ok); color: #000; }
  .badge-warn { background: #f59e0b; color: #000; }
  label { display: block; margin-bottom: .3rem; font-weight: 500; }
  input, textarea { width: 100%; padding: .6rem; background: var(--bg);
                    border: 1px solid var(--border); border-radius: 6px;
                    color: var(--text); margin-bottom: 1rem; font-family: monospace; }
  textarea { min-height: 120px; resize: vertical; }
  button { padding: .6rem 1.2rem; border: none; border-radius: 6px; cursor: pointer;
           font-weight: 500; }
  .btn-go { background: var(--accent); color: #fff; }
  .btn-del { background: var(--danger); color: #fff; }
  .toast { position: fixed; top: 1rem; right: 1rem; padding: .8rem 1.2rem;
           border-radius: 6px; color: #fff; display: none; z-index: 100; }
  .toast-ok { background: var(--ok); color: #000; }
  .toast-err { background: var(--danger); }
  .src-row { display: flex; align-items: center; justify-content: space-between;
             padding: .3rem 0; font-size: .85rem; }
  .src-row label { margin: 0; cursor: pointer; }
  .src-toggle { width: 16px; height: 16px; cursor: pointer; accent-color: var(--ok); }
  .expand-btn { background: none; border: 1px solid var(--border); color: var(--muted);
                padding: .2rem .5rem; border-radius: 4px; cursor: pointer; font-size: .75rem; }
  .expand-btn:hover { color: var(--text); border-color: var(--text); }
  .src-panel { display: none; padding: .5rem 0 0 1rem; border-top: 1px solid var(--border);
               margin-top: .5rem; }
  .src-panel.open { display: block; }
</style>
</head>
<body>
<h1>VN MCP Hub — Studio</h1>
<p class="sub">Tạo và quản lý MCP server từ file markdown. Không cần code.</p>

<div id="toast" class="toast"></div>

<div class="card">
  <h2>Tạo KB mới</h2>
  <form id="createForm">
    <label for="name">Tên collection (slug)</label>
    <input id="name" placeholder="vi_du_1" required pattern="[a-z0-9_]+" maxlength="30">
    <label for="label">Nhãn hiển thị</label>
    <input id="label" placeholder="Kho tri thức về...">
    <label for="content">Nội dung markdown</label>
    <textarea id="content" placeholder="Dán nội dung markdown vào đây..." required></textarea>
    <button type="submit" class="btn-go">Tạo MCP</button>
  </form>
</div>

<div class="card">
  <h2>Danh sách MCP</h2>
  <table>
    <thead><tr><th>Tên</th><th>Nhãn</th><th>Chunks</th><th>Cập nhật</th><th>Sources</th><th></th></tr></thead>
    <tbody id="mcpTable"><tr><td colspan="6">Đang tải...</td></tr></tbody>
  </table>
</div>

<script>
const API = '/api/studio';

async function toast(msg, ok) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast ' + (ok ? 'toast-ok' : 'toast-err');
  t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3000);
}

async function refresh() {
  const [mcpR, srcR] = await Promise.all([
    fetch(API + '/mcps'),
    fetch(API + '/sources')
  ]);
  const data = await mcpR.json();
  const srcData = await srcR.json();
  const allSources = srcData.sources || {};

  // Fetch metadata for KB collections
  const kbNames = (data.mcps || []).filter(m => m.name.startsWith('kb_')).map(m => m.name);
  const metaMap = {};
  await Promise.all(kbNames.map(async (name) => {
    try {
      const r = await fetch(API + '/collection/' + encodeURIComponent(name) + '/meta');
      metaMap[name] = await r.json();
    } catch(e) {}
  }));

  const tbody = document.getElementById('mcpTable');
  if (!data.mcps || !data.mcps.length) {
    tbody.innerHTML = '<tr><td colspan="6">Chưa có MCP động nào.</td></tr>';
    return;
  }
  tbody.innerHTML = data.mcps.map(m => {
    const builtin = m.builtin;
    const delBtn = builtin ? '' : `<button class="btn-del" onclick="del('${m.name}')">Xóa</button>`;
    const badge = builtin
      ? '<span class="badge badge-ok">built-in</span>'
      : '<span class="badge badge-warn">dynamic</span>';
    const srcCfg = allSources[m.name] || {};
    const srcCount = Object.keys(srcCfg).length;
    const srcBtn = srcCount > 0
      ? `<button class="expand-btn" onclick="toggleSources('${m.name}')">${srcCount} src</button>`
      : '';
    // Metadata column
    const meta = metaMap[m.name] || {};
    const age = meta.age || '—';
    const autoIcon = (meta.meta && meta.meta.auto_update) ? ' 🔄' : '';
    const ageBtn = m.name.startsWith('kb_')
      ? `<button class="expand-btn" onclick="showSettings('${m.name}',${meta.meta?meta.meta.update_interval_hours||168:168},${meta.meta?meta.meta.auto_update||false:false})" title="Cài đặt cập nhật">${age}${autoIcon}</button>`
      : age;
    // Source panel
    let srcPanel = '';
    if (srcCount > 0) {
      srcPanel = `<div class="src-panel" id="src-${m.name}">` +
        Object.entries(srcCfg).map(([k,v]) =>
          `<div class="src-row"><label>${k}</label><input type="checkbox" class="src-toggle" ${v?'checked':''} onchange="toggleSource('${m.name}','${k}',this.checked)"></div>`
        ).join('') + '</div>';
    }
    return `<tr>
      <td>${badge} ${m.name}</td>
      <td>${m.label || m.name}</td>
      <td>${m.chunks ?? '—'}</td>
      <td>${ageBtn}</td>
      <td>${srcBtn}</td>
      <td>${delBtn}</td>
    </tr><tr id="src-row-${m.name}" style="display:none"><td colspan="6">${srcPanel}</td></tr>`;
  }).join('');
}

function showSettings(name, interval, autoUpdate) {
  const h = prompt('Chu kỳ cập nhật (giờ):', interval);
  if (h === null) return;
  const auto = confirm('Bật tự động cập nhật? (OK=Có, Cancel=Không)');
  fetch(API + '/collection/' + encodeURIComponent(name) + '/settings', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({update_interval_hours: parseInt(h), auto_update: auto})
  }).then(r => r.json()).then(d => {
    if (d.ok) toast('Đã lưu cài đặt cho ' + name, true);
    refresh();
  });
}

function toggleSources(name) {
  const row = document.getElementById('src-row-' + name);
  const panel = document.getElementById('src-' + name);
  if (row && panel) {
    const open = row.style.display !== 'none';
    row.style.display = open ? 'none' : 'table-row';
    panel.className = 'src-panel' + (open ? '' : ' open');
  }
}

async function toggleSource(mcp, source, enabled) {
  const r = await fetch(API + '/sources/' + encodeURIComponent(mcp), {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({[source]: enabled})
  });
  if (r.ok) toast(source + ' ' + (enabled ? 'ON' : 'OFF'), true);
}

async function del(name) {
  if (!confirm(`Xóa KB '${name}'? Hành động này không thể hoàn tác.`)) return;
  const r = await fetch(API + '/kb/' + encodeURIComponent(name), { method: 'DELETE' });
  const data = await r.json();
  if (data.ok) { toast('Đã xóa ' + name, true); refresh(); }
  else { toast(data.error || 'Lỗi', false); }
}

document.getElementById('createForm').onsubmit = async (e) => {
  e.preventDefault();
  const body = JSON.stringify({
    name: document.getElementById('name').value.trim(),
    label: document.getElementById('label').value.trim(),
    content: document.getElementById('content').value,
  });
  const r = await fetch(API + '/kb', { method: 'POST', headers: {'Content-Type':'application/json'}, body });
  const data = await r.json();
  if (data.ok) {
    toast(`Đã tạo KB '${data.name}' (${data.chunks} chunks). Endpoint: /${data.name}/mcp`, true);
    document.getElementById('createForm').reset();
    refresh();
  } else {
    toast((data.errors || ['Lỗi']).join('. '), false);
  }
};

refresh();
</script>
</body>
</html>"""
