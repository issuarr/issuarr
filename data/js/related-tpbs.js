/* Series page: Related TPBs. Trades that collect this series' issues, or, on a trade, the other trades
   that collect the same series, so volumes ComicVine files as separate one-issue series link to each other. */
(function () {
  'use strict';

  var box = document.getElementById('related-tpbs');
  if (!box) return;
  var PILL = { Wanted: 'is-wanted', Snatched: 'is-snatched', Failed: 'is-failed', Downloaded: 'is-have', Archived: 'is-have', Ignored: 'is-ignored' };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };

  function row(t) {
    return '<tr' + (t.this ? ' class="rt-this"' : '') + '>' +
      '<td><a href="comicDetails?ComicID=' + encodeURIComponent(t.cid) + '">' + esc(t.name) + '</a> <span class="rt-dim">(' + esc(t.year) + ') #' + esc(t.num) + '</span>' +
      (t.title ? '<br><small class="rt-dim">' + esc(t.title) + '</small>' : '') + (t.this ? ' <span class="rt-badge">This trade</span>' : '') + '</td>' +
      '<td class="rt-dim">' + esc(t.type) + '</td>' +
      '<td class="rt-issues">' + esc(t.issues) + (t.whole ? ' <span class="rt-badge">Whole series</span>' : '') + '</td>' +
      '<td><span class="status ' + (PILL[t.status] || 'is-idle') + '">' + esc(t.status) + '</span></td></tr>';
  }

  function render(d) {
    if (!d.groups.length) {
      if (d.stored) return;
      box.hidden = false;
      box.innerHTML = '<h2 class="rt-title">Related TPBs</h2><p class="rt-dim">Trade contents haven\'t been read yet. Use <a href="ledger#trades">Library › Trades</a> to read them.</p>';
      return;
    }
    var html = '<h2 class="rt-title">Related TPBs</h2>';
    d.groups.forEach(function (g) {
      if (d.trade) html += '<h3 class="rt-series">Collects from <a href="comicDetails?ComicID=' + encodeURIComponent(g.cid) + '">' + esc(g.name) + ' (' + esc(g.year) + ')</a> <span class="rt-dim">' + g.issues + ' issue' + (g.issues === 1 ? '' : 's') + ' tracked</span></h3>';
      html += '<div class="rt-tablebox"><table class="rt-table"><thead><tr><th>Trade</th><th>Format</th><th>' + (d.trade ? 'Issues of ' + esc(g.name) : 'Issues it collects') + '</th><th>Status</th></tr></thead><tbody>' +
        g.trades.map(row).join('') + '</tbody></table></div>';
    });
    html += '<p class="rt-note rt-dim">From each trade\'s ComicVine description and the summary saved in the trade file. Only series you track are linked.</p>';
    box.innerHTML = html;
    box.hidden = false;
  }

  fetch('ledger_related?ComicID=' + encodeURIComponent(box.getAttribute('data-comicid')), { credentials: 'same-origin' })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(render)
    .catch(function () {});
})();
