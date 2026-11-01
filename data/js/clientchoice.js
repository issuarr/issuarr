/* Downloads > Choose match: pick the series a download you added to a client is, from your
   watchlist or ComicVine (a pasted ComicVine link works too). It's filed as that series' issues
   when it finishes, and the issue it names is marked Snatched so search doesn't grab it again. */
(function () {
  'use strict';
  var dlg, body, src, cur = null, busy = false;

  function I() { return window.Issuarr; }
  function esc(t) { return I().esc(t == null ? '' : String(t)); }
  function json(r) { if (!r.ok) throw new Error(r.status); return r.json(); }
  function q(p) {
    var o = {};
    Object.keys(p).forEach(function (k) { if (p[k] != null && p[k] !== '') o[k] = p[k]; });
    return new URLSearchParams(o).toString();
  }

  function row(c, where) {
    var meta = [c.year, c.publisher].filter(Boolean).map(esc);
    if (c.issues != null) meta.push(c.issues + (c.issues === 1 ? ' issue' : ' issues'));
    if (c.issue) meta.push('has #' + esc(c.issue));
    return '<li class="match-row choose-row">' +
      (where === 'cv' ? '<div class="match-covers"><figure class="match-cover">' +
        (c.thumb ? '<img src="' + esc(c.thumb) + '" alt="Cover of ' + esc(c.name) + '" loading="lazy" />' : '<span class="match-nocover">No cover</span>') +
        '</figure></div>' : '') +
      '<div class="match-file">' +
        '<p class="choose-name">' + (where === 'cv' ? '<a href="https://comicvine.gamespot.com/volume/4050-' + esc(c.comicid) + '/" target="_blank" rel="noopener" title="Open on ComicVine">' + esc(c.name) + '</a>' : esc(c.name)) +
          ' <span class="muted mono">4050-' + esc(c.comicid) + '</span>' +
          (c.watched ? ' <span class="match-hand">On your watchlist</span>' : '') + '</p>' +
        '<p class="match-meta">' + meta.join(' · ') + '</p>' +
        '<div class="match-do"><button type="button" class="btn btn-sm btn-primary" data-cc-pick="' + esc(c.comicid) + '" data-name="' + esc(c.name) +
          '" data-year="' + esc(c.year || '') + '">Use this series</button></div>' +
      '</div></li>';
  }

  function draw(d) {
    var dl = d.download;
    var said = [dl.series, dl.issue ? '#' + dl.issue : '', dl.year ? '(' + dl.year + ')' : ''].filter(Boolean).join(' ');
    var files = dl.files.length ? '<ul class="choose-filelist">' + dl.files.map(function (f) { return '<li class="mono">' + esc(f) + '</li>'; }).join('') +
      (dl.more ? '<li class="faint">and ' + dl.more + ' more</li>' : '') + '</ul>' :
      '<p class="match-meta">' + (dl.state === 'Finished' ? 'Issuarr can\'t see its comic files.' : 'Its files are listed once it finishes.') + '</p>';
    body.innerHTML =
      '<div class="match-file">' +
        '<p class="choose-name mono">' + esc(dl.name) + '</p>' +
        '<p class="match-meta">' + esc(dl.state) + (said ? ' · the name reads as ' + esc(said) : '') + '</p>' +
        (d.chosen ? '<p class="match-meta">Chosen now: <b>' + esc(d.chosen.name) + '</b></p>' : '') +
        files +
        '<p class="match-meta">Each file is filed as the issue of the series you pick that its number names.</p>' +
      '</div>' +
      '<form class="match-do choose-search" data-cc-find>' +
        '<input type="search" class="match-search" aria-label="Series name or ComicVine link" placeholder="Search ComicVine: series name or link" value="' + esc(dl.series || '') + '" />' +
        '<button type="submit" class="btn btn-sm">Search ComicVine</button></form>' +
      '<div data-cc-found></div>' +
      '<h3 class="match-h">On your watchlist</h3>' +
      (d.candidates.length ? '<ul class="match-list">' + d.candidates.map(function (c) { return row(c, 'watch'); }).join('') + '</ul>'
        : '<p class="match-meta">No series on your watchlist is close to this name. Search ComicVine above.</p>');
  }

  function open(btn) {
    cur = { client: btn.getAttribute('data-client-choose'), id: btn.getAttribute('data-jobid') };
    body.innerHTML = '<p class="match-meta">Loading…</p>';
    src.textContent = '';
    if (!dlg.open) dlg.showModal();
    var me = cur;
    fetch('client_choice?' + q({ client: cur.client, id: cur.id }), { credentials: 'same-origin', cache: 'no-store' })
      .then(json)
      .then(function (d) {
        if (cur !== me) return;
        if (!d.ok) { body.innerHTML = '<p class="match-meta">' + esc(d.note) + '</p>'; return; }
        src.textContent = d.download.source;
        draw(d);
      })
      .catch(function () { body.innerHTML = '<p class="match-meta">Couldn\'t load this download. Check the log.</p>'; });
  }

  function find(text) {
    var out = body.querySelector('[data-cc-found]');
    out.innerHTML = '<p class="match-meta">Searching ComicVine…</p>';
    fetch('attention_find?' + q({ q: text }), { credentials: 'same-origin' })
      .then(json)
      .then(function (d) {
        var cands = (d.series || []).map(function (x) {
          var n = x.issues == null ? null : parseInt(x.issues, 10);
          return { comicid: x.comicid, name: x.name, year: x.year, publisher: x.publisher, issues: isNaN(n) ? null : n, thumb: x.thumb, watched: x.watched };
        });
        out.innerHTML = (d.ok === false ? '<p class="match-meta">' + esc(d.note) + '</p>' : '') + '<h3 class="match-h">ComicVine search</h3>' +
          (cands.length ? '<ul class="match-list">' + cands.map(function (c) { return row(c, 'cv'); }).join('') + '</ul>' : '<p class="match-meta">ComicVine found nothing for that.</p>');
      })
      .catch(function () { out.innerHTML = '<p class="match-meta">Couldn\'t search ComicVine. Check the log.</p>'; });
  }

  function pick(btn) {
    if (busy || !cur) return;
    busy = true;
    btn.disabled = true;
    var p = new URLSearchParams({ client: cur.client, id: cur.id, comicid: btn.getAttribute('data-cc-pick'), name: btn.getAttribute('data-name') });
    if (btn.getAttribute('data-year')) p.set('year', btn.getAttribute('data-year'));
    fetch('client_choose', { method: 'POST', credentials: 'same-origin', body: p })
      .then(json)
      .then(function (d) {
        busy = false;
        if (!d.ok) { btn.disabled = false; I().toast(d.note, false); return; }
        I().toast(d.note);
        dlg.close();
        // a finished download is filed now rather than on the next check
        fetch('checkDownloadClients', { method: 'POST', credentials: 'same-origin', body: new URLSearchParams() })
          .catch(function () {})
          .then(function () { document.dispatchEvent(new CustomEvent('issuarr:queue-reload')); });
      })
      .catch(function () { busy = false; btn.disabled = false; I().toast('That didn\'t work. Check the log.', false); });
  }

  function init() {
    dlg = document.getElementById('client-choose');
    if (!dlg) return;
    body = document.getElementById('client-choose-body');
    src = document.getElementById('client-choose-src');
    document.addEventListener('click', function (e) {
      var t = e.target;
      var b = t.closest('[data-client-choose]');
      if (b) { e.preventDefault(); open(b); return; }
      if (!dlg.contains(t)) return;
      if (t.closest('[data-cc-close]')) { dlg.close(); return; }
      var p = t.closest('[data-cc-pick]');
      if (p) pick(p);
    });
    dlg.addEventListener('submit', function (e) {
      if (!e.target.matches('[data-cc-find]')) return;
      e.preventDefault();
      find(e.target.querySelector('.match-search').value);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();

  /* Remove: take a download out of its client, and for Issuarr's own grabs block the release or skip the issue. */
  function initRemove() {
    var rd = document.getElementById('client-remove');
    if (!rd) return;
    var target = null;
    var TORRENT = ['qbittorrent', 'deluge', 'transmission', 'rtorrent', 'utorrent'];
    document.addEventListener('click', function (e) {
      var b = e.target.closest('[data-client-remove]');
      if (b) {
        e.preventDefault();
        target = { client: b.getAttribute('data-client-remove'), id: b.getAttribute('data-jobid'), own: !!b.getAttribute('data-own') };
        document.getElementById('client-remove-name').textContent = b.getAttribute('data-name') + ' in ' + b.getAttribute('data-source');
        rd.querySelectorAll('[data-own-only]').forEach(function (el) { el.hidden = !target.own; });
        rd.querySelectorAll('[data-torrent-only]').forEach(function (el) { el.hidden = TORRENT.indexOf(target.client) < 0 || target.client === 'transmission'; });
        ['cr-block', 'cr-skip', 'cr-relabel'].forEach(function (id) { var x = document.getElementById(id); if (x) x.checked = false; });
        document.getElementById('cr-files').checked = true;
        rd.showModal();
        return;
      }
      if (rd.contains(e.target) && e.target.closest('[data-cr-close]')) rd.close();
    });
    document.getElementById('cr-go').addEventListener('click', function () {
      if (!target) return;
      var btn = this;
      var relabel = document.getElementById('cr-relabel');
      var p = new URLSearchParams({ client: target.client, id: target.id, files: document.getElementById('cr-files').checked ? '1' : '0',
        blocklist: target.own && document.getElementById('cr-block').checked ? '1' : '0', skip: target.own && document.getElementById('cr-skip').checked ? '1' : '0',
        relabel: relabel && !relabel.closest('[hidden]') && relabel.checked ? '1' : '0' });
      btn.disabled = true;
      fetch('client_remove', { method: 'POST', credentials: 'same-origin', body: p })
        .then(json)
        .then(function (d) {
          btn.disabled = false;
          I().toast(d.note, d.ok);
          if (d.ok) { rd.close(); document.dispatchEvent(new CustomEvent('issuarr:queue-reload')); }
        })
        .catch(function () { btn.disabled = false; I().toast('That didn\'t work. Check the log.', false); });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initRemove); else initRemove();
})();
