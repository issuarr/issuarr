/* Series page: Other files in this folder. Files in the series' folder that aren't its own issues: ones another
   series sharing the folder counts as its own, and ones no issue points to. */
(function () {
  'use strict';

  var box = document.getElementById('other-files');
  if (!box) return;
  var comicid = box.getAttribute('data-comicid');
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
  var mb = function (n) { return n >= 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; };

  function what(f) {
    if (f.series) {
      return '<span class="status is-have">Matched elsewhere</span> #' + esc(f.series.number) + ' of <a href="comicDetails?ComicID=' +
        encodeURIComponent(f.series.id) + '">' + esc(f.series.name) + (f.series.year ? ' (' + esc(f.series.year) + ')' : '') + '</a>';
    }
    var r = f.reads_as || {};
    return '<span class="status is-snatched">Unmatched</span>' + (r.series ? ' <small class="rt-dim">reads as ' + esc(r.series) +
      (r.issue ? ' #' + esc(r.issue) : '') + (r.year ? ' (' + esc(r.year) + ')' : '') + '</small>' : '');
  }

  function row(f) {
    var acts = f.series ? '' :
      '<button type="button" class="btn btn-sm" data-of-match title="Match it to an issue of this series">Match…</button> ' +
      '<a class="btn btn-sm btn-ghost" href="unmatchedFolder?path=' + encodeURIComponent(f.folder) + '" title="Match it to another series">Other series…</a>';
    return '<tr><td><span title="' + esc(f.path) + '">' + (f.sub ? '<span class="rt-dim">' + esc(f.sub) + '/</span>' : '') + esc(f.name) + '</span>' +
      (f.note ? '<br><small class="rt-dim">' + esc(f.note) + '</small>' : '') + '</td>' +
      '<td class="rt-issues">' + mb(f.size) + '</td><td>' + what(f) + '</td><td class="nowrap">' + acts + '</td></tr>';
  }

  function render(d) {
    var files = (d && d.files) || [];
    box.hidden = !files.length;
    if (!files.length) { box.innerHTML = ''; return; }
    var loose = files.filter(function (f) { return !f.series; }).length;
    box.innerHTML = '<h2 class="rt-title">Other files in this folder</h2>' +
      '<p class="rt-note rt-dim">' + files.length + (files.length === 1 ? ' file' : ' files') + ' here ' + (files.length === 1 ? 'isn\'t' : 'aren\'t') +
      ' one of this series\' issues' + (loose ? ', ' + loose + ' of them tied to no issue at all' : '') + '. Hover a name for its full path.</p>' +
      '<div class="rt-tablebox"><table class="rt-table"><thead><tr><th>File</th><th>Size</th><th>What it is</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>' +
      files.map(row).join('') + '</tbody></table></div>';
  }

  function load() {
    fetch('series_other_files?comicid=' + encodeURIComponent(comicid), { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(render)
      .catch(function () {});
  }

  box.addEventListener('click', function (e) {
    if (e.target.closest('[data-of-match]') && window.IssuarrMatch) window.IssuarrMatch.open(comicid);
  });
  var dlg = document.getElementById('match-dialog');
  if (dlg) dlg.addEventListener('close', load);

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
  else load();
})();
