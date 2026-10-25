/* Tools > Duplicates: find issues with more than one file, tick the copies to move out. */
(function () {
  'use strict';

  var st = { data: null, poll: null, drop: {} };

  function $(id) { return document.getElementById(id); }
  function toast(msg, ok) { if (window.Issuarr) window.Issuarr.toast(msg, ok); }
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function mb(n) { return (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + ' MB'; }
  function post(url, params) {
    return fetch(url, { method: 'POST', credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body: new URLSearchParams(params || {}).toString() })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function load() {
    clearTimeout(st.poll);
    fetch('duplicates_status', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var fresh = !st.data || st.data.state !== d.state || st.data.groups.length !== d.groups.length;
        st.data = d;
        if (fresh) {
          st.drop = {};
          d.groups.forEach(function (g) { g.files.forEach(function (f) { if (!f.keep) st.drop[f.path] = true; }); });
        }
        render();
        if (d.state === 'running') st.poll = setTimeout(load, 3000);
      })
      .catch(function () { $('dp-note').textContent = 'Couldn\'t get the results. Check the log.'; });
  }

  function fileRow(g, f) {
    var bits = [f.readable ? (f.pages + ' pages') : 'won\'t open', f.tagged ? 'tagged' : 'no tags', mb(f.size),
                f.matched ? 'matched to this issue' : 'name reads as #' + g.number];
    return '<li class="dp-file' + (st.drop[f.path] ? ' is-drop' : '') + '">' +
      '<label class="set-inline"><input type="checkbox" data-path="' + esc(f.path) + '"' + (st.drop[f.path] ? ' checked' : '') + ' /> Move</label>' +
      '<div class="dp-name"><span class="mono">' + (f.sub ? '<span class="faint">' + esc(f.sub) + '/</span>' : '') + esc(f.name) + '</span>' +
      (f.keep ? ' <span class="status is-have">Best copy</span>' : '') +
      '<small class="muted">' + esc(bits.join(' · ')) + '</small></div></li>';
  }

  function render() {
    var d = st.data;
    var running = d.state === 'running';
    $('dp-scan').disabled = running;
    $('dp-stop').hidden = !running;
    if (running) $('dp-note').textContent = 'Looking through series ' + d.done + ' of ' + (d.total || '…') + '. ' + d.groups.length + ' found so far.';
    else if (d.finished) $('dp-note').textContent = d.groups.length
      ? d.groups.length + (d.groups.length === 1 ? ' issue has' : ' issues have') + ' more than one file (checked ' + d.finished + '). Untick a copy to leave it, or tick the best copy to keep another one instead. Every issue keeps at least one file.'
      : 'No duplicates found (checked ' + d.finished + ').';
    $('dp-list').innerHTML = d.groups.map(function (g) {
      return '<article class="dp-group"><h3><a href="comicDetails?ComicID=' + encodeURIComponent(g.comicid) + '">' + esc(g.series) + (g.year ? ' (' + esc(g.year) + ')' : '') + '</a> #' + esc(g.number) + '</h3>' +
        '<ul>' + g.files.map(function (f) { return fileRow(g, f); }).join('') + '</ul></article>';
    }).join('');
    var n = Object.keys(st.drop).filter(function (p) { return st.drop[p]; }).length;
    $('dp-bulk').hidden = running || !d.groups.length;
    $('dp-count').textContent = n + (n === 1 ? ' copy ticked' : ' copies ticked');
    $('dp-remove').disabled = !n;
  }

  document.addEventListener('change', function (e) {
    var p = e.target.getAttribute && e.target.getAttribute('data-path');
    if (!p) return;
    st.drop[p] = e.target.checked;
    render();
  });

  $('dp-scan').addEventListener('click', function () {
    post('duplicates_scan').then(function () { st.data = null; load(); }).catch(function () { toast('Couldn\'t start. Check the log.', false); });
  });
  $('dp-stop').addEventListener('click', function () { post('duplicates_stop'); });
  $('dp-remove').addEventListener('click', function () {
    var paths = Object.keys(st.drop).filter(function (p) { return st.drop[p]; });
    if (!paths.length || !confirm('Move ' + paths.length + (paths.length === 1 ? ' copy' : ' copies') + ' out of the library?')) return;
    $('dp-remove').disabled = true;
    post('duplicates_remove', { paths: JSON.stringify(paths) })
      .then(function (r) { toast(r.note, !!r.ok); st.data = null; load(); })
      .catch(function () { toast('Couldn\'t move them. Check the log.', false); render(); });
  });

  load();
})();
