/* Issue details on the series page: one issue at a time, with Previous and Next (or the arrow keys) to step through the list. */
(function () {
  'use strict';

  var box = null, back = null, cur = null, cache = {}, timer = null, seq = 0;
  // Each issue not seen yet asks ComicVine (or opens the file), so wait until stepping stops before asking.
  var SETTLE_MS = 350;

  function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function blank(v) { return v == null || v === '' || v === 'None'; }

  function build() {
    box = document.createElement('div');
    box.className = 'jump-backdrop';
    box.id = 'issue-panel';
    box.hidden = true;
    box.innerHTML = '<div class="jump ip" role="dialog" aria-modal="true" aria-labelledby="ip-title">' +
      '<div class="ip-head"><div class="ip-heading"><h2 id="ip-title"></h2><p id="ip-sub"></p></div>' +
      '<div class="ip-nav"><span class="ip-pos" id="ip-pos" aria-live="polite"></span>' +
      '<button type="button" class="btn btn-sm" data-ui id="ip-prev" aria-label="Previous issue" title="Previous issue (←)">‹</button>' +
      '<button type="button" class="btn btn-sm" data-ui id="ip-next" aria-label="Next issue" title="Next issue (→)">›</button>' +
      '<button type="button" class="btn btn-sm btn-ghost" data-ui id="ip-close" aria-label="Close">✕</button></div></div>' +
      '<div class="ip-body"><div class="ip-cover" id="ip-cover"></div><div class="ip-info" id="ip-info"></div></div></div>';
    document.body.appendChild(box);
    box.addEventListener('mousedown', function (e) { if (e.target === box) close(); });
    box.querySelector('#ip-close').addEventListener('click', close);
    box.querySelector('#ip-prev').addEventListener('click', function () { step(-1); });
    box.querySelector('#ip-next').addEventListener('click', function () { step(1); });
    box.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); close(); return; }
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); step(e.key === 'ArrowLeft' ? -1 : 1); return; }
      if (e.key !== 'Tab') return;
      var f = Array.prototype.filter.call(box.querySelectorAll('button, a[href]'), function (el) { return !el.disabled; });
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }

  function rows() { return cur.dt.rows({ page: 'current' }).nodes().toArray(); }

  // Row data from the series page tables: 0 number, 1 name, 2 cover date, 3 status, 4 issue id, 10 store date.
  function show(i) {
    var list = rows();
    if (!list.length) { close(); return; }
    cur.i = Math.max(0, Math.min(i, list.length - 1));
    var d = cur.dt.row(list[cur.i]).data();
    cur.id = d[4];
    var info = cur.dt.page.info(), at = info.start + cur.i;
    box.querySelector('#ip-title').textContent = '#' + d[0] + (blank(d[1]) ? '' : ' ' + d[1]);
    var date = !blank(d[10]) && d[10] !== '0000-00-00' ? d[10] : d[2];
    box.querySelector('#ip-sub').innerHTML = (typeof window.issueStatus === 'function' ? window.issueStatus(d, false) : esc(d[3])) +
      (blank(date) || date === '0000-00-00' ? '' : ' <span class="ip-date">' + esc(date) + '</span>');
    box.querySelector('#ip-pos').textContent = (at + 1) + ' of ' + info.recordsDisplay;
    box.querySelector('#ip-prev').disabled = at <= 0;
    box.querySelector('#ip-next').disabled = at >= info.recordsDisplay - 1;
    load(d[4]);
  }

  function step(dir) {
    if (!cur) return;
    var list = rows(), i = cur.i + dir;
    if (i >= 0 && i < list.length) { show(i); return; }
    var info = cur.dt.page.info();
    if ((dir < 0 && info.page <= 0) || (dir > 0 && info.page >= info.pages - 1)) return;
    // Past the end of this page: turn the table's page and carry on from its first or last issue.
    cur.dt.one('draw', function () { if (cur && !box.hidden) show(dir > 0 ? 0 : rows().length - 1); });
    cur.dt.page(dir > 0 ? 'next' : 'previous').draw('page');
  }

  function load(id) {
    clearTimeout(timer);
    var mine = ++seq;
    if (cache[id]) { fill(cache[id]); return; }
    box.querySelector('#ip-cover').innerHTML = '<div class="ip-noimg"></div>';
    box.querySelector('#ip-info').innerHTML = '<p class="ip-muted">Loading details…</p>';
    timer = setTimeout(function () {
      fetch('IssueInfo?issueid=' + encodeURIComponent(id), { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (o) { if (o.status === 'success') cache[id] = o; if (mine === seq) fill(o); })
        .catch(function () {
          if (mine !== seq) return;
          box.querySelector('#ip-info').innerHTML = '<p class="ip-muted">Couldn\'t load details from ComicVine or the file. The log may say why.</p>';
        });
    }, SETTLE_MS);
  }

  var CREDITS = [['writers', 'Writer'], ['pencillers', 'Pencils'], ['inkers', 'Inks'], ['colorists', 'Colours'],
    ['letterers', 'Letters'], ['cover_artists', 'Cover'], ['editors', 'Editor']];

  function fill(o) {
    var m = o.metadata || {}, img = o.IssueImage;
    box.querySelector('#ip-cover').innerHTML = !blank(img) ? '<img alt="Cover" src="data:image/jpeg;base64,' + esc(img) + '">' : '<div class="ip-noimg"></div>';
    if (o.status !== 'success') {
      box.querySelector('#ip-info').innerHTML = '<p class="ip-muted">' + (m.filename ? 'Couldn\'t read the details inside the file. Writing metadata into it again may help.' : 'Couldn\'t get this issue\'s details from ComicVine.') + '</p>';
      return;
    }
    var h = '';
    if (!blank(m.issue_title)) h += '<p class="ip-title2">' + esc(m.issue_title) + '</p>';
    var cr = CREDITS.filter(function (c) { return !blank(m[c[0]]); });
    if (cr.length) h += '<dl class="ip-credits">' + cr.map(function (c) { return '<dt>' + c[1] + '</dt><dd>' + esc(m[c[0]]) + '</dd>'; }).join('') + '</dl>';
    if (!blank(m.summary)) h += '<p class="ip-summary">' + esc(m.summary) + '</p>';
    var foot = [];
    if (!blank(m.pagecount)) foot.push(esc(m.pagecount) + ' pages');
    foot.push(m.filename ? '<span class="ip-file">' + esc(m.filename) + '</span>' : 'No file yet');
    var src = [m.metadata_source, m.metadata_type].filter(function (v) { return !blank(v); });
    if (src.length) foot.push('From ' + esc(src.join(', ')));
    h += '<p class="ip-foot">' + foot.join(' · ') + '</p>';
    box.querySelector('#ip-info').innerHTML = h;
  }

  function open(table, tr) {
    if (!box) build();
    var dt = window.jQuery(table).DataTable();
    cur = { dt: dt, i: 0 };
    back = document.activeElement;
    box.hidden = false;
    show(Math.max(0, rows().indexOf(tr)));
    box.querySelector('#ip-close').focus();
  }

  function close() {
    if (!box || box.hidden) return;
    box.hidden = true;
    clearTimeout(timer);
    seq++;
    cur = null;
    if (back && back.focus && document.body.contains(back)) back.focus();
  }

  window.IssuarrIssue = { open: open, close: close };
})();
