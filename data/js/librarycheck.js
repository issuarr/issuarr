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
        if (d.state === 'running' || d.tagging.state === 'running') st.poll = setTimeout(load, 3000);
      })
      .catch(function () { $('lc-note').textContent = 'Couldn\'t get the results. Check the log.'; });
  }

  function row(f, n) {
    var where = f.series ? '<a href="comicDetails?ComicID=' + encodeURIComponent(f.comicid) + '">' + esc(f.series) + (f.year ? ' (' + esc(f.year) + ')' : '') + '</a>' + (f.number ? ' #' + esc(f.number) : '') : '';
    var acts = (f.unwrap ? '<button type="button" class="btn btn-sm btn-primary" data-act="unwrap" data-n="' + n + '">Unwrap</button>' : '') +
      (f.issueid ? '<button type="button" class="btn btn-sm' + (f.unwrap ? '' : ' btn-primary') + '" data-act="redownload" data-n="' + n + '" title="Move it to the trash and mark the issue Wanted">Download again</button>' : '') +
      '<button type="button" class="btn btn-sm btn-ghost" data-act="remove" data-n="' + n + '" title="Move it to the trash">Remove</button>';
    return '<li class="lc-file"><div class="lc-main"><span class="status ' + (f.status === 'nested' ? 'is-snatched' : 'is-failed') + '">' +
      (f.status === 'nested' ? 'Wrapped' : 'Damaged') + '</span> <span class="mono">' + esc(f.name) + '</span>' +
      '<small class="muted">' + (where ? where + ' · ' : '') + esc(f.detail) + '</small></div>' +
      '<div class="lc-acts">' + acts + '</div></li>';
  }

  function render() {
    var d = st.data, running = d.state === 'running';
    $('lc-scan').disabled = running || d.tagging.state === 'running';
    $('lc-stop').hidden = !running;
    var note;
    if (running) note = 'Checking file ' + d.done + ' of ' + (d.total || '…') + ' (' + d.opened + ' opened, the rest unchanged since last time).';
    else if (!d.checked) note = 'Not checked yet.';
    else note = d.files.length ? d.files.length + (d.files.length === 1 ? ' file needs' : ' files need') + ' a look.' : 'Every file checked out.';
    if (!running && d.finished) note += ' Last run ' + d.finished + '.';
    if (d.unchecked) note += ' ' + d.unchecked + ' .cbr ' + (d.unchecked === 1 ? 'file' : 'files') + ' couldn\'t be checked because unrar isn\'t installed.';
    $('lc-note').textContent = note;
    $('lc-list').innerHTML = d.files.map(row).join('');
    renderTags(d, running);
  }

  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  function renderTags(d, checking) {
    var t = d.tagging, tagging = t.state === 'running', note;
    $('lc-tags').hidden = !d.checked;
    $('lc-tag').hidden = tagging;
    $('lc-tag').disabled = checking || !d.untagged;
    $('lc-tag').textContent = d.untagged ? 'Tag ' + plural(d.untagged, 'untagged file', 'untagged files') : 'Tag untagged files';
    $('lc-tag-stop').hidden = !tagging;
    if (tagging) note = 'Tagging file ' + t.done + ' of ' + (t.total || '…') + ' (' + t.tagged + ' tagged so far).';
    else if (d.untagged) note = plural(d.untagged, 'file', 'files') + ' in ' + plural(d.untagged_series, 'series', 'series') +
      ' have no ComicInfo.xml. Tagging writes one from the series and issue details Issuarr already has, without asking ComicVine (.cbr files are made .cbz first, since only a .cbz can hold tags). For full tags (credits, summary) use Tag issues on the series page.';
    else note = 'Every checked issue file has tags.';
    if (!tagging && t.finished) note += ' Last tagging run ' + t.finished + ': ' + plural(t.tagged, 'file', 'files') + ' tagged' +
      (t.failed ? ', ' + t.failed + ' couldn\'t be tagged (see the log)' : '') + '.';
    $('lc-tag-note').textContent = note;
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
    post('library_check_scan').then(load).catch(function () { toast('Couldn\'t start. Check the log.', false); });
  });
  $('lc-stop').addEventListener('click', function () { post('library_check_stop'); });
  $('lc-tag').addEventListener('click', function () {
    post('library_check_tag')
      .then(function (r) { if (!r.ok) toast('Wait for the check or tagging that is running to finish.', false); load(); })
      .catch(function () { toast('Couldn\'t start. Check the log.', false); });
  });
  $('lc-tag-stop').addEventListener('click', function () { post('library_check_tag_stop'); });

  load();
})();
