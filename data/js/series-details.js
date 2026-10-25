/* Details tab of a series page: edit each field in place, including empty ones. */
(function () {
  'use strict';

  var EDITIONS = [['TPB', 'Trade paperback'], ['HC', 'Hardcover'], ['GN', 'Graphic novel'], ['Digital', 'Digital'], ['One-Shot', 'One-Shot'], ['Print', 'Print']];
  var AGE_RATINGS = ['All Ages', '9+', '12+', '15+', '17+', 'Adult'];
  var DESC_CLAMP = 300;

  function toast(msg, ok) { if (window.Issuarr) window.Issuarr.toast(msg, ok); }
  function editionLabel(t) {
    for (var i = 0; i < EDITIONS.length; i++) if (EDITIONS[i][0] === t) return EDITIONS[i][1];
    return t;
  }

  function post(params) {
    return fetch('series_detail_edit', { method: 'POST', credentials: 'same-origin',
                 headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams(params).toString() })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function makeInput(dd, cvType) {
    var kind = dd.dataset.kind, value = dd.dataset.value || '', el;
    if (kind === 'edition' || kind === 'age_rating') {
      el = document.createElement('select');
      var opts = kind === 'edition'
        ? [['', 'As ComicVine lists it (' + editionLabel(cvType) + ')']].concat(EDITIONS.filter(function (e) { return e[0] !== cvType; }))
        : [['', 'Not rated']].concat(AGE_RATINGS.map(function (a) { return [a, a]; }));
      opts.forEach(function (o) {
        var op = document.createElement('option');
        op.value = o[0]; op.textContent = o[1]; op.selected = o[0] === value;
        el.appendChild(op);
      });
    } else if (kind === 'description') {
      el = document.createElement('textarea');
      el.rows = 8;
      el.value = value;
    } else {
      el = document.createElement('input');
      el.type = 'text';
      el.value = value;
      if (kind === 'year') { el.inputMode = 'numeric'; el.maxLength = 4; el.placeholder = 'e.g. 2016'; el.className = 'set-num'; }
      if (kind === 'volume') { el.placeholder = 'e.g. v2'; el.className = 'set-num'; }
    }
    el.classList.add('sf-input');
    var label = document.getElementById('sf-' + dd.dataset.field + '-label');
    if (label) el.setAttribute('aria-label', label.textContent);
    return el;
  }

  // Shown text for a field. The description is cut short with a More button.
  function render(dd, data) {
    var val = dd.querySelector('.sf-val');
    var empty = !data.value;
    var text = empty ? dd.dataset.empty : data.value;
    if (dd.dataset.kind === 'edition') { text = editionLabel(data.value); empty = false; }
    if (dd.dataset.kind === 'description') {
      var more = dd.querySelector('.sf-more');
      var long = !empty && text.length > DESC_CLAMP;
      val.textContent = long ? text.slice(0, DESC_CLAMP).trimEnd() + '…' : text;
      val.dataset.full = text;
      more.hidden = !long;
      more.textContent = 'More';
    } else {
      val.textContent = text;
    }
    val.classList.toggle('is-empty', empty);
  }

  function tagFor(dd) {
    return dd.dataset.kind === 'description' ? dd.closest('.series-description').querySelector('.sf-tag') : dd.querySelector('.sf-tag');
  }
  function editBtnFor(dd) {
    return dd.dataset.kind === 'description' ? dd.closest('.series-description').querySelector('.sf-edit') : dd.querySelector('.sf-edit');
  }

  // Keep the header and the Settings tab in step, so saving settings later doesn't put the old value back.
  function syncPage(field, data) {
    var v = data.value;
    var meta = function (k) { return document.querySelector('[data-meta="' + k + '"]'); };
    var set = function (el, text) { if (el) { el.textContent = text; el.hidden = !text; } };
    var setInput = function (id, val) { var el = document.getElementById(id); if (el) el.value = val; };
    if (field === 'publisher') { set(meta('publisher'), v); set(meta('crumb'), v ? ' / ' + v : ''); }
    if (field === 'imprint') { set(meta('imprint'), v); setInput('ss-imprint', v); }
    if (field === 'year') {
      set(meta('year'), v); setInput('ss-year', v);
      var ty = document.getElementById('tab_comicyear'); if (ty) ty.value = v;
    }
    if (field === 'volume') { set(meta('volume'), v && v.toLowerCase() !== 'v1' ? v : ''); setInput('ss-volume', v); }
    if (field === 'edition') { set(meta('edition'), editionLabel(v)); setInput('ss-type', data.input || ''); }
    if (field === 'age_rating') {
      set(meta('age_rating'), v);
      var age = document.getElementById('ss-age');
      if (age && !v && !age.querySelector('option[value=""]')) {
        // an unselectable "Not set" isn't sent with the form, so saving settings leaves the rating empty
        var none = document.createElement('option');
        none.value = ''; none.textContent = 'Not set'; none.disabled = true; none.hidden = true;
        age.insertBefore(none, age.firstChild);
      }
      if (age) age.value = v;
    }
  }

  function startEdit(dd) {
    if (dd.classList.contains('is-editing')) return;
    var list = dd.closest('[data-comicid]') || document.querySelector('.series-fields');
    var comicid = list.dataset.comicid, cvType = list.dataset.cvtype || 'Print';
    var btn = editBtnFor(dd);
    var input = makeInput(dd, cvType);
    var form = document.createElement('form');
    form.className = 'sf-form';
    form.appendChild(input);
    var save = document.createElement('button');
    save.type = 'submit'; save.className = 'btn btn-sm btn-primary'; save.textContent = 'Save';
    var cancel = document.createElement('button');
    cancel.type = 'button'; cancel.className = 'btn btn-sm'; cancel.textContent = 'Cancel';
    var acts = document.createElement('span');
    acts.className = 'sf-acts';
    acts.appendChild(save); acts.appendChild(cancel);
    form.appendChild(acts);

    dd.classList.add('is-editing');
    btn.hidden = true;
    dd.insertBefore(form, dd.firstChild);

    function close() {
      form.remove();
      dd.classList.remove('is-editing');
      btn.hidden = false;
      btn.focus();
    }
    cancel.addEventListener('click', close);
    form.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); close(); } });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      save.disabled = true;
      post({ ComicID: comicid, field: dd.dataset.field, value: input.value })
        .then(function (d) {
          save.disabled = false;
          if (!d.ok) { toast(d.error || 'That didn\'t save. Check the log.', false); input.focus(); return; }
          dd.dataset.value = dd.dataset.kind === 'edition' ? (d.input || '') : d.value;
          render(dd, d);
          tagFor(dd).hidden = !d.edited;
          syncPage(dd.dataset.field, d);
          close();
          toast(d.note || 'Saved.');
        })
        .catch(function () { save.disabled = false; toast('That didn\'t save. Check the log.', false); });
    });
    input.focus();
    if (input.select && input.tagName !== 'SELECT') input.select();
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.series-details .sf').forEach(function (dd) {
      editBtnFor(dd).addEventListener('click', function () { startEdit(dd); });
      if (dd.dataset.kind === 'description') {
        render(dd, { value: dd.dataset.value });
        dd.querySelector('.sf-more').addEventListener('click', function () {
          var val = dd.querySelector('.sf-val'), open = this.textContent === 'More';
          val.textContent = open ? val.dataset.full : val.dataset.full.slice(0, DESC_CLAMP).trimEnd() + '…';
          this.textContent = open ? 'Less' : 'More';
        });
      }
    });
  });
})();

/* Want from issue…: issues from #N on are Wanted, earlier ones Skipped; a blank number goes back to the usual rules. */
(function () {
  var btn = document.getElementById('want-from-btn');
  if (!btn) return;
  btn.addEventListener('click', function () {
    var current = btn.getAttribute('data-current');
    var answer = prompt('Want issues from which number on? Earlier issues you don\'t have are set to Skipped.' +
                        (current ? ' Leave it blank to go back to your usual settings.' : ''), current || btn.getAttribute('data-latest') || '');
    if (answer === null) return;
    fetch('want_from_set', { method: 'POST', credentials: 'same-origin',
                             headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                             body: new URLSearchParams({ comicid: btn.getAttribute('data-comicid'), number: answer }).toString() })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        Issuarr.toast(d.note, !!d.ok);
        if (d.ok) setTimeout(function () { location.reload(); }, 1200);
      })
      .catch(function () { Issuarr.toast('That didn\'t work. Check the log.', false); });
  });
})();
