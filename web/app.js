const state = {
  config: null, lat: null, lng: null, radius: 1000, mode: 'area', nonce: 0,
  map: null, markers: [], selectedId: null, lock: false, lastItems: [], retries: 0,
  originMarker: null, minRating: 0, menuTarget: null, originSource: 'default', lastQuery: null, menuFix: null,
  lastMeta: null, originLabel: null, originLabelKey: null, showClassicOnMap: false, classicMarkers: [],
};

const $ = (sel) => document.querySelector(sel);

const token = () => {
  let t = localStorage.getItem('df-token');
  if (!t) {
    t = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
    localStorage.setItem('df-token', t);
  }
  return t;
};

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));

async function api(path, params = {}) {
  const qs = new URLSearchParams(params);
  const resp = await fetch(`${path}?${qs}`, { headers: { 'X-Client-Token': token() } });
  if (!resp.ok) {
    const err = new Error(`${path} ${resp.status}`);
    err.status = resp.status;
    err.retryAfter = Number(resp.headers.get('Retry-After') || 0);
    try { err.data = await resp.json(); } catch (e) { err.data = null; }
    throw err;
  }
  return resp.json();
}

function wgs84ToGcj02(lat, lng) {
  // 浏览器定位是 WGS-84，高德底图/POI 是 GCJ-02，不转换会整体偏几百米
  if (lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271) return { lat, lng };
  const a = 6378245.0;
  const ee = 0.00669342162296594323;
  const tLat = (x, y) => -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
    + (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3
    + (20 * Math.sin(y * Math.PI) + 40 * Math.sin(y / 3 * Math.PI)) * 2 / 3
    + (160 * Math.sin(y / 12 * Math.PI) + 320 * Math.sin(y * Math.PI / 30)) * 2 / 3;
  const tLng = (x, y) => 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
    + (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3
    + (20 * Math.sin(x * Math.PI) + 40 * Math.sin(x / 3 * Math.PI)) * 2 / 3
    + (150 * Math.sin(x / 12 * Math.PI) + 300 * Math.sin(x / 30 * Math.PI)) * 2 / 3;
  let dLat = tLat(lng - 105, lat - 35);
  let dLng = tLng(lng - 105, lat - 35);
  const radLat = lat / 180 * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - ee * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  dLat = (dLat * 180) / ((a * (1 - ee)) / (magic * sqrtMagic) * Math.PI);
  dLng = (dLng * 180) / (a / sqrtMagic * Math.cos(radLat) * Math.PI);
  return { lat: lat + dLat, lng: lng + dLng };
}

function pos() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve(wgs84ToGcj02(p.coords.latitude, p.coords.longitude)),
      () => resolve(null), { timeout: 8000 });
  });
}

function telHtml(tel) {
  if (!tel) return '';
  const numbers = String(tel).split(/[;,、\s]+/).filter((x) => x.trim());
  if (!numbers.length) return '';
  const links = numbers.map((n) => `<a class="tel" href="tel:${esc(n)}">${esc(n)}</a>`).join(' / ');
  return `<div class="meta tel-row">📞 ${links}</div>`;
}

function renderCard(pick, meta, source) {
  const card = $('#daily-card');
  if (!pick) { card.innerHTML = '<div class="notice">今天没有可选的结果</div>'; return; }
  const rating = pick.rating ? `· ${pick.rating} 分` : '';
  const cost = pick.cost ? `· 人均 ¥${pick.cost}` : '';
  const addr = pick.address ? `${esc(pick.address)} · ` : '';
  const address = `<div class="meta">${addr}<span class="coord">${pick.lat.toFixed(5)}, ${pick.lng.toFixed(5)}</span></div>`;
  card.innerHTML = `
    <div class="name">${esc(pick.name)}</div>
    <div class="meta">${pick.distance ?? '?'}m ${rating} ${cost}</div>
    ${address}
    ${telHtml(pick.tel)}
    <div class="actions">
      <button class="btn primary" data-nav="${pick.id}">去这里</button>
      <button class="btn" data-locate="${pick.id}">📍 地图定位</button>
      <button class="btn" id="btn-again">换一换</button>
    </div>`;
  card.querySelector('[data-nav]').onclick = () => navigate(pick);
  card.querySelector('[data-locate]').onclick = () => {
    select(pick);
    toast(`地图上标出了：${pick.name}`);
  };
  card.querySelector('#btn-again').onclick = () => {
    if (source === 'list') cycleFromList();
    else { state.nonce += 1; loadToday(); }
  };
  if (meta && meta.degraded) {
    card.insertAdjacentHTML('beforeend', `<div class="notice">${meta.degraded}</div>`);
  }
  if (meta && meta.stale) {
    card.insertAdjacentHTML('beforeend', '<div class="notice">显示的是缓存结果</div>');
  }
}

