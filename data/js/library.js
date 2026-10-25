/* Library: every series as covers or a list, with filters and bulk edit.
   The filter box searches your library only; Add series searches ComicVine. */
(function () {
  'use strict';

  var STORE = 'issuarr-library';
  var CHUNK = 120;
  var TABS = [
    ['all', 'All', function () { return true; }],
    ['continuing', 'Continuing', function (s) { return s.recent === 'Continuing'; }],
    ['ended', 'Ended', function (s) { return s.recent === 'Ended'; }],
    ['paused', 'Paused', function (s) { return s.status === 'Paused'; }],
    ['gaps', 'Has gaps', function (s) { return s.total > 0 && s.have < s.total; }],
    ['loading', 'Loading', function (s) { return s.status === 'Loading' || s.recent === 'Loading'; }],
    ['problems', 'Problems', function (s) { return isError(s) || s.cv_removed === 1; }]
  ];
  var BULK = {
    refresh: { done: 'Refreshing', confirm: null },
    pause: { done: 'Paused', confirm: null },
    resume: { done: 'Resumed', confirm: null },
    recheck: { done: 'Rechecking files for', confirm: null },
    metatag: { done: 'Writing metadata for', confirm: 'Write ComicInfo metadata into the files of {n}? This changes the files on disk.', ok: 'Write metadata' },
    rename: { done: 'Renaming files for', confirm: 'Rename the files of {n} to match your naming settings? This changes the files on disk.', ok: 'Rename files' },
    delete: { done: 'Removed', confirm: 'Remove {n} from Issuarr? The series, its issue list and statuses are removed. Files on disk stay where they are.', ok: 'Remove' }
  };

  var st = { all: [], tab: 'all', q: '', pub: '', sort: 'title', col: null, view: 'covers', limit: CHUNK, selecting: /[?&]select=1\b/.test(location.search), sel: {}, loaded: false, noArt: {} };
  try {
    var saved = JSON.parse(localStorage.getItem(STORE) || 'null');
    if (saved) { st.view = saved.view || st.view; st.sort = saved.sort || st.sort; }
  } catch (e) {}

  function save() { try { localStorage.setItem(STORE, JSON.stringify({ view: st.view, sort: st.sort })); } catch (e) {} }
  function $id(id) { return document.getElementById(id); }
  function I() { return window.Issuarr; }
  function esc(t) { return I().esc(t); }
  function isError(s) { return ['Active', 'Paused', 'Loading'].indexOf(s.status) < 0; }
  function fmt(n) { return Number(n).toLocaleString(); }

  function tint(name) {
    var h = 0;
    for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
    return 'hsl(' + h + ' 28% 30%)';
  }

  function statusOf(s) {
    if (s.status === 'Paused') return ['Paused', 'is-ignored'];
    if (s.status === 'Loading' || s.recent === 'Loading') return ['Loading', 'is-snatched is-running'];
    if (isError(s)) return ['Error', 'is-failed'];
    if (s.recent === 'Ended') return ['Ended', 'is-ignored'];
    return [s.recent || 'Unknown', ''];
  }

  // The same bar as the Ledger: a series' issues in number order as runs (on disk, wanted, missing and so on),
  // so each gap shows where it is. Hover a run for its issue numbers.
  var RUN = { h: ['seg-have', 'on disk'], w: ['seg-wanted', 'wanted'], s: ['seg-snatched', 'snatched'], f: ['seg-failed', 'failed'],
              i: ['seg-ignored', 'ignored'], m: ['seg-missing', 'missing'] };
  function bar(s) {
    var runs = s.runs || [];
    if (!runs.length) return '<div class="collection-bar" title="No issues listed yet"></div>';
    var tot = {}, n = 0;
    var spans = runs.map(function (r) {
      var k = RUN[r[0]] || RUN.m;
      tot[k[1]] = (tot[k[1]] || 0) + r[1]; n += r[1];
      var which = r[1] === 1 ? '#' + r[2] : '#' + r[2] + '–#' + r[3];
      return '<span class="' + k[0] + '" style="flex: ' + r[1] + ' 1 0" title="' + esc(which + ' ' + k[1]) + '"></span>';
    }).join('');
    var label = n + ' issues: ' + Object.keys(tot).map(function (k) { return tot[k] + ' ' + k; }).join(', ');
    return '<div class="collection-bar is-runs" role="img" aria-label="' + esc(label) + '">' + spans + '</div>';
  }

  function counts(s) {
    var t = s.total ? s.have + '/' + s.total : String(s.have);
    return '<span class="card-count">' + esc(t) + (s.wanted ? ' <b class="is-wanted">' + s.wanted + ' wanted</b>' : '') + '</span>';
  }

  function link(s) { return 'comicDetails?ComicID=' + encodeURIComponent(s.id); }

  // Covers that failed once aren't asked for again until the page reloads.
  function img(s, cls) {
    if (!s.image || st.noArt[s.id]) return '';
    return '<img class="' + cls + '" loading="lazy" decoding="async" src="' + esc(s.image) + '" alt="" data-art="' + esc(s.id) + '">';
  }
  document.addEventListener('error', function (e) {
    var t = e.target;
    if (!t || !t.getAttribute || !t.hasAttribute('data-art')) return;
    st.noArt[t.getAttribute('data-art')] = true;
    t.remove();
  }, true);

  function card(s) {
    var stt = statusOf(s);
    var badges = '';
    if (s.status === 'Paused') badges += '<span class="cover-badge is-dim">Paused</span>';
    if (stt[0] === 'Loading') badges += '<span class="cover-badge is-dim">Loading</span>';
    if (stt[0] === 'Error') badges += '<span class="cover-badge is-bad">Error</span>';
    if (s.cv_removed === 1) badges += '<span class="cover-badge is-bad">Not on ComicVine</span>';
    if (s.latest) badges += '<span class="cover-badge">#' + esc(s.latest) + '</span>';
    var meta = [s.publisher, s.year, stt[0]].filter(Boolean).map(esc).join(' · ');
    var picked = !!st.sel[s.id];
    return '<article class="cover-card' + (picked ? ' is-picked' : '') + '" data-id="' + esc(s.id) + '">' +
      '<input type="checkbox" class="card-check" data-pick="' + esc(s.id) + '" aria-label="Select ' + esc(s.name) + '"' + (picked ? ' checked' : '') + '>' +
      '<a class="cover" href="' + link(s) + '" tabindex="-1" aria-hidden="true">' + img(s, 'cover-art') +
      '<span class="cover-fallback" style="--tint: ' + tint(s.name || '') + '">' + esc(s.name) + '</span>' +
      '<span class="cover-badges">' + badges + '</span></a>' +
      '<div class="card-text"><a class="card-title" href="' + link(s) + '" title="' + esc(s.name) + '">' + esc(s.name) +
      (s.volume && s.volume !== 'v1' ? ' <span class="muted">' + esc(s.volume) + '</span>' : '') + '</a>' +
      bar(s) + '<div class="card-nums"><span>' + esc(s.total ? fmt(s.have) + ' / ' + fmt(s.total) : fmt(s.have)) + '</span>' +
      (s.wanted ? '<span class="is-wanted">' + fmt(s.wanted) + ' wanted</span>' : '') + '</div>' +
      '<div class="card-meta">' + meta + '</div></div></article>';
  }

  function row(s) {
    var stt = statusOf(s);
    var picked = !!st.sel[s.id];
    return '<tr data-id="' + esc(s.id) + '"' + (picked ? ' class="is-picked"' : '') + '>' +
      '<td class="check lib-check"><input type="checkbox" data-pick="' + esc(s.id) + '" aria-label="Select ' + esc(s.name) + '"' + (picked ? ' checked' : '') + '></td>' +
      '<td><span class="lib-name"><span class="thumb-wrap">' + img(s, 'thumb') + '</span><a href="' + link(s) + '">' + esc(s.name) + '</a>' +
      (s.cv_removed === 1 ? ' <span class="status is-failed">Not on ComicVine</span>' : '') + '</span></td>' +
      '<td class="nowrap">' + esc(s.publisher || '-') + '</td>' +
      '<td class="mono">' + esc(s.year || '-') + '</td>' +
      '<td class="mono nowrap">' + (s.latest ? '#' + esc(s.latest) : '-') + '</td>' +
      '<td><span class="status ' + stt[1] + '">' + esc(stt[0]) + '</span></td>' +
      '<td><div class="lib-issues">' + bar(s) + counts(s) + '</div></td></tr>';
  }

  function filtered() {
    var test = (TABS.filter(function (t) { return t[0] === st.tab; })[0] || TABS[0])[2];
    // Every word has to match the name, publisher or year: "batman dc", "saga 2012".
    var words = st.q.toLowerCase().split(/\s+/).filter(Boolean);
    var list = st.all.filter(function (s) {
      if (!test(s) || (st.pub && s.publisher !== st.pub)) return false;
      if (!words.length) return true;
      var hay = [s.name, s.publisher, s.year].join(' ').toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) > -1; });
    });
    var byTitle = function (a, b) { return String(a.sort || a.name).localeCompare(String(b.sort || b.name), undefined, { sensitivity: 'base' }); };
    var sorts = {
      title: byTitle,
      updated: function (a, b) { return String(b.updated || '').localeCompare(String(a.updated || '')) || byTitle(a, b); },
      year: function (a, b) { return (parseInt(a.year, 10) || 9999) - (parseInt(b.year, 10) || 9999) || byTitle(a, b); },
      missing: function (a, b) { return (b.total - b.have) - (a.total - a.have) || byTitle(a, b); },
      publisher: function (a, b) { return String(a.publisher || '').localeCompare(String(b.publisher || '')) || byTitle(a, b); }
    };
    if (st.col) {
      // A column header was clicked: sort by that column, title breaks ties.
      var col = st.col, num = function (v) { var n = parseFloat(v); return isNaN(n) ? null : n; };
      var val = {
        name: function (s) { return String(s.sort || s.name); },
        publisher: function (s) { return s.publisher || null; },
        year: function (s) { return num(s.year); },
        latest: function (s) { return num(s.latest); },
        status: function (s) { return statusOf(s)[0]; },
        // Issues you have, then the series' length, the same as the have/total it shows.
        have: function (s) { return (s.have || 0) * 1e6 + (s.total || 0); }
      }[col.key] || function (s) { return String(s.sort || s.name); };
      return list.sort(function (a, b) {
        var x = val(a), y = val(b);
        if (x === null || y === null) return (x === y ? 0 : x === null ? 1 : -1) || byTitle(a, b);
        var c = typeof x === 'number' ? x - y : String(x).localeCompare(String(y), undefined, { sensitivity: 'base', numeric: true });
        return col.dir * c || byTitle(a, b);
      });
    }
    return list.sort(sorts[st.sort] || byTitle);
  }

  function renderTabs() {
    $id('lib-tabs').innerHTML = TABS.map(function (t) {
      var n = st.all.filter(t[2]).length;
      if (!n && t[0] !== 'all' && (t[0] === 'loading' || t[0] === 'problems') && st.tab !== t[0]) return '';
      return '<button type="button" data-ui data-tab="' + t[0] + '" aria-pressed="' + (st.tab === t[0]) + '">' + t[1] + '<span class="count">' + fmt(n) + '</span></button>';
    }).join('');
  }

  function renderStats() {
    var issues = 0, have = 0;
    st.all.forEach(function (s) { issues += s.total || 0; have += Math.min(s.have, s.total || s.have); });
    var pct = issues ? Math.floor(have / issues * 100) : 0;
    $id('lib-stats').textContent = fmt(st.all.length) + ' series · ' + fmt(issues) + ' issues · ' + pct + '% on disk';
  }

  function renderPublishers() {
    var sel = $id('lib-pub');
    var pubs = {};
    st.all.forEach(function (s) { if (s.publisher) pubs[s.publisher] = (pubs[s.publisher] || 0) + 1; });
    var names = Object.keys(pubs).sort(function (a, b) { return a.localeCompare(b); });
    if (st.pub && !pubs[st.pub]) st.pub = '';
    sel.innerHTML = '<option value="">All</option>' + names.map(function (p) {
      return '<option value="' + esc(p) + '"' + (p === st.pub ? ' selected' : '') + '>' + esc(p) + ' (' + pubs[p] + ')</option>';
    }).join('');
  }

  function render() {
    var list = filtered();
    var shown = list.slice(0, st.limit);
    var covers = st.view === 'covers';
    $id('lib-grid').hidden = !covers || !shown.length;
    $id('lib-list').hidden = covers || !shown.length;
    if (covers) $id('lib-grid').innerHTML = shown.map(card).join('');
    else $id('lib-list').querySelector('tbody').innerHTML = shown.map(row).join('');
    var empty = $id('lib-empty');
    empty.hidden = !!shown.length || !st.loaded;
    if (!shown.length && st.loaded) {
      empty.innerHTML = st.all.length
        ? 'No series match. <button type="button" class="btn btn-sm" id="lib-clear-filters">Clear filters</button>'
        : 'Your library is empty. <button type="button" class="btn btn-sm btn-primary" data-action-add>Add a series</button> ' +
          '<a class="btn btn-sm" href="manage#tabs-1">Scan a folder you already have</a>';
    }
    var more = $id('lib-more-rows');
    more.hidden = list.length <= st.limit;
    more.textContent = 'Show more (' + fmt(Math.max(list.length - st.limit, 0)) + ' left)';
    document.querySelectorAll('.library [data-view]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-view') === st.view)); });
    $id('lib-sort').value = st.sort;
    renderBulk();
  }

  function renderBulk() {
    var n = Object.keys(st.sel).length;
    $id('lib-bulk').hidden = !st.selecting;
    $id('lib-bulk-count').textContent = n ? n + (n === 1 ? ' series selected' : ' series selected') : 'Select series below';
    document.querySelectorAll('#lib-bulk [data-bulk]').forEach(function (b) { b.disabled = !n; });
    document.querySelector('.library').classList.toggle('is-selecting', st.selecting);
    $id('lib-select').setAttribute('aria-pressed', String(st.selecting));
    $id('lib-select').textContent = st.selecting ? 'Done' : 'Select';
  }

  function load() {
    return fetch('library_data', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        st.all = d.series || [];
        st.loaded = true;
        var ids = {};
        st.all.forEach(function (s) { ids[s.id] = true; });
        Object.keys(st.sel).forEach(function (k) { if (!ids[k]) delete st.sel[k]; });
        renderStats(); renderTabs(); renderPublishers(); render();
      })
      .catch(function () {
        st.loaded = true;
        $id('lib-empty').hidden = false;
        $id('lib-empty').textContent = 'Couldn\'t load your library. Check the log.';
      });
  }

  function bulk(action) {
    act(action, st.all.filter(function (s) { return st.sel[s.id]; }));
  }

  function act(action, picked) {
    if (!picked.length) return;
    var what = picked.length === 1 ? '"' + picked[0].name + '"' : picked.length + ' series';
    var cfg = BULK[action];
    if (cfg.confirm) { I().ask(cfg.confirm.replace('{n}', what), { ok: cfg.ok, danger: action === 'delete' }, function () { send(action, picked, what); }); return; }
    send(action, picked, what);
  }

  function send(action, picked, what) {
    var cfg = BULK[action];
    var body = new URLSearchParams();
    body.append('action', action);
    picked.forEach(function (s) { body.append(s.name + '[' + s.year + ']', s.id); });
    fetch('markComics', { method: 'POST', credentials: 'same-origin', body: body })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        var bg = ['refresh', 'recheck', 'metatag', 'rename'].indexOf(action) > -1;
        I().toast(cfg.done + ' ' + what + (bg ? '. Follow it in Tasks › Jobs or the log.' : '.'));
        if (action === 'delete') picked.forEach(function (s) { delete st.sel[s.id]; });
        return load();
      })
      .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
  }

  /* ---- right-click / long-press menu on a series ---- */
  var ctx = null, ctxFor = null, ctxAt = 0, pressTimer = null, pressAt = null, pressed = false;

  function ctxItems(s) {
    var paused = s.status === 'Paused';
    return [
      ['open', 'Open series'],
      ['missing', 'Search for missing issues'],
      ['refresh', 'Refresh from ComicVine'],
      ['recheck', 'Recheck files'],
      [paused ? 'resume' : 'pause', paused ? 'Resume series' : 'Pause series'],
      ['select', st.sel[s.id] ? 'Unselect' : 'Select'],
      null,
      ['delete', 'Remove series…']
    ];
  }

  function closeCtx(refocus) {
    if (!ctx || ctx.hidden) return;
    ctx.hidden = true;
    var back = ctxFor && document.querySelector('#lib-grid [data-id="' + CSS.escape(ctxFor.id) + '"] .card-title, #lib-table tr[data-id="' + CSS.escape(ctxFor.id) + '"] a');
    ctxFor = null;
    if (refocus && back) back.focus();
  }

  function openCtx(s, x, y) {
    if (!ctx) {
      ctx = document.createElement('div');
      ctx.className = 'menu-list ctx-menu';
      ctx.id = 'lib-ctx';
      ctx.setAttribute('role', 'menu');
      ctx.hidden = true;
      document.body.appendChild(ctx);
      ctx.addEventListener('click', function (e) {
        var b = e.target.closest('[data-ctx]');
        if (!b || !ctxFor) return;
        var s = ctxFor, what = b.getAttribute('data-ctx');
        closeCtx(what !== 'open');
        ctxRun(what, s);
      });
      ctx.addEventListener('keydown', function (e) {
        var items = Array.prototype.slice.call(ctx.querySelectorAll('[data-ctx]'));
        var i = items.indexOf(document.activeElement);
        if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
        else if (e.key === 'Home') { e.preventDefault(); items[0].focus(); }
        else if (e.key === 'End') { e.preventDefault(); items[items.length - 1].focus(); }
        else if (e.key === 'Escape' || e.key === 'Tab') { e.preventDefault(); closeCtx(true); }
      });
    }
    ctxFor = s;
    ctx.innerHTML = '<p class="ctx-title">' + esc(s.name) + (s.year ? ' <span class="muted">' + esc(s.year) + '</span>' : '') + '</p>' +
      ctxItems(s).map(function (it) {
        if (!it) return '<hr />';
        return '<button type="button" role="menuitem" class="btn btn-ghost' + (it[0] === 'delete' ? ' series-remove-btn' : '') + '" data-ctx="' + it[0] + '">' + esc(it[1]) + '</button>';
      }).join('');
    ctx.hidden = false;
    var w = ctx.offsetWidth, h = ctx.offsetHeight;
    ctx.style.left = Math.max(6, Math.min(x, window.innerWidth - w - 6)) + 'px';
    ctx.style.top = Math.max(6, Math.min(y, window.innerHeight - h - 6)) + 'px';
    ctx.querySelector('[data-ctx]').focus({ preventScroll: true });
    ctxAt = Date.now();
  }

  function ctxRun(what, s) {
    if (what === 'open') { location.href = link(s); return; }
    if (what === 'missing') {
      fetch('searchformissing?ComicID=' + encodeURIComponent(s.id), { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); I().toast('Searching for the missing issues of "' + s.name + '".'); })
        .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
      return;
    }
    if (what === 'select') {
      if (st.sel[s.id]) delete st.sel[s.id]; else { st.sel[s.id] = true; st.selecting = true; }
      render();
      return;
    }
    act(what, [s]);
  }

  function seriesAt(el) {
    var holder = el.closest('#lib-grid .cover-card, #lib-table tbody tr[data-id]');
    if (!holder) return null;
    var id = holder.getAttribute('data-id');
    return st.all.filter(function (s) { return s.id === id; })[0] || null;
  }

  document.addEventListener('contextmenu', function (e) {
    var s = seriesAt(e.target);
    if (!s) { closeCtx(); return; }
    e.preventDefault();
    if (pressed) return;  // the long-press already opened it
    var x = e.clientX, y = e.clientY;
    if (!x && !y) {  // opened from the keyboard (menu key or Shift+F10)
      var r = e.target.getBoundingClientRect();
      x = r.left + 8; y = r.bottom + 4;
    }
    openCtx(s, x, y);
  });

  // Phones that don't fire contextmenu on a long press (iOS Safari) get it from a touch timer.
  document.addEventListener('touchstart', function (e) {
    pressed = false;
    clearTimeout(pressTimer);
    var s = e.touches.length === 1 && seriesAt(e.target);
    if (!s) return;
    pressAt = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    pressTimer = setTimeout(function () { pressed = true; openCtx(s, pressAt.x, pressAt.y); }, 550);
  }, { passive: true });
  document.addEventListener('touchmove', function (e) {
    if (pressAt && Math.abs(e.touches[0].clientX - pressAt.x) + Math.abs(e.touches[0].clientY - pressAt.y) > 12) clearTimeout(pressTimer);
  }, { passive: true });
  document.addEventListener('touchend', function () { clearTimeout(pressTimer); });
  document.addEventListener('touchcancel', function () { clearTimeout(pressTimer); });
  // The tap that ends a long press must not also open the series or pick the menu item under the finger.
  document.addEventListener('click', function (e) {
    if (pressed) { e.preventDefault(); e.stopPropagation(); }
    pressed = false;
  }, true);

  document.addEventListener('mousedown', function (e) { if (!pressed && ctx && !ctx.hidden && !ctx.contains(e.target)) closeCtx(); });
  document.addEventListener('touchstart', function (e) { if (ctx && !ctx.hidden && !ctx.contains(e.target)) closeCtx(); }, { passive: true });
  window.addEventListener('resize', function () { closeCtx(); });
  // A long press can nudge the page; only a real scroll after that closes the menu.
  window.addEventListener('scroll', function (e) { if (ctx && !ctx.contains(e.target) && Date.now() - ctxAt > 500) closeCtx(); }, true);

  /* ---- events ---- */
  document.addEventListener('click', function (e) {
    var t = e.target;
    var tab = t.closest('#lib-tabs [data-tab]');
    if (tab) { st.tab = tab.getAttribute('data-tab'); st.limit = CHUNK; renderTabs(); render(); return; }
    var view = t.closest('.library [data-view]');
    if (view) { st.view = view.getAttribute('data-view'); save(); render(); return; }
    var b = t.closest('#lib-bulk [data-bulk]');
    if (b) { bulk(b.getAttribute('data-bulk')); return; }
    if (t.closest('#lib-clear-filters')) {
      st.tab = 'all'; st.q = ''; st.pub = ''; $id('lib-q').value = ''; $id('lib-pub').value = '';
      renderTabs(); render(); return;
    }
    if (t.closest('[data-action-add]')) { var add = document.querySelector('[data-action="add"]'); if (add) add.click(); return; }
    var exp = t.closest('[data-export]');
    if (exp) {
      $id('lib-more').open = false;
      var mode = exp.getAttribute('data-export');
      fetch('wanted_Export?mode=' + encodeURIComponent(mode), { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); I().toast('Saved ' + mode + '_list.csv in the data folder.'); })
        .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
      return;
    }
    if (t.closest('#lib-update-all')) {
      $id('lib-more').open = false;
      I().ask('Update every series from ComicVine? On a big library this takes a while and uses ComicVine requests.', { ok: 'Update all' }, function () {
        fetch('forceUpdate', { credentials: 'same-origin' })
          .then(function () { I().toast('Updating every series. Follow it in Tasks › Jobs or the log.'); })
          .catch(function () { I().toast('That didn\'t work. Check the log.', false); });
      });
      return;
    }
  });

  document.addEventListener('change', function (e) {
    var pick = e.target.closest('[data-pick]');
    if (!pick) return;
    var id = pick.getAttribute('data-pick');
    if (pick.checked) st.sel[id] = true; else delete st.sel[id];
    var holder = pick.closest('.cover-card, tr');
    if (holder) holder.classList.toggle('is-picked', pick.checked);
    renderBulk();
  });

  // In select mode a click anywhere on a card picks it instead of opening the series.
  $id('lib-grid').addEventListener('click', function (e) {
    if (!st.selecting || e.target.closest('[data-pick]')) return;
    var cardEl = e.target.closest('.cover-card');
    if (!cardEl) return;
    e.preventDefault();
    var cb = cardEl.querySelector('[data-pick]');
    cb.checked = !cb.checked;
    cb.dispatchEvent(new Event('change', { bubbles: true }));
  });

  $id('lib-select').addEventListener('click', function () {
    st.selecting = !st.selecting;
    if (!st.selecting) st.sel = {};
    render();
  });
  $id('lib-select-all').addEventListener('click', function () {
    filtered().slice(0, st.limit).forEach(function (s) { st.sel[s.id] = true; });
    render();
  });
  var qTimer = null;
  $id('lib-q').addEventListener('input', function (e) {
    clearTimeout(qTimer);
    qTimer = setTimeout(function () { st.q = e.target.value.trim(); st.limit = CHUNK; render(); }, 120);
  });
  $id('lib-pub').addEventListener('change', function (e) { st.pub = e.target.value; st.limit = CHUNK; render(); });
  $id('lib-sort').addEventListener('change', function (e) { st.sort = e.target.value; st.col = null; I().clearSort($id('lib-table')); save(); render(); });
  $id('lib-table').addEventListener('issuarr:sort', function (e) { st.col = e.detail; render(); });
  $id('lib-more-rows').addEventListener('click', function () { st.limit += CHUNK; render(); });
  if (window.IntersectionObserver) {
    new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting && !$id('lib-more-rows').hidden) { st.limit += CHUNK; render(); }
    }, { rootMargin: '600px' }).observe($id('lib-more-rows'));
  }
  var refreshTimer = null;
  document.addEventListener('issuarr:refresh', function () { clearTimeout(refreshTimer); refreshTimer = setTimeout(load, 800); });

  render();
  if (window.jQuery) window.jQuery(load); else document.addEventListener('DOMContentLoaded', load);
})();
