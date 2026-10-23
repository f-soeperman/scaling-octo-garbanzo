/* Op pad! — page wiring: search, routing, GPS, screens, voice, wake lock, touch lock.
   The navigation maths lives in nav.js (OpPadNav). Everything personal
   (favourites, settings) stays in this phone's localStorage — never in the repo. */
(function () {
  'use strict';

  const Nav = window.OpPadNav;
  const $ = id => document.getElementById(id);

  const PDOK_URL = 'https://api.pdok.nl/bzk/locatieserver/search/v3_1/free';
  const PHOTON_URL = 'https://photon.komoot.io/api/';
  const NL_BBOX = '3.2,50.7,7.3,53.6';   // the whole country, west,south,east,north
  const VALHALLA_URL = 'https://valhalla1.openstreetmap.de/route';
  const FAV_COLORS = ['#FFC628', '#9FD8C2', '#FFB59A', '#BFD7FF'];
  const REROUTE_COOLDOWN_MS = 15000;
  const RELOCK_MS = 15000;
  const UNLOCK_HOLD_MS = 3000;
  const FALLBACK_SPEED = 15 / 3.6;   // bakfiets cruising speed for the ETA when standing still

  // Hidden test feed: ?sim (or ?sim=<km/h>) rides the fetched route instead of GPS.
  const params = new URLSearchParams(location.search);
  const SIM_KMH = params.has('sim') ? (parseFloat(params.get('sim')) || 15) : null;

  // ── storage (fails soft: private mode, blocked storage) ─────────────
  function load(key, fallback) {
    try { const v = JSON.parse(localStorage.getItem(key)); return v == null ? fallback : v; }
    catch (e) { return fallback; }
  }
  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* not persisted */ }
  }

  const settings = Object.assign({ voice: true, chime: true, readyM: 100, nowM: 15, nowS: 4 },
    load('oppad.settings', {}));
  let favs = load('oppad.favs', []);
  let dest = load('oppad.last', null);    // {name, lat, lon}

  // ── main screen: settings ───────────────────────────────────────────
  function bindSettings() {
    const bind = (id, key, isBool) => {
      const el = $(id);
      if (isBool) el.checked = settings[key]; else el.value = settings[key];
      el.addEventListener('change', () => {
        if (isBool) settings[key] = el.checked;
        else {
          const v = parseFloat(el.value);
          if (!isNaN(v) && v > 0) settings[key] = v; else el.value = settings[key];
        }
        save('oppad.settings', settings);
      });
    };
    bind('set-voice', 'voice', true);
    bind('set-chime', 'chime', true);
    bind('set-ready', 'readyM');
    bind('set-now-m', 'nowM');
    bind('set-now-s', 'nowS');
    $('btn-settings').addEventListener('click', () => {
      const panel = $('settings');
      panel.hidden = !panel.hidden;
      $('btn-settings').setAttribute('aria-expanded', String(!panel.hidden));
    });
  }

  // ── main screen: search — addresses (PDOK) + places (Photon/OSM) ───
  // PDOK knows every Dutch address but no places (museums, playgrounds,
  // shops); Photon searches OpenStreetMap by name. Both run in parallel and
  // each fails soft, so one service down still leaves the other.
  let searchTimer = null, searchSeq = 0;

  function parsePoint(wkt) {
    const m = /POINT\(([-\d.]+) ([-\d.]+)\)/.exec(wkt || '');
    return m ? { lon: parseFloat(m[1]), lat: parseFloat(m[2]) } : null;
  }

  async function searchAddresses(q) {
    const url = PDOK_URL + '?' + new URLSearchParams({
      q, rows: '5', fl: 'weergavenaam,type,centroide_ll',
      fq: 'type:(adres OR weg OR postcode OR woonplaats)',
    });
    const res = await fetch(url);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    return ((data.response && data.response.docs) || []).map(d => {
      const pt = parsePoint(d.centroide_ll);
      return pt && { name: d.weergavenaam, lat: pt.lat, lon: pt.lon };
    }).filter(Boolean);
  }

  async function searchPlaces(q) {
    const url = PHOTON_URL + '?' + new URLSearchParams({ q, limit: '5', bbox: NL_BBOX });
    const res = await fetch(url);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    return (data.features || []).map(f => {
      const p = f.properties || {}, c = f.geometry && f.geometry.coordinates;
      if (!c || !p.name) return null;     // nameless hits are plain addresses: PDOK has those
      const where = [p.street && [p.street, p.housenumber].filter(Boolean).join(' '), p.city]
        .filter(Boolean).join(', ');
      return { name: where ? p.name + ', ' + where : p.name, lat: c[1], lon: c[0] };
    }).filter(Boolean);
  }

  async function search(q) {
    const seq = ++searchSeq;
    const [places, addrs] = await Promise.allSettled([searchPlaces(q), searchAddresses(q)]);
    if (seq !== searchSeq) return;
    if (places.status === 'rejected' && addrs.status === 'rejected') {
      showMsg('Zoeken lukt nu niet. Is er internet?');
      return;
    }
    hideMsg();
    const seen = new Set();
    const hits = [].concat(places.value || [], addrs.value || []).filter(h => {
      const k = h.name.toLowerCase();
      return seen.has(k) ? false : (seen.add(k), true);
    });
    showSuggestions(hits.slice(0, 8));
  }

  function showSuggestions(hits) {
    const list = $('suggestions');
    list.textContent = '';
    for (const h of hits) {
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = h.name;
      b.addEventListener('click', () => {
        choose(h);
        $('q').value = '';
        list.hidden = true;
      });
      li.appendChild(b);
      list.appendChild(li);
    }
    list.hidden = !list.children.length;
  }

  function bindSearch() {
    const q = $('q');
    q.addEventListener('input', () => {
      clearTimeout(searchTimer);
      const v = q.value.trim();
      if (v.length < 3) { $('suggestions').hidden = true; return; }
      searchTimer = setTimeout(() => search(v), 350);
    });
    q.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        const first = $('suggestions').querySelector('button');
        if (first) first.click();
        q.blur();
      }
    });
    document.addEventListener('click', e => {
      if (!e.target.closest('.search')) $('suggestions').hidden = true;
    });
  }

  // ── main screen: chosen destination + favourites ────────────────────
  function choose(d) {
    dest = d;
    save('oppad.last', d);
    hideMsg();
    renderMain();
  }

  function renderMain() {
    $('chosen').hidden = !dest;
    if (dest) $('chosen-name').textContent = dest.name;
    const isFav = dest && favs.some(f => f.lat === dest.lat && f.lon === dest.lon);
    $('btn-fav').hidden = !!isFav;
    $('fav-form').hidden = true;
    $('btn-go').disabled = !dest;

    const list = $('fav-list');
    list.textContent = '';
    favs.forEach((f, i) => {
      const row = document.createElement('div');
      row.className = 'fav';
      const pick = document.createElement('button');
      pick.type = 'button';
      pick.className = 'fav-pick' + (dest && f.lat === dest.lat && f.lon === dest.lon ? ' active' : '');
      const av = document.createElement('span');
      av.className = 'fav-avatar';
      av.style.background = FAV_COLORS[i % FAV_COLORS.length];
      av.textContent = (f.label || '?').charAt(0).toUpperCase();
      const txt = document.createElement('span');
      txt.className = 'fav-text';
      const n = document.createElement('span'); n.className = 'fav-name'; n.textContent = f.label;
      const a = document.createElement('span'); a.className = 'fav-addr'; a.textContent = f.name;
      txt.append(n, a);
      pick.append(av, txt);
      pick.addEventListener('click', () => choose({ name: f.name, lat: f.lat, lon: f.lon }));
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'fav-del';
      del.setAttribute('aria-label', f.label + ' verwijderen');
      del.textContent = '×';
      del.addEventListener('click', () => {
        favs = favs.filter(x => x !== f);
        save('oppad.favs', favs);
        renderMain();
      });
      row.append(pick, del);
      list.appendChild(row);
    });
    $('fav-empty').hidden = favs.length > 0;
  }

  function bindFavs() {
    $('btn-fav').addEventListener('click', () => {
      $('fav-form').hidden = false;
      $('fav-name').value = '';
      $('fav-name').focus();
    });
    const saveFav = () => {
      const label = $('fav-name').value.trim();
      if (!label || !dest) return;
      favs.push({ label, name: dest.name, lat: dest.lat, lon: dest.lon });
      save('oppad.favs', favs);
      renderMain();
    };
    $('fav-save').addEventListener('click', saveFav);
    $('fav-name').addEventListener('keydown', e => { if (e.key === 'Enter') saveFav(); });
  }

  function showMsg(text) { $('main-msg').textContent = text; $('main-msg').hidden = false; }
  function hideMsg() { $('main-msg').hidden = true; }

  // ── routing (Valhalla, bicycle) ─────────────────────────────────────
  async function fetchRoute(from, to) {
    const req = {
      locations: [{ lat: from.lat, lon: from.lon }, { lat: to.lat, lon: to.lon }],
      costing: 'bicycle',
      // A loaded bakfiets is slow and wide: prefer cycle paths, avoid hills.
      costing_options: { bicycle: { bicycle_type: 'City', cycling_speed: 15, use_roads: 0.2, use_hills: 0.1 } },
      directions_options: { language: 'nl-NL', units: 'kilometers' },
    };
    // GET with ?json= keeps it a simple CORS request (no preflight).
    const res = await fetch(VALHALLA_URL + '?json=' + encodeURIComponent(JSON.stringify(req)));
    if (!res.ok) throw new Error('route HTTP ' + res.status);
    return Nav.parseValhalla(await res.json());
  }

  // ── position: GPS, or the hidden test feed ──────────────────────────
  function currentPosition() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error('geen GPS'));
      navigator.geolocation.getCurrentPosition(
        p => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
        reject, { enableHighAccuracy: true, timeout: 20000, maximumAge: 10000 });
    });
  }

  let watchId = null, simTimer = null;

  function startPositions() {
    if (SIM_KMH) {
      const v = SIM_KMH / 3.6;
      let along = 0, last = Date.now();
      simTimer = setInterval(() => {
        const t = Date.now();
        along += v * (t - last) / 1000;
        last = t;
        const p = Nav.pointAt(ride.route, along);
        onFix({ lat: p[0], lon: p[1], t, speed: v });
      }, 500);
      return;
    }
    watchId = navigator.geolocation.watchPosition(
      p => onFix({ lat: p.coords.latitude, lon: p.coords.longitude, t: p.timestamp || Date.now(), speed: p.coords.speed }),
      () => { /* keep the last screen; GPS usually comes back */ },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 30000 });
  }

  function stopPositions() {
    if (watchId != null) navigator.geolocation.clearWatch(watchId);
    if (simTimer) clearInterval(simTimer);
    watchId = null; simTimer = null;
  }

  // ── the ride ────────────────────────────────────────────────────────
  let ride = null, lastScreen = null, rerouting = false, lastReroute = 0;

  async function startRide() {
    if (!dest) return;
    hideMsg();
    const go = $('btn-go');
    go.disabled = true;
    $('go-label').textContent = 'Route zoeken...';
    unlockAudio();           // must happen inside the tap
    requestWakeLock();
    try {
      const here = await currentPosition();
      const route = await fetchRoute(here, dest);
      ride = new Nav.Ride(route, { readyM: settings.readyM, nowM: settings.nowM, nowS: settings.nowS });
      lastScreen = null;
      setLock(true);
      render(ride.update({ lat: here.lat, lon: here.lon, t: Date.now(), speed: null }));
      startPositions();
    } catch (e) {
      releaseWakeLock();
      showMsg(e && e.code === 1
        ? 'Op pad! heeft je locatie nodig. Sta locatie toe voor deze site en probeer opnieuw.'
        : 'Er kwam geen route. Controleer het adres en het internet, en probeer opnieuw.');
    } finally {
      go.disabled = !dest;
      $('go-label').textContent = 'Copiloot, jij bent!';
    }
  }

  async function reroute(fix) {
    rerouting = true;
    lastReroute = Date.now();
    try {
      const route = await fetchRoute({ lat: fix.lat, lon: fix.lon }, dest);
      if (ride) ride.setRoute(route);
    } catch (e) { /* try again after the cooldown */ }
    rerouting = false;
  }

  function onFix(fix) {
    if (!ride) return;
    const st = ride.update(fix);
    if (st.reroute && !rerouting && Date.now() - lastReroute > REROUTE_COOLDOWN_MS) reroute(fix);
    render(st);
  }

  function endRide() {
    stopPositions();
    releaseWakeLock();
    setLock(false);
    ride = null;
    showView('v-main');
    renderMain();
  }

  // ── rendering ───────────────────────────────────────────────────────
  const VIEWS = { cruise: 'v-cruise', ready: 'v-ready', now: 'v-now', arrived: 'v-arrived' };

  function showView(id) {
    for (const v of ['v-main', 'v-cruise', 'v-ready', 'v-now', 'v-arrived']) $(v).hidden = v !== id;
  }

  function fmtDist(m) {
    if (m < 1000) return Math.max(0, Math.round(m / 10) * 10) + ' m';
    return (m / 1000).toFixed(1).replace('.', ',') + ' km';
  }

  function render(st) {
    // Off route: the child just keeps seeing "Rechtdoor!" while we reroute.
    const screen = st.onRoute || st.screen === 'arrived' ? st.screen : 'cruise';
    const view = $(VIEWS[screen]);
    for (const id of Object.values(VIEWS)) $(id).classList.toggle('right', st.side === 'right');

    const turnWord = st.side === 'left' ? 'linksaf' : 'rechtsaf';
    const text = !st.onRoute ? 'Route wordt aangepast...'
      : st.toTurn != null ? `Over ${fmtDist(st.toTurn)} ${turnWord}${st.street ? ' ' + st.street : ''}`
      : `Nog ${fmtDist(st.remaining)} tot de finish`;
    const mins = Math.max(1, Math.round(st.remaining / Math.max(st.speed || 0, FALLBACK_SPEED) / 60));
    for (const s of view.querySelectorAll('.strip')) {
      s.querySelector('.strip-text').textContent = text;
      s.querySelector('.strip-eta').textContent = mins + ' min';
      s.querySelector('.strip-icon').style.visibility = st.toTurn != null ? 'visible' : 'hidden';
    }

    if (screen === lastScreen) return;
    if (screen === 'now') announce(st.side);
    if (screen === 'arrived') arrive(st.stars);
    lastScreen = screen;
    showView(VIEWS[screen]);
  }

  function arrive(stars) {
    stopPositions();
    releaseWakeLock();
    setLock(false);
    const box = $('stars');
    box.textContent = '';
    const n = Math.max(1, stars);
    for (let i = 0; i < n; i++) {
      box.insertAdjacentHTML('beforeend',
        '<svg viewBox="0 0 24 24" fill="#FFC628" stroke="#1B1F3B" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5L2.5 9.4l6.6-.9z"></path></svg>');
    }
    box.setAttribute('aria-label', n === 1 ? 'Eén ster verdiend' : n + ' sterren verdiend, één per bocht');
  }

  // ── voice + chime ───────────────────────────────────────────────────
  let audioCtx = null, nlVoice = null;

  function pickVoice() {
    if (!('speechSynthesis' in window)) return;
    const voices = speechSynthesis.getVoices();
    nlVoice = voices.find(v => /^nl[-_]NL/i.test(v.lang)) || voices.find(v => /^nl/i.test(v.lang)) || null;
  }

  function unlockAudio() {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (AC && !audioCtx) audioCtx = new AC();
      if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
    } catch (e) { audioCtx = null; }
    // iOS only lets speech start from a tap; a silent utterance unlocks it for the ride.
    if ('speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(' ');
      u.volume = 0;
      speechSynthesis.speak(u);
    }
  }

  function chime() {
    if (!audioCtx) return;
    const t0 = audioCtx.currentTime;
    [[784, 0], [1047, 0.14]].forEach(([f, dt]) => {
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type = 'sine';
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t0 + dt);
      g.gain.exponentialRampToValueAtTime(0.5, t0 + dt + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dt + 0.35);
      o.connect(g).connect(audioCtx.destination);
      o.start(t0 + dt);
      o.stop(t0 + dt + 0.4);
    });
  }

  function announce(side) {
    if (settings.chime) chime();
    if (navigator.vibrate) navigator.vibrate([120, 60, 120]);   // Android only; iPhone ignores it
    if (settings.voice && 'speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(side === 'left' ? 'Links!' : 'Rechts!');
      u.lang = 'nl-NL';
      if (nlVoice) u.voice = nlVoice;
      u.rate = 0.95;
      speechSynthesis.cancel();
      setTimeout(() => speechSynthesis.speak(u), settings.chime ? 350 : 0);
    }
  }

  // ── screen wake lock ────────────────────────────────────────────────
  let wakeLock = null, wantWake = false;

  async function requestWakeLock() {
    wantWake = true;
    if (!('wakeLock' in navigator) || document.visibilityState !== 'visible') return updateWakeDots();
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; updateWakeDots(); });
    } catch (e) { wakeLock = null; }
    updateWakeDots();
  }

  function releaseWakeLock() {
    wantWake = false;
    if (wakeLock) wakeLock.release().catch(() => {});
    wakeLock = null;
    updateWakeDots();
  }

  function updateWakeDots() {
    for (const d of document.querySelectorAll('.wake-dot')) d.classList.toggle('on', !!wakeLock);
  }

  // The browser drops the lock whenever the page is hidden; take it back.
  document.addEventListener('visibilitychange', () => {
    if (wantWake && document.visibilityState === 'visible' && !wakeLock) requestWakeLock();
  });

  // ── touch lock ──────────────────────────────────────────────────────
  let holdTimer = null, relockTimer = null;

  function setLock(on) {
    clearTimeout(relockTimer);
    $('lock').hidden = !on;
    $('parent-bar').hidden = true;
  }

  function bindLock() {
    const lock = $('lock'), btn = $('lock-btn');
    // Swallow every touch on the overlay: no taps, scrolls, pinches or long-press menus.
    const block = e => e.preventDefault();
    for (const ev of ['touchstart', 'touchmove', 'touchend', 'gesturestart', 'dblclick', 'contextmenu']) {
      lock.addEventListener(ev, block, { passive: false });
    }
    const cancel = () => { clearTimeout(holdTimer); btn.classList.remove('holding'); };
    btn.addEventListener('pointerdown', e => {
      e.preventDefault();
      btn.classList.add('holding');
      holdTimer = setTimeout(() => {
        cancel();
        lock.hidden = true;
        $('parent-bar').hidden = false;
        relockTimer = setTimeout(() => { if (ride) setLock(true); }, RELOCK_MS);
      }, UNLOCK_HOLD_MS);
    });
    for (const ev of ['pointerup', 'pointercancel', 'pointerleave']) btn.addEventListener(ev, cancel);
    $('btn-relock').addEventListener('click', () => setLock(true));
    $('btn-stop').addEventListener('click', endRide);
  }

  // ── boot ────────────────────────────────────────────────────────────
  bindSettings();
  bindSearch();
  bindFavs();
  bindLock();
  $('btn-go').addEventListener('click', startRide);
  $('btn-done').addEventListener('click', endRide);
  if ('speechSynthesis' in window) {
    pickVoice();
    speechSynthesis.addEventListener('voiceschanged', pickVoice);
  }
  renderMain();
})();