function renderDaily(pick, meta) {
  renderCard(pick, meta, 'daily');
}

function cycleFromList() {
  const items = state.lastItems || [];
  if (!items.length) { state.nonce += 1; loadToday(); return; }
  const idx = items.findIndex((p) => p.id === state.selectedId);
  const next = items[(idx + 1) % items.length];
  select(next);
}

function renderList(items) {
  const list = $('#list');
  const inClassic = state.mode === 'classic';
  list.innerHTML = items.map((p) => `
    <div class="item" data-id="${p.id}">
      <div class="item-main">
        <div>${inClassic ? '<span class="star-item">⭐</span> ' : ''}${esc(p.name)}</div>
        <div class="sub">${p.distance ?? '?'}m ${p.rating ? p.rating + ' 分' : '暂无评分'}${p.tel ? ' · 📞' : ''}</div>
      </div>
      ${inClassic ? `<button class="item-del" data-del="${p.id}" title="删除">🗑</button>` : ''}
    </div>`).join('');
  list.querySelectorAll('.item').forEach((el) => {
    const item = items.find((p) => p.id === el.dataset.id);
    el.onclick = () => select(item);
    el.oncontextmenu = (e) => { e.preventDefault(); addClassic(item); };
    const del = el.querySelector('.item-del');
    if (del) del.onclick = (e) => { e.stopPropagation(); openDeleteDialog(item); };
  });
}

function renderMarkers(items) {
  // 默认不在地图上铺满标记，只有右侧选中某家时才落地一个标记
  state.lastItems = items;
  if (state.selectedId && !items.some((p) => p.id === state.selectedId)) {
    state.selectedId = null;
    renderSelectedMarker(null);
  }
}

function renderSelectedMarker(poi) {
  if (!state.map || !window.AMap) return;
  state.map.remove(state.markers);
  state.markers = [];
  if (!poi) return;
  const marker = new AMap.Marker({
    position: [poi.lng, poi.lat], title: poi.name, anchor: 'bottom-center', zIndex: 110, extData: poi,
  });
  marker.on('click', () => select(poi));
  marker.on('rightclick', () => {
    const p = state.map.lngLatToContainer(marker.getPosition());
    showMapMenu(p, marker.getPosition(), poi);
  });
  state.markers.push(marker);
  state.map.add(marker);
}

function ensureMap() {
  if (state.map || !window.AMap) return;
  $('#map-fallback').hidden = true;
  $('#map').hidden = false;
  state.map = new AMap.Map('map', { center: [state.lng, state.lat], zoom: 15, viewMode: '2D' });
  state.map.on('rightclick', (e) => {
    showMapMenu(e.pixel, e.lnglat, nearestMarker(e.pixel));
  });
  state.map.on('click', handleMapClick);
  renderOrigin();
  renderMarkers(state.lastItems || []);
  updateOriginBadge();
  const selected = (state.lastItems || []).find((p) => p.id === state.selectedId);
  if (selected) renderSelectedMarker(selected);
  if (state.showClassicOnMap) renderClassicMarkers();
}

