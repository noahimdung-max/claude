/* 마크 낚시 매크로 화면. 파이썬(webapp.py)과는 window.pywebview.api (화면 -> 파이썬) 와
   window.App.push(종류, 데이터) (파이썬 -> 화면) 로 주고받음. 파이썬 없이 열면 미리보기(가짜 데이터)로 돎. */
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  const LABEL = { idle: '쉬는 중', cast: '던지는 중', wait: '입질 기다리는 중', bite: '입질!', reel: '끌어올리는 중', caught: '낚았다!' };
  const ORDER = ['cast', 'wait', 'bite', 'reel', 'caught'];
  const FISH_HEX = { '빨강': '#e53935', '주황': '#fb8c00', '노랑': '#fdd835', '초록': '#43a047', '하늘': '#29b6f6', '파랑': '#1e88e5', '보라': '#8e24aa', '분홍': '#ec407a' };
  const ADV = [
    ['subtitle_threshold', '자막 일치 기준 (0~1)', 0.5, 0.99, 0.01],
    ['bite_confirm_frames', '입질 확인 횟수 (연속)', 1, 5, 1],
    ['bite_drop_ratio', '입질: 찌가 이 비율 아래로 줄면', 0.1, 0.95, 0.05],
    ['bite_dip_px', '입질: 찌가 이만큼(px) 내려가면', 1, 30, 1],
    ['tolerance', '색 허용 오차', 5, 80, 1],
    ['deadzone_px', '바 따라가기 허용 오차(px)', 0, 30, 1],
    ['left_click_cps', '미니게임 중 좌클릭 (초당, 0=끔)', 0, 20, 1],
    ['lead_sec', '바 움직임 예측(초)', 0, 0.3, 0.01],
    ['cast_settle_sec', '던진 뒤 대기(초)', 0.5, 5, 0.1],
    ['bite_timeout_sec', '입질 최대 대기(초)', 10, 120, 5],
    ['recast_delay_sec', '다시 던지기 전 대기(초)', 0.2, 5, 0.1],
    ['start_delay_sec', '시작 버튼 후 대기(초)', 0, 10, 1],
    ['max_fails', '연속 실패 이만큼이면 멈춤', 1, 50, 1]
  ];
  const GUIDE = [
    ['처음 한 번만', [
      '마크 설정 → 접근성 → 자막 표시 켜기',
      '접근성 → 텍스트 배경 불투명도 올리기 (자막이 잘 보여야 함)',
      "'설정' → 입질 자막 → 지정하기 → 직접 낚시하다 자막 뜨면 F7",
      "미니게임 바, 낚싯대 내구도는 자동으로 찾음 (안 되면 '직접')"]],
    ['찌를 형광색으로 (리소스팩, 선택)', [
      "'설정' 의 '찌 리소스팩' 에서 분홍/연두 고르고 '리소스팩 만들기'",
      "'마크 버전'에서 쓰는 버전(26.1.2 / 26.3 / 둘 다 / 모든 버전)을 고르고 만들기. 마크 옵션 → 리소스팩 에서 맞는 팩을 켜고 맨 위로 (호환 안 됨 표시가 떠도 켜면 돼)",
      '찌가 형광색으로 보이면 성공. 찌를 색만으로 찾아서 어두운 곳·작은 창에서도 잘 잡혀',
      "서버가 리소스팩을 막거나 강제하면 안 바뀔 수 있어. 그땐 찌 색을 '기본'으로 돌려둬"]],
    ['잘 낚이게 하는 마크 설정', [
      '파티클: 최소  (물보라·거품이 찌/화면 판정을 방해함)',
      'GUI 배율이 바뀌면(자동 배율은 창 크기 따라 바뀜) 자막·바는 자동으로 맞춤. 안 맞으면 다시 지정',
      '낚시 중에는 마크 창 크기를 바꾸지 말기 (최대화든 작은 창이든 하나로 고정)',
      '밤·물속처럼 어두우면 찌 화면 모드는 어려움 → 자막 모드 사용',
      '낚싯대는 핫바에서 선택한 상태로, 물을 바라보고 시작']],
    ['낚싯대 탭 (교체·정밀 내구도·인벤)', [
      '자동 교체: 낚싯대를 넣은 핫바 칸을 눌러 고르고 켜기. 내구도 기준 아래면 다음 칸으로',
      '정밀 내구도(실험): 마크에서 F3+H(고급 툴팁) 켜기. N마리마다 인벤을 1~2초 열었다 닫음',
      '인벤 가득 참: 빈칸 기준 이하면 멈추고 디스코드 알림. 인벤 확인 때 같이 셈',
      "리소스팩으로 인벤/툴팁 모양이 바뀌면 안 될 수 있음 → '툴팁 숫자 못 읽음'이 뜨면 꺼줘"]],
    ['모루 자동 수리 (실험)', [
      '모루는 낚시 자리 바로 뒤(뒤돌면 십자선에 걸리게) 1~2칸에 두는 걸 추천',
      "낚싯대 탭 → 낚싯대 칸·실 칸 고르기 → '방향 기록하기': 물 보고 F7, 모루 보고 F7",
      "또는 감도 %(마크 설정 숫자)와 각도(뒤돌기 = 180) 넣고 '각도로 쓰기'",
      "모루 창을 빈 상태로 열고 '수리 창 위치 지정' → F7 → 칸 6곳 클릭",
      "'골드 숫자 영역'을 지정하면 수리비보다 적을 때 미리 멈추고 알림",
      '마크 설정 > 마우스 > 원시 입력 켜짐 필요. 일반 모드에서만 됨']],
    ['다른 창 쓰면서 낚시 (실험)', [
      "마크에서 F3+P 한 번 → '포커스를 잃으면 일시정지' 꺼짐",
      '마크 창은 최소화하지 말고 다른 창 뒤에 두기만',
      '마크 창 크기·위치는 지정할 때와 같게',
      "안 되면 '이 PC에선 캡처할 수 없어' 알림 → 이 기능 끄고 사용",
      "마크가 뒤로 가면 끊길 때: 비디오 설정 → '비활성 FPS 제한'을 '최소화 시'로",
      "Dynamic FPS 모드나 런처(루나·페더 등)를 쓰면 '포커스 없을 때 FPS'를 60 이상으로",
      "NVIDIA 제어판 → '백그라운드 응용 프로그램 최대 프레임 속도' 끄기",
      "윈도우 설정 → 디스플레이 → 그래픽 → javaw.exe 를 '고성능'으로"]],
    ['멈추는 경우', [
      "내구도가 정한 % 이하 (수선 낚싯대는 '안 봄')",
      '연속으로 못 낚으면 (기본 5번) 알림 띄우고 멈춤',
      '일반 모드에서 마크 창이 뒤로 가면 잠깐 멈췄다가 돌아오면 계속']],
    ['단축키', ['F8: 시작 / 정지', 'F7: 화면 위치 지정할 때 장면 찍기', 'F12: 완전 종료']]
  ];

  let cfg = {};
  let page = 'home';
  let running = false;
  let logs = [];
  let lastAnim = null;
  let hist = null;

  // ---------------- 파이썬 호출 ----------------
  const real = () => window.pywebview && window.pywebview.api;
  function api(name, ...args) {
    const a = real();
    if (a && a[name]) return a[name](...args).catch(e => console.error(name, e));
    return Promise.resolve(Preview.call(name, args));
  }

  // ---------------- 화면 전환 ----------------
  function go(p) {
    page = p;
    $$('main[data-page]').forEach(m => { m.hidden = m.dataset.page !== p; });
    $$('.tab').forEach(t => t.setAttribute('aria-current', t.dataset.go === p ? 'page' : 'false'));
    $('#mainScroll').scrollTop = 0;
    api('set_page', p);
  }

  // ---------------- 설정 값 넣기 ----------------
  function fillCfg() {
    $$('[data-cfg]').forEach(el => {
      const v = cfg[el.dataset.cfg];
      if (el.type === 'checkbox') el.checked = !!v; else el.value = v == null ? '' : v;
    });
    ['bite_mode', 'bobber_style', 'pack_version', 'sneak_key', 'win_preset'].forEach(name => {
      $$(`input[name="${name}"]`).forEach(r => { r.checked = r.value === String(cfg[name]); });
    });
    $$('#advFields input').forEach(el => { el.value = cfg[el.dataset.adv]; });
    $('#advReel').checked = !!cfg.reel_click_after_game;
    $('#advLog').checked = !!cfg.log_file;
    $('#hookUrl').value = cfg.discord_webhook || '';
    $('#hookEach').checked = !!cfg.notify_each_catch;
    $('#sens').value = cfg.mouse_sens_pct ?? '';
    $('#yaw').value = cfg.repair_yaw ?? '';
    $('#pitch').value = cfg.repair_pitch ?? '';
    setTop(cfg.topmost !== false);
    setSize(cfg.win_preset || 'mid');
  }
  function setTop(on) {
    cfg.topmost = on;
    $('#topBtn').setAttribute('aria-pressed', on ? 'true' : 'false');
    $('#winTop').checked = on;
  }
  function setSize(p) {
    cfg.win_preset = p;
    $$('[data-size]').forEach(b => b.setAttribute('aria-pressed', b.dataset.size === p ? 'true' : 'false'));
    $$('input[name="win_preset"]').forEach(r => { r.checked = r.value === p; });
  }

  function buildAdv() {
    const box = $('#advFields');
    box.innerHTML = '';
    ADV.forEach(([k, label, lo, hi, step]) => {
      const row = document.createElement('label');
      row.className = 'field';
      row.innerHTML = `<span class="lab"></span><input class="num" type="number" min="${lo}" max="${hi}" step="${step}" data-adv="${k}">`;
      row.firstChild.textContent = label;
      box.appendChild(row);
    });
  }
  function buildGuide() {
    const pg = $('#guidePage');
    const colors = [['#E3F2FA', '#0B5C80'], ['#FCE8F6', '#9C2B7F'], ['#E3F4EA', '#1B6B3A'], ['#EAF1FF', '#2F55B5'], ['#FFF1E2', '#A84E0E']];
    GUIDE.forEach(([title, lines], i) => {
      const sec = document.createElement('section');
      sec.className = 'card';
      const [bg, fg] = colors[i % colors.length];
      sec.innerHTML = `<h2><span class="ic" style="background:${bg};color:${fg}"><svg width="18" height="18" aria-hidden="true"><use href="#i-book"/></svg></span><span></span></h2><ul class="gl"></ul>`;
      sec.querySelector('h2 span:last-child').textContent = title;
      const ul = sec.querySelector('ul');
      lines.forEach(t => { const li = document.createElement('li'); li.textContent = t; ul.appendChild(li); });
      pg.appendChild(sec);
    });
  }

  // ---------------- 실시간 상태 ----------------
  function fmtElapsed(sec) {
    const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  function setAnim(k) {
    if (k === lastAnim) return;
    lastAnim = k;
    $$('.scene').forEach(sv => {
      sv.setAttribute('class', 'scene st-' + k);
      sv.setAttribute('aria-label', '낚시꾼 캐릭터: ' + LABEL[k]);
    });
    $('#stateLabel').textContent = LABEL[k];
    $('#miniState').textContent = LABEL[k];
    $('#liveDot').className = 'live' + (k === 'idle' ? ' idle' : '');
    const idx = ORDER.indexOf(k);
    $$('#steps .step').forEach((li, i) => { li.className = 'step' + (i === idx ? ' on' : (idx > 0 && i < idx ? ' done' : '')); });
  }
  function setRunning(on) {
    running = on;
    const b = $('#runBtn');
    b.classList.toggle('stop', on);
    $('#runLabel').textContent = on ? '그만 낚기' : '낚시 시작';
    $('#runIcon').setAttribute('href', on ? '#i-stop' : '#i-play');
    const mb = $('#miniRun');
    mb.classList.toggle('stop', on);
    mb.firstChild.textContent = on ? '정지 ' : '시작 ';
  }
  function onState(s) {
    setRunning(s.running);
    setAnim(s.anim);
    $('#macroState').textContent = s.state;
    $('#bannerCount').textContent = s.caught + '마리';
    $('#miniCount').textContent = s.caught;
    $('#sCaught').textContent = s.caught + '마리';
    $('#sPerHour').textContent = '시간당 ' + s.perHour + '마리';
    $('#sElapsed').textContent = fmtElapsed(s.elapsed);
    $('#sGoal').textContent = (s.goalN || s.goalM) ? `목표 ${s.goalN ? s.goalN + '마리' : ''}${s.goalN && s.goalM ? ' · ' : ''}${s.goalM ? s.goalM + '분' : ''}` : '목표 없음';
    $('#sCasts').textContent = s.casts + '번';
    $('#sTotal').textContent = '지금까지 총 ' + s.total + '마리';
    $('#sRate').textContent = s.rate + '%';
    const bt = $('#biteText');
    bt.textContent = s.bite.text;
    bt.style.color = s.bite.hit ? 'var(--ok)' : '';
    const dm = $('#duraMeter');
    if (s.dura) {
      $('#duraText').textContent = s.dura.text;
      $('#duraText').style.color = s.dura.ignore ? 'var(--muted)' : (s.dura.danger ? 'var(--bad)' : 'var(--ok)');
      dm.firstElementChild.style.width = Math.round(s.dura.frac * 100) + '%';
      dm.setAttribute('aria-valuenow', Math.round(s.dura.frac * 100));
      dm.classList.toggle('danger', !!s.dura.danger);
    } else {
      $('#duraText').textContent = '-';
      dm.firstElementChild.style.width = '0%';
    }
    $('#bobberLive').hidden = !s.showLive;
    if (s.bobberImg) { $('#bobberImg').src = s.bobberImg; $('#bobberImg').hidden = false; }
    if (s.trace) drawTrace(s.trace);
    drawBar(s.bar);
    drawFish(s.colors, s.bins);
  }
  function hiDpi(cv) {
    const r = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== Math.round(w * r) || cv.height !== Math.round(h * r)) { cv.width = Math.round(w * r); cv.height = Math.round(h * r); }
    const c = cv.getContext('2d');
    c.setTransform(r, 0, 0, r, 0, 0);
    return [c, w, h];
  }
  function drawTrace(tr) {
    const [c, W, H] = hiDpi($('#traceCv'));
    c.clearRect(0, 0, W, H);
    const y1 = H * 0.75 - H * 0.55;
    c.setLineDash([4, 3]); c.strokeStyle = '#7CCB84'; c.lineWidth = 1;
    c.beginPath(); c.moveTo(4, y1); c.lineTo(W - 4, y1); c.stroke(); c.setLineDash([]);
    c.font = '11px "Gowun Dodum"'; c.fillStyle = '#B6E3BC'; c.textAlign = 'right'; c.fillText('입질 기준', W - 6, y1 + 12);
    [[0, '#5FB8F0'], [1, '#7CCB84']].forEach(([idx, col]) => {
      if (tr.length < 2) return;
      c.strokeStyle = col; c.lineWidth = 2; c.beginPath();
      tr.forEach((t, i) => {
        const v = Math.max(-0.3, Math.min(1.3, t[idx]));
        const x = 4 + (W - 8) * i / 99, y = H * 0.75 - H * 0.55 * v;
        i ? c.lineTo(x, y) : c.moveTo(x, y);
      });
      c.stroke();
    });
    c.textAlign = 'left'; c.fillStyle = '#5FB8F0'; c.fillText('━ 가라앉음', 6, 12);
    c.fillStyle = '#7CCB84'; c.fillText('━ 물보라', 78, 12);
  }
  function drawBar(b) {
    const [c, W, H] = hiDpi($('#barCv'));
    c.clearRect(0, 0, W, H);
    c.font = '13px "Gowun Dodum"'; c.fillStyle = '#C9DCE5'; c.textAlign = 'center'; c.textBaseline = 'middle';
    if (!b || !b.roi) { c.fillText('미니게임이 뜨면 바를 자동으로 찾아요', W / 2, H / 2); return; }
    if (!b.active) { c.fillText('미니게임 기다리는 중 ...', W / 2, H / 2); return; }
    const sc = (W - 8) / b.w;
    if (b.zone != null) {
      const zw = b.zw * sc, zx = 4 + b.zone * sc;
      c.strokeStyle = '#7CCB84'; c.lineWidth = 2; c.strokeRect(zx - zw / 2, 4, zw, H - 8);
    }
    if (b.fish != null) {
      const x = 4 + b.fish * sc;
      c.fillStyle = '#FFB45C'; c.beginPath(); c.ellipse(x, H / 2, 8, 5, 0, 0, Math.PI * 2); c.fill();
      c.beginPath(); c.moveTo(x - 7, H / 2); c.lineTo(x - 13, H / 2 - 5); c.lineTo(x - 13, H / 2 + 5); c.fill();
    }
  }
  let fishKey = '';
  function drawFish(colors, bins) {
    const key = JSON.stringify(colors) + JSON.stringify(bins);
    if (key === fishKey) return;
    fishKey = key;
    const box = $('#fishChips');
    box.innerHTML = '';
    const items = Object.entries(colors || {}).sort((a, b) => b[1] - a[1]);
    if (!items.length) { const s = document.createElement('span'); s.className = 'desc'; s.textContent = '아직 없음'; box.appendChild(s); }
    items.forEach(([name, n]) => {
      const ch = document.createElement('span');
      ch.className = 'fish-chip';
      ch.innerHTML = '<i></i><span></span>';
      ch.firstChild.style.background = FISH_HEX[name] || '#9e9e9e';
      ch.lastChild.textContent = `${name} ${n}`;
      box.appendChild(ch);
    });
    const sp = $('#spark');
    sp.innerHTML = '';
    const top = Math.max(1, ...bins);
    bins.forEach(v => { const d = document.createElement('div'); d.className = v ? 'on' : ''; d.style.height = Math.max(6, 100 * v / top) + '%'; sp.appendChild(d); });
  }

  function addLog(e) {
    logs.unshift(e);
    logs = logs.slice(0, 5);
    const ul = $('#logList');
    ul.innerHTML = '';
    logs.forEach(l => {
      const li = document.createElement('li');
      li.innerHTML = '<span class="dot"></span><span class="t"></span><span class="x"></span>';
      li.children[0].className = 'dot ' + (l.tag || 'info');
      li.children[1].textContent = l.time;
      li.children[2].textContent = l.text;
      li.children[2].className = 'x ' + (l.tag || '');
      ul.appendChild(li);
    });
  }

  function onStatus(st) {
    $$('[data-st]').forEach(b => {
      const s = st[b.dataset.st];
      if (!s) return;
      b.textContent = s.text;
      b.className = 'badge b-' + s.cls;
    });
  }

  // ---------------- 기록 페이지 ----------------
  function iso(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
  function fmtT(sec) { const m = Math.floor(sec / 60); return m >= 60 ? `${Math.floor(m / 60)}시간 ${m % 60}분` : `${m}분`; }
  function onHistory(data) {
    hist = data.hist || {};
    const [y, mo, d] = data.today.split('-').map(Number);
    const today = new Date(y, mo - 1, d);
    const days = Array.from({ length: 14 }, (_, i) => new Date(y, mo - 1, d - 13 + i));
    const agg = keys => keys.reduce((o, k) => { const e = hist[k] || {}; o.caught += e.caught || 0; o.casts += e.casts || 0; o.seconds += e.seconds || 0; return o; }, { caught: 0, casts: 0, seconds: 0 });
    const tiles = [['오늘', agg([iso(today)])], ['어제', agg([iso(new Date(y, mo - 1, d - 1))])], ['최근 7일', agg(days.slice(-7).map(iso))], ['전체', agg(Object.keys(hist))]];
    const tb = $('#tiles');
    tb.innerHTML = '';
    tiles.forEach(([name, a], i) => {
      const t = document.createElement('div');
      t.className = 'tile';
      const ph = a.seconds >= 300 ? Math.round(a.caught / (a.seconds / 3600)) : null;
      t.innerHTML = '<div class="k"></div><div class="v"></div><div class="s"></div><div class="s"></div>';
      t.children[0].textContent = name;
      t.children[1].textContent = a.caught + '마리';
      if (i === 0) t.children[1].style.color = 'var(--sea)';
      t.children[2].textContent = fmtT(a.seconds);
      t.children[3].textContent = ph ? `시간당 ${ph}마리` : '';
      tb.appendChild(t);
    });
    const vals = days.map(dd => (hist[iso(dd)] || {}).caught || 0);
    const vmax = Math.max(1, ...vals);
    const box = $('#days'), xs = $('#daysX');
    box.innerHTML = ''; xs.innerHTML = '';
    const info = i => {
      const e = hist[iso(days[i])] || {};
      const rate = e.casts ? ` · 성공 ${Math.round((e.caught || 0) / e.casts * 100)}%` : '';
      return `${days[i].getMonth() + 1}/${days[i].getDate()}  ${e.caught || 0}마리 · ${fmtT(e.seconds || 0)}${rate}`;
    };
    const best = vals.indexOf(Math.max(...vals));
    const idle = vals[best] ? `가장 많이: ${days[best].getMonth() + 1}/${days[best].getDate()} ${vals[best]}마리 (막대에 마우스를 올리면 자세히)` : '아직 기록이 없어요. 낚시하면 여기에 쌓여요';
    $('#dayInfo').textContent = idle;
    vals.forEach((v, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = v ? '' : 'zero';
      b.setAttribute('aria-label', info(i));
      b.innerHTML = '<i></i>';
      b.firstChild.style.height = (v ? Math.max(3, 100 * v / vmax) : 0) + '%';
      const show = () => { $('#dayInfo').textContent = info(i); };
      b.addEventListener('mouseenter', show); b.addEventListener('focus', show);
      b.addEventListener('mouseleave', () => { $('#dayInfo').textContent = idle; });
      box.appendChild(b);
      const sx = document.createElement('span');
      sx.textContent = (i % 2 === 1 || i === 13) ? (i === 13 ? '오늘' : `${days[i].getMonth() + 1}/${days[i].getDate()}`) : '';
      xs.appendChild(sx);
    });
    const colors = {};
    Object.values(hist).forEach(e => Object.entries(e.colors || {}).forEach(([k, v]) => { colors[k] = (colors[k] || 0) + v; }));
    const items = Object.entries(colors).sort((a, b) => b[1] - a[1]);
    const cb = $('#colorBars');
    cb.innerHTML = '';
    if (!items.length) { cb.innerHTML = '<p class="desc">색은 미니게임 시작할 때 물고기 색으로 기록돼요</p>'; return; }
    const total = items.reduce((s, kv) => s + kv[1], 0), top = items[0][1];
    items.forEach(([name, v]) => {
      const r = document.createElement('div');
      r.className = 'cbar';
      r.innerHTML = '<i style="width:14px;height:14px;border-radius:50%"></i><span></span><div class="track"><div></div></div><span></span>';
      const col = FISH_HEX[name] || '#9e9e9e';
      r.children[0].style.background = col;
      r.children[1].textContent = name;
      r.children[2].firstChild.style.width = Math.max(4, 100 * v / top) + '%';
      r.children[2].firstChild.style.background = col;
      r.children[3].textContent = `${v}마리 · ${Math.round(v / total * 100)}%`;
      cb.appendChild(r);
    });
  }

  // ---------------- 낚싯대 페이지 ----------------
  function slotButtons(box, n0, n1, isOn, label, kind, extra) {
    box.innerHTML = '';
    for (let n = n0; n <= n1; n++) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'slot';
      b.setAttribute('aria-pressed', isOn(n) ? 'true' : 'false');
      b.innerHTML = '<span></span>';
      b.firstChild.textContent = label(n);
      if (extra) extra(b, n);
      b.addEventListener('click', () => api('rod_click', kind, n));
      box.appendChild(b);
    }
  }
  function onRod(r) {
    cfg.rod_slots = r.rodSlots;
    slotButtons($('#swapSlots'), 1, 9, n => r.rodSlots.includes(n), n => String(n), 'swap', (b, n) => {
      const on = r.rodSlots.includes(n), dep = r.depleted.includes(n);
      if (dep && on) b.classList.add('dep');
      if (n === r.cur) b.classList.add('cur');
      let frac = null;
      if (n === r.cur && r.dura != null) frac = r.dura; else if (on && dep) frac = 0.05;
      if (frac != null) {
        const bar = document.createElement('span');
        bar.className = 'dbar';
        bar.innerHTML = '<i></i>';
        bar.firstChild.style.width = Math.round(frac * 100) + '%';
        bar.firstChild.style.background = `hsl(${Math.round(frac * 120)},80%,50%)`;
        b.appendChild(bar);
      }
      if (on) { const s = document.createElement('small'); s.textContent = dep ? '다 씀' : (n === r.cur ? '사용 중' : '대기'); b.appendChild(s); }
      b.setAttribute('aria-label', `${n}번 칸${on ? ' (고름)' : ''}${n === r.cur ? ', 지금 들고 있음' : ''}${dep ? ', 다 씀' : ''}`);
    });
    $('#swapText').textContent = `고른 칸: ${r.rodSlots.join(', ') || '없음'}` + (r.cur ? `  ·  지금 ${r.cur}번 칸` : '');
    slotButtons($('#exactSlots'), 0, 9, n => n === r.exactSlot, n => n === 0 ? '자동' : String(n), 'exact');
    slotButtons($('#repRodSlots'), 1, 9, n => n === r.repairRod, n => String(n), 'repair_rod_slot');
    slotButtons($('#repStrSlots'), 1, 9, n => n === r.repairString, n => String(n), 'repair_string_slot');
    if (r.repairText != null) {
      const t = $('#repairText');
      t.textContent = r.repairText;
      t.style.color = r.repairReady ? 'var(--ok)' : '';
    }
    const inv = $('#inv');
    inv.innerHTML = '';
    for (let k = 0; k < 36; k++) {
      const i = document.createElement('i');
      if (r.invMap && !r.invMap[k]) i.className = 'full';
      if (k >= 27) i.classList.add('hot');
      inv.appendChild(i);
    }
    const it = $('#invText');
    it.textContent = r.invNote;
    it.style.color = r.invBad ? 'var(--bad)' : '';
  }

  // ---------------- 영역 지정 창 ----------------
  let pick = null;
  function openPick(d) {
    pick = { token: d.token, mode: d.mode, w: d.w, h: d.h, sel: null, start: null };
    $('#pickGuide').textContent = d.guide;
    const img = $('#pickImg');
    img.src = d.img;
    img.className = d.pixel ? 'pixel' : '';
    $('#pickWrap').classList.toggle('view', d.mode === 'view');
    $('#pickRect').hidden = true; $('#pickPt').hidden = true;
    $('#pickRetry').hidden = d.mode !== 'view';
    $('#pickOk').textContent = (d.ok || '확인') + ' (Enter)';
    $('#pickOk').disabled = d.mode !== 'view';
    $('#pickOv').hidden = false;
    $('#pickOk').focus();
  }
  function closePick(result) {
    if (!pick) return;
    const t = pick.token;
    pick = null;
    $('#pickOv').hidden = true;
    api('pick_result', t, result);
  }
  function pickPos(e) {
    const img = $('#pickImg'), r = img.getBoundingClientRect();
    const x = Math.max(0, Math.min(r.width, e.clientX - r.left)), y = Math.max(0, Math.min(r.height, e.clientY - r.top));
    return { x, y, sx: pick.w / r.width, sy: pick.h / r.height };
  }
  function bindPick() {
    const wrap = $('#pickWrap');
    wrap.addEventListener('mousedown', e => {
      if (!pick || e.button !== 0) return;
      const p = pickPos(e);
      if (pick.mode === 'rect') { pick.start = p; e.preventDefault(); }
      else if (pick.mode === 'point') {
        const pt = $('#pickPt');
        pt.style.left = p.x + 'px'; pt.style.top = p.y + 'px'; pt.hidden = false;
        pick.sel = [Math.floor(p.x * p.sx), Math.floor(p.y * p.sy)];
        $('#pickOk').disabled = false;
      }
    });
    window.addEventListener('mousemove', e => {
      if (!pick || pick.mode !== 'rect' || !pick.start) return;
      const p = pickPos(e), s = pick.start, rc = $('#pickRect');
      const x0 = Math.min(s.x, p.x), y0 = Math.min(s.y, p.y);
      rc.style.left = x0 + 'px'; rc.style.top = y0 + 'px';
      rc.style.width = Math.abs(p.x - s.x) + 'px'; rc.style.height = Math.abs(p.y - s.y) + 'px';
      rc.hidden = false;
    });
    window.addEventListener('mouseup', e => {
      if (!pick || pick.mode !== 'rect' || !pick.start) return;
      const p = pickPos(e), s = pick.start;
      pick.start = null;
      const x0 = Math.min(s.x, p.x), x1 = Math.max(s.x, p.x), y0 = Math.min(s.y, p.y), y1 = Math.max(s.y, p.y);
      if (x1 - x0 >= 2 && y1 - y0 >= 2) {
        pick.sel = [Math.floor(x0 * p.sx), Math.floor(y0 * p.sy), Math.max(1, Math.round((x1 - x0) * p.sx)), Math.max(1, Math.round((y1 - y0) * p.sy))];
        $('#pickOk').disabled = false;
      }
    });
    $('#pickOk').addEventListener('click', () => {
      if (!pick) return;
      if (pick.mode === 'view') closePick(true);
      else if (pick.sel) closePick(pick.sel);
    });
    $('#pickCancel').addEventListener('click', () => closePick(null));
    $('#pickRetry').addEventListener('click', () => closePick(false));
  }

  // ---------------- 알림 / 질문 ----------------
  let dlg = null;
  function openDialog(d, isConfirm) {
    dlg = { token: d.token || null, confirm: isConfirm };
    $('#dlgTitle').textContent = d.title;
    $('#dlgText').textContent = d.text;
    $('#dlgOk').textContent = isConfirm ? d.yes : '확인';
    $('#dlgNo').hidden = !isConfirm;
    if (isConfirm) $('#dlgNo').textContent = d.no;
    $('#dlgOv').hidden = false;
    $('#dlgOk').focus();
  }
  function closeDialog(v) {
    if (!dlg) return;
    const d = dlg;
    dlg = null;
    $('#dlgOv').hidden = true;
    if (d.confirm) api('answer', d.token, v);
  }

  // ---------------- 파이썬 -> 화면 ----------------
  const App = {
    push(kind, data) {
      switch (kind) {
        case 'state': onState(data); break;
        case 'log': addLog(data); break;
        case 'status': onStatus(data); break;
        case 'guide': {
          const bar = $('#f7bar');
          bar.hidden = !data;
          if (data) { $('#f7text').textContent = data.text; }
          break;
        }
        case 'pick': openPick(data); break;
        case 'dialog': openDialog(data, false); break;
        case 'confirm': openDialog(data, true); break;
        case 'rod': onRod(data); break;
        case 'history': onHistory(data); break;
        case 'packMade': $('#packText').textContent = data; $('#packText').style.color = 'var(--ok)'; break;
        case 'repairGuide': $('#repairGuide').hidden = !data; $('#repairGuide').textContent = data || ''; break;
        case 'mini': document.body.classList.toggle('mini', !!data); break;
      }
    }
  };
  window.App = App;

  // ---------------- 버튼 연결 ----------------
  function bind() {
    $$('.tab').forEach(t => t.addEventListener('click', () => go(t.dataset.go)));
    $('#runBtn').addEventListener('click', () => api('toggle'));
    $('#miniRun').addEventListener('click', () => api('toggle'));
    $('#miniBtn').addEventListener('click', () => api('set_mini', true));
    $('#miniBack').addEventListener('click', () => api('set_mini', false));
    $('#topBtn').addEventListener('click', () => { const on = !cfg.topmost; setTop(on); api('set_top', on); });
    $('#winTop').addEventListener('change', e => { setTop(e.target.checked); api('set_top', e.target.checked); });
    $$('[data-size]').forEach(b => b.addEventListener('click', () => { setSize(b.dataset.size); api('set_size', b.dataset.size); }));
    $$('input[name="win_preset"]').forEach(r => r.addEventListener('change', () => { setSize(r.value); api('set_size', r.value); }));
    $$('[data-cfg]').forEach(el => {
      const ev = el.type === 'checkbox' ? 'change' : 'input';
      el.addEventListener(ev, () => {
        const v = el.type === 'checkbox' ? el.checked : el.value;
        cfg[el.dataset.cfg] = v;
        api('set_cfg', el.dataset.cfg, v);
      });
    });
    ['bite_mode', 'bobber_style', 'pack_version', 'sneak_key'].forEach(name => {
      $$(`input[name="${name}"]`).forEach(r => r.addEventListener('change', () => { cfg[name] = r.value; api('set_cfg', name, r.value); }));
    });
    $$('[data-set]').forEach(b => b.addEventListener('click', () => {
      const cap = ($('input[name="capture"]:checked') || {}).value || 'live';
      api('begin_set', b.dataset.set, cap);
    }));
    $('#f7cancel').addEventListener('click', () => { $('#f7bar').hidden = true; api('cancel_set'); });
    $('#barAuto').addEventListener('click', () => api('reset_bar'));
    $('#packBtn').addEventListener('click', () => api('make_pack'));
    $('#advSave').addEventListener('click', () => {
      const v = {};
      $$('#advFields input').forEach(el => { v[el.dataset.adv] = el.value; });
      v.reel_click_after_game = $('#advReel').checked;
      v.log_file = $('#advLog').checked;
      v.sneak_key = ($('input[name="sneak_key"]:checked') || {}).value;
      api('save_adv', v);
    });
    const saveHook = () => api('save_hook', $('#hookUrl').value, $('#hookEach').checked);
    $('#hookUrl').addEventListener('change', saveHook);
    $('#hookEach').addEventListener('change', saveHook);
    $('#hookTest').addEventListener('click', () => api('test_hook', $('#hookUrl').value, $('#hookEach').checked));
    $('#anBtn').addEventListener('click', async () => { $('#anText').textContent = '분석 중...'; $('#anText').textContent = await api('run_analysis') || ''; });
    $('#anCopy').addEventListener('click', async () => {
      const t = $('#anText').textContent.trim();
      try { await navigator.clipboard.writeText(t); addLog({ time: new Date().toTimeString().slice(0, 5), text: '분석 내용을 복사했어', tag: 'good' }); }
      catch (e) { addLog({ time: new Date().toTimeString().slice(0, 5), text: '복사 실패: 글을 직접 선택해서 Ctrl+C', tag: 'warn' }); }
    });
    $('#checkNow').addEventListener('click', () => api('check_now'));
    $('#turnRec').addEventListener('click', () => api('start_turn_record'));
    $('#turnTest').addEventListener('click', () => api('test_turn'));
    $('#useAngle').addEventListener('click', () => api('use_angle', $('#sens').value, $('#yaw').value, $('#pitch').value));
    $('#quitBtn').addEventListener('click', () => api('quit'));
    $('#dlgOk').addEventListener('click', () => closeDialog(true));
    $('#dlgNo').addEventListener('click', () => closeDialog(false));
    document.addEventListener('keydown', e => {
      if (pick) {
        if (e.key === 'Escape') { e.preventDefault(); closePick(null); }
        else if (e.key === 'Enter') { e.preventDefault(); $('#pickOk').click(); }
      } else if (dlg && e.key === 'Escape') { e.preventDefault(); closeDialog(false); }
    });
    bindPick();
    // 미니 모드용 장면: 홈 배너 그림을 복사해서 낚시꾼 쪽만 보이게
    const mini = $('#scene').cloneNode(true);
    mini.removeAttribute('id');
    mini.setAttribute('viewBox', '108 20 230 170');
    mini.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    $('#miniScene').appendChild(mini);
  }

  async function start() {
    const init = await api('ready');
    cfg = init.cfg;
    $('#ver').textContent = init.version === 'dev' ? '개발판' : 'v' + init.version;
    fillCfg();
    onStatus(init.status);
    (init.logs || []).forEach(addLog);
    if (init.mini) document.body.classList.add('mini');
  }

  // ---------------- 미리보기 (파이썬 없이 브라우저로 열었을 때) ----------------
  const Preview = {
    on: false, cfg: null, st: null,
    call(name, args) {
      if (!this.on) return null;
      const s = this.st;
      switch (name) {
        case 'ready': return { cfg: this.cfg, status: { subtitle: { text: '지정됨', cls: 'ok' }, bobber: { text: '지정됨', cls: 'ok' }, rod: { text: '자동 (선택한 칸)', cls: 'auto' }, bar: { text: '자동으로 찾음', cls: 'auto' } }, version: '미리보기', mini: false };
        case 'toggle': s.running = !s.running; s.phase = s.running ? 0 : -1; if (s.running && !s.started) s.started = Date.now(); return null;
        case 'set_mini': App.push('mini', args[0]); return null;
        case 'set_page':
          if (args[0] === 'rod') App.push('rod', { cur: 2, depleted: [1], dura: 0.7, rodSlots: [1, 2, 3], rodSwap: true, exactSlot: 0, repairRod: 1, repairString: 9, repairText: '방향: 아직 없음  ·  수리 창: 아직 없음  ·  골드 영역: 없음 (확인 안 함)', repairReady: false, invMap: Array.from({ length: 36 }, (_, k) => k % 4 !== 0), invNote: '빈칸 9개', invBad: false });
          if (args[0] === 'log') { const h = {}; const d = new Date(); for (let i = 0; i < 14; i++) { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate() - i); if (i % 3 !== 2) h[iso(x)] = { caught: 20 + (i * 37) % 90, casts: 30 + (i * 41) % 100, seconds: 3600 + i * 400, colors: { '파랑': 10 + i, '초록': 7, '빨강': 3 } }; } App.push('history', { hist: h, today: iso(d) }); }
          return null;
        case 'run_analysis': return '미리보기에서는 분석 결과가 없어요.';
        case 'begin_set': App.push('guide', { text: '게임에서 [미리보기] 장면을 띄우고 F7 !' }); return null;
        default: return null;
      }
    },
    start() {
      this.on = true;
      this.cfg = { bite_mode: 'both', bobber_style: 'auto', pack_version: 'both', background: true, durability_ignore: false, durability_stop_pct: 20, durability_max: 64, goal_count: 0, goal_minutes: 0, sneak_key: 'shift', reel_click_after_game: false, log_file: true, discord_webhook: '', notify_each_catch: false, rod_swap: true, exact_durability: false, inv_check_every: 20, repair_on: false, repair_cost: 0, inv_full_stop: false, inv_min_empty: 0, topmost: true, win_preset: 'mid', remember_window: true, total_caught: 812, subtitle_threshold: 0.8, bite_confirm_frames: 2, bite_drop_ratio: 0.5, bite_dip_px: 4, tolerance: 30, deadzone_px: 3, left_click_cps: 10, lead_sec: 0.05, cast_settle_sec: 2, bite_timeout_sec: 45, recast_delay_sec: 1, start_delay_sec: 1, max_fails: 5 };
      this.st = { running: false, phase: -1, caught: 0, casts: 0, started: 0, t: 0, colors: {} };
      const dur = { cast: 1400, wait: 3200, bite: 900, reel: 2600, caught: 1800 };
      const names = { cast: '던지는 중', wait: '입질 기다리는 중 (찌 + 자막)', bite: '미니게임 기다리는 중', reel: '미니게임 중', caught: '다시 던지기 대기' };
      let next = 0;
      setInterval(() => {
        const s = this.st, now = Date.now();
        if (s.running && now >= next) {
          s.phase = (s.phase + 1) % ORDER.length;
          const k = ORDER[s.phase];
          if (k === 'cast') s.casts++;
          if (k === 'caught') { s.caught++; const f = ['파랑', '초록', '빨강'][s.caught % 3]; s.colors[f] = (s.colors[f] || 0) + 1; addLog({ time: new Date().toTimeString().slice(0, 5), text: f + ' 물고기 낚음', tag: 'good' }); }
          if (k === 'bite') addLog({ time: new Date().toTimeString().slice(0, 5), text: '입질! (찌 픽셀감소)', tag: 'good' });
          next = now + dur[k];
        }
        const k = s.running ? ORDER[s.phase] : 'idle';
        const el = s.started && s.running ? Math.floor((now - s.started) / 1000) : 0;
        const tr = Array.from({ length: 100 }, (_, i) => [Math.sin((now / 300) + i / 8) * 0.25 + (k === 'bite' && i > 90 ? 1.1 : 0), 0.02]);
        onState({ running: s.running, state: s.running ? names[k] : '정지됨', anim: k, caught: s.caught, elapsed: el, casts: s.casts, caughtAll: s.caught, perHour: el > 60 ? Math.round(s.caught / (el / 3600)) : 0, rate: s.casts ? Math.round(s.caught / s.casts * 100) : 0, total: 812 + s.caught, colors: s.colors, bins: [0, 0, 1, 3, 2, 4, 5, 3, 6, 4, 5, s.caught % 7], bite: { text: k === 'bite' ? '찌 0px' : '찌 12px', hit: false }, dura: { text: '48/64', frac: 0.75, ignore: false, danger: false }, bar: { roi: true, active: k === 'reel', zone: 180 + Math.sin(now / 400) * 80, fish: 180 + Math.sin(now / 330) * 100, zw: 60, w: 371 }, showLive: true, trace: tr, goalN: 0, goalM: 0 });
      }, 150);
      addLog({ time: new Date().toTimeString().slice(0, 5), text: '준비 완료! (미리보기: 파이썬 없이 열림)', tag: 'good' });
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    buildAdv();
    buildGuide();
    bind();
    let started = false;
    const go2 = () => { if (!started) { started = true; start(); } };
    window.addEventListener('pywebviewready', go2);
    if (real()) go2();
    setTimeout(() => { if (!started && !real()) { Preview.start(); go2(); } }, 800);
  });
})();
