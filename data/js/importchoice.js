/* Import results > Needs a choice: the Choose match window. Like Needs attention, it puts the
   scanned files' cover next to each ComicVine series the import found, with its year, publisher,
   issue count and description, and searches ComicVine for another one. Picking a series imports it
   and moves on to the next series that needs a choice. */
(function () {
  'use strict';
  var dlg, body, pos, cur = null, busy = false;

  function esc(t) { return window.Issuarr.esc(t == null ? '' : String(t)); }
  function q(p) {
    var o = {};
    Object.keys(p).forEach(function (k) { if (p[k] != null) o[k] = p[k]; });
    return new URLSearchParams(o).toString();
  }
  function failed() { window.Issuarr.toast('That didn\'t work. Check the log.', false); }
  function json(r) { if (!r.ok) throw new Error(r.status); return r.json(); }
  function num(n) { return n == null ? '' : String(n).replace(/\.0+$/, ''); }

  // the rows still waiting for a choice, in table order
  function waiting() {
    return Array.prototype.slice.call(document.querySelectorAll('#imp-table tbody tr [data-choose]:not([disabled])'));
  }

  function cover(src, alt, caption) {
    return '<figure class="match-cover"><button type="button" class="match-cover-btn" data-zoom aria-label="Show the cover larger">' +
      (src ? '<img src="' + esc(src) + '" alt="' + esc(alt) + '" loading="lazy" data-choose-img />' : '<span class="match-nocover">No cover</span>') +
      '</button>' + (caption ? '<figcaption>' + caption + '</figcaption>' : '') + '</figure>';
  }

  function fileCover(f) {
    return cover(f ? 'import_cover?' + q({ impid: f.id }) : null, f ? 'Front cover of ' + f.name : '', f ? 'This file' + (f.number ? ', #' + esc(num(f.number)) : '') : '');
  }

  // the folder names can hold a year or the publisher
  function folders(s) {
    var dirs = s.folders || [];
    if (!dirs.length) return '';
    var shown = dirs.slice(0, 3).map(function (d) { return '<span class="mono">' + esc(d) + '</span>'; }).join('<br>');
    return '<p class="match-meta choose-folder">' + (dirs.length === 1 ? 'Folder: ' : 'Folders:<br>') + shown +
      (dirs.length > 3 ? '<br>and ' + (dirs.length - 3) + ' more' : '') + '</p>' +
      (s.publisher_folder ? '<p class="match-meta">In a ' + esc(s.publisher_folder) + ' folder, so that publisher\'s series are listed first.</p>' : '');
  }

  // ComicVine shows a series by its first issue's cover, so the file shown first is #1 (or the
  // lowest whole number after it), not a #0 or #½ that sorts ahead of it
  function firstShown(s) {
    var best = -1;
    s.files.forEach(function (f, i) {
      if (f.missing) return;
      if (best < 0 && /^\d+(\.0+)?$/.test(String(f.number || '').trim()) && parseFloat(f.number) >= 1) best = i;
    });
    if (best < 0) best = s.files.findIndex(function (f) { return !f.missing; });
    return best;
  }

  function files(s) {
    var n = s.files.length, shown = firstShown(s);
    var nums = s.files.map(function (f) { return f.number; }).filter(function (x) { return x != null && x !== ''; });
    var range = nums.length ? ' · #' + esc(num(nums[0])) + (nums.length > 1 ? '–#' + esc(num(nums[nums.length - 1])) : '') : '';
    return '<div class="choose-files">' +
      '<div class="match-covers" data-file-cover>' + fileCover(s.files[shown]) + '</div>' +
      '<div class="match-file">' +
        '<p class="choose-name">' + esc(s.name) + (s.year ? ' <span class="muted">(' + esc(s.year) + ')</span>' : '') +
          (s.volume ? ' <span class="muted mono">' + esc(s.volume) + '</span>' : '') + '</p>' +
        folders(s) +
        '<p class="match-meta">' + n + (n === 1 ? ' file' : ' files') + range + '. Click a file to see its cover.</p>' +
        '<ul class="choose-filelist">' + s.files.map(function (f, i) {
          if (f.missing) return '<li class="mono faint" title="Not on disk any more">' + esc(f.name) + ' (missing)</li>';
          return '<li><button type="button" class="link-btn mono' + (i === shown ? ' is-current' : '') + '" data-file="' + i + '" title="' + esc(f.path) + '">' + esc(f.name) + '</button></li>';
        }).join('') + '</ul>' +
      '</div></div>';
  }

  function candidate(c, top) {
    var meta = [c.year, c.publisher].filter(Boolean).map(esc);
    if (c.issues != null) meta.push(c.issues + (c.issues === 1 ? ' issue' : ' issues'));
    var warn = c.fits === false ? '<p class="match-meta choose-warn">Has ' + c.issues + (c.issues === 1 ? ' issue' : ' issues') + ', but your files go up to #' + esc(num(top)) + '.</p>' : '';
    return '<li class="match-row choose-row" data-cand="' + esc(c.comicid) + '">' +
      '<div class="match-covers">' + cover(c.thumb, 'Cover of ' + c.name, '') + '</div>' +
      '<div class="match-file">' +
        '<p class="choose-name">' + (c.url ? '<a href="' + esc(c.url) + '" target="_blank" rel="noopener" title="Open on ComicVine">' + esc(c.name) + '</a>' : esc(c.name)) +
          ' <span class="muted mono">4050-' + esc(c.comicid) + '</span>' +
          (c.watched ? ' <span class="match-hand">On your watchlist</span>' : '') +
          (c.samepub ? ' <span class="match-hand">Matches the folder</span>' : '') +
          (c.type && c.type !== 'Print' ? ' <span class="match-hand">' + esc(c.type) + '</span>' : '') +
          ' <span data-cover-badge></span></p>' +
        '<p class="match-meta">' + meta.join(' · ') + '</p>' + warn +
        (c.about ? '<p class="choose-about">' + esc(c.about) + '</p>' : '') +
        '<div class="match-do"><button type="button" class="btn btn-sm btn-primary" data-pick="' + esc(c.comicid) + '" data-name="' + esc(c.name) + '">Use this series</button></div>' +
      '</div></li>';
  }

  function list(cands, top, total, none) {
    if (!cands.length) return '<p class="match-meta">' + none + '</p>';
    return (total > cands.length ? '<p class="match-meta">The ' + cands.length + ' closest of ' + total + '. Search for the one you want if it isn\'t here.</p>' : '') +
      '<ul class="match-list">' + cands.map(function (c) { return candidate(c, top); }).join('') + '</ul>';
  }

  function draw(d) {
    var s = d.series;
    body.innerHTML = files(s) +
      '<form class="match-do choose-search" data-choose-find>' +
        '<input type="search" class="match-search" aria-label="Series name or ComicVine link" placeholder="Search ComicVine: series name or link" value="' + esc(s.comicname) + '" />' +
        '<button type="submit" class="btn btn-sm">Search ComicVine</button></form>' +
      '<div data-choose-found></div>' +
      '<h3 class="match-h">Found by the import</h3>' +
      '<p class="match-meta" data-cover-note></p>' +
      list(d.candidates, s.top, d.total, 'The import saved no possible series for this one. Search ComicVine above.');
  }

  function open(btn) {
    cur = btn;
    var rows = waiting();
    var at = rows.indexOf(btn);
    pos.textContent = at >= 0 ? (at + 1) + ' of ' + rows.length : '';
    body.innerHTML = '<p class="match-meta">Loading…</p>';
    if (!dlg.open) dlg.showModal();
    fetch('import_choice?' + btn.getAttribute('data-choose'), { credentials: 'same-origin', cache: 'no-store' })
      .then(json)
      .then(function (d) {
        if (cur !== btn) return;
        if (d.gone) { gone(btn, d.note); return; }
        if (!d.ok) { body.innerHTML = '<p class="match-meta">' + esc(d.note) + '</p>'; return; }
        cur.data = d;
        draw(d);
        coverMatch(btn, d.series);
      })
      .catch(function () { body.innerHTML = '<p class="match-meta">Couldn\'t load this series. Check the log.</p>'; });
  }

  // The shown file's cover against that issue of each series found: one ComicVine call, so it
  // fills in after the window opens. A single clear match moves to the top.
  var COVER = { match: 'Cover matches', unsure: 'Cover is close', mismatch: 'Cover differs' };
  function coverMatch(btn, s) {
    var p = { DynamicName: s.dynamicname };
    if (s.volume) p.Volume = s.volume;
    var note = body.querySelector('[data-cover-note]');
    if (note) note.textContent = 'Comparing covers with ComicVine…';
    fetch('import_cover_match?' + q(p), { credentials: 'same-origin', cache: 'no-store' })
      .then(json)
      .then(function (r) {
        if (cur !== btn) return;
        if (!r.ok) { if (note) note.textContent = ''; return; }
        var at = s.files.findIndex(function (f) { return f.id === r.file; });
        if (at >= 0) {
          body.querySelector('[data-file-cover]').innerHTML = fileCover(s.files[at]);
          body.querySelectorAll('[data-file]').forEach(function (b) { b.classList.toggle('is-current', +b.getAttribute('data-file') === at); });
        }
        Object.keys(r.covers).forEach(function (cid) {
          var c = r.covers[cid], li = body.querySelector('[data-cand="' + cid + '"]');
          var badge = li && li.querySelector('[data-cover-badge]');
          if (!badge) return;
          badge.innerHTML = c.distance == null ? '<span class="match-hand faint">No #' + esc(num(r.number)) + ' cover to compare</span>' :
            '<span class="match-hand cover-' + c.verdict + '" title="' + c.distance + ' apart; 0 is the same picture">' + COVER[c.verdict] + ' #' + esc(num(r.number)) + '</span>';
        });
        var win = r.winner && body.querySelector('[data-cand="' + r.winner + '"]');
        if (win) win.parentNode.insertBefore(win, win.parentNode.firstChild);
        if (note) note.textContent = win ? 'Its cover picks one series, now at the top.' : '';
      })
      .catch(function () { if (note && cur === btn) note.textContent = ''; });
  }

  // its files were deleted or moved since the scan: the server forgot it, so move on
  function gone(btn, note) {
    var at = waiting().indexOf(btn);
    btn.disabled = true;
    var tr = btn.closest('tr');
    var label = tr && tr.querySelector('.status');
    if (label) { label.className = 'status is-ignored'; label.textContent = 'Files gone (removed)'; }
    window.Issuarr.toast(note);
    var rows = waiting();
    if (rows[at]) open(rows[at]); else { dlg.close(); window.Issuarr.toast('No more series need a choice.'); }
  }

  function next() {
    var rows = waiting();
    var at = rows.indexOf(cur);
    var nxt = rows[at + 1] || (at < 0 ? rows[0] : null);
    if (nxt) open(nxt); else { dlg.close(); window.Issuarr.toast('No more series need a choice.'); }
  }

  function find(text) {
    var out = body.querySelector('[data-choose-found]');
    out.innerHTML = '<p class="match-meta">Searching ComicVine…</p>';
    fetch('attention_find?' + q({ q: text }), { credentials: 'same-origin' })
      .then(json)
      .then(function (d) {
        var top = cur.data ? cur.data.series.top : null;
        var cands = (d.series || []).map(function (x) {
          var issues = x.issues == null ? null : parseInt(x.issues, 10);
          return { comicid: x.comicid, name: x.name, year: x.year, publisher: x.publisher, issues: isNaN(issues) ? null : issues,
                   thumb: x.thumb, type: x.type, watched: x.watched, url: 'https://comicvine.gamespot.com/volume/4050-' + x.comicid + '/',
                   fits: issues == null || isNaN(issues) || top == null || top <= issues };
        });
        out.innerHTML = (d.ok === false ? '<p class="match-meta">' + esc(d.note) + '</p>' : '') +
          '<h3 class="match-h">ComicVine search</h3>' + list(cands, top, cands.length, 'ComicVine found nothing for that.');
      })
      .catch(function () { out.innerHTML = '<p class="match-meta">Couldn\'t search ComicVine. Check the log.</p>'; });
  }

  function pick(btn) {
    if (busy || !cur || !cur.data) return;
    busy = true;
    var s = cur.data.series;
    var row = cur;
    btn.disabled = true;
    var p = new URLSearchParams({ cvid: '4050-' + btn.getAttribute('data-pick'), ComicName: s.comicname, DynamicName: s.dynamicname });
    if (s.volume) p.set('Volume', s.volume);
    fetch('importByCvid', { method: 'POST', credentials: 'same-origin', body: p })
      .then(json)
      .then(function (d) {
        busy = false;
        if (!d.ok) { btn.disabled = false; window.Issuarr.toast(d.note, false); return; }
        window.Issuarr.toast(d.queued ? s.name + ': ' + d.note
          : d.joined ? 'Importing ' + s.name + ' as ' + btn.getAttribute('data-name') + ' next. The import that\'s running picks it up.'
          : 'Importing ' + s.name + ' as ' + btn.getAttribute('data-name') + '. Follow it in Tasks › Jobs.');
        // it's no longer waiting for a choice
        var at = waiting().indexOf(row);
        row.disabled = true;
        var rows = waiting();
        if (rows[at]) open(rows[at]); else { dlg.close(); window.Issuarr.toast('No more series need a choice.'); }
        var tr = row.closest('tr');
        var label = tr.querySelector('.status');
        if (label) { label.className = 'status is-idle'; label.textContent = d.queued ? 'Not imported (chosen)' : d.joined ? 'Importing next' : 'Importing'; }
      })
      .catch(function () { busy = false; btn.disabled = false; failed(); });
  }

  function init() {
    dlg = document.getElementById('choose-dialog');
    if (!dlg) return;
    body = document.getElementById('choose-body');
    pos = document.getElementById('choose-pos');

    document.addEventListener('click', function (e) {
      var t = e.target;
      var choose = t.closest('#imp-table [data-choose]');
      if (choose) { e.preventDefault(); open(choose); return; }
      if (!dlg.contains(t)) return;
      if (t.closest('[data-choose-close]')) { dlg.close(); return; }
      if (t.closest('[data-choose-skip]')) { next(); return; }
      var f = t.closest('[data-file]');
      if (f && cur && cur.data) {
        body.querySelector('[data-file-cover]').innerHTML = fileCover(cur.data.series.files[+f.getAttribute('data-file')]);
        body.querySelectorAll('[data-file]').forEach(function (b) { b.classList.toggle('is-current', b === f); });
        return;
      }
      var z = t.closest('[data-zoom]');
      if (z) { z.closest('.match-covers').classList.toggle('is-large'); return; }
      var p = t.closest('[data-pick]');
      if (p) pick(p);
    });
    dlg.addEventListener('submit', function (e) {
      if (!e.target.matches('[data-choose-find]')) return;
      e.preventDefault();
      find(e.target.querySelector('.match-search').value);
    });

    // A file cover can fail because the server was busy making others: ask again after 3, 6 and 12 seconds.
    dlg.addEventListener('error', function (e) {
      var im = e.target;
      if (!im.matches || !im.matches('[data-choose-img]')) return;
      var tries = +(im.getAttribute('data-tries') || 0);
      var src = im.getAttribute('data-src') || im.getAttribute('src');
      im.style.visibility = 'hidden';   // not its alt text while it retries
      if (tries < 3 && src.indexOf('import_cover?') === 0) {
        im.setAttribute('data-src', src);
        im.setAttribute('data-tries', tries + 1);
        setTimeout(function () { if (im.isConnected) im.src = src + '&r=' + (tries + 1); }, 3000 * Math.pow(2, tries));
        return;
      }
      im.parentNode.innerHTML = '<span class="match-nocover">No cover</span>';
    }, true);
    dlg.addEventListener('load', function (e) {
      if (e.target.matches && e.target.matches('[data-choose-img]')) e.target.style.visibility = '';
    }, true);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