function updateOriginBadge() {
  const el = $('#origin-badge');
  if (!el) return;
  const src = state.originSource === 'geo' ? '定位' : state.originSource === 'manual' ? '右键设置' : '默认点';
  const coords = `${state.lat.toFixed(5)}, ${state.lng.toFixed(5)}`;
  const place = state.originLabel || '（定位中…）';
  el.innerHTML = `
    <div class="text">
      <div class="place">📍 ${esc(place)}</div>
      <div class="sub-coords">${coords} · ${src}</div>
    </div>
    <button class="locate-me" type="button">用我的定位</button>`;
  el.querySelector('.locate-me').onclick = async () => {
    const geo = await pos();
    if (!geo) { toast('拿不到定位权限，请右键地图手动设置出发点'); return; }
    state.lat = geo.lat;
    state.lng = geo.lng;
    state.originSource = 'geo';
    if (state.map) state.map.setCenter([state.lng, state.lat]);
    renderOrigin();
    toast('出发点已改为当前位置');
    loadToday();
  };
}

async function refreshOriginLabel() {
  const key = `${state.lat.toFixed(4)},${state.lng.toFixed(4)}`;
  if (state.originLabelKey === key) { updateOriginBadge(); return; }
  state.originLabelKey = key;
  state.originLabel = null;
  updateOriginBadge();
  try {
    const body = await api('/api/regeo', { lat: state.lat, lng: state.lng });
    if (state.originLabelKey !== key) return;
    state.originLabel = body.data.label || body.data.address || '';
  } catch (e) {
    if (state.originLabelKey !== key) return;
    state.originLabel = '';
  }
  updateOriginBadge();
}

function renderOrigin() {
  updateOriginBadge();
  refreshOriginLabel();
  if (!state.map || !window.AMap) return;
  const pos = [state.lng, state.lat];
  if (!state.originMarker) {
    state.originMarker = new AMap.Marker({
      position: pos, anchor: 'center', zIndex: 120, content: '<div class="origin-dot"></div>',
    });
    state.map.add(state.originMarker);
  } else {
    state.originMarker.setPosition(pos);
  }
}

