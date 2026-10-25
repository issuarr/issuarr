/* "?" help: a short guide to the page you are on. Open it with the ? button or the ? key. */
(function () {
  'use strict';

  var SITE = 'https://issuarr.github.io/issuarr/';

  // Keyed by page name (the last part of the address, lower case). Each entry: title, then lines of HTML.
  var PAGES = {
    home: ['Library', [
      'Every series you follow. The bar under each series shows its run, issue by issue, in the colours of the legend at the top.',
      'The tabs narrow the list: <b>Has gaps</b> shows series missing issues, <b>Problems</b> shows series that failed to load or that ComicVine removed.',
      'The filter matches every word against the name, publisher and year, so <i>batman dc</i> or <i>saga 2012</i> both work.',
      '<b>Select</b> lets you pick several series to refresh, pause, recheck, tag, rename or remove at once.',
      '<b>Scan folders</b> finds comics you already have on disk. The <b>⋯</b> menu saves lists as CSV and updates every series from ComicVine.'
    ]],
    comicdetails: ['Series page', [
      '<b>Search for missing issues</b> searches every Skipped, Wanted or Snatched issue of this series without changing its status.',
      '<b>Refresh from ComicVine</b> gets new issues and details. <b>Recheck files</b> looks at the series folder again and matches files to issues.',
      'The <b>⋯</b> menu has <b>Match files…</b> (pick the issue for each file yourself), <b>Wrong series…</b> (move the files to the right ComicVine series), pause or resume, and remove.',
      'Pick issues in the list to change their status together. The arrows next to the title step to the previous and next series in your library.'
    ]],
    issuedetails: null,
    manageissues: ['Manage issues', [
      'Your issues grouped by status. Pick some and change their status in one go.',
      'Issues that are Wanted live on the <a href="wanted">Wanted</a> page instead.'
    ]],
    ledger: ['Ledger', [
      'Every issue missing from the series you follow, sorted into kinds: a <b>Gap</b> has owned issues on both sides, others are before your first or after your last owned issue.',
      '<b>Files not recognised</b> means the series folder has files Issuarr can\'t match to issues. Open the series and use <b>Match files…</b> in its ⋯ menu.',
      'Set <b>Collection ended</b> to a date and issues released after it get their own kind, so they don\'t crowd the list.',
      'Picking issues and marking them Wanted also starts a search for them.',
      'The <b>Trades</b> tab shows which trades and collections fill your gaps, duplicate singles you own, or replace a whole series.'
    ]],
    storyarc_main: ['Story arcs', [
      'Crossovers and events across several series, in reading order. Add one from ComicVine with <b>Add arc</b>, or bring in a reading list with <a href="cblimport">CBL import</a>.',
      'Open an arc to see which of its issues you have.'
    ]],
    detailstoryarc: ['Story arc', [
      'The issues of this arc in reading order, with where each one is in your library.',
      'Issues of series you don\'t follow can still be searched for this arc.'
    ]],
    readlist: ['Reading list', [
      'Issues you\'ve put aside to read. Mark them read or to read, or remove them; the issues and files stay in your library.',
      'With a tablet set up under <b>Reading list options</b>, Issuarr can send issues to it.'
    ]],
    cblimport: ['CBL import', [
      'Brings in a CBL reading list: its series are added and its issues marked Wanted. Issues already Downloaded, Wanted or Snatched are left alone.',
      'The list needs ComicVine IDs in it.'
    ]],
    discover: ['Discover', [
      'New and recent series from the weekly release lists. Add one and Issuarr starts following it.'
    ]],
    wanted: ['Wanted', [
      '<b>Tier 1</b> issues are searched on every scheduled search. <b>Tier 2</b> issues are older and only picked up from RSS feeds, unless you use <b>Search all</b>.',
      'Each row says where its issue is right now: waiting in the search queue, being searched, found, or downloading.',
      'Pick issues to search them now, switch their tier, or change their status.',
      '<b>Pause searches</b> holds the search queue. The <b>⋯</b> menu can put issues stuck at Snatched back to Wanted.'
    ]],
    pullist: ['Calendar', [
      'This week\'s releases. <b>Following</b> shows series you follow, <b>Wanted</b> what Issuarr is looking for, <b>Everything</b> the whole list.',
      '<b>Search for this week\'s wanted issues</b> starts those searches now.',
      'Issues ComicVine doesn\'t list yet are on <a href="upcoming">Upcoming</a>.'
    ]],
    upcoming: ['Upcoming', [
      'Releases Issuarr knows about but can\'t match yet: issues ComicVine doesn\'t list, new #1s you\'re watching for, and pull-list entries that didn\'t line up with your library.',
      '<b>Watching for new #1s</b> adds a series as soon as ComicVine lists it. <b>Check ComicVine now</b> looks them up without waiting for the next check.'
    ]],
    queuemanage: ['Downloads', [
      'Everything on its way into your library, from every download client and direct download in one list.',
      'You can pause downloads, stop them, or clear finished and failed ones. Downloads that can\'t be filed end up in <a href="needsAttention">Needs attention</a>.'
    ]],
    needsattention: ['Needs attention', [
      'Files Issuarr couldn\'t file on its own. For each one, pick the issue it is (<b>File as…</b>), search ComicVine, ignore it, or move it to the trash.',
      '<b>By folder</b> groups the files, so a whole pack can be handled at once.',
      '<b>Try filing again</b> runs the files through filing once more.'
    ]],
    history: ['History', [
      'Everything Issuarr has grabbed and what became of it.',
      '<b>Search again</b> looks for an issue once more. <b>Clear history…</b> removes entries by kind: snatched, processed, unprocessed or all.'
    ]],
    managefailed: ['Failed', [
      'Releases that failed once, so Issuarr won\'t grab them again.',
      '<b>Allow again</b> lets the next search pick a release up again.'
    ]],
    manage: ['Tools', [
      '<b>Import &amp; scan</b> scans a folder of comics you already have; the results show up in <a href="importResults">Import results</a>.',
      '<b>Post-processing</b> files a folder of downloads into your library by hand.',
      '<b>Export</b> saves your wanted or downloaded list as CSV in the data folder.'
    ]],
    importresults: ['Import results', [
      'Series found by the last library scan. Import the ones you want.',
      'When ComicVine has several possible matches for a series, choose the right one before importing.'
    ]],
    webpconvert: ['WebP conversion', [
      'Re-encodes the pages of comics already in your library as WebP to save space.',
      'New downloads are handled by the option in the post-processing settings.'
    ]],
    tasks: ['Jobs', [
      'What\'s running now, what runs next on the schedule, and the workers behind them.',
      'Problems usually show up in the <a href="logs">log</a> first.'
    ]],
    logs: ['Logs', [
      'The newest lines are at the top. Use the filter to find a series or an error.',
      '<b>Turn on debug logging</b> when you\'re chasing a problem, and turn it off again after: it writes a lot.',
      '<b>Exceptions and tracebacks</b> lists errors with their full details, which helps when reporting a problem.'
    ]],
    config: ['Settings', [
      'Each section in the sidebar is one page of settings. Nothing changes until you save, and the save bar says when you have unsaved changes.',
      'Download clients, search providers and ComicVine need their keys or addresses before searching works.',
      'Setting up JDownloader 2 or AirDC++? See the <a href="' + SITE + 'JDOWNLOADER2/" target="_blank" rel="noopener">JDownloader 2</a> and <a href="' + SITE + 'AIRDCPP/" target="_blank" rel="noopener">AirDC++</a> guides.'
    ]],
    searchit: ['Search results', [
      'Series on ComicVine that match your search. Add one and Issuarr starts following it and loads its issues.'
    ]],
    about: ['About', [
      'Which version of Issuarr this is and the branch it follows.'
    ]]
  };
  PAGES.issuedetails = PAGES.comicdetails;

  var GENERAL = [
    'Every page has a <b>?</b> button with help for that page.',
    'Status colours: <span class="help-dot" style="--c: var(--have)"></span>on disk, <span class="help-dot" style="--c: var(--wanted)"></span>wanted, ' +
      '<span class="help-dot" style="--c: var(--snatched)"></span>snatched, <span class="help-dot" style="--c: var(--failed)"></span>failed.'
  ];
  var KEYS = [['Ctrl K', 'Jump to any series, page or setting'], ['?', 'Help for this page'], ['Alt N', 'Notifications'], ['Esc', 'Close a window']];

  function page() {
    var p = location.pathname.split('/').pop().toLowerCase() || 'home';
    return p === 'index' ? 'home' : p;
  }

  var box = null, back = null;
  function build() {
    box = document.createElement('div');
    box.className = 'jump-backdrop';
    box.id = 'help';
    box.hidden = true;
    box.innerHTML = '<div class="jump help" role="dialog" aria-modal="true" aria-labelledby="help-title">' +
      '<div class="add-head"><h2 id="help-title"></h2></div><div class="help-body" id="help-body"></div>' +
      '<div class="help-foot"><a href="' + SITE + '" target="_blank" rel="noopener">Documentation</a>' +
      '<a href="' + SITE + 'TROUBLESHOOTING/" target="_blank" rel="noopener">Troubleshooting</a>' +
      '<a href="https://github.com/issuarr/issuarr/issues" target="_blank" rel="noopener">Report a problem</a>' +
      '<button type="button" class="btn btn-primary" id="help-close">Close</button></div></div>';
    document.body.appendChild(box);
    box.addEventListener('mousedown', function (e) { if (e.target === box) close(); });
    box.querySelector('#help-close').addEventListener('click', close);
    box.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); close(); return; }
      if (e.key !== 'Tab') return;
      var f = box.querySelectorAll('a[href], button');
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }

  function list(lines) { return '<ul>' + lines.map(function (l) { return '<li>' + l + '</li>'; }).join('') + '</ul>'; }

  function open() {
    if (!box) build();
    var h = PAGES[page()];
    box.querySelector('#help-title').textContent = h ? h[0] : 'Help';
    box.querySelector('#help-body').innerHTML = (h ? list(h[1]) : '') +
      '<h3>Anywhere in Issuarr</h3>' + list(GENERAL) +
      '<dl class="help-keys">' + KEYS.map(function (k) { return '<dt><kbd>' + k[0] + '</kbd></dt><dd>' + k[1] + '</dd>'; }).join('') + '</dl>';
    back = document.activeElement;
    box.hidden = false;
    box.querySelector('#help-close').focus();
  }

  function close() {
    if (!box || box.hidden) return;
    box.hidden = true;
    if (back && back.focus) back.focus();
  }

  document.addEventListener('keydown', function (e) {
    if (e.key !== '?' || e.ctrlKey || e.metaKey || e.altKey) return;
    var t = e.target;
    if (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
    if (document.querySelector('.jump-backdrop:not([hidden]):not(#help), .ui-dialog:not([style*="display: none"])')) return;
    e.preventDefault();
    if (box && !box.hidden) close(); else open();
  });
  document.addEventListener('click', function (e) {
    if (e.target.closest('[data-action="help"]')) { e.preventDefault(); open(); }
  });

  window.IssuarrHelp = { open: open, pages: PAGES };
})();
