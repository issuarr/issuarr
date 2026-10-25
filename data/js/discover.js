/* Discover page: new #1s, the latest issue of each series, and new #1s from the publishers
   you collect most, all from the weekly release lists (discover_feed). */
(function () {
  'use strict';

  var NOTES = {
    'new': 'Issue #1s that shipped in this window, newest first.',
    'foryou': 'New #1s from the publishers you have the most series from',
    'latest': 'Every series with an issue in this window, showing its newest issue.'
  };
  var st = { feed: 'new', weeks: null, hideOwned: false, data: null, adding: {}, poll: null };

  function $(id) { return document.getElementById(id); }
  function toast(msg, ok) { if (window.Issuarr) window.Issuarr.toast(msg, ok); }
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  function day(s) {
    var d = new Date(String(s || '') + 'T12:00:00');
    return isNaN(d) ? '' : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  function load() {
    clearTimeout(st.poll);
    fetch('discover_feed?' + new URLSearchParams({ weeks: st.weeks }).toString(), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        st.data = d;
        render();
        // older weeks are fetched in the background on first visit
        if (d.loading) st.poll = setTimeout(load, 5000);
      })
      .catch(function () { $('dc-grid').innerHTML = '<p class="empty-state">Couldn\'t load the release lists. Check the log.</p>'; });
  }

  function card(c) {
    var name = c.series + (c.year ? ' (' + c.year + ')' : '');
    var cover = c.issueid && st.data.covers
      ? '<img src="discover_cover?issueid=' + encodeURIComponent(c.issueid) + '" alt="" loading="lazy" data-tries="0" />'
      : '';
    var act;
    if (c.owned) act = '<a class="status is-have" href="comicDetails?ComicID=' + encodeURIComponent(c.comicid) + '">In library</a>';
    else if (st.adding[c.comicid]) act = '<span class="status is-snatched is-running">Adding…</span>';
    else if (c.comicid) act = '<button type="button" class="btn btn-sm btn-primary" data-add="' + esc(c.comicid) + '" data-name="' + esc(c.series) + '">Add</button>';
    else act = '<a class="btn btn-sm" href="searchit?' + new URLSearchParams({ name: c.series }).toString() + '" title="This release has no ComicVine id yet">Find</a>';
    var cv = c.comicid ? '<a class="dc-cv" href="https://comicvine.gamespot.com/volume/4050-' + encodeURIComponent(c.comicid) + '/" target="_blank" rel="noopener">ComicVine</a>' : '';
    return '<article class="dc-card' + (c.owned ? ' is-owned' : '') + '">' +
      '<div class="dc-cover">' + cover + '<span class="dc-issue">#' + esc(c.issue) + '</span></div>' +
      '<div class="dc-body">' +
        '<h3 class="dc-title" title="' + esc(name) + '">' + esc(c.series) + '</h3>' +
        '<p class="dc-meta">' + esc(c.publisher || 'Unknown publisher') + (c.year ? ' · ' + esc(c.year) : '') + '</p>' +
        '<p class="dc-meta">Shipped ' + esc(day(c.shipdate)) + '</p>' +
        '<div class="dc-acts">' + act + cv + '</div>' +
      '</div></article>';
  }

  function render() {
    var d = st.data;
    if (!d) return;
    ['new', 'foryou', 'latest'].forEach(function (f) {
      var n = (d[f] || []).filter(function (c) { return !(st.hideOwned && c.owned); }).length;
      document.querySelector('[data-count="' + f + '"]').textContent = n;
    });
    var tabs = document.querySelectorAll('#dc-tabs [data-feed]');
    for (var i = 0; i < tabs.length; i++) tabs[i].setAttribute('aria-pressed', String(tabs[i].getAttribute('data-feed') === st.feed));

    var note = NOTES[st.feed];
    if (st.feed === 'foryou') note += d.publishers && d.publishers.length ? ': ' + d.publishers.join(', ') + '.' : '. Add some series first so Issuarr knows what you collect.';
    if (d.loading) note += ' Getting older release lists…';
    else if (d.missing) note += ' ' + d.missing + (d.missing === 1 ? ' week' : ' weeks') + ' of release lists couldn\'t be fetched, so this is incomplete.';
    if (!d.covers) note += ' Covers need your ComicVine API key (Settings > ComicVine).';
    $('dc-note').textContent = note;

    var list = (d[st.feed] || []).filter(function (c) { return !(st.hideOwned && c.owned); });
    $('dc-grid').innerHTML = list.length
      ? list.map(card).join('')
      : '<p class="empty-state">' + (d.loading ? 'Getting the release lists…' : 'Nothing here for these weeks.') + '</p>';
  }

  function add(btn) {
    var id = btn.getAttribute('data-add'), name = btn.getAttribute('data-name');
    st.adding[id] = true;
    render();
    fetch('addbyid?' + new URLSearchParams({ comicid: id, calledby: 'True', ogcname: name }).toString(), { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        toast('Adding ' + name + '. It appears in your library when ComicVine has sent everything.');
      })
      .catch(function () { delete st.adding[id]; render(); toast('Couldn\'t add ' + name + '. Check the log.', false); });
  }

  // a cover still being looked up answers 503: try it again a few times
  document.addEventListener('error', function (e) {
    var img = e.target;
    if (!img || img.tagName !== 'IMG' || !img.closest('.dc-cover')) return;
    var tries = +img.getAttribute('data-tries') + 1;
    if (tries > 6) { img.remove(); return; }
    img.setAttribute('data-tries', tries);
    setTimeout(function () { img.src = img.src.replace(/&r=\d+$/, '') + '&r=' + tries; }, 4000);
  }, true);

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-add]');
    if (b) return add(b);
    var t = e.target.closest('#dc-tabs [data-feed]');
    if (t) { st.feed = t.getAttribute('data-feed'); store('discover.feed', st.feed); render(); }
  });

  $('dc-weeks').addEventListener('change', function () { st.weeks = this.value; store('discover.weeks', st.weeks); load(); });
  $('dc-hide-owned').addEventListener('change', function () { st.hideOwned = this.checked; store('discover.hideOwned', this.checked ? '1' : ''); render(); });

  var saved = store('discover.weeks');
  if (saved && $('dc-weeks').querySelector('option[value="' + saved + '"]')) $('dc-weeks').value = saved;
  st.weeks = $('dc-weeks').value;
  st.feed = { 'new': 1, foryou: 1, latest: 1 }[store('discover.feed')] ? store('discover.feed') : 'new';
  st.hideOwned = $('dc-hide-owned').checked = !!store('discover.hideOwned');
  load();
})();