let toastTimer = null;
function toast(text) {
  let el = $('#toast');
  if (!el) { el = document.createElement('div'); el.id = 'toast'; document.body.appendChild(el); }
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

function positionRatingMenu() {
  const menu = $('#rating-menu');
  const footer = $('#panel footer');
  const btn = $('#btn-weighted');
  const f = footer.getBoundingClientRect();
  const b = btn.getBoundingClientRect();
  const wasHidden = menu.hidden;
  menu.hidden = false; // 先显示才能量到宽度
  const w = menu.offsetWidth || 150;
  let left = b.left - f.left + (b.width - w) / 2;
  left = Math.min(Math.max(left, 4), Math.max(4, f.width - w - 4));
  menu.style.left = `${Math.round(left)}px`;
  menu.style.bottom = `${Math.round(f.bottom - b.top + 8)}px`;
  menu.style.top = 'auto';
  menu.hidden = wasHidden;
}

function nearestMarker(pixel) {
  if (!state.map || !pixel) return null;
  let best = null;
  let bestDist = 26;
  state.markers.forEach((m) => {
    const p = state.map.lngLatToContainer(m.getPosition());
    const d = Math.hypot(p.x - pixel.x, p.y - pixel.y);
    if (d < bestDist) { bestDist = d; best = m.getExtData(); }
  });
  return best;
}

function showMapMenu(pixel, lnglat, poi) {
  state.menuTarget = { lnglat, poi };
  const menu = $('#map-menu');
  $('#mm-rest').textContent = poi
    ? `⭐ 加入经典馆子：${poi.name}`
    : '⭐ 加入经典馆子（按此处识别店名）';
  const fixBtn = $('#mm-fix');
  const fixTarget = poi || (state.lastItems || []).find((p) => p.id === state.selectedId) || null;
  state.menuFix = fixTarget;
  fixBtn.hidden = !fixTarget;
  if (fixTarget) fixBtn.textContent = `📌 把「${fixTarget.name}」的位置校正到这里`;
  const pane = $('#map-pane').getBoundingClientRect();
  menu.hidden = false;
  menu.style.left = `${Math.round(Math.min(Math.max(8, pixel.x), pane.width - 210))}px`;
  menu.style.top = `${Math.round(Math.min(Math.max(8, pixel.y), pane.height - 92))}px`;
}

function closeMapMenu() {
  const menu = $('#map-menu');
  if (menu) menu.hidden = true;
  state.menuTarget = null;
  state.menuFix = null;
}

function refreshCurrent() {
  if (state.lastQuery) search(state.lastQuery);
  else loadToday();
}

function removeClassicMarkers() {
  if (!state.map || !window.AMap) { state.classicMarkers = []; return; }
  state.map.remove(state.classicMarkers);
  state.classicMarkers = [];
}

async function renderClassicMarkers() {
  if (!state.map || !window.AMap) return;
  removeClassicMarkers();
  if (!state.showClassicOnMap) return;
  try {
    const body = await api('/api/classics');
    const items = body.data.items || [];
    state.classicMarkers = items.map((c) => {
      const m = new AMap.Marker({
        position: [c.lng, c.lat],
        content: '<div class="star-marker">⭐</div>',
        anchor: 'center',
        zIndex: 90,
        extData: {
          id: c.poiid, name: c.name, lat: c.lat, lng: c.lng,
          rating: c.rating, cost: c.cost, type: c.type, address: c.address,
        },
      });
      m.on('click', () => select(m.getExtData()));
      m.on('rightclick', () => {
        const p = state.map.lngLatToContainer(m.getPosition());
        showMapMenu(p, m.getPosition(), m.getExtData());
      });
      return m;
    });
    state.map.add(state.classicMarkers);
  } catch (e) {
    toast('经典馆子位置加载失败');
  }
}

function bindMapMenu() {
  $('#mm-origin').onclick = () => {
    const t = state.menuTarget;
    if (!t) return;
    state.lat = t.lnglat.lat;
    state.lng = t.lnglat.lng;
    state.originSource = 'manual';
    if (state.map) state.map.setCenter([state.lng, state.lat]);
    renderOrigin();
    closeMapMenu();
    toast('出发点已改到这里');
    loadToday();
  };
  $('#mm-rest').onclick = async () => {
    const t = state.menuTarget;
    if (!t) return;
    if (t.poi) {
      addClassic(t.poi);
      closeMapMenu();
      return;
    }
    const lat = t.lnglat.lat;
    const lng = t.lnglat.lng;
    closeMapMenu();
    toast('正在识别这个位置的商家…');
    let info = { label: '', address: '', poiName: '', poiId: '', poiDistance: null };
    try {
      const body = await api('/api/regeo', { lat, lng });
      info = body.data || info;
    } catch (e) { /* 识别失败就留空让用户手填 */ }
    const guess = info.poiName || info.label || '';
    const bits = [];
    if (info.address) bits.push(info.address);
    bits.push(`${lat.toFixed(6)}, ${lng.toFixed(6)}`);
    if (info.poiDistance) bits.push(`最近的店约 ${info.poiDistance} 米`);
    openNameDialog(guess, bits.join(' · '), (name) => {
      if (!name) return;
      const keepPoiid = info.poiId && guess && name === guess;
      addClassicByCoords(name, lat, lng, keepPoiid ? info.poiId : null);
    });
  };
  $('#mm-fix').onclick = async () => {
    const t = state.menuTarget;
    const target = state.menuFix;
    if (!t || !target) return;
    const payload = { poiid: target.id, lat: t.lnglat.lat, lng: t.lnglat.lng };
    closeMapMenu();
    try {
      const resp = await fetch('/api/fixes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Client-Token': token() },
        body: JSON.stringify(payload),
      });
      toast(resp.ok ? `已校正「${target.name}」的位置` : `校正失败（${resp.status}）`);
    } catch (e) {
      toast('校正失败，请检查网络');
    }
    state.selectedId = null;
    refreshCurrent();
  };
  document.addEventListener('click', (e) => {
    const menu = $('#map-menu');
    if (menu && !menu.hidden && !menu.contains(e.target)) closeMapMenu();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMapMenu(); });
}

async function addClassicByCoords(name, lat, lng, poiId) {
  const payload = { name, lat, lng };
  if (poiId) payload.poiid = poiId;
  try {
    const resp = await fetch('/api/classics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-Token': token() },
      body: JSON.stringify(payload),
    });
    if (resp.ok) afterClassicAdd(name);
    else toast(`加入失败（${resp.status}）`);
  } catch (e) {
    toast('加入失败，请检查网络');
  }
}

