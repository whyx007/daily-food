const state = {
  config: null, lat: null, lng: null, radius: 1000, mode: 'area', nonce: 0,
  map: null, markers: [], selectedId: null, lock: false,
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
  if (!resp.ok) throw new Error(`${path} ${resp.status}`);
  return resp.json();
}

function pos() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
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
    el.onclick = () => select(items.find((p) => p.id === el.dataset.id));
  });
}

function renderMarkers(items) {
  if (!state.map || !window.AMap) return;
  state.map.remove(state.markers);
  state.markers = items.slice(0, 20).map((p) => new AMap.Marker({
    position: [p.lng, p.lat], title: p.name, anchor: 'bottom-center', extData: p,
  }));
  state.map.add(state.markers);
  state.markers.forEach((m) => m.on('click', () => select(m.getExtData())));
}

function select(poi) {
  if (!poi) return;
  state.selectedId = poi.id;
  $('#list').querySelectorAll('.item').forEach((el) => {
    el.classList.toggle('active', el.dataset.id === poi.id);
  });
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
    const body = await api('/api/today', {
      lat: state.lat, lng: state.lng, mode: state.mode,
      radius: state.radius, nonce: state.nonce,
    });
    renderDaily(body.data.pick, body.meta);
    renderList(body.data.candidates);
    renderMarkers(body.data.candidates);
  } catch (e) {
    $('#daily-card').innerHTML = '<div class="notice">加载失败，稍后再试</div>';
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
  if (!window.AMap) {
    $('#map').hidden = true;
    $('#map-fallback').hidden = false;
    const img = document.createElement('img');
    img.src = `/api/staticmap?lat=${state.lat}&lng=${state.lng}`;
    img.alt = '附近地图';
    img.style.cssText = 'width:100%;height:100%;object-fit:cover';
    $('#map-fallback').appendChild(img);
    return;
  }
  state.map = new AMap.Map('map', { center: [state.lng, state.lat], zoom: 15, viewMode: '2D' });
}

async function boot() {
  const cfg = (await api('/api/config')).data;
  state.config = cfg;
  $('#site-name').textContent = cfg.siteName;

  const geo = await pos();
  state.lat = geo ? geo.lat : cfg.defaultCenter.lat;
  state.lng = geo ? geo.lng : cfg.defaultCenter.lng;

  if (cfg.jsKey) {
    window._AMapSecurityConfig = { serviceHost: cfg.securityServiceHost || location.host };
    await new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = `https://webapi.amap.com/maps?v=2.0&key=${cfg.jsKey}`;
      s.onload = resolve;
      s.onerror = resolve;
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
    if (v.length >= 2) search(v);
  };

  $('#btn-random').onclick = () => { state.mode = 'area'; state.nonce += 1; loadToday(); };
  $('#btn-classic').onclick = () => { state.mode = 'classic'; state.nonce += 1; loadToday(); };
  $('#btn-weighted').onclick = () => { state.mode = 'weighted'; state.nonce += 1; loadToday(); };

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

  loadToday();
}

boot().catch(() => {
  $('#daily-card').innerHTML = '<div class="notice">初始化失败</div>';
});
