const state = {
  config: null, lat: null, lng: null, radius: 1000, mode: 'area', nonce: 0,
  map: null, markers: [], selectedId: null, lock: false, lastItems: [], retries: 0,
  originMarker: null, minRating: 0, menuTarget: null,
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

function renderDaily(pick, meta) {
  const card = $('#daily-card');
  if (!pick) { card.innerHTML = '<div class="notice">今天没有可选的结果</div>'; return; }
  const rating = pick.rating ? `· ${pick.rating} 分` : '';
  const cost = pick.cost ? `· 人均 ¥${pick.cost}` : '';
  card.innerHTML = `
    <div class="name">${pick.name}</div>
    <div class="meta">${pick.distance ?? '?'}m ${rating} ${cost}</div>
    <div class="actions">
      <button class="btn primary" data-nav="${pick.id}">去这里</button>
      <button class="btn" id="btn-again">换一换</button>
    </div>`;
  card.querySelector('[data-nav]').onclick = () => navigate(pick);
  card.querySelector('#btn-again').onclick = () => { state.nonce += 1; loadToday(); };
  if (meta && meta.degraded) {
    card.insertAdjacentHTML('beforeend', `<div class="notice">${meta.degraded}</div>`);
  }
  if (meta && meta.stale) {
    card.insertAdjacentHTML('beforeend', '<div class="notice">显示的是缓存结果</div>');
  }
}

function renderList(items) {
  const list = $('#list');
  list.innerHTML = items.map((p) => `
    <div class="item" data-id="${p.id}">
      <div>${p.name}</div>
      <div class="sub">${p.distance ?? '?'}m ${p.rating ? p.rating + ' 分' : '暂无评分'}</div>
    </div>`).join('');
  list.querySelectorAll('.item').forEach((el) => {
    const item = items.find((p) => p.id === el.dataset.id);
    el.onclick = () => select(item);
    el.oncontextmenu = (e) => { e.preventDefault(); addClassic(item); };
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
  state.map.on('click', closeMapMenu);
  renderOrigin();
  renderMarkers(state.lastItems || []);
  const selected = (state.lastItems || []).find((p) => p.id === state.selectedId);
  if (selected) renderSelectedMarker(selected);
}

function renderOrigin() {
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
    : '⭐ 输入馆子名称加入经典馆子';
  const pane = $('#map-pane').getBoundingClientRect();
  menu.hidden = false;
  menu.style.left = `${Math.round(Math.min(Math.max(8, pixel.x), pane.width - 210))}px`;
  menu.style.top = `${Math.round(Math.min(Math.max(8, pixel.y), pane.height - 92))}px`;
}

function closeMapMenu() {
  const menu = $('#map-menu');
  if (menu) menu.hidden = true;
  state.menuTarget = null;
}

function bindMapMenu() {
  $('#mm-origin').onclick = () => {
    const t = state.menuTarget;
    if (!t) return;
    state.lat = t.lnglat.lat;
    state.lng = t.lnglat.lng;
    if (state.map) state.map.setCenter([state.lng, state.lat]);
    renderOrigin();
    closeMapMenu();
    toast('出发点已改到这里');
    loadToday();
  };
  $('#mm-rest').onclick = () => {
    const t = state.menuTarget;
    if (!t) return;
    if (t.poi) {
      addClassic(t.poi);
      closeMapMenu();
    } else {
      const name = window.prompt('这家馆子叫什么？');
      closeMapMenu();
      if (name && name.trim()) addClassicByCoords(name.trim(), t.lnglat.lat, t.lnglat.lng);
    }
  };
  document.addEventListener('click', (e) => {
    const menu = $('#map-menu');
    if (menu && !menu.hidden && !menu.contains(e.target)) closeMapMenu();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMapMenu(); });
}

async function addClassicByCoords(name, lat, lng) {
  try {
    const resp = await fetch('/api/classics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-Token': token() },
      body: JSON.stringify({ name, lat, lng }),
    });
    toast(resp.ok ? `已加入经典馆子：${name}` : `加入失败（${resp.status}）`);
  } catch (e) {
    toast('加入失败，请检查网络');
  }
}

async function addClassic(poi) {
  if (!poi || !poi.id) return;
  try {
    const resp = await fetch('/api/classics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-Token': token() },
      body: JSON.stringify({ poiid: poi.id }),
    });
    toast(resp.ok ? `已加入经典馆子：${poi.name}` : `加入失败（${resp.status}）`);
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
  renderSelectedMarker(poi);
  if (state.map) state.map.setCenter([poi.lng, poi.lat]);
}

function navigate(poi) {
  if (/MicroMessenger/i.test(navigator.userAgent)) {
    alert('微信内无法唤起高德，请点右上角「在浏览器中打开」后再试。');
    return;
  }
  const to = `${poi.lng},${poi.lat},${encodeURIComponent(poi.name)}`;
  const from = state.lat ? `${state.lng},${state.lat},我的位置` : '';
  const src = encodeURIComponent(state.config ? state.config.siteName : 'daily-food');
  window.location.href = `https://uri.amap.com/navigation?from=${from}&to=${to}&mode=walk&callnative=1&src=${src}`;
}

async function loadToday() {
  if (state.lock) return;
  state.lock = true;
  try {
    const params = { lat: state.lat, lng: state.lng, mode: state.mode,
                     radius: state.radius, nonce: state.nonce };
    if (state.mode === 'weighted' && state.minRating) params.min_rating = state.minRating;
    const body = await api('/api/today', params);
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

async function search(q) {
  try {
    const body = await api('/api/search', { q, lat: state.lat, lng: state.lng, radius: state.radius });
    renderList(body.data.items);
    renderMarkers(body.data.items);
  } catch (e) {
    /* 保持原列表 */
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
    if (v.length >= 2) search(v);
  };

  $('#map-search-form').onsubmit = (e) => {
    e.preventDefault();
    const v = $('#map-search-input').value.trim();
    $('#search-input').value = v;
    if (v.length >= 2) search(v);
  };

  const modeButtons = { area: $('#btn-random'), classic: $('#btn-classic'), weighted: $('#btn-weighted') };
  const setMode = (mode) => {
    state.mode = mode;
    state.nonce += 1;
    Object.entries(modeButtons).forEach(([m, el]) => el.classList.toggle('active', m === mode));
    loadToday();
  };
  modeButtons.area.onclick = () => setMode('area');
  modeButtons.classic.onclick = () => setMode('classic');

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

  $('#radius-row').innerHTML = cfg.radiusOptions
    .map((r) => `<span class="chip ${r === state.radius ? 'active' : ''}" data-r="${r}">${r}m</span>`)
    .join('');
  $('#radius-row').querySelectorAll('.chip').forEach((el) => {
    el.onclick = () => {
      state.radius = Number(el.dataset.r);
      $('#radius-row').querySelectorAll('.chip').forEach((c) => c.classList.remove('active'));
      el.classList.add('active');
      loadToday();
    };
  });

  bindMapMenu();
  setMode('area');
  window.__df = { state, addClassic, toast, loadToday, toGcj: wgs84ToGcj02 };
}

boot().catch(() => {
  $('#daily-card').innerHTML = '<div class="notice">初始化失败</div>';
});