function hidePoiPopup() {
  const pop = $('#poi-popup');
  if (pop) pop.hidden = true;
}

function renderPoiPopup(poi, pixel, click) {
  const pop = $('#poi-popup');
  const body = $('#poi-body');
  const rating = poi.rating ? `${poi.rating} 分` : '';
  const cost = poi.cost ? `人均 ¥${poi.cost}` : '';
  const meta = [rating, cost].filter(Boolean).join(' · ');
  const tel = poi.tel ? `<div class="poi-line">📞 ${telHtml(poi.tel).replace(/^<div[^>]*>|<\/div>$/g, '')}</div>` : '';
  body.innerHTML = `
    <div class="poi-name">${esc(poi.name)}</div>
    ${poi.type ? `<div class="poi-line">${esc(poi.type)}</div>` : ''}
    ${meta ? `<div class="poi-line">${meta}</div>` : ''}
    ${poi.address ? `<div class="poi-line">${esc(poi.address)}</div>` : ''}
    ${tel}
    <div class="poi-line">${poi.lat.toFixed(5)}, ${poi.lng.toFixed(5)}</div>
    <div class="poi-actions">
      <button class="btn primary" data-act="nav">去这里</button>
      <button class="btn" data-act="classic">加入经典馆子</button>
      <button class="btn" data-act="origin">设为出发点</button>
    </div>`;
  body.querySelector('[data-act="nav"]').onclick = () => navigate(poi);
  body.querySelector('[data-act="classic"]').onclick = () => {
    if (poi.id.startsWith('pt:')) {
      openNameDialog(poi.name, '这个点位没有对应的商家档案，确认名字后加入', (name) => {
        if (name) addClassicByCoords(name, poi.lat, poi.lng, null);
      });
    } else {
      addClassic(poi);
    }
    hidePoiPopup();
  };
  body.querySelector('[data-act="origin"]').onclick = () => {
    state.lat = click.lat;
    state.lng = click.lng;
    state.originSource = 'manual';
    if (state.map) state.map.setCenter([state.lng, state.lat]);
    renderOrigin();
    hidePoiPopup();
    toast('出发点已改到这里');
    loadToday();
  };

  const pane = $('#map-pane').getBoundingClientRect();
  pop.hidden = false;
  const w = pop.offsetWidth || 240;
  const h = pop.offsetHeight || 150;
  pop.style.left = `${Math.round(Math.min(Math.max(8, pixel.x - w / 2), pane.width - w - 8))}px`;
  pop.style.top = `${Math.round(Math.min(Math.max(8, pixel.y - h - 12), pane.height - h - 8))}px`;
  $('#poi-close').onclick = hidePoiPopup;
}

async function handleMapClick(e) {
  hidePoiPopup();
  closeMapMenu();
  if (!e || !e.lnglat || !e.pixel) return;
  const click = { lat: e.lnglat.lat, lng: e.lnglat.lng };
  const pop = $('#poi-popup');
  const body = $('#poi-body');
  pop.hidden = false;
  body.innerHTML = '<div class="poi-line">正在识别这个位置的商家…</div>';
  pop.style.left = `${Math.round(e.pixel.x)}px`;
  pop.style.top = `${Math.round(e.pixel.y - 60)}px`;
  try {
    const resp = await api('/api/poi-nearby', { lat: click.lat, lng: click.lng });
    const data = resp.data;
    if (!data || !data.poi) { hidePoiPopup(); toast('这个位置没识别到商家'); return; }
    renderPoiPopup(data.poi, e.pixel, click);
  } catch (err) {
    hidePoiPopup();
    toast(`识别失败（${err.status || '网络'}）`);
  }
}

function syncClassicCheck() {
  const chk = $('#chk-classic');
  if (chk) chk.checked = state.showClassicOnMap;
}

function setMode(mode) {
  state.mode = mode;
  state.nonce += 1;
  const map = { area: '#btn-random', classic: '#btn-classic', weighted: '#btn-weighted' };
  Object.entries(map).forEach(([m, sel]) => {
    const el = $(sel);
    if (el) el.classList.toggle('active', m === mode);
  });
  const row = $('#radius-row');
  if (row) row.classList.toggle('disabled', mode === 'classic');
  loadToday();
}

