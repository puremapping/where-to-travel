/* Where to Travel — 前端逻辑 */

const $ = (s) => document.querySelector(s);
const show = (el) => el.classList.remove('hidden');
const hide = (el) => el.classList.add('hidden');

let currentMotivation = null;
let map = null;
let mapLayer = null;
let lastItinerary = null;

// ---------- 初始化 ----------

async function loadStats() {
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();
    $('#stats').textContent =
      `${d.attractions} 个景区 · ${d.crowd_index} 条人流 · ${d.transport} 条交通`;
  } catch (e) { /* 静默 */ }
}

function loading(on, text) {
  const el = $('#loading');
  if (text) $('#loading-text').textContent = text;
  on ? show(el) : hide(el);
}

// ---------- 步骤一：动机分析 ----------

$('#btn-analyze').onclick = async () => {
  const text = $('#user-input').value.trim();
  if (!text) { alert('先说说你的想法吧'); return; }

  loading(true, '正在理解你的旅行想法……');
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);

    currentMotivation = d.motivation;
    renderMotivation(d);
    hide($('#step-input'));
    show($('#step-motive'));
  } catch (e) {
    alert('分析失败：' + e.message);
  } finally {
    loading(false);
  }
};

function renderMotivation(d) {
  const m = d.motivation;
  const intensity = m.primary_intensity || 3;
  const c = m.constraints || {};

  let html = `
    <div class="motive-primary">
      ${m.primary}
      <span class="intensity">强度 ${intensity}/5</span>
    </div>
    <div class="bar"><i style="width:${intensity * 20}%"></i></div>
  `;

  if (m.secondary && m.secondary.length) {
    html += `<div>次要动机：`;
    html += m.secondary.map(s => `<span class="chip on">${s}</span>`).join(' ');
    html += `</div>`;
  }

  const parts = [];
  if (c.hours) parts.push(`时长约 ${c.hours} 小时`);
  if (c.companions) parts.push(`同伴：${c.companions}`);
  if (c.note) parts.push(c.note);
  if (parts.length) {
    html += `<div class="constraints">识别到的约束：${parts.join(' · ')}</div>`;
  }

  html += `<div class="constraints" style="margin-top:14px">如果理解有偏差，点「重新描述」换个说法。</div>`;

  $('#motive-result').innerHTML = html;

  // 如果识别出时长，同步到下拉框
  if (c.hours) {
    const opt = [...$('#hours').options].find(o => parseInt(o.value) === c.hours);
    if (opt) $('#hours').value = c.hours;
  }
}

$('#btn-back').onclick = () => {
  hide($('#step-motive'));
  hide($('#step-result'));
  show($('#step-input'));
};

// ---------- 步骤二：生成行程 ----------

$('#btn-itinerary').onclick = async () => {
  if (!currentMotivation) return;

  loading(true, '正在编排行程……');
  try {
    const r = await fetch('/api/itinerary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        motivation: currentMotivation.primary,
        intensity: currentMotivation.primary_intensity || 3,
        hours: $('#hours').value || null,
      }),
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);

    lastItinerary = d;
    renderItinerary(d);
    hide($('#step-motive'));
    show($('#step-result'));
    loadReco();
  } catch (e) {
    alert('生成失败：' + e.message);
  } finally {
    loading(false);
  }
};

