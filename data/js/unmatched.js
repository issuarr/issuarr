/* Library > Unmatched: one folder's files that no issue points to. */
(function () {
  'use strict';

  var page = document.getElementById('um-page');
  var path = page.getAttribute('data-path');
  var st = { files: [] };
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
      '<td class="actions"><button type="button" class="btn btn-sm btn-ghost" data-ignore="' + n + '" title="Hide this file until it changes">Ignore</button></td></tr>';
  }

  function render(d) {
    st.files = d.files || [];
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
