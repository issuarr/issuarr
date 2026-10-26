/* Series page: Match files (every file in the series folder) and Match a file (one issue), and
   a notice when files in the folder look like they belong to another series.
   Each file shows its own cover next to the ComicVine cover of the issue it would be, so the two
   can be compared. A match made here holds through rechecks until it is undone or the file goes.
   Files waiting in Needs attention that look like this series are listed too; matching one files it. */
(function () {
  'use strict';

  var dlg, title, intro, body, state = {}, data = null;

  function esc(t) { return window.Issuarr.esc(t == null ? '' : String(t)); }
  function q(p) { return new URLSearchParams(p).toString(); }
  function num(n) { var s = String(n == null ? '' : n).trim().replace(/^0+(?=\d)/, ''); return s.toLowerCase(); }
  function mb(n) { return n == null ? '' : (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + ' MB'; }

  function post(url, params) {
    return fetch(url, { method: 'POST', credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: q(params) })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function reloadTable() {
    if (window.jQuery && jQuery.fn.dataTable && jQuery.fn.dataTable.isDataTable('#issue_table')) {
      jQuery('#issue_table').DataTable().ajax.reload(null, false);
    }
  }

  function busy(on) {
    body.classList.toggle('is-busy', on);
    dlg.querySelectorAll('.match-body button, .match-body select').forEach(function (b) { b.disabled = on || b.hasAttribute('data-off'); });
  }

  function run(url, params, label) {
    busy(true);
    intro.textContent = label;
    return post(url, params).then(function (d) {
      window.Issuarr.toast(d.note || (d.ok ? 'Done.' : 'That didn\'t work.'), !!d.ok);
      reloadTable();
      load();
    }).catch(function () {
      window.Issuarr.toast('That didn\'t work. Check the log.', false);
      busy(false);
    });
  }

  /* covers: the file's own front cover, and ComicVine's cover of an issue */
  function img(src, alt) {
    return '<img src="' + src + '" alt="' + esc(alt) + '" loading="lazy" data-cover-img />';
  }
  function fileCover(f) {
    var src = f.path ? 'attention_cover?' + q({ path: f.path, v: f.modified })
                     : 'match_cover?' + q({ comicid: state.comicid, name: f.name });
    return '<figure class="match-cover"><button type="button" class="match-cover-btn" data-zoom aria-label="Show the covers larger">' +
      img(src, 'Front cover of ' + f.name) + '</button><figcaption>This file</figcaption></figure>';
  }
  function issueCover(issue, caption) {
    var inner = issue && issue.cover ? img('attention_issue_cover?' + q({ issueid: issue.issueid }), 'Cover of #' + issue.number)
                                     : '<span class="match-nocover">' + (issue ? 'No cover' : 'Pick an issue') + '</span>';
    return '<figure class="match-cover" data-issue-cover><button type="button" class="match-cover-btn" data-zoom aria-label="Show the covers larger">' +
      inner + '</button><figcaption>' + esc(caption || (issue ? '#' + issue.number : '')) + '</figcaption></figure>';
  }

  function issueById(id) {
    return (data.issues || []).filter(function (i) { return String(i.issueid) === String(id); })[0] || null;
  }
  function fileName(f) {
    return (f.sub ? '<span class="faint">' + esc(f.sub) + '/</span>' : '') + esc(f.name);
  }
  function nowText(f) {
    if (f.path) return '<span class="match-wait">In Needs attention</span>' + (f.number ? ' · looks like #' + esc(f.number) : '');
    if (!f.issueid) return '<span class="match-none">Not matched</span>';
    return 'Now #' + esc(f.number) + (f.pinned ? ' <span class="match-hand">matched by hand</span>' : '');
  }
  function meta(f) {
    return nowText(f) + (f.reads_as ? ' · name reads as #' + esc(f.reads_as) : '') + ' · ' + mb(f.size);
  }
  function searchText(f) {
    var i = issueById(f.issueid);
    return [f.name, f.sub, f.number, f.reads_as, i && i.name].join(' ').toLowerCase();
  }

  function searchBox(placeholder) {
    return '<input type="search" class="match-search" placeholder="' + esc(placeholder) + '" aria-label="' + esc(placeholder) + '" value="' + esc(state.q || '') + '" />' +
      '<p class="match-meta" data-link-note aria-live="polite" hidden></p>';
  }

  /* A ComicVine issue link pasted into the search opens that issue's Match a file. */
  var CV_LINK = /comicvine(\.gamespot)?\.com\/\S*\b(4050|4000)-\d+|^\s*(4050|4000)-\d+\s*$/i;
  var linkTimer = null;

  function linkNote(text) {
    var p = body.querySelector('[data-link-note]');
    if (!p) return;
    p.hidden = !text;
    p.textContent = text || '';
  }

  function followLink(text) {
    clearTimeout(linkTimer);
    if (!CV_LINK.test(text)) { linkNote(''); return false; }
    linkTimer = setTimeout(function () {
      linkNote('Looking up that ComicVine link…');
      fetch('cv_link?' + q({ q: text }), { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          if ((state.q || '') !== text) return;   // typed on meanwhile
          if (!d.comicid) return linkNote(d.kind === 'issue' ? 'Couldn\'t find that issue on ComicVine.' : '');
          if (String(d.comicid) !== String(state.comicid)) {
            return linkNote('That link is ' + (d.kind === 'issue' ? 'an issue of ' : '') + 'another series' + (d.series ? ', ' + d.series : '') +
                            '. If these files belong to it, use Wrong series… in the series menu.');
          }
          if (d.kind !== 'issue') return linkNote('That link is this series. Paste an issue link to match a file to that issue.');
          if (!issueById(d.issueid)) return linkNote('#' + (d.number || '?') + ' isn\'t on this series here yet. Refresh the series to load it from ComicVine.');
          state.issueid = d.issueid;
          state.q = '';
          load();
        })
        .catch(function () { linkNote('Couldn\'t look up that link. Check the log.'); });
    }, 300);
    return true;
  }
  function applySearch() {
    var words = (state.q || '').toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    body.querySelectorAll('[data-text]').forEach(function (row) {
      var t = row.getAttribute('data-text');
      var hit = words.every(function (w) { return t.indexOf(w.replace(/^#/, '')) >= 0; });
      row.hidden = !hit;
      if (hit) shown++;
    });
    body.querySelectorAll('[data-section]').forEach(function (sec) {
      sec.hidden = !sec.querySelector('[data-text]:not([hidden])');
    });
    var none = body.querySelector('.match-empty');
    if (none) none.hidden = shown > 0;
  }

  function options(selected) {
    return (selected ? '' : '<option value="" selected disabled>Choose an issue</option>') + data.issues.map(function (i) {
      return '<option value="' + esc(i.issueid) + '"' + (String(i.issueid) === String(selected) ? ' selected' : '') + '>#' +
        esc(i.number) + (i.name ? ' · ' + esc(i.name) : '') + '</option>';
    }).join('');
  }

  function seriesRow(f, n, kind) {
    var current = kind === 'waiting' ? null : f.issueid;
    return '<li class="match-row' + (current ? '' : ' is-unmatched') + '" data-text="' + esc(searchText(f)) + '" data-kind="' + kind + '" data-n="' + n + '">' +
      '<div class="match-covers">' + fileCover(f) + issueCover(issueById(f.issueid), f.issueid ? null : '') + '</div>' +
      '<div class="match-file"><span class="match-name">' + fileName(f) + '</span><span class="match-meta">' + meta(f) + '</span>' +
      '<div class="match-do"><select aria-label="Issue for ' + esc(f.name) + '">' + options(f.issueid) + '</select>' +
      '<button type="button" class="btn btn-sm btn-primary" data-match hidden>' + (kind === 'waiting' ? 'File as this issue' : 'Match') + '</button>' +
      (f.pinned ? '<button type="button" class="btn btn-sm btn-ghost" data-undo="' + esc(f.issueid) + '">Undo</button>' : '') +
      '</div></div></li>';
  }

  function seriesView() {
    title.textContent = 'Match files';
    intro.textContent = data.files.length || data.waiting.length
      ? 'Compare each file\'s cover with the issue\'s cover from ComicVine, then pick the issue it is. A match you make here stays through rechecks until you undo it.'
      : 'There are no comic files in the series folder, and nothing in Needs attention looks like this series.';
    var html = searchBox('Search by file name, issue number or title, or paste a ComicVine issue link');
    if (data.files.length) {
      html += '<section data-section><h3 class="match-h">In the series folder</h3><ul class="match-list">' +
        data.files.map(function (f, n) { return seriesRow(f, n, 'folder'); }).join('') + '</ul></section>';
    }
    if (data.waiting.length) {
      html += '<section data-section><h3 class="match-h">Waiting in Needs attention</h3><ul class="match-list">' +
        data.waiting.map(function (f, n) { return seriesRow(f, n, 'waiting'); }).join('') + '</ul></section>';
    }
    body.innerHTML = html + '<p class="match-empty faint" hidden>Nothing matches that search.</p>';
    body.querySelectorAll('.match-row').forEach(function (row) {
      var f = (row.getAttribute('data-kind') === 'waiting' ? data.waiting : data.files)[+row.getAttribute('data-n')];
      var sel = row.querySelector('select'), go = row.querySelector('[data-match]');
      sel.addEventListener('change', function () {
        var i = issueById(sel.value);
        row.querySelector('[data-issue-cover]').outerHTML = issueCover(i);
        go.hidden = !i || (!f.path && String(i.issueid) === String(f.issueid));
      });
      go.addEventListener('click', function () {
        var i = issueById(sel.value);
        if (!i) return;
        if (f.path) run('attention_file', { path: f.path, comicid: state.comicid, issueid: i.issueid }, 'Filing ' + f.name + ' as #' + i.number + '…');
        else run('match_file', { comicid: state.comicid, issueid: i.issueid, name: f.name }, 'Matching ' + f.name + ' to #' + i.number + '…');
      });
    });
  }

  function issueView() {
    var issue = issueById(state.issueid);
    if (!issue) {
      title.textContent = 'Match a file';
      intro.textContent = 'That issue isn\'t on this series any more.';
      body.innerHTML = '';
      return;
    }
    title.textContent = 'Match a file to #' + issue.number;
    var mine = num(issue.number);
    function rank(f) { return num(f.reads_as) === mine || num(f.number) === mine && f.path ? 0 : !f.issueid ? 1 : f.path ? 1 : 2; }
    var files = data.files.concat(data.waiting).slice().sort(function (a, b) { return rank(a) - rank(b); });
    intro.innerHTML = 'Compare each file\'s cover with this issue\'s cover from ComicVine. ' +
      (issue.file ? 'Now ' + esc(issue.file) + (issue.pinned ? ' <span class="match-hand">matched by hand</span>' : '') + '.' : 'No file is matched to it yet.');
    body.innerHTML = '<div class="match-issue">' + issueCover(issue, '#' + issue.number + (issue.name ? ' · ' + issue.name : '')) +
      '<div class="match-issue-side">' + searchBox('Search files by name or number, or paste a ComicVine issue link') +
      (issue.pinned ? '<p class="match-undo"><button type="button" class="btn btn-sm" data-undo="' + esc(issue.issueid) + '">Match by file name again</button></p>' : '') +
      '</div></div>' +
      (files.length ? '' : '<p class="faint">There are no comic files in the series folder, and nothing in Needs attention looks like this series.</p>') +
      '<ul class="match-list">' + files.map(function (f, n) {
        var here = !f.path && String(f.issueid) === String(issue.issueid);
        return '<li class="match-row' + (here ? ' is-current' : '') + '" data-text="' + esc(searchText(f)) + '" data-n="' + n + '">' +
          '<div class="match-covers">' + fileCover(f) + '</div>' +
          '<div class="match-file"><span class="match-name">' + fileName(f) + '</span><span class="match-meta">' + meta(f) + '</span>' +
          '<div class="match-do"><button type="button" class="btn btn-sm' + (here ? '" data-off disabled' : ' btn-primary"') + ' data-use>' +
          (here ? 'This issue' : f.path ? 'File as this issue' : 'Use this file') + '</button></div></div></li>';
      }).join('') + '</ul><p class="match-empty faint" hidden>Nothing matches that search.</p>';
    body.querySelectorAll('[data-use]').forEach(function (b) {
      b.addEventListener('click', function () {
        var f = files[+b.closest('[data-n]').getAttribute('data-n')];
        if (f.path) run('attention_file', { path: f.path, comicid: state.comicid, issueid: issue.issueid }, 'Filing ' + f.name + ' as #' + issue.number + '…');
        else run('match_file', { comicid: state.comicid, issueid: issue.issueid, name: f.name }, 'Matching ' + f.name + ' to #' + issue.number + '…');
      });
    });
  }

  function load() {
    busy(true);
    return fetch('match_files?' + q({ comicid: state.comicid }), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        if (!d.ok) { intro.textContent = d.note || 'Couldn\'t list the files.'; body.innerHTML = ''; return; }
        data = d;
        data.waiting = d.waiting || [];
        if (state.issueid) issueView(); else seriesView();
        body.querySelectorAll('[data-undo]').forEach(function (b) {
          b.addEventListener('click', function () {
            run('match_undo', { comicid: state.comicid, issueid: b.getAttribute('data-undo') }, 'Undoing the match…');
          });
        });
        var box = body.querySelector('.match-search');
        if (box) {
          box.addEventListener('input', function () {
            state.q = box.value;
            if (followLink(box.value)) return;
            applySearch();
          });
          applySearch();
        }
        busy(false);
      })
      .catch(function () { intro.textContent = 'Couldn\'t list the files. Check the log.'; body.innerHTML = ''; });
  }

  function open(comicid, issueid) {
    dlg = document.getElementById('match-dialog');
    title = document.getElementById('match-title');
    intro = document.getElementById('match-intro');
    body = document.getElementById('match-body');
    if (!dlg) return;
    document.querySelectorAll('details.menu[open]').forEach(function (m) { m.open = false; });
    clearTimeout(wrongTimer);
    clearTimeout(linkTimer);
    state = { comicid: comicid, issueid: issueid || null, q: '' };
    title.textContent = issueid ? 'Match a file' : 'Match files';
    intro.textContent = 'Reading the series folder…';
    body.innerHTML = '';
    if (!dlg.open) dlg.showModal();
    load();
  }

  /* Wrong series: the series was added as the wrong ComicVine series. Find the right one, add it,
     move the files into its folder and match them, then remove the wrong one if you want. */
  var wrongTimer = null;

  function wrongOpen(comicid, name, year) {
    dlg = document.getElementById('match-dialog');
    title = document.getElementById('match-title');
    intro = document.getElementById('match-intro');
    body = document.getElementById('match-body');
    if (!dlg) return;
    document.querySelectorAll('details.menu[open]').forEach(function (m) { m.open = false; });
    clearTimeout(wrongTimer);
    state = { comicid: comicid, name: name, label: name + (year ? ' (' + year + ')' : ''), wrong: true };
    title.textContent = 'Wrong series';
    intro.textContent = 'Find the series these files belong to on ComicVine, or paste its ComicVine link. The files move to it and are matched to its issues.';
    body.innerHTML = '<form class="match-do" data-wrong-find><input type="search" class="match-search" aria-label="Series name or ComicVine link" placeholder="Series name or ComicVine link" value="' + esc(name) + '" />' +
      '<button type="submit" class="btn btn-sm btn-primary">Search ComicVine</button></form><div data-wrong-out></div>';
    body.querySelector('[data-wrong-find]').addEventListener('submit', function (e) {
      e.preventDefault();
      wrongSearch(body.querySelector('.match-search').value);
    });
    if (!dlg.open) dlg.showModal();
    // a job already running for this series shows how it's going instead of a new search
    fetch('match_wrong_series_state?' + q({ comicid: comicid }), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        if (d.state === 'adding' || d.state === 'moving' || d.state === 'removing') { wrongShow(d); wrongWatch(comicid); }
        else wrongSearch(name);
      })
      .catch(function () { wrongSearch(name); });
  }

  function wrongOut(html) {
    var out = body.querySelector('[data-wrong-out]');
    out.innerHTML = html;
    return out;
  }

  function wrongSearch(text) {
    text = (text || '').trim();
    if (!text) return;
    clearTimeout(wrongTimer);
    wrongOut('<p class="match-meta">Searching ComicVine for ' + esc(text) + '…</p>');
    fetch('attention_find?' + q({ q: text }), { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        if (d.ok === false) { wrongOut('<p class="match-meta">' + esc(d.note) + '</p>'); return; }
        if (!d.series.length) {
          wrongOut('<p class="match-meta">' + (d.link ? 'ComicVine has no series at that link.' : 'ComicVine has nothing called ' + esc(text) + '. Try fewer words.') + '</p>');
          return;
        }
        var out = wrongOut('<ul class="match-list">' + d.series.map(function (s) {
          var same = String(s.comicid) === String(state.comicid);
          var meta = [s.alias ? 'also called ' + s.alias : '', s.publisher, s.issues != null ? s.issues + ' issues' : '', s.type, same ? 'this series' : s.watched ? 'on your watchlist' : '']
            .filter(Boolean).map(esc).join(' · ');
          var cover = s.thumb ? '<img src="' + esc(s.thumb) + '" alt="Cover of ' + esc(s.name) + '" loading="lazy" referrerpolicy="no-referrer" />'
                              : '<span class="match-nocover">No cover</span>';
          return '<li class="match-row"><div class="match-covers"><figure class="match-cover"><span class="match-cover-btn">' + cover + '</span></figure></div>' +
            '<div class="match-file"><span>' + esc(s.name) + ' (' + esc(s.year) + ')' + (s.volume ? ' ' + esc(s.volume) : '') + '</span>' +
            '<span class="match-meta">' + meta + '</span><div class="match-do">' +
            (same ? '' : '<button type="button" class="btn btn-sm" data-wrong-pick="' + esc(s.comicid) + '" data-name="' + esc(s.name) + '" data-year="' + esc(s.year) + '">This one</button>') +
            '</div></div></li>';
        }).join('') + '</ul>');
        out.querySelectorAll('[data-wrong-pick]').forEach(function (b) {
          b.addEventListener('click', function () {
            wrongPick(b.getAttribute('data-wrong-pick'), b.getAttribute('data-name'), b.getAttribute('data-year'));
          });
        });
      })
      .catch(function () { wrongOut('<p class="match-meta">Couldn\'t search ComicVine. Check the log.</p>'); });
  }

  /* The choices come first, so the dialog can be closed while the right series loads (it can take
     a minute with many issues). The server carries on and the page says when it's done. */
  function wrongPick(newid, cvName, year) {
    var name = cvName + (year ? ' (' + year + ')' : '');
    var out = wrongOut('<p class="match-meta">Use ' + esc(name) + ' for the files of ' + esc(state.label) + '?</p>' +
      '<label class="match-meta"><input type="checkbox" data-wrong-move checked /> Move the files to it and match them to its issues</label><br />' +
      '<label class="match-meta"><input type="checkbox" data-wrong-remove /> Then remove ' + esc(state.label) + ' from your library (its folder stays)</label>' +
      '<div class="match-do"><button type="button" class="btn btn-sm btn-primary" data-wrong-start>Add ' + esc(name) + '</button></div>');
    out.querySelector('[data-wrong-start]').addEventListener('click', function (e) {
      e.target.disabled = true;
      var move = out.querySelector('[data-wrong-move]').checked, remove = out.querySelector('[data-wrong-remove]').checked;
      post('match_wrong_series', { comicid: state.comicid, newid: newid, name: cvName, year: year, move: move ? 1 : '', remove: remove ? 1 : '' })
        .then(function (d) {
          if (d.ok === false && !d.state) { wrongOut('<p class="match-meta">' + esc(d.note) + '</p>'); return; }
          wrongShow(d);
          wrongWatch(state.comicid);
        })
        .catch(function () { wrongOut('<p class="match-meta">That didn\'t work. Check the log.</p>'); });
    });
  }

  function wrongVisible(comicid) {
    return dlg && dlg.open && state.wrong && String(state.comicid) === String(comicid);
  }

  // Keeps asking while the job runs, whether the dialog is open or not.
  function wrongWatch(comicid) {
    clearTimeout(wrongTimer);
    fetch('match_wrong_series_state?' + q({ comicid: comicid }), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        if (d.state === 'done' || d.state === 'failed') {
          reloadTable();
          if (wrongVisible(comicid)) wrongShow(d);
          else window.Issuarr.toast(d.note, d.state === 'done');
          return;
        }
        if (wrongVisible(comicid)) wrongShow(d);
        wrongTimer = setTimeout(function () { wrongWatch(comicid); }, 3000);
      })
      .catch(function () { wrongTimer = setTimeout(function () { wrongWatch(comicid); }, 10000); });
  }

  function wrongShow(d) {
    if (d.state === 'failed') { wrongOut('<p class="match-meta">' + esc(d.note) + '</p>'); return; }
    if (d.state !== 'done') {
      wrongOut('<p class="match-meta">' + esc(d.note) + '</p>' +
        '<p class="match-meta">You can close this window. It carries on in the background and says when it\'s done.</p>');
      return;
    }
    var go = 'comicDetails?' + q({ ComicID: d.newid });
    var out = wrongOut('<p class="match-meta">' + esc(d.note) + '</p><div class="match-do">' +
      (d.removed ? '' : '<button type="button" class="btn btn-sm" data-wrong-remove>Remove ' + esc(d.old) + ' from your library</button>') +
      '<a class="btn btn-sm btn-primary" href="' + esc(go) + '">Go to the right series</a></div>');
    var rm = out.querySelector('[data-wrong-remove]');
    if (!rm) return;
    rm.addEventListener('click', function (e) {
      e.target.disabled = true;
      fetch('deleteSeries?' + q({ ComicID: d.comicid, ajax: 1 }), { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (r) {
          if (r.ok) location.href = go;
          else { window.Issuarr.toast('Couldn\'t remove it. Check the log.', false); e.target.disabled = false; }
        })
        .catch(function () { window.Issuarr.toast('Couldn\'t remove it. Check the log.', false); e.target.disabled = false; });
    });
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest) return;
    if (e.target.closest('#match-dialog [data-close]')) document.getElementById('match-dialog').close();
    var zoom = e.target.closest('#match-dialog [data-zoom]');
    if (zoom) {
      var box = zoom.closest('.match-covers, .match-issue');
      if (box) box.classList.toggle('is-large');
    }
  });

  // A cover can fail because the server was busy making others: ask again after 3, 6 and 12 seconds.
  document.addEventListener('error', function (e) {
    var im = e.target;
    if (!im.matches || !im.matches('#match-dialog [data-cover-img]')) return;
    var tries = +(im.getAttribute('data-tries') || 0);
    im.style.visibility = 'hidden';
    if (tries < 3) {
      if (!im.getAttribute('data-src')) im.setAttribute('data-src', im.getAttribute('src'));
      im.setAttribute('data-tries', tries + 1);
      setTimeout(function () { if (im.isConnected) im.src = im.getAttribute('data-src') + '&r=' + (tries + 1); }, 3000 * Math.pow(2, tries));
      return;
    }
    im.parentNode.innerHTML = '<span class="match-nocover">No cover</span>';
  }, true);

  document.addEventListener('load', function (e) {
    if (e.target.matches && e.target.matches('#match-dialog [data-cover-img]')) e.target.style.visibility = '';
  }, true);

  /* Files that may belong to another series: past the series' last issue (another volume), or a
     collected edition in a series of single issues (by name, or far bigger than its other files). */
  function suspectsCheck() {
    var box = document.getElementById('series_suspects');
    if (!box) return;
    var id = box.getAttribute('data-comicid');
    fetch('match_suspects?' + q({ comicid: id }), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        var n = d.ok ? d.files.length : 0;
        box.hidden = !n;
        if (!n) return;
        box.innerHTML = '<span>' + (d.whole
          ? 'Most files here are numbered past the end of this series. It may have been added as the wrong ComicVine volume.'
          : n + (n === 1 ? ' file here looks like it belongs' : ' files here look like they belong') + ' to another series.') + '</span>' +
          '<button type="button" class="btn btn-sm" data-suspects>Review</button>' +
          (d.whole ? '<button type="button" class="btn btn-sm btn-primary" data-suspects-wrong>Wrong series…</button>' : '');
        box.querySelector('[data-suspects]').addEventListener('click', function () { suspectsOpen(id, d); });
        var w = box.querySelector('[data-suspects-wrong]');
        if (w) w.addEventListener('click', function () { wrongOpen(id, box.getAttribute('data-name'), box.getAttribute('data-year')); });
      })
      .catch(function () { box.hidden = true; });
  }

  function suspectsOpen(comicid, d) {
    dlg = document.getElementById('match-dialog');
    title = document.getElementById('match-title');
    intro = document.getElementById('match-intro');
    body = document.getElementById('match-body');
    if (!dlg) return;
    state = { comicid: comicid, suspects: true };
    title.textContent = 'Files that may belong elsewhere';
    intro.textContent = 'Move a file to Needs attention, then use File as there to put it in the series it belongs to. ' +
      'If a file is right where it is, leave it.';
    body.innerHTML = '<ul class="match-list">' + d.files.map(function (f, n) {
      return '<li class="match-row" data-n="' + n + '"><div class="match-covers">' + fileCover(f) + '</div>' +
        '<div class="match-file"><span class="match-name">' + fileName(f) + '</span>' +
        '<span class="match-meta">' + (f.number ? 'Now #' + esc(f.number) + ' · ' : '') + esc(f.note) + ' · ' + mb(f.size) + '</span>' +
        '<div class="match-do"><button type="button" class="btn btn-sm btn-primary" data-away>Move to Needs attention</button></div></div></li>';
    }).join('') + '</ul>';
    body.querySelectorAll('[data-away]').forEach(function (b) {
      b.addEventListener('click', function () {
        var f = d.files[+b.closest('[data-n]').getAttribute('data-n')];
        b.disabled = true;
        post('match_send_away', { comicid: comicid, name: f.name }).then(function (r) {
          window.Issuarr.toast(r.note || (r.ok ? 'Done.' : 'That didn\'t work.'), !!r.ok);
          if (!r.ok) { b.disabled = false; return; }
          b.closest('.match-row').remove();
          reloadTable();
          suspectsCheck();
        }).catch(function () { window.Issuarr.toast('That didn\'t work. Check the log.', false); b.disabled = false; });
      });
    });
    if (!dlg.open) dlg.showModal();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', suspectsCheck);
  else suspectsCheck();

  window.IssuarrMatch = { open: open, wrongSeries: wrongOpen };
})();