async function afterClassicAdd(name) {
  // 加入后立即把右侧列表刷成经典馆子，让新增的这家马上可见
  try {
    const body = await api('/api/classics');
    const count = (body.data.items || []).length;
    toast(`已加入经典馆子：${name}（共 ${count} 家）`);
  } catch (e) {
    toast(`已加入经典馆子：${name}`);
  }
  if (state.showClassicOnMap) renderClassicMarkers();  // 新店立即在地图上显示星星
  if (state.mode === 'classic') loadToday();
  else setMode('classic');
}

function openDeleteDialog(poi) {
  if (!poi) return;
  const dlg = $('#delete-dialog');
  $('#delete-sub').textContent = poi.name;
  $('#delete-password').value = '';
  dlg.hidden = false;
  $('#delete-password').focus();

  const close = () => { dlg.hidden = true; };
  const ok = async () => {
    const pwd = $('#delete-password').value.trim();
    if (!pwd) { $('#delete-password').focus(); return; }
    dlg.hidden = true;
    try {
      const resp = await fetch(`/api/classics/${encodeURIComponent(poi.id)}`, {
        method: 'DELETE',
        headers: { 'X-Admin-Password': pwd },
      });
      if (resp.ok) {
        toast(`已删除：${poi.name}`);
        state.selectedId = null;
        if (state.showClassicOnMap) renderClassicMarkers();  // 删除后地图星星即时移除
        if (state.mode === 'classic') loadToday();
        else refreshCurrent();
      } else if (resp.status === 403) {
        toast('密码错误，无法删除');
      } else {
        toast(`删除失败（${resp.status}）`);
      }
    } catch (e) {
      toast('删除失败，请检查网络');
    }
  };
  $('#delete-cancel').onclick = close;
  $('#delete-ok').onclick = ok;
  $('#delete-password').onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); ok(); }
    if (e.key === 'Escape') { e.preventDefault(); close(); }
  };
}

function openNameDialog(prefill, subtitle, onSubmit) {
  const dlg = $('#name-dialog');
  const input = $('#dialog-name');
  $('#dialog-sub').textContent = subtitle || '';
  input.value = prefill || '';
  dlg.hidden = false;
  input.focus();
  input.select();

  const close = () => { dlg.hidden = true; onSubmit(null); };
  const ok = () => {
    const name = input.value.trim();
    if (!name) { input.focus(); return; }
    dlg.hidden = true;
    onSubmit(name);
  };
  $('#dialog-cancel').onclick = close;
  $('#dialog-ok').onclick = ok;
  input.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); ok(); }
    if (e.key === 'Escape') { e.preventDefault(); close(); }
  };
}

async function addClassic(poi) {
  if (!poi || !poi.id) return;
  try {
    const resp = await fetch('/api/classics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-Token': token() },
      body: JSON.stringify({ poiid: poi.id }),
    });
    if (resp.ok) afterClassicAdd(poi.name);
    else toast(`加入失败（${resp.status}）`);
  } catch (e) {
    toast('加入失败，请检查网络');
  }
}

function showFallback() {
  if (state.map) return;
  $('#map').hidden = true;
  $('#map-fallback').hidden = false;
  if (!$('#map-fallback').querySelector('img')) {
    const img = document.createElement('img');
    img.src = `/api/staticmap?lat=${state.lat}&lng=${state.lng}`;
    img.alt = '附近地图';
    img.style.cssText = 'width:100%;height:100%;object-fit:cover';
    $('#map-fallback').appendChild(img);
  }
}

function select(poi) {
  if (!poi) return;
  state.selectedId = poi.id;
  $('#list').querySelectorAll('.item').forEach((el) => {
    el.classList.toggle('active', el.dataset.id === poi.id);
  });
  renderCard(poi, state.lastMeta || null, 'list');
  renderSelectedMarker(poi);
  if (state.map) state.map.setCenter([poi.lng, poi.lat]);
}