function renderItinerary(d) {
  // 叙述
  $('#narrative').textContent = d.narrative || '（未生成叙述）';

  // 评估
  const a = d.assessment || {};
  $('#assessment').innerHTML = `
    <div>整体强度：<span class="lvl ${a.intensity || ''}">${a.intensity || '—'}</span></div>
    ${a.strength ? `<div style="margin-top:6px">${a.strength}</div>` : ''}
    ${a.suggestion ? `<div style="margin-top:6px;color:var(--accent)">建议：${a.suggestion}</div>` : ''}
    ${d.risks && d.risks.length ? `<div class="risks">${d.risks.map(r => `<div class="risk">${r}</div>`).join('')}</div>` : ''}
  `;

  // 时间线
  const stops = d.stops || [];
  $('#timeline').innerHTML = stops.map(s => {
    let crowdBadge = '';
    if (s.crowd !== null && s.crowd !== undefined) {
      if (s.crowd >= 60) crowdBadge = `<span class="badge crowd-high">人流 ${s.crowd.toFixed(0)}</span>`;
      else if (s.crowd <= 10) crowdBadge = `<span class="badge crowd-low">人流 ${s.crowd.toFixed(0)}</span>`;
      else crowdBadge = `<span class="badge">人流 ${s.crowd.toFixed(0)}</span>`;
    }
    const metro = s.metro ? `<span class="badge">地铁 ${String(s.metro).slice(0, 12)}</span>` : '';
    const reasons = (s.reasons && s.reasons.length)
      ? `<div class="stop-reasons">${s.reasons.join('；')}</div>` : '';
    return `
      <div class="stop">
        <div class="stop-head">
          <span class="stop-time">${s.arrive}</span>
          <span class="stop-name">${s.name}</span>
          <span class="badge">${s.level || '—'}</span>
          ${crowdBadge}${metro}
        </div>
        <div class="stop-meta">${s.district || ''} · 停留约 ${s.duration_min} 分钟</div>
        ${reasons}
      </div>`;
  }).join('') + `
    <div class="stop-meta" style="margin-top:8px">
      全程约 ${d.total_distance_km} 公里（直线距离估算）
    </div>`;

  renderMap(stops);
}

function renderMap(stops) {
  if (!stops.length) return;
  if (!map) {
    map = L.map('map').setView([stops[0].lat, stops[0].lon], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap',
    }).addTo(map);
  }
  if (mapLayer) { map.removeLayer(mapLayer); }
  mapLayer = L.layerGroup().addTo(map);

  const coords = [];
  stops.forEach((s, i) => {
    if (s.lat == null || s.lon == null) return;
    coords.push([s.lat, s.lon]);
    L.marker([s.lat, s.lon])
      .bindPopup(`<b>${i + 1}. ${s.name}</b><br>${s.arrive}<br>${s.district || ''}`)
      .addTo(mapLayer);
  });
  if (coords.length > 1) {
    L.polyline(coords, { color: '#4c8dff', weight: 2.5, opacity: 0.8 }).addTo(mapLayer);
    map.fitBounds(coords, { padding: [40, 40] });
  }
  setTimeout(() => map.invalidateSize(), 100);
}

// ---------- 其他推荐 ----------

async function loadReco() {
  if (!currentMotivation) return;
  try {
    const r = await fetch('/api/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        motivation: currentMotivation.primary,
        intensity: currentMotivation.primary_intensity || 3,
        top_k: 6,
      }),
    });
    const d = await r.json();
    const used = new Set((lastItinerary?.stops || []).map(s => s.name));
    const rest = (d.items || []).filter(i => !used.has(i.name)).slice(0, 5);

    $('#reco-list').innerHTML = rest.length ? rest.map(i => `
      <div class="reco">
        <div class="reco-top">
          <span class="reco-name">${i.name}</span>
          <span class="reco-score">匹配 ${(i.score * 100).toFixed(0)}%</span>
        </div>
        <div class="stop-meta">${i.level || ''} · ${i.district || ''}</div>
        ${i.reasons && i.reasons.length ? `<div class="reco-reasons">${i.reasons.join('；')}</div>` : ''}
      </div>`).join('') : '<div class="hint">没有更多推荐了</div>';
  } catch (e) { /* 静默 */ }
}

// ---------- 示例按钮 ----------

document.querySelectorAll('button.ex').forEach(btn => {
  btn.onclick = () => {
    $('#user-input').value = btn.textContent;
    $('#user-input').focus();
  };
});

// Ctrl/Cmd + Enter 快捷提交
$('#user-input').addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') $('#btn-analyze').click();
});

loadStats();
