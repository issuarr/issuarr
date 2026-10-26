/* Tools > Library check: damaged and wrapped comics, and what to do with each. */
(function () {
  'use strict';

  var st = { data: null, poll: null };

  function $(id) { return document.getElementById(id); }
  function toast(msg, ok) { if (window.Issuarr) window.Issuarr.toast(msg, ok); }
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function post(url, params) {
    return fetch(url, { method: 'POST', credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body: new URLSearchParams(params || {}).toString() })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function load() {
    clearTimeout(st.poll);
    fetch('library_check_status', { credentials: 'same-origin', cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        st.data = d;
        render();
        if (d.state === 'running') st.poll = setTimeout(load, 3000);
      })
      .catch(function () { $('lc-note').textContent = 'Couldn\'t get the results. Check the log.'; });
  }

  function row(f, n) {
    var where = f.series ? '<a href="comicDetails?ComicID=' + encodeURIComponent(f.comicid) + '">' + esc(f.series) + (f.year ? ' (' + esc(f.year) + ')' : '') + '</a>' + (f.number ? ' #' + esc(f.number) : '') : '';
    var fix = f.unwrap || f.repack;
    var acts = (f.unwrap ? '<button type="button" class="btn btn-sm btn-primary" data-act="unwrap" data-n="' + n + '">Unwrap</button>' : '') +
      (f.repack ? '<button type="button" class="btn btn-sm btn-primary" data-act="repack" data-n="' + n + '" title="Make it a .cbz with the same pages; the original goes to the trash">Repack to .cbz</button>' : '') +
      (f.issueid && !f.repack ? '<button type="button" class="btn btn-sm' + (fix ? '' : ' btn-primary') + '" data-act="redownload" data-n="' + n + '" title="Move it to the trash and mark the issue Wanted">Download again</button>' : '') +
      '<button type="button" class="btn btn-sm btn-ghost" data-act="remove" data-n="' + n + '" title="Move it to the trash">Remove</button>';
    var label = { nested: ['is-snatched', 'Wrapped'], repack: ['is-snatched', 'Solid RAR'] }[f.status] || ['is-failed', 'Damaged'];
    return '<li class="lc-file"><div class="lc-main"><span class="status ' + label[0] + '">' + label[1] + '</span> <span class="mono">' + esc(f.name) + '</span>' +
      '<small class="muted">' + (where ? where + ' · ' : '') + esc(f.detail) + '</small></div>' +
      '<div class="lc-acts">' + acts + '</div></li>';
  }

  function render() {
    var d = st.data, running = d.state === 'running';
    $('lc-scan').disabled = running;
    $('lc-stop').hidden = !running;
    var note;
    if (running) note = 'Checking file ' + d.done + ' of ' + (d.total || '…') + ' (' + d.opened + ' opened, ' + d.trusted + ' already read through by WebP, the rest unchanged since last time).';
    else if (d.error) note = 'The check stopped after ' + d.done + ' of ' + d.total + ' files: ' + d.error + '. Files after that weren\'t checked; see the log.';
    else if (!d.checked) note = 'Not checked yet.';
    else note = d.files.length ? d.files.length + (d.files.length === 1 ? ' file needs' : ' files need') + ' a look.' : 'Every file checked out.';
    if (!running && d.finished) note += ' Last run ' + d.finished + '.';
    if (d.unchecked) note += ' ' + d.unchecked + ' ' + (d.unchecked === 1 ? 'file' : 'files') + ' couldn\'t be checked (a .cbr needs unrar installed; the log names any others).';
    $('lc-note').textContent = note;
    $('lc-list').innerHTML = d.files.map(row).join('');
  }

  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-act]');
    if (!b) return;
    var f = st.data.files[+b.getAttribute('data-n')], act = b.getAttribute('data-act');
    var ask = { remove: 'Move ' + f.name + ' to the trash?', redownload: 'Move ' + f.name + ' to the trash and search for the issue again?' }[act];
    if (ask && !confirm(ask)) return;
    b.closest('.lc-file').querySelectorAll('button').forEach(function (x) { x.disabled = true; });
    post('library_check_act', { path: f.path, action: act })
      .then(function (r) { toast(r.note, !!r.ok); load(); })
      .catch(function () { toast('That didn\'t work. Check the log.', false); load(); });
  });

  $('lc-scan').addEventListener('click', function () {
    if (!st.data.checked && !confirm('The first check reads every comic file that WebP hasn\'t already read through, from start to finish. On a large library this can take hours. Run it now?')) return;
    post('library_check_scan').then(load).catch(function () { toast('Couldn\'t start. Check the log.', false); });
  });
  $('lc-stop').addEventListener('click', function () { post('library_check_stop'); });

  load();
})();