function buildNavUrl(poi) {
  const to = `${poi.lng},${poi.lat},${encodeURIComponent(poi.name || '目的地')}`;
  // 出发点仍是默认点时不要传 from，交给高德用设备定位，避免从几千公里外规划路线
  const known = state.originSource === 'geo' || state.originSource === 'manual';
  const from = known ? `${state.lng},${state.lat},${encodeURIComponent('出发点')}` : '';
  const src = encodeURIComponent(state.config ? state.config.siteName : 'daily-food');
  return `https://uri.amap.com/navigation?from=${from}&to=${to}&mode=walk&callnative=1&src=${src}`;
}

function navigate(poi) {
  if (/MicroMessenger/i.test(navigator.userAgent)) {
    alert('微信内无法唤起高德，请点右上角「在浏览器中打开」后再试。');
    return;
  }
  if (state.originSource === 'default') {
    toast('出发点还是默认点，已交给高德使用手机定位；想固定起点可右键地图设置');
  }
  window.location.href = buildNavUrl(poi);
}

async function loadToday() {
  if (state.lock) return;
  state.lock = true;
  try {
    const params = { lat: state.lat, lng: state.lng, mode: state.mode,
                     radius: state.radius, nonce: state.nonce };
    if (state.mode === 'weighted' && state.minRating) params.min_rating = state.minRating;
    const body = await api('/api/today', params);
    state.lastMeta = body.meta;
    state.selectionActive = false;
    renderDaily(body.data.pick, body.meta);
    renderList(body.data.candidates);
    renderMarkers(body.data.candidates);
    state.retries = 0;
  } catch (e) {
    if (e.status === 429 && (state.retries || 0) < 2) {
      state.retries = (state.retries || 0) + 1;
      $('#daily-card').innerHTML = '<div class="notice">点得太快了，稍后自动重试…</div>';
      setTimeout(() => loadToday(), 2500);
    } else if (e.status === 429) {
      $('#daily-card').innerHTML = '<div class="notice">点得太快了，请等一会儿再试</div>';
    } else if (e.status === 404) {
      const code = e.data && e.data.meta && e.data.meta.degraded;
      $('#daily-card').innerHTML = code === 'no_match'
        ? '<div class="notice">没有达到这个评分的餐厅，换个档位试试</div>'
        : '<div class="notice">这个区域暂时没有可选餐厅</div>';
    } else {
      $('#daily-card').innerHTML = '<div class="notice">加载失败，稍后再试</div>';
    }
  } finally {
    state.lock = false;
  }
}

async function search(q, expand = false) {
  state.lastQuery = q;
  try {
    // 搜索不受距离档位约束：按当前城市全城搜索
    const body = await api('/api/search', {
      q, lat: state.lat, lng: state.lng, city: 'true', expand: expand ? 'true' : 'false',
    });
    state.lastMeta = body.meta;
    const items = body.data.items || [];
    if (!items.length) {
      $('#list').innerHTML = `<div class="notice">本市没搜到「${esc(q)}」，换个关键词试试</div>`;
      renderMarkers([]);
      return;
    }
    renderList(items);
    renderMarkers(items);
    state.selectedId = null;
    select(items[0]);
  } catch (e) {
    $('#list').innerHTML = `<div class="notice">搜索失败（${e.status || '网络'}），稍后再试</div>`;
  }
}

function initMap() {
  if (window.AMap) {
    ensureMap();
  } else {
    showFallback();
  }
}

