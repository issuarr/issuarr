/* Series page: Match files (every file in the series folder) and Match a file (one issue).
   A match made here holds through rechecks until it is undone or the file goes. */
(function () {
  'use strict';

  var dlg, title, intro, body, state = {};

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
    body.querySelectorAll('button, select').forEach(function (b) { b.disabled = on || b.hasAttribute('data-off'); });
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

  function fileName(f) {
    return (f.sub ? '<span class="faint">' + esc(f.sub) + '/</span>' : '') + esc(f.name);
  }

  function nowText(f) {
    if (!f.issueid) return '<span class="match-none">Not matched</span>';
    return 'Now #' + esc(f.number) + (f.pinned ? ' <span class="match-hand">matched by hand</span>' : '');
  }

  function seriesView(d) {
    title.textContent = 'Match files';
    intro.textContent = d.files.length ? 'Pick the issue each file in the series folder is. A match you make here stays through rechecks until you undo it.'
                                       : 'There are no comic files in the series folder.';
    var opts = d.issues.map(function (i) {
      return '<option value="' + esc(i.issueid) + '">#' + esc(i.number) + (i.name ? ' · ' + esc(i.name) : '') + '</option>';
    }).join('');
    body.innerHTML = '<ul class="match-list">' + d.files.map(function (f, n) {
      return '<li class="match-row' + (f.issueid ? '' : ' is-unmatched') + '">' +
        '<div class="match-file"><span class="match-name">' + fileName(f) + '</span>' +
        '<span class="match-meta">' + nowText(f) + (f.reads_as ? ' · name reads as #' + esc(f.reads_as) : '') + ' · ' + mb(f.size) + '</span></div>' +
        '<div class="match-do"><select data-n="' + n + '" aria-label="Issue for ' + esc(f.name) + '">' +
        (f.issueid ? '' : '<option value="" selected disabled>Choose an issue</option>') + opts + '</select>' +
        (f.pinned ? '<button type="button" class="btn btn-sm btn-ghost" data-undo="' + esc(f.issueid) + '">Undo</button>' : '') +
        '</div></li>';
    }).join('') + '</ul>';
    body.querySelectorAll('select').forEach(function (s) {
      var f = d.files[+s.getAttribute('data-n')];
      if (f.issueid) s.value = f.issueid;
      s.addEventListener('change', function () {
        run('match_file', { comicid: state.comicid, issueid: s.value, name: f.name }, 'Matching ' + f.name + '…');
      });
    });
  }

  function issueView(d) {
    var issue = d.issues.filter(function (i) { return String(i.issueid) === String(state.issueid); })[0];
    if (!issue) {
      title.textContent = 'Match a file';
      intro.textContent = 'That issue isn\'t on this series any more.';
      body.innerHTML = '';
      return;
    }
    title.textContent = 'Match a file to #' + issue.number;
    var mine = num(issue.number);
    var files = d.files.slice().sort(function (a, b) {
      function rank(f) { return num(f.reads_as) === mine ? 0 : f.issueid ? 2 : 1; }
      return rank(a) - rank(b);
    });
    intro.innerHTML = issue.file ? 'Now ' + esc(issue.file) + (issue.pinned ? ' <span class="match-hand">matched by hand</span>' : '') + '.'
                                 : 'No file is matched to this issue yet.';
    if (!files.length) intro.innerHTML += ' There are no comic files in the series folder.';
    body.innerHTML = (issue.pinned ? '<p class="match-undo"><button type="button" class="btn btn-sm" data-undo="' + esc(issue.issueid) + '">Match by file name again</button></p>' : '') +
      '<ul class="match-list">' + files.map(function (f, n) {
        var here = String(f.issueid) === String(issue.issueid);
        return '<li class="match-row' + (here ? ' is-current' : '') + '">' +
          '<div class="match-file"><span class="match-name">' + fileName(f) + '</span>' +
          '<span class="match-meta">' + nowText(f) + (f.reads_as ? ' · name reads as #' + esc(f.reads_as) : '') + ' · ' + mb(f.size) + '</span></div>' +
          '<div class="match-do"><button type="button" class="btn btn-sm' + (here ? '" data-off disabled' : ' btn-primary"') + ' data-use="' + esc(f.name) + '">' +
          (here ? 'This issue' : 'Use this file') + '</button></div></li>';
      }).join('') + '</ul>';
    body.querySelectorAll('[data-use]').forEach(function (b) {
      b.addEventListener('click', function () {
        var name = b.getAttribute('data-use');
        run('match_file', { comicid: state.comicid, issueid: issue.issueid, name: name }, 'Matching ' + name + ' to #' + issue.number + '…');
      });
    });
  }

  function load() {
    busy(true);
    return fetch('match_files?' + q({ comicid: state.comicid }), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        if (!d.ok) { intro.textContent = d.note || 'Couldn\'t list the files.'; body.innerHTML = ''; return; }
        if (state.issueid) issueView(d); else seriesView(d);
        body.querySelectorAll('[data-undo]').forEach(function (b) {
          b.addEventListener('click', function () {
            run('match_undo', { comicid: state.comicid, issueid: b.getAttribute('data-undo') }, 'Undoing the match…');
          });
        });
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
    state = { comicid: comicid, issueid: issueid || null };
    title.textContent = issueid ? 'Match a file' : 'Match files';
    intro.textContent = 'Reading the series folder…';
    body.innerHTML = '';
    if (!dlg.open) dlg.showModal();
    load();
  }

  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('#match-dialog [data-close]')) document.getElementById('match-dialog').close();
  });

  window.IssuarrMatch = { open: open };
})();
