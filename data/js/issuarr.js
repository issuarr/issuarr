/* Issuarr interface: sidebar state, Ctrl K jump menu, the "Running now" box,
   pages whose sections moved into the sidebar, and the custom CSS editor. */
(function () {
  'use strict';

  var doc = document;
  var $ = window.jQuery;
  var path = (location.pathname.split('/').pop() || 'home').toLowerCase();

  function $id(id) { return doc.getElementById(id); }
  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  // Messages stack in the corner. Errors stay longer, and pointing at a message (or focusing it) holds it
  // until you move away. ok: false is an error, true or nothing a success, 'info' plain.
  var TOAST_MS = { ok: 4500, info: 4500, error: 9000 };
  var TOAST_MAX = 4;
  function toastStack() {
    var box = $id('toasts');
    if (!box) {
      box = el('div', 'toasts');
      box.id = 'toasts';
      box.setAttribute('aria-live', 'polite');
      doc.body.appendChild(box);
    }
    return box;
  }
  function dismissToast(t) {
    if (t.out) return;
    t.out = true;
    clearTimeout(t.timer);
    t.node.classList.add('is-out');
    setTimeout(function () { if (t.node.parentNode) t.node.parentNode.removeChild(t.node); }, 200);
  }
  function holdToast(t, hold) {
    clearTimeout(t.timer);
    if (!hold && !t.out) t.timer = setTimeout(function () { dismissToast(t); }, 2500);
  }
  var shown = [];
  function pushToast(content, kind) {
    kind = kind === false || kind === 'error' ? 'error' : kind === 'info' ? 'info' : 'ok';
    var text = typeof content === 'string' ? content : content.textContent;
    text = text.replace(/\s+/g, ' ').trim();
    if (!text) return;
    shown = shown.filter(function (t) { return !t.out; });
    // The same message again (a retry, a spinner added to it) refreshes the one on screen.
    for (var i = 0; i < shown.length; i++) {
      if (shown[i].text === text && shown[i].kind === kind) { holdToast(shown[i], true); holdToast(shown[i], false); return; }
    }
    var node = el('div', 'toast is-' + kind);
    node.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    var msg = el('div', 'toast-msg');
    if (typeof content === 'string') msg.textContent = content;
    else msg.appendChild(content);
    var x = el('button', 'toast-x');
    x.type = 'button';
    x.setAttribute('aria-label', 'Dismiss');
    x.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';
    node.appendChild(msg);
    node.appendChild(x);
    var t = { node: node, text: text, kind: kind, out: false, timer: null };
    x.addEventListener('click', function () { dismissToast(t); });
    node.addEventListener('mouseenter', function () { holdToast(t, true); });
    node.addEventListener('mouseleave', function () { holdToast(t, false); });
    node.addEventListener('focusin', function () { holdToast(t, true); });
    node.addEventListener('focusout', function () { holdToast(t, false); });
    toastStack().appendChild(node);
    shown.push(t);
    t.timer = setTimeout(function () { dismissToast(t); }, TOAST_MS[kind]);
    while (shown.filter(function (s) { return !s.out; }).length > TOAST_MAX) {
      dismissToast(shown.filter(function (s) { return !s.out; })[0]);
    }
  }
  function toast(message, ok) { pushToast(String(message == null ? '' : message), ok === false ? 'error' : 'ok'); }

  // Older pages still write their messages into #ajaxMsg and fade it in. It stays hidden; whatever is
  // written there becomes a toast, an error when the page marks it error or failure.
  function bridgeAjaxMsg() {
    var box = $id('ajaxMsg');
    if (!box || !window.MutationObserver) return;
    var queued = false;
    new MutationObserver(function () {
      if (queued) return;
      queued = true;
      // The class is set just after the text, so read both once the page's own code has run.
      setTimeout(function () {
        queued = false;
        var copy = el('div');
        copy.innerHTML = box.innerHTML;
        copy.querySelectorAll('.ui-icon, .fa, img, script').forEach(function (n) { n.parentNode.removeChild(n); });
        var cls = ' ' + box.className + ' ';
        pushToast(copy, /\s(error|failure)\s/.test(cls) ? 'error' : /\ssuccess\s/.test(cls) ? 'ok' : 'info');
      }, 0);
    }).observe(box, { childList: true, subtree: true, characterData: true });
  }
  function mark() { return window.issuarrMarkNav ? window.issuarrMarkNav() : null; }

  // Helpers shared by the rebuilt pages.
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function span(secs) {
    secs = Math.abs(secs);
    if (secs < 60) return 'under a minute';
    var m = Math.round(secs / 60);
    if (m < 60) return m + ' min';
    var h = Math.round(m / 60);
    if (h < 48) return h + ' h';
    return Math.round(h / 24) + ' days';
  }
  function relTime(epoch) {
    if (!epoch) return '';
    var d = epoch - Date.now() / 1000;
    if (Math.abs(d) < 45) return 'now';
    return d > 0 ? 'in ' + span(d) : span(d) + ' ago';
  }
  function clock(epoch) {
    if (!epoch) return '';
    var t = new Date(epoch * 1000);
    var today = new Date();
    var time = t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return t.toDateString() === today.toDateString() ? time : t.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + time;
  }
  function size(n) {
    if (n >= 1e12) return (n / 1e12).toFixed(2) + ' TB';
    if (n >= 1e9) return (n / 1e9).toFixed(1) + ' GB';
    return Math.round(n / 1e6) + ' MB';
  }
  // One line for a WebP preview, run, on-import queue or night's gradual conversion (the "webp" field of pp_activity).
  function webpText(w) {
    if (!w) return '';
    var num = function (n) { return (n || 0).toLocaleString(); };
    if (w.state === 'running') {
      var count = num(w.done) + '/' + num(w.total);
      if (w.stopping) return 'Stopping WebP (' + count + ')';
      return 'WebP: ' + count + ' issues' + (w.saved > 0 ? ', ' + size(w.saved) + ' saved' : '');
    }
    if (w.state === 'previewing') return w.stopping ? 'Stopping WebP preview' : 'WebP preview: ' + num(w.scanned) + ' files checked';
    if (w.state === 'import') return 'WebP on import: ' + num(w.waiting) + (w.waiting === 1 ? ' issue' : ' issues') + ' to convert';
    if (w.state === 'gradual') return 'WebP tonight: ' + num(w.done) + ' of ' + num(w.quota) + (w.why ? ' (waiting while ' + w.why + ')' : '');
    return '';
  }

  /* ---------- Sortable table headers ---------- */
  // Click a column header in a .dt table to sort by it, click again to flip it. Tables that show their rows a
  // page at a time set data-sort="custom" and sort their own data when they get the "issuarr:sort" event.
  // Headers with class "check", data-nosort or no visible text stay plain.
  var collate = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
  function sortHeaders(table) {
    var row = table.tHead && table.tHead.rows[0];
    return row ? Array.prototype.filter.call(row.cells, function (th) { return th.classList.contains('sortable'); }) : [];
  }
  function cellValue(td) {
    if (!td) return null;
    var v = td.getAttribute('data-sort');
    if (v == null) { var inp = td.querySelector('input:not([type=checkbox])'); v = inp ? inp.value : td.textContent; }
    v = String(v).replace(/\s+/g, ' ').trim();
    if (v === '' || v === '-' || v === '—') return null;
    var n = /^#?\s*(-?\d[\d,]*(?:\.\d+)?)$/.exec(v);
    return { text: v, num: n ? parseFloat(n[1].replace(/,/g, '')) : null };
  }
  function compareValues(a, b) {
    if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
    if (a.num !== null && b.num !== null) return a.num - b.num;
    // Text, or a number next to text such as #12 and #12A: compare as text with numbers in order (2 before 10).
    return collate.compare(a.text.replace(/^#\s*/, ''), b.text.replace(/^#\s*/, ''));
  }
  function sortRows(table) {
    var th = sortHeaders(table).filter(function (h) { return h.getAttribute('aria-sort') !== 'none'; })[0];
    var body = table.tBodies[0];
    if (!th || !body) return;
    var rows = Array.prototype.slice.call(body.rows);
    if (rows.some(function (r) { return r.cells.length === 1 && r.cells[0].colSpan > 1; })) return;
    var col = th.cellIndex, dir = th.getAttribute('aria-sort') === 'descending' ? -1 : 1;
    var keyed = rows.map(function (r, i) { return { r: r, v: cellValue(r.cells[col]), i: i }; });
    keyed.sort(function (a, b) {
      // Empty cells stay at the bottom whichever way the column is sorted.
      if (a.v === null || b.v === null) return compareValues(a.v, b.v) || a.i - b.i;
      return dir * compareValues(a.v, b.v) || a.i - b.i;
    });
    keyed.forEach(function (k) { body.appendChild(k.r); });
    if (table._sortWatch) table._sortWatch.takeRecords();
  }
  // Fix the column widths at their current size the first time a header is clicked, so they don't jump
  // about when the order changes.
  function freezeColumns(table) {
    if (table.classList.contains('is-frozen')) return;
    var row = table.tHead.rows[0];
    var widths = Array.prototype.map.call(row.cells, function (th) { return th.getBoundingClientRect().width; });
    Array.prototype.forEach.call(row.cells, function (th, i) { th.style.width = widths[i] + 'px'; });
    table.classList.add('is-frozen');
  }
  function setupSortable(table) {
    if (table.hasAttribute('data-sort-ready') || !table.tHead || !table.tHead.rows[0]) return;
    table.setAttribute('data-sort-ready', '');
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th) {
      var label = th.cloneNode(true);
      Array.prototype.forEach.call(label.querySelectorAll('.sr-only, input'), function (n) { n.remove(); });
      if (th.classList.contains('check') || th.hasAttribute('data-nosort') || !label.textContent.trim()) return;
      th.classList.add('sortable');
      th.tabIndex = 0;
      if (!th.hasAttribute('aria-sort')) th.setAttribute('aria-sort', 'none');
    });
    if (table.getAttribute('data-sort') === 'custom' || !table.tBodies[0] || !window.MutationObserver) return;
    // Pages that redraw their rows (live refresh, filters) keep the order the person picked.
    table._sortWatch = new MutationObserver(function () { sortRows(table); });
    table._sortWatch.observe(table.tBodies[0], { childList: true });
  }
  function sortBy(th) {
    var table = th.closest('table');
    var dir = th.getAttribute('aria-sort') === 'ascending' ? 'descending'
      : th.getAttribute('aria-sort') === 'descending' ? 'ascending'
      : th.getAttribute('data-sort-first') === 'desc' ? 'descending' : 'ascending';
    freezeColumns(table);
    sortHeaders(table).forEach(function (h) { h.setAttribute('aria-sort', h === th ? dir : 'none'); });
    if (table.getAttribute('data-sort') === 'custom') {
      table.dispatchEvent(new CustomEvent('issuarr:sort', { detail: { key: th.getAttribute('data-key') || String(th.cellIndex), dir: dir === 'ascending' ? 1 : -1 } }));
    } else {
      sortRows(table);
    }
  }
  // For pages with their own sort menu: picking from the menu clears the header arrows.
  function clearSort(table) { sortHeaders(table).forEach(function (h) { h.setAttribute('aria-sort', 'none'); }); }
  function setupSortableTables() {
    Array.prototype.forEach.call(doc.querySelectorAll('table.dt'), setupSortable);
    doc.addEventListener('click', function (e) {
      var th = e.target.closest && e.target.closest('table.dt th.sortable');
      if (th) sortBy(th);
    });
    doc.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var th = e.target.closest && e.target.closest('table.dt th.sortable');
      if (th) { e.preventDefault(); sortBy(th); }
    });
  }

  // "Are you sure?" in the page instead of the browser's confirm(). then() runs only when the person says yes.
  // opts.ok names the button ("Remove"); opts.danger makes it red and starts on Cancel. A message that opens with
  // a question ("Remove 3 series? Files stay on disk.") shows the question as the title and the rest below it,
  // unless opts.title gives the title.
  var askBox = null, askThen = null, askLast = null;
  function ask(message, opts, then) {
    if (typeof opts === 'function') { then = opts; opts = {}; }
    opts = opts || {};
    if (!askBox) {
      askBox = el('div', 'jump-backdrop');
      askBox.id = 'ask';
      askBox.hidden = true;
      askBox.innerHTML = '<div class="jump ask" role="alertdialog" aria-modal="true" aria-labelledby="ask-title" aria-describedby="ask-text">' +
        '<div class="add-head"><h2 id="ask-title"></h2><p id="ask-text"></p></div>' +
        '<div class="ask-foot"><button type="button" class="btn" id="ask-no">Cancel</button><button type="button" class="btn" id="ask-yes"></button></div></div>';
      doc.body.appendChild(askBox);
      var done = function (yes) {
        askBox.hidden = true;
        var fn = askThen;
        askThen = null;
        if (askLast && askLast.focus) askLast.focus();
        if (yes && fn) fn();
      };
      $id('ask-yes').addEventListener('click', function () { done(true); });
      $id('ask-no').addEventListener('click', function () { done(false); });
      askBox.addEventListener('mousedown', function (e) { if (e.target === askBox) done(false); });
      askBox.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); }
        else if (e.key === 'Tab') {
          // Keep focus on the two buttons while the question is open.
          e.preventDefault();
          ($id(doc.activeElement && doc.activeElement.id === 'ask-yes' ? 'ask-no' : 'ask-yes')).focus();
        }
      });
    }
    var text = String(message || '');
    var m = opts.title ? [null, opts.title, text] : /^([^?]*\?)\s+([\s\S]+)$/.exec(text);
    $id('ask-title').textContent = m ? m[1] : text;
    $id('ask-text').textContent = m ? m[2] : '';
    $id('ask-text').hidden = !m;
    var yes = $id('ask-yes');
    yes.textContent = opts.ok || 'OK';
    yes.className = 'btn ' + (opts.danger ? 'btn-danger' : 'btn-primary');
    askThen = then;
    askLast = doc.activeElement;
    askBox.hidden = false;
    (opts.danger ? $id('ask-no') : yes).focus();
  }

  // Links and buttons that only need a yes first: <a href="restart" data-confirm="Restart Issuarr now?" data-confirm-ok="Restart">.
  doc.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-confirm]');
    if (!a) return;
    e.preventDefault();
    ask(a.getAttribute('data-confirm'), { ok: a.getAttribute('data-confirm-ok'), danger: a.hasAttribute('data-confirm-danger') }, function () {
      location.href = a.href;
    });
  });

  window.Issuarr = { esc: esc, toast: toast, ask: ask, relTime: relTime, clock: clock, webpText: webpText, clearSort: clearSort };

  /* ---------- Pages whose tab strip moved into the sidebar ---------- */

  var TABBED = { manage: true, config: true };

  function tabsWidget() {
    if (!$) return null;
    var t = $('#tabs');
    return t.length && t.data('tabs') ? t : null;
  }

  function selectTab(hash) {
    var t = tabsWidget();
    if (!t || !hash) return false;
    var anchors = t.find('> ul a');
    var idx = -1;
    anchors.each(function (i) { if (this.getAttribute('href') === hash) idx = i; });
    if (idx < 0) return false;
    t.tabs('select', idx);
    return true;
  }

  // The browser jumps to #tabs-N on load; keep the page title in view instead.
  function toTop() {
    setTimeout(function () { window.scrollTo(0, 0); }, 0);
    window.addEventListener('load', function () { window.scrollTo(0, 0); }, { once: true });
  }

  // On pages split across the sidebar, the title names the section shown.
  function syncTitle() {
    if (!doc.body.classList.contains('tabs-in-sidebar') || !TABBED[path]) return;
    var cur = doc.querySelector('#sidebar [aria-current="page"]');
    var h1 = doc.querySelector('#main h1');
    if (!cur || !h1) return;
    var label = cur.getAttribute('data-label') || cur.textContent.trim();
    var parentLink = cur.classList.contains('nav-child') ? cur.closest('.nav-item').querySelector('.nav-link') : null;
    var parent = parentLink ? parentLink.getAttribute('data-label') : '';
    h1.textContent = '';
    if (parent) h1.appendChild(el('span', 'page-crumb', parent + ' › '));
    h1.appendChild(doc.createTextNode(label));
    doc.title = doc.title.replace(/ - [^-]*$/, ' - ' + (parent ? parent + ' › ' : '') + label);
  }

  function setupTabbedPage(tries) {
    if (path === 'ledger') doc.body.classList.add('tabs-in-sidebar');
    if (!TABBED[path] || !$id('tabs')) return;
    doc.body.classList.add('tabs-in-sidebar');
    var t = tabsWidget();
    if (!t) {
      // Some pages build their tabs in a late ready handler; wait for them.
      tries = tries || 0;
      if (tries < 60) setTimeout(function () { setupTabbedPage(tries + 1); }, 50);
      return;
    }
    t.bind('tabsselect', function (e, ui) {
      if (ui && ui.panel && ui.panel.id && location.hash !== '#' + ui.panel.id) {
        history.replaceState(null, '', '#' + ui.panel.id);
        mark();
        syncTitle();
      }
    });
    if (location.hash) {
      selectTab(location.hash);
      toTop();
    } else {
      var current = mark();
      var href = current && current.getAttribute('href');
      if (href && href.indexOf('#') > 0) {
        var hash = href.slice(href.indexOf('#'));
        if (selectTab(hash)) history.replaceState(null, '', hash);
      }
    }
    window.addEventListener('hashchange', function () {
      if (selectTab(location.hash)) window.scrollTo(0, 0);
      mark();  // the title reads the highlighted sidebar entry, so update that first
      syncTitle();
    });
    syncTitle();
  }

  /* ---------- Title + actions in one row ---------- */

  function setupPageHead() {
    var main = $id('main');
    var menu = $id('subhead_menu');
    if (!main || !menu || !menu.querySelector('a')) return;
    var title = main.querySelector('h1');
    if (!title || title.closest('.page-head') || title.closest('.lg-head')) return;
    var head = el('div', 'page-head');
    title.parentNode.insertBefore(head, title);
    head.appendChild(title);
    menu.classList.add('page-actions');
    head.appendChild(menu);
    var sub = $id('subhead');
    if (sub && !sub.textContent.trim() && !sub.querySelector('img, input, a, select')) sub.style.display = 'none';
  }

  /* ---------- Small screens ---------- */

  function setupMobileNav() {
    var app = doc.querySelector('.app');
    var toggle = $id('nav-toggle');
    var scrim = $id('nav-scrim');
    if (!app || !toggle) return;
    function set(open) {
      app.classList.toggle('nav-open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (scrim) scrim.hidden = !open;
    }
    toggle.addEventListener('click', function () { set(!app.classList.contains('nav-open')); });
    if (scrim) scrim.addEventListener('click', function () { set(false); });
    doc.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && app.classList.contains('nav-open')) set(false);
    });
    $id('sidebar').addEventListener('click', function (e) {
      if (e.target.closest('a[href]') && window.matchMedia('(max-width: 900px)').matches) set(false);
    });
  }

  /* ---------- Running now ---------- */

  function setupDock() {
    var dock = $id('dock');
    if (!dock) return;
    var rows = { pp: $id('dock-pp'), search: $id('dock-search'), dl: $id('dock-dl'), webp: $id('dock-webp'), mon: $id('dock-monitor'), idle: $id('dock-idle') };
    var importRow = $id('import_indicator');
    var timer = null;

    function show(row, text) {
      if (!row) return;
      row.hidden = !text;
      if (text) row.querySelector('.dock-text').textContent = text;
    }
    function refreshIdle() {
      var busy = ['pp', 'search', 'dl', 'webp'].some(function (k) { return rows[k] && !rows[k].hidden; });
      if (importRow && importRow.style.display !== 'none') busy = true;
      if (rows.idle) rows.idle.hidden = busy;
    }
    function searchText(s) {
      if (!s) return '';
      var n = (s.waiting || []).length;
      var waiting = n ? ' (' + n + ' waiting)' : '';
      if (s.current) return 'Searching ' + (s.current.name || '') + ' #' + (s.current.number == null ? '?' : s.current.number) + waiting;
      if (s.busy) return 'Checking RSS feeds' + waiting;
      return n ? n + ' queued for search' : '';
    }
    // Live counts next to Downloads and Wanted, before the Needs attention count if there is one.
    function liveCount(sel, n, title) {
      var link = doc.querySelector(sel);
      if (!link) return;
      var b = link.querySelector('.nav-badge.is-live');
      if (!n) { if (b) b.remove(); return; }
      if (!b) {
        b = doc.createElement('span');
        b.className = 'nav-badge is-live';
        link.insertBefore(b, link.querySelector('.nav-badge.is-attention'));
      }
      b.textContent = n;
      b.title = title;
    }
    function poll() {
      if (doc.hidden || offline.down) return;
      fetch('pp_activity', { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          show(rows.pp, d.state === 'Working' ? 'Post-processing' + (d.detail ? ': ' + d.detail : '') : '');
          show(rows.search, searchText(d.search));
          var queued = (d.download_counts || {}).Queued || 0;
          var dl = d.download ? 'Downloading ' + d.download : '';
          if (queued) dl = dl ? dl + ' (' + queued + ' queued)' : queued + ' queued for download';
          show(rows.dl, dl);
          show(rows.webp, webpText(d.webp));
          if (rows.webp) rows.webp.title = d.webp && d.webp.current ? d.webp.current : '';
          show(rows.mon, d.monitor_enabled ? 'Folder Monitor: ' + (d.monitor_status || 'on') : '');
          if (d.queue_count != null) {
            var q = d.queue_count;
            liveCount('#sidebar .nav-link[href="queueManage"]', q, q + ' downloading or queued');
            liveCount('#sidebar .nav-child[href="queueManage"]', q, q + ' downloading or queued');
          }
          if (d.search) {
            var s = (d.search.current ? 1 : 0) + (d.search.waiting || []).length;
            liveCount('#sidebar .nav-link[href="wanted"]', s, s + ' in the search queue');
          }
          refreshIdle();
        })
        .catch(function (err) {
          // The server not answering at all is a lost connection; keep polling once it's back.
          if (err instanceof TypeError || /^50[234]$/.test(err.message)) { offline.lost(); return; }
          if (timer) { clearInterval(timer); timer = null; }
        });
    }
    offline.onBack = poll;
    poll();
    timer = setInterval(poll, 20000);
    doc.addEventListener('visibilitychange', function () { if (!doc.hidden && timer) poll(); });
    // Pages with the flow line poll more often: keep the search row in step with it.
    doc.addEventListener('issuarr:flow', function (e) {
      var s = e.detail.now.search;
      show(rows.search, searchText({ current: s.current, busy: s.busy, waiting: new Array(s.waiting) }));
      refreshIdle();
    });
    if (importRow && window.MutationObserver) {
      new MutationObserver(refreshIdle).observe(importRow, { attributes: true, attributeFilter: ['style'] });
    }
  }

  /* ---------- Lost connection ---------- */

  // When Issuarr stops answering (restarting, updating, the container stopped), a notice says so instead of
  // the page quietly going stale. It checks again every few seconds and goes away by itself once Issuarr is back.
  var offline = {
    down: false, onBack: null, timer: null, fails: 0, bar: null,
    lost: function () {
      if (offline.timer) return;
      offline.fails = 0;
      offline.check();
    },
    check: function () {
      offline.timer = setTimeout(function () {
        fetch('pp_activity', { credentials: 'same-origin', cache: 'no-store', headers: { 'Accept': 'application/json' } })
          .then(function (r) { if (!r.ok && /^50[234]$/.test(String(r.status))) throw new Error(r.status); offline.back(); })
          .catch(function () {
            offline.fails += 1;
            // One missed answer can be a blip; say something from the second one on.
            if (offline.fails >= 2) offline.show();
            offline.check();
          });
      }, offline.fails ? 5000 : 2000);
    },
    show: function () {
      if (offline.down) return;
      offline.down = true;
      var bar = offline.bar;
      if (!bar) {
        bar = offline.bar = el('div', 'offline-bar');
        bar.setAttribute('role', 'status');
        bar.innerHTML = '<span class="offline-dot" aria-hidden="true"></span><span>Issuarr isn\'t answering. Trying again every few seconds…</span>';
        doc.body.appendChild(bar);
      }
      bar.hidden = false;
    },
    back: function () {
      offline.timer = null;
      var was = offline.down;
      offline.down = false;
      if (offline.bar) offline.bar.hidden = true;
      if (was) toast('Connected to Issuarr again. Reload the page if anything looks out of date.');
      if (offline.onBack) offline.onBack();
    }
  };

  /* ---------- Ctrl K jump menu ---------- */

  var ACTIONS = [
    { label: 'Search for wanted issues now', job: 'search', done: 'Search started' },
    { label: 'Check RSS feeds now', job: 'rss', done: 'RSS check started' },
    { label: 'Run Folder Monitor now', job: 'monitor', done: 'Folder Monitor started' },
    { label: 'Update all series from ComicVine', job: 'updater', done: 'Series update started' },
    { label: 'Refresh this week\'s pull list', job: 'weekly', done: 'Pull list refresh started' },
    { label: 'Check for a new version', job: 'version', done: 'Version check started' },
    { label: 'Restart Issuarr', href: 'restart', confirm: 'Restart Issuarr now?', ok: 'Restart' },
    { label: 'Shut down Issuarr', href: 'shutdown', confirm: 'Shut down Issuarr? It stays off until you start it again.', ok: 'Shut down' }
  ];

  function setupJump() {
    var backdrop = $id('jump');
    var input = $id('jump-input');
    var list = $id('jump-list');
    if (!backdrop || !input || !list) return;

    var pages = [];
    doc.querySelectorAll('#sidebar .nav-item').forEach(function (item) {
      var link = item.querySelector(':scope > .nav-link');
      if (!link) return;
      var parent = link.getAttribute('data-label') || link.textContent.trim();
      if (link.getAttribute('href') && link.getAttribute('href') !== '#' && !link.hasAttribute('data-action')) {
        pages.push({ label: parent, href: link.getAttribute('href') });
      }
      item.querySelectorAll('.nav-child').forEach(function (c) {
        pages.push({ label: parent + ' › ' + (c.getAttribute('data-label') || c.textContent.trim()), href: c.getAttribute('href') });
      });
    });

    var options = [];
    var active = 0;
    var series = [];
    var seriesFor = '';
    var seriesTimer = null;
    var lastFocus = null;

    // Every word has to appear; words that start a word in the label rank higher.
    function score(label, q) {
      var l = label.toLowerCase(), total = 0;
      var words = q.split(/\s+/).filter(Boolean);
      for (var k = 0; k < words.length; k++) {
        var i = l.indexOf(words[k]);
        if (i < 0) return 0;
        total += i === 0 || /[\s›(]/.test(l.charAt(i - 1)) ? 2 : 1;
      }
      return total;
    }
    function pick(items, q) {
      if (!q) return items.slice();
      return items.map(function (x) { return { x: x, s: score(x.label, q) }; })
        .filter(function (r) { return r.s; })
        .sort(function (a, b) { return b.s - a.s; })
        .map(function (r) { return r.x; });
    }

    function render() {
      var q = input.value.trim();
      var lq = q.toLowerCase();
      var groups = [];
      if (q && series.length && seriesFor === lq) {
        groups.push({ title: 'In your library', items: series.map(function (s) {
          return { label: s.name + (s.year ? ' (' + s.year + ')' : ''), hint: s.publisher || '', href: 'comicDetails?ComicID=' + encodeURIComponent(s.id) };
        }) });
      }
      var p = pick(pages, lq);
      if (p.length) groups.push({ title: 'Pages', items: p.slice(0, q ? 8 : 40) });
      var a = pick(ACTIONS, lq);
      if (a.length) groups.push({ title: 'Actions', items: a });

      list.textContent = '';
      options = [];
      groups.forEach(function (g, gi) {
        var head = el('li', 'jump-group', g.title);
        head.setAttribute('role', 'presentation');
        head.id = 'jump-g' + gi;
        list.appendChild(head);
        g.items.forEach(function (item) {
          var li = el('li', 'jump-opt');
          li.setAttribute('role', 'option');
          li.id = 'jump-o' + options.length;
          li.appendChild(el('span', null, item.label));
          if (item.hint) li.appendChild(el('span', 'jump-hint', item.hint));
          li.addEventListener('mousemove', function () { setActive(options.indexOf(item)); });
          li.addEventListener('click', function () { run(item); });
          item.node = li;
          options.push(item);
          list.appendChild(li);
        });
      });
      if (!options.length) list.appendChild(el('li', 'jump-empty', 'Nothing in your library or menus matches. To add a new series, use Add series.'));
      setActive(Math.min(active, options.length - 1));
    }

    function setActive(i) {
      active = Math.max(0, i);
      options.forEach(function (o, j) { o.node.setAttribute('aria-selected', j === active ? 'true' : 'false'); });
      var cur = options[active];
      if (cur) {
        input.setAttribute('aria-activedescendant', cur.node.id);
        cur.node.scrollIntoView({ block: 'nearest' });
      } else {
        input.removeAttribute('aria-activedescendant');
      }
    }

    function run(item) {
      if (item.job) {
        close();
        fetch('schedulerForceCheck?jobid=' + encodeURIComponent(item.job), { credentials: 'same-origin' })
          .then(function (r) { toast(r.ok ? item.done : 'That didn\'t work. Check the log.', r.ok); })
          .catch(function () { toast('That didn\'t work. Check the log.', false); });
        return;
      }
      if (!item.confirm) { location.href = item.href; return; }
      close();
      ask(item.confirm, { ok: item.ok, danger: true }, function () { location.href = item.href; });
    }

    function fetchSeries() {
      var q = input.value.trim().toLowerCase();
      if (q.length < 2) { series = []; seriesFor = ''; return; }
      fetch('jump_series?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (rows) {
          if (input.value.trim().toLowerCase() !== q) return;
          series = rows || [];
          seriesFor = q;
          active = 0;
          render();
        })
        .catch(function () {});
    }

    function open(prefill) {
      lastFocus = doc.activeElement;
      backdrop.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      input.value = prefill || '';
      active = 0;
      series = [];
      render();
      input.focus();
    }
    function close() {
      backdrop.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    input.addEventListener('input', function () {
      active = 0;
      render();
      clearTimeout(seriesTimer);
      seriesTimer = setTimeout(fetchSeries, 160);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setActive((active + 1) % Math.max(options.length, 1)); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((active - 1 + options.length) % Math.max(options.length, 1)); }
      else if (e.key === 'Enter') { e.preventDefault(); if (options[active]) run(options[active]); }
      else if (e.key === 'Escape') { e.preventDefault(); close(); }
      else if (e.key === 'Tab') { e.preventDefault(); }
    });
    backdrop.addEventListener('mousedown', function (e) { if (e.target === backdrop) close(); });
    doc.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        if (backdrop.hidden) open(); else close();
      }
    });
    doc.querySelectorAll('[data-action="jump"]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); open(); });
    });
  }

  /* ---------- Settings › Appearance ---------- */

  var CSS_VARS = [
    ['--ink', 'Page background'], ['--surface', 'Panels and tables'], ['--raised', 'Buttons, hover'],
    ['--line', 'Borders, empty bar'], ['--text', 'Text and main buttons'], ['--muted', 'Secondary text'],
    ['--have', 'Downloaded'], ['--wanted', 'Wanted'], ['--snatched', 'Snatched, in progress'],
    ['--failed', 'Failed'], ['--ignored', 'Ignored'], ['--radius', 'Corner rounding'],
    ['--font-display', 'Titles'], ['--font-body', 'Everything else'], ['--font-mono', 'Numbers and paths']
  ];

  function setupAppearance() {
    var area = $id('custom_css');
    if (!area) return;
    var check = $id('css-check');
    var preview = $id('css-preview');
    var varsBody = $id('css-vars-body');
    var saved = $id('custom-css');
    var timer = null;

    doc.querySelectorAll('input[name="ui_theme"]').forEach(function (r) {
      r.addEventListener('change', function () {
        if (r.value === 'system') doc.documentElement.removeAttribute('data-theme');
        else doc.documentElement.setAttribute('data-theme', r.value);
        drawVars();
      });
    });

    function drawVars() {
      if (!varsBody) return;
      var style = getComputedStyle(doc.documentElement);
      var text = area.value;
      varsBody.textContent = '';
      CSS_VARS.forEach(function (v) {
        var value = style.getPropertyValue(v[0]).trim();
        if (v[0].indexOf('--font') === 0) value = value.split(',')[0].replace(/["']/g, '');
        var tr = el('tr');
        if (new RegExp(v[0].replace(/-/g, '\\-') + '\\s*:').test(text)) tr.className = 'is-set';
        var sw = el('td', 'swatch');
        var chip = el('span');
        if (/^(#|rgb|hsl|color-mix)/i.test(value)) chip.style.background = value;
        else chip.style.borderStyle = 'dashed';
        sw.appendChild(chip);
        var name = el('td');
        name.appendChild(el('code', null, v[0]));
        tr.appendChild(sw);
        tr.appendChild(name);
        tr.appendChild(el('td', null, v[1]));
        tr.appendChild(el('td', 'value', value.length > 28 ? value.slice(0, 26) + '…' : value));
        varsBody.appendChild(tr);
      });
    }

    function applyPreview() {
      var live = $id('css-live');
      if (preview && preview.checked) {
        if (!live) {
          live = el('style');
          live.id = 'css-live';
          doc.head.appendChild(live);
        }
        live.textContent = area.value;
        if (saved) saved.disabled = true;
      } else {
        if (live) live.remove();
        if (saved) saved.disabled = false;
      }
    }

    function update() {
      var text = area.value;
      var opens = (text.match(/{/g) || []).length;
      var closes = (text.match(/}/g) || []).length;
      var lines = text ? text.split('\n').length : 0;
      var set = CSS_VARS.filter(function (v) { return new RegExp(v[0].replace(/-/g, '\\-') + '\\s*:').test(text); }).length;
      var ok = opens === closes;
      area.classList.toggle('is-bad', !ok);
      if (check) {
        check.className = 'css-check' + (!text.trim() ? '' : ok ? ' is-ok' : ' is-bad');
        check.textContent = !text.trim() ? 'Empty' : ok
          ? 'Looks valid · ' + lines + (lines === 1 ? ' line' : ' lines') + ' · ' + set + ' of ' + CSS_VARS.length + ' variables set'
          : 'Check your braces: ' + opens + ' { and ' + closes + ' }';
      }
      applyPreview();
      drawVars();
    }

    area.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(update, 150); });
    area.addEventListener('keydown', function (e) {
      if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
        e.preventDefault();
        var s = area.selectionStart;
        area.setRangeText('  ', s, area.selectionEnd, 'end');
        clearTimeout(timer); timer = setTimeout(update, 150);
      }
    });
    if (preview) preview.addEventListener('change', update);

    var file = $id('css-file');
    var importBtn = $id('css-import');
    if (file && importBtn) {
      importBtn.addEventListener('click', function () { file.click(); });
      file.addEventListener('change', function () {
        var f = file.files && file.files[0];
        if (!f) return;
        var reader = new FileReader();
        reader.onload = function () { area.value = String(reader.result || ''); update(); toast('Loaded ' + f.name + '. Save to keep it.'); };
        reader.readAsText(f);
        file.value = '';
      });
    }
    var exportBtn = $id('css-export');
    if (exportBtn) exportBtn.addEventListener('click', function () {
      var url = URL.createObjectURL(new Blob([area.value], { type: 'text/css' }));
      var a = el('a');
      a.href = url;
      a.download = 'issuarr-custom.css';
      doc.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    });
    var resetBtn = $id('css-reset');
    if (resetBtn) resetBtn.addEventListener('click', function () {
      var go = function () {
        area.value = '/* Loaded after the built-in theme, on every page. */\n:root {\n  \n}\n';
        update();
        area.focus();
      };
      if (area.value.trim()) ask('Clear the editor? Nothing changes until you save.', { ok: 'Clear' }, go);
      else go();
    });
    update();
  }

  /* ---------- Add series: searches ComicVine, never the library ---------- */

  function setupAddSeries() {
    var box = $id('add-series');
    var input = $id('add-series-input');
    if (!box || !input) return;
    var last = null;
    function open() {
      last = doc.activeElement;
      box.hidden = false;
      input.value = '';
      input.focus();
    }
    function close() {
      box.hidden = true;
      if (last && last.focus) last.focus();
    }
    doc.querySelectorAll('[data-action="add"]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); open(); });
    });
    box.addEventListener('mousedown', function (e) { if (e.target === box) close(); });
    box.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); close(); } });
  }

  // Once after an update: the changelog lines this install hasn't shown yet. Closing it marks them seen.
  function setupWhatsNew() {
    var box = $id('whats-new');
    if (!box || !doc.body.hasAttribute('data-whats-new')) return;
    var body = $id('whats-new-body');
    var last = null;
    function close() {
      box.hidden = true;
      fetch('whats_new_seen', { method: 'POST', credentials: 'same-origin' }).catch(function () {});
      doc.body.removeAttribute('data-whats-new');
      if (last && last.focus) last.focus();
    }
    fetch('whats_new', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.releases || !d.releases.length) return;
        body.textContent = '';
        d.releases.forEach(function (rel) {
          body.appendChild(el('h3', null, rel.name));
          rel.groups.forEach(function (g) {
            if (g.name) body.appendChild(el('h4', null, g.name));
            var ul = el('ul');
            g.items.forEach(function (it) {
              var li = el('li');
              // Built on the server from the changelog that ships with this install.
              li.innerHTML = it.html + ' ';
              var ids = el('span', 'whats-new-ids');
              it.commits.forEach(function (c, i) {
                var a = el('a', null, c.id);
                a.href = c.url; a.target = '_blank'; a.rel = 'noopener';
                a.title = 'The commit that made this change';
                if (i) ids.appendChild(doc.createTextNode(', '));
                ids.appendChild(a);
              });
              li.appendChild(doc.createTextNode('('));
              li.appendChild(ids);
              li.appendChild(doc.createTextNode(')'));
              ul.appendChild(li);
            });
            body.appendChild(ul);
          });
        });
        if (d.changelog_url) $id('whats-new-more').href = d.changelog_url;
        last = doc.activeElement;
        box.hidden = false;
        $id('whats-new-close').focus();
      })
      .catch(function () {});
    $id('whats-new-close').addEventListener('click', close);
    box.addEventListener('mousedown', function (e) { if (e.target === box) close(); });
    box.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); close(); } });
  }

  // "More" menus (details.menu) close on an outside click, on Escape, and after a choice.
  function setupMenus() {
    function closeAll(except) {
      doc.querySelectorAll('details.menu[open]').forEach(function (m) { if (m !== except) m.open = false; });
    }
    doc.addEventListener('click', function (e) {
      var inMenu = e.target.closest && e.target.closest('details.menu');
      closeAll(inMenu);
      if (inMenu && e.target.closest('.menu-list .btn')) inMenu.open = false;
    });
    // A menu near the bottom of the window, or of a scrolling table that would clip it,
    // opens upward so its last items aren't cut off. When the table is too short for
    // either direction, the menu is lifted out of it and pinned to the window instead.
    function clipBox(el) {
      var top = 0, bottom = window.innerHeight;
      for (var p = el.parentElement; p && p !== doc.body; p = p.parentElement) {
        var cs = getComputedStyle(p);
        if (cs.overflowY !== 'visible' || cs.overflowX !== 'visible') {
          var r = p.getBoundingClientRect();
          top = Math.max(top, r.top);
          bottom = Math.min(bottom, r.bottom);
        }
      }
      return { top: top, bottom: bottom };
    }
    doc.addEventListener('toggle', function (e) {
      var m = e.target;
      if (!m.matches || !m.matches('details.menu')) return;
      var list = m.querySelector('.menu-list');
      m.classList.remove('menu-up', 'menu-fixed');
      if (list) { list.style.top = ''; list.style.left = ''; }
      if (!m.open || !list) return;
      var r = list.getBoundingClientRect(), box = clipBox(m), s = m.getBoundingClientRect(), gap = 6;
      if (r.bottom <= box.bottom) return;
      if (s.top - box.top > r.height + gap) { m.classList.add('menu-up'); return; }
      var winH = window.innerHeight;
      var top = winH - s.bottom - gap >= r.height || s.top < winH - s.bottom ? s.bottom + gap : s.top - gap - r.height;
      m.classList.add('menu-fixed');
      list.style.top = Math.max(gap, top) + 'px';
      list.style.left = r.left + 'px';
    }, true);
    // A pinned menu would drift away from its button, so scrolling or resizing closes it.
    function closePinned(e) {
      var m = doc.querySelector('details.menu.menu-fixed[open]');
      if (m && !(e.target && e.target.nodeType === 1 && m.contains(e.target))) m.open = false;
    }
    doc.addEventListener('scroll', closePinned, true);
    window.addEventListener('resize', closePinned);
    doc.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      var open = doc.querySelector('details.menu[open]');
      if (!open) return;
      open.open = false;
      var s = open.querySelector('summary');
      if (s) s.focus();
    });
  }

  function start() {
    bridgeAjaxMsg();
    setupSortableTables();
    setupMenus();
    setupTabbedPage();
    setupPageHead();
    setupMobileNav();
    setupDock();
    setupJump();
    setupAddSeries();
    setupAppearance();
    setupWhatsNew();
    setupSecrets();
    window.addEventListener('hashchange', mark);
  }

  // input.secret boxes are masked by CSS. A browser that can't draw them as dots gets a
  // real password box instead, so the value stays hidden (it may then offer to save it).
  function setupSecrets() {
    var ok = window.CSS && CSS.supports && CSS.supports('-webkit-text-security', 'disc');
    if (ok) return;
    var boxes = doc.querySelectorAll('input.secret');
    for (var i = 0; i < boxes.length; i++) boxes[i].type = 'password';
  }

  if ($) $(start);
  else doc.addEventListener('DOMContentLoaded', start);
})();