async function boot() {
  const cfg = (await api('/api/config')).data;
  state.config = cfg;
  $('#site-name').textContent = cfg.siteName;

  const geo = await pos();
  state.lat = geo ? geo.lat : cfg.defaultCenter.lat;
  state.lng = geo ? geo.lng : cfg.defaultCenter.lng;
  state.originSource = geo ? 'geo' : 'default';
  if (!cfg.radiusOptions.includes(state.radius)) state.radius = cfg.radiusOptions[0];

  if (cfg.jsKey) {
    // serviceHost 必须是「源 + 代理前缀」的完整地址，否则 JS API 会把主机名当成路径拼出来
    window._AMapSecurityConfig = { serviceHost: `${location.origin}/_AMapService` };
    await new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = `https://webapi.amap.com/maps?v=2.0&key=${cfg.jsKey}`;
      let settled = false;
      const done = () => { if (!settled) { settled = true; resolve(); } };
      s.onload = () => { done(); if (window.AMap && !state.map) ensureMap(); };
      s.onerror = done;
      setTimeout(done, 6000);
      document.head.appendChild(s);
    });
  }
  initMap();
  updateOriginBadge();
  // 默认在地图上显示经典馆子星星
  state.showClassicOnMap = true;
  syncClassicCheck();
  renderClassicMarkers();

  const chips = [['饺子', '饺子'], ['面', '面'], ['火锅', '火锅'], ['快餐', '快餐']];
  $('#chips').innerHTML = chips
    .map(([label, q]) => `<span class="chip" data-q="${q}">${label}</span>`).join('');
  $('#chips').querySelectorAll('.chip').forEach((el) => {
    el.onclick = () => {
      $('#chips').querySelectorAll('.chip').forEach((c) => c.classList.remove('active'));
      el.classList.add('active');
      search(el.dataset.q);
    };
  });

  $('#search-form').onsubmit = (e) => {
    e.preventDefault();
    const v = $('#search-input').value.trim();
    $('#map-search-input').value = v;
    if (v.length >= 1) search(v);
  };

  $('#map-search-form').onsubmit = (e) => {
    e.preventDefault();
    const v = $('#map-search-input').value.trim();
    $('#search-input').value = v;
    if (v.length >= 1) search(v);
  };

  const modeButtons = { area: $('#btn-random'), classic: $('#btn-classic'), weighted: $('#btn-weighted') };
  modeButtons.area.onclick = () => setMode('area');
  modeButtons.classic.onclick = () => setMode('classic');
  $('#chk-classic').onchange = (e) => {
    state.showClassicOnMap = e.target.checked;
    syncClassicCheck();
    if (state.showClassicOnMap) renderClassicMarkers();
    else removeClassicMarkers();
  };

  const ratingMenu = $('#rating-menu');
  const ratingButtons = [...ratingMenu.querySelectorAll('button')];
  const closeRatingMenu = () => { ratingMenu.hidden = true; };
  const applyRatingLabel = () => {
    $('#btn-weighted').textContent = state.minRating
      ? `🏆 高分优先 ${state.minRating}+`
      : '🏆 高分优先';
  };
  ratingButtons.forEach((btn) => {
    btn.onclick = () => {
      state.minRating = Number(btn.dataset.r) || 0;
      ratingButtons.forEach((b) => b.classList.toggle('active', b === btn));
      applyRatingLabel();
      closeRatingMenu();
      setMode('weighted');
    };
  });
  modeButtons.weighted.onclick = (e) => {
    e.stopPropagation();
    if (ratingMenu.hidden) {
      positionRatingMenu();
      ratingMenu.hidden = false;
    } else {
      ratingMenu.hidden = true;
    }
  };
  document.addEventListener('click', (e) => {
    if (!ratingMenu.hidden && !ratingMenu.contains(e.target)) closeRatingMenu();
  });

  const fmtKm = (r) => (r >= 1000 ? `${r / 1000}km` : `${r}m`);
  $('#radius-row').innerHTML = cfg.radiusOptions
    .map((r) => `<span class="chip ${r === state.radius ? 'active' : ''}" data-r="${r}">${fmtKm(r)}</span>`)
    .join('');
  $('#radius-row').querySelectorAll('.chip').forEach((el) => {
    el.onclick = () => {
      state.radius = Number(el.dataset.r);
      $('#radius-row').querySelectorAll('.chip').forEach((c) => c.classList.remove('active'));
      el.classList.add('active');
      refreshCurrent();
    };
  });

  bindMapMenu();
  setMode('area');
  window.__df = { state, addClassic, toast, loadToday, toGcj: wgs84ToGcj02, buildNavUrl,
    afterClassicAdd, setMode, handleMapClick, addClassicByCoords };
}

boot().catch(() => {
  $('#daily-card').innerHTML = '<div class="notice">初始化失败</div>';
});
