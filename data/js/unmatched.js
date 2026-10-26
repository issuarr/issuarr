/* Library > Unmatched: one folder's files that no issue points to. */
(function () {
  'use strict';

  var page = document.getElementById('um-page');
  var path = page.getAttribute('data-path');
  var st = { files: [], data: null };
  var dlg = { mode: null, file: null, series: null, issueid: null, poll: null };
  var IMPORT = {
    'Manual Intervention': ['is-snatched', 'Needs a choice', 'importResults#needs-a-choice'],
    'Not Imported': ['is-wanted', 'Not imported', 'importResults#not-imported'],
    'No Results': ['is-ignored', 'No results', 'importResults#no-results'],
    'Imported': ['is-snatched', 'Imported, no issue', null],
    'No Issue': ['is-snatched', 'Imported, no issue', null]
  };

  function $(id) { return document.getElementById(id); }
  function I() { return window.Issuarr; }
  function esc(t) { return I().esc(t); }
  function mb(n) { return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; }
  function post(url, params) {
    return fetch(url, { method: 'POST', credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body: new URLSearchParams(params || {}).toString() })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }
  function seriesLink(s) {
    return '<a href="comicDetails?ComicID=' + encodeURIComponent(s.id) + '">' + esc(s.name) + (s.year ? ' (' + esc(s.year) + ')' : '') + '</a>';
  }

  function readsAs(r) {
    if (!r || !r.series) return '<span class="muted">Can\'t read the name</span>';
    return esc(r.series) + (r.issue ? ' #' + esc(r.issue) : '') + (r.year ? ' <span class="muted">(' + esc(r.year) + ')</span>' : '') +
      (r.collected ? ' <span class="status is-ignored">Collected edition</span>' : '');
  }

  function near(n) {
    if (!n) return '<span class="muted">None close</span>';
    return '<a href="comicDetails?ComicID=' + encodeURIComponent(n.comicid) + '">' + esc(n.name) + (n.year ? ' (' + esc(n.year) + ')' : '') + '</a>' +
      (n.number ? ' #' + esc(n.number) : ' <span class="muted">no issue fits</span>');
  }

  function imported(x) {
    if (!x) return '<span class="muted" title="No library scan has listed this file on Import results, or it was removed from there">Not listed</span>';
    var m = IMPORT[x.Status] || ['is-idle', x.Status, null];
    var pill = '<span class="status ' + m[0] + '">' + esc(m[1]) + '</span>';
    if (m[2]) return '<a href="' + m[2] + '">' + pill + '</a>';
    if (x.ComicID) return pill + ' <a href="comicDetails?ComicID=' + encodeURIComponent(x.ComicID) + '" class="muted">series</a>';
    return pill;
  }

  function row(f, n) {
    var cover = 'unmatched_cover?path=' + encodeURIComponent(f.path) + '&v=' + f.mtime;
    return '<tr data-n="' + n + '">' +
      '<td><span class="lib-name"><span class="thumb-wrap"><img loading="lazy" decoding="async" alt="" data-um-cover src="' + esc(cover) + '"></span>' +
      '<span class="um-file" title="' + esc(f.path) + '">' + esc(f.name) + '</span></span></td>' +
      '<td class="num mono nowrap">' + mb(f.size) + '</td>' +
      '<td>' + readsAs(f.reads_as) + '</td>' +
      '<td>' + near(f.near) + '</td>' +
      '<td class="nowrap">' + imported(f['import']) + '</td>' +
      '<td class="actions nowrap"><button type="button" class="btn btn-sm" data-match-file="' + n + '">Match to issue…</button> ' +
      '<button type="button" class="btn btn-sm btn-ghost" data-ignore="' + n + '" title="Hide this file until it changes">Ignore</button></td></tr>';
  }

  function render(d) {
    st.data = d;
    st.files = d.files || [];
    $('um-match-folder').hidden = !st.files.length;
    var name = d.rel || 'Library folder';
    $('um-title').textContent = name + ' [unmatched]';
    document.title = name + ' [unmatched] - Issuarr';
    var owner = $('um-owner');
    if (d.series && d.series.length) {
      owner.hidden = false;
      owner.innerHTML = (d.series_above ? 'This folder is inside the folder of ' : 'This is the folder of ') +
        d.series.map(seriesLink).join(' and ') + ', but no issue of ' + (d.series.length > 1 ? 'those series' : 'that series') + ' points to these files.';
    } else {
      owner.hidden = true;
    }
    var n = st.files.length;
    $('um-note').textContent = n ? n + (n === 1 ? ' file' : ' files') + '. Hover a name for its full path.' : (d.note || 'No unmatched files here.');
    $('um-wrap').hidden = !n;
    $('um-table').tBodies[0].innerHTML = st.files.map(row).join('');
  }

  function load() {
    fetch('unmatched_folder?path=' + encodeURIComponent(path), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(render)
      .catch(function () { $('um-note').textContent = 'Couldn\'t list this folder. Check the log.'; });
  }

  document.addEventListener('click', function (e) {
    var m = e.target.closest && e.target.closest('[data-match-file]');
    if (m) { openPick('file', st.files[+m.getAttribute('data-match-file')]); return; }
    var b = e.target.closest && e.target.closest('[data-ignore]');
    if (!b) return;
    var f = st.files[+b.getAttribute('data-ignore')];
    if (!f) return;
    b.disabled = true;
    post('unmatched_ignore', { path: f.path })
      .then(function (d) {
        if (!d.ok) throw new Error(d.note);
        I().toast('Ignoring ' + f.name + ' until it changes.');
        load();
      })
      .catch(function (err) { b.disabled = false; I().toast(err && err.message && isNaN(err.message) ? err.message : 'That didn\'t work. Check the log.', false); });
  });

  /* ---- matching: pick a series (watchlist or ComicVine), then an issue, then confirm what moves ---- */
  var body = function () { return $('um-dialog-body'); };
  function get(url) { return fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }
  function busy(on) { body().classList.toggle('is-busy', on); }
  function stopPoll() { clearTimeout(dlg.poll); dlg.poll = null; }
  function label(s) { return s.name + (s.year ? ' (' + s.year + ')' : '') + (s.volume && s.volume !== 'v1' ? ' ' + s.volume : ''); }

  function openPick(mode, file) {
    stopPoll();
    dlg.mode = mode; dlg.file = file; dlg.series = null; dlg.issueid = null;
    var d = $('um-dialog');
    $('um-dialog-title').textContent = mode === 'file' ? 'Match a file to an issue' : 'Match this folder to a series';
    $('um-dialog-intro').textContent = mode === 'file'
      ? file.name + ': pick its series, then the issue it is.'
      : 'Every unmatched file here (' + st.files.length + ') goes to the series you pick, each tied to the issue its name says. Files no issue fits stay listed for matching one by one.';
    var first = mode === 'file' ? file : st.files[0];
    var q = (first && first.reads_as && first.reads_as.series) || (st.data && st.data.rel || '').split('/').pop() || '';
    pickSeries(q, first && first.near);
    if (!d.open) d.showModal();
  }

  function seriesRows(list, cv) {
    if (!list.length) return '<p class="muted">' + (cv ? 'ComicVine found nothing for that.' : 'No series on your watchlist match.') + '</p>';
    return '<ul class="match-list">' + list.map(function (s, i) {
      var meta = [s.publisher, s.issues ? s.issues + ' issues' : '', s.alias ? 'also called ' + s.alias : ''].filter(Boolean).join(' · ');
      var btn = cv && !s.watched
        ? '<button type="button" class="btn btn-sm" data-um-add="' + i + '">Add and use</button>'
        : '<button type="button" class="btn btn-sm btn-primary" data-um-series="' + i + '"' + (cv ? ' data-cv' : '') + '>This one</button>';
      return '<li class="match-row"><div class="match-file"><span class="match-name">' + esc(label(s)) + '</span>' +
        (meta ? '<span class="match-meta">' + esc(meta) + '</span>' : '') + '</div>' + btn + '</li>';
    }).join('') + '</ul>';
  }

  function pickSeries(q, near) {
    dlg.list = []; dlg.cv = [];
    body().innerHTML = '<form class="match-do" data-um-find><input type="search" class="match-search" aria-label="Series name or ComicVine link" placeholder="Series name or ComicVine link" value="' + esc(q) + '" />' +
      '<button type="submit" class="btn btn-sm">Search watchlist</button><button type="button" class="btn btn-sm btn-ghost" data-um-cv>Search ComicVine</button></form>' +
      (near ? '<p class="match-h">Closest on your watchlist</p>' + seriesRows([{ comicid: near.comicid, name: near.name, year: near.year, volume: near.volume }], false).replace('data-um-series="0"', 'data-um-near') : '') +
      '<div id="um-results"></div>';
    dlg.near = near ? { comicid: near.comicid, name: near.name, year: near.year, volume: near.volume } : null;
    if (q) searchWatch(q);
  }

  function searchWatch(q) {
    busy(true);
    get('attention_search?q=' + encodeURIComponent(q))
      .then(function (d) { dlg.list = d.series || []; $('um-results').innerHTML = '<p class="match-h">On your watchlist</p>' + seriesRows(dlg.list, false); })
      .catch(function () { $('um-results').innerHTML = '<p class="match-none">The search didn\'t work. Check the log.</p>'; })
      .then(function () { busy(false); });
  }

  function searchCv(q) {
    busy(true);
    $('um-results').innerHTML = '<p class="match-wait">Asking ComicVine…</p>';
    get('attention_find?q=' + encodeURIComponent(q))
      .then(function (d) {
        dlg.cv = d.series || [];
        $('um-results').innerHTML = (d.ok === false ? '<p class="match-none">' + esc(d.note) + '</p>' : '') + '<p class="match-h">On ComicVine</p>' + seriesRows(dlg.cv, true);
      })
      .catch(function () { $('um-results').innerHTML = '<p class="match-none">The ComicVine search didn\'t work. Check the log.</p>'; })
      .then(function () { busy(false); });
  }

  function addSeries(s) {
    busy(true);
    post('attention_add_series', { comicid: s.comicid, name: s.name, year: s.year || '' })
      .then(function (d) {
        if (!d.ok) throw new Error(d.note);
        if (d.state === 'ready') { chosen(d.series || s); return; }
        $('um-results').innerHTML = '<p class="match-wait">' + esc(d.note) + '</p>';
        waitFor(s);
      })
      .catch(function (err) { busy(false); $('um-results').innerHTML = '<p class="match-none">' + esc(err && err.message && isNaN(err.message) ? err.message : 'Adding didn\'t work. Check the log.') + '</p>'; });
  }

  function waitFor(s) {
    dlg.poll = setTimeout(function () {
      get('attention_series_state?comicid=' + encodeURIComponent(s.comicid))
        .then(function (d) { if (d.state === 'ready') chosen(d.series); else waitFor(s); })
        .catch(function () { waitFor(s); });
    }, 3000);
  }

  function chosen(s) {
    stopPoll();
    busy(false);
    dlg.series = s;
    if (dlg.mode === 'folder') { confirmStep(); return; }
    busy(true);
    get('attention_issues?comicid=' + encodeURIComponent(s.comicid))
      .then(function (d) {
        var want = String((dlg.file.reads_as || {}).issue || '').replace(/^0+(?=\d)/, '');
        var issues = d.issues || [];
        body().innerHTML = '<p>Which issue of <b>' + esc(label(s)) + '</b> is ' + esc(dlg.file.name) + '?</p>' +
          '<div class="match-do"><select id="um-issue" aria-label="Issue">' + issues.map(function (i) {
            var n = String(i.Issue_Number || '').replace(/^0+(?=\d)/, '');
            return '<option value="' + esc(i.IssueID) + '"' + (n === want ? ' selected' : '') + '>#' + esc(i.Issue_Number) +
              (i.IssueDate ? ' · ' + esc(i.IssueDate) : '') + ' · ' + esc(i.Status || '') + '</option>';
          }).join('') + '</select><button type="button" class="btn btn-sm btn-primary" data-um-issue' + (issues.length ? '' : ' disabled') + '>Next</button>' +
          '<button type="button" class="btn btn-sm btn-ghost" data-um-back>Another series</button></div>' +
          (issues.length ? '' : '<p class="match-none">This series has no issues listed yet.</p>');
      })
      .catch(function () { body().innerHTML = '<p class="match-none">Couldn\'t load the issues. Check the log.</p>'; })
      .then(function () { busy(false); });
  }

  function confirmStep() {
    var s = dlg.series;
    var q = 'unmatched_plan?comicid=' + encodeURIComponent(s.comicid) +
      (dlg.mode === 'file' ? '&path=' + encodeURIComponent(dlg.file.path) : '&folder=' + encodeURIComponent(st.data.folder));
    busy(true);
    get(q)
      .then(function (p) {
        if (!p.ok) { body().innerHTML = '<p class="match-none">' + esc(p.note) + '</p><div class="match-do"><button type="button" class="btn btn-sm" data-um-back>Another series</button></div>'; return; }
        var lines = [];
        if (p.move.length) lines.push('<b>' + p.move.length + (p.move.length === 1 ? ' file moves' : ' files move') + '</b> into ' + esc(p.dest) + ', keeping ' + (p.move.length === 1 ? 'its name' : 'their names') + '.');
        if (p.stay.length) lines.push(p.stay.length + (p.stay.length === 1 ? ' file is' : ' files are') + ' already in the series\' folder and ' + (p.stay.length === 1 ? 'stays' : 'stay') + ' put.');
        p.blocked.forEach(function (b) { lines.push('<span class="match-none">' + esc(b.path.split(/[\\/]/).pop()) + ': ' + esc(b.note) + '</span>'); });
        var can = p.move.length + p.stay.length > 0 && !(dlg.mode === 'file' && p.blocked.length);
        var what = dlg.mode === 'file' ? 'Match' : 'Match folder';
        body().innerHTML = '<p>' + esc(dlg.mode === 'file' ? dlg.file.name + ' becomes the issue you picked of ' + label(s) + '.' : 'These files go to ' + label(s) + '.') + '</p>' +
          '<ul>' + lines.map(function (l) { return '<li>' + l + '</li>'; }).join('') + '</ul>' +
          '<div class="match-do"><button type="button" class="btn btn-sm btn-primary" data-um-go' + (can ? '' : ' disabled') + '>' +
          (p.move.length ? 'Move ' + p.move.length + ' and ' + what.toLowerCase() : what) + '</button>' +
          '<button type="button" class="btn btn-sm btn-ghost" data-um-back>Another series</button></div>';
      })
      .catch(function () { body().innerHTML = '<p class="match-none">Couldn\'t work out what would move. Check the log.</p>'; })
      .then(function () { busy(false); });
  }

  function go(btn) {
    btn.disabled = true;
    busy(true);
    var s = dlg.series;
    var req = dlg.mode === 'file'
      ? post('unmatched_match_file', { path: dlg.file.path, comicid: s.comicid, issueid: dlg.issueid })
      : post('unmatched_match_folder', { folder: st.data.folder, comicid: s.comicid });
    req.then(function (d) {
      if (!d.ok) throw new Error(d.note);
      $('um-dialog').close();
      I().toast(d.note);
      load();
    }).catch(function (err) {
      btn.disabled = false;
      I().toast(err && err.message && isNaN(err.message) ? err.message : 'That didn\'t work. Check the log.', false);
    }).then(function () { busy(false); });
  }

  $('um-dialog').addEventListener('close', stopPoll);
  $('um-dialog').addEventListener('submit', function (e) {
    if (!e.target.matches('[data-um-find]')) return;
    e.preventDefault();
    searchWatch(e.target.querySelector('input').value.trim());
  });
  $('um-dialog').addEventListener('click', function (e) {
    var t = e.target;
    if (t.closest('[data-um-close]')) { $('um-dialog').close(); return; }
    if (t.closest('[data-um-cv]')) { searchCv(body().querySelector('.match-search').value.trim()); return; }
    if (t.closest('[data-um-near]')) { chosen(dlg.near); return; }
    var pick = t.closest('[data-um-series]');
    if (pick) { var list = pick.hasAttribute('data-cv') ? dlg.cv : dlg.list; chosen(list[+pick.getAttribute('data-um-series')]); return; }
    var add = t.closest('[data-um-add]');
    if (add) { addSeries(dlg.cv[+add.getAttribute('data-um-add')]); return; }
    if (t.closest('[data-um-issue]')) { dlg.issueid = $('um-issue').value; confirmStep(); return; }
    if (t.closest('[data-um-back]')) { openPick(dlg.mode, dlg.file); return; }
    var g = t.closest('[data-um-go]');
    if (g) go(g);
  });
  $('um-match-folder').addEventListener('click', function () { openPick('folder', null); });

  // A cover can fail because the server was busy making others: ask again after 3, 6 and 12 seconds.
  document.addEventListener('error', function (e) {
    var im = e.target;
    if (!im.matches || !im.matches('[data-um-cover]')) return;
    var tries = +(im.getAttribute('data-tries') || 0);
    if (tries < 3) {
      if (!im.getAttribute('data-src')) im.setAttribute('data-src', im.getAttribute('src'));
      im.setAttribute('data-tries', tries + 1);
      setTimeout(function () { if (im.isConnected) im.src = im.getAttribute('data-src') + '&r=' + (tries + 1); }, 3000 * Math.pow(2, tries));
      return;
    }
    im.remove();
  }, true);

  load();
})();
