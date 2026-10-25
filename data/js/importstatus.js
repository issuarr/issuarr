// Library scan / mass import progress: header indicator on every page, plus the
// panel on Manage > Activity / Jobs and Settings > Information when present.
(function($) {
    var pollTimer = null, logTimer = null;

    function dur(secs) {
        if (secs === null || secs === undefined) return '-';
        secs = Math.max(0, Math.round(secs));
        var h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
        if (h > 0) return h + 'h ' + m + 'm';
        if (m > 0) return m + 'm ' + s + 's';
        return s + 's';
    }
    function ts(epoch) {
        if (!epoch) return '-';
        return new Date(epoch * 1000).toLocaleString();
    }
    function ratio(a, b) {
        if (!b) return a ? String(a) : '-';
        return a + ' / ' + b;
    }
    function esc(t) {
        return $('<div/>').text(t === null || t === undefined ? '' : String(t)).html();
    }

    function progress(d) {
        if (d.phase == 'importing' && d.series_total) return d.series_done / d.series_total;
        if (d.phase == 'metadata' && d.files_total) return d.files_analyzed / d.files_total;
        if (d.phase == 'cv_lookup' && d.issueids_total) return d.issueids_resolved / d.issueids_total;
        if (d.phase == 'saving') return 1;
        return null;
    }

    function indicatorText(d) {
        var rl = d.ratelimit;
        if (rl.active) return 'CV rate limit ' + dur(rl.remaining);
        if (d.mode == 'import') return 'Importing ' + d.series_done + '/' + d.series_total;
        if (d.phase == 'metadata') return 'Scanning ' + d.files_analyzed + '/' + d.files_total;
        if (d.phase == 'cv_lookup') return 'CV lookup ' + d.issueids_resolved + '/' + d.issueids_total;
        if (d.phase == 'stopping') return 'Stopping...';
        return 'Scanning ' + d.files_found + ' files';
    }

    function render(d) {
        var ind = $('#import_indicator');
        if (d.running) {
            ind.find('.ii-text').text(indicatorText(d));
            ind.toggleClass('ii-wait', d.ratelimit.active);
            ind.attr('title', d.phase_label + (d.series_current ? ': ' + d.series_current : ''));
            ind.show();
        } else {
            ind.hide();
        }

        if (!$('#import_panel').length) return;
        var phase = $('#ip_phase');
        phase.removeClass('ip-active ip-waiting ip-error');
        if (d.running) {
            phase.text(d.phase_label).addClass(d.ratelimit.active ? 'ip-waiting' : 'ip-active');
        } else if (d.result) {
            phase.text('Idle - last ' + (d.mode == 'scan' ? 'scan' : 'import') + ' ' + d.result);
            if (d.result == 'error') phase.addClass('ip-error');
        } else {
            phase.text('Idle');
        }
        $('#ip_message').text(d.message || d.legacy_status || '');
        var p = progress(d);
        $('#ip_fill').css('width', (p === null ? (d.running ? 0 : (d.result == 'completed' ? 100 : 0)) : Math.round(p * 100)) + '%');
        $('#ip_started').text(ts(d.started));
        $('#ip_elapsed').text(d.started ? dur(d.elapsed) : '-');
        $('#ip_eta').text(d.eta !== null ? dur(d.eta) : '-');
        $('#ip_files_found').text(d.files_found ? d.files_found + (d.files_unchanged ? ' (' + d.files_unchanged + ' unchanged, left out)' : '') : '-');
        $('#ip_files_parsed').text(d.files_parsed || '-');
        $('#ip_parse_failures').text(d.parse_failures || '-');
        $('#ip_files_analyzed').text(ratio(d.files_analyzed, d.files_total));
        $('#ip_issueids').text(ratio(d.issueids_resolved, d.issueids_total));
        $('#ip_rl_waits').text(d.ratelimit.waits || '-');
        $('#ip_series').text(ratio(d.series_done, d.series_total));
        // Manual = ComicVine had several possible series: they wait on Import results under Needs a choice.
        $('#ip_series_breakdown').html(d.series_total ? (esc(d.series_added) + ' / ' +
            (d.series_manual ? '<a href="importResults#needs-a-choice" title="Choose their ComicVine match on Import results">' + esc(d.series_manual) + '</a>' : '0') +
            ' / ' + esc(d.series_noresults) + ' / ' + esc(d.series_failed)) : '-');
        $('#ip_current').text(d.series_current ? d.series_current + (d.series_started ? ' (for ' + dur(Date.now() / 1000 - d.series_started) + ')' : '') : '-');

        var rl = d.ratelimit;
        if (rl.active) {
            $('#ip_ratelimit').html('ComicVine rate limit hit on the <b>' + esc(rl.resource) + '</b> resource (' + esc(rl.reason) +
                ') - waiting <b>' + dur(rl.remaining) + '</b> before retrying (attempt ' + rl.attempt + '). Nothing is skipped while waiting.').show();
        } else {
            $('#ip_ratelimit').hide();
        }

        var showResume = false;
        if (!d.running && d.pending && d.pending.series > 0) {
            $('#ip_pending').html(esc(d.pending.series) + ' series (' + esc(d.pending.files) + ' files) are waiting to be imported' +
                (d.resume_marker ? ' - an interrupted import will resume automatically.' : '.')).show();
            showResume = true;
        } else {
            $('#ip_pending').hide();
        }
        $('#ip_stop').text(d.mode == 'scan' ? 'Stop scan' : 'Stop import').toggle(d.running && d.phase != 'stopping');
        $('#ip_resume').toggle(showResume);
    }

    function poll() {
        clearTimeout(pollTimer);
        var panel = $('#import_panel').length > 0;
        $.ajax({url: 'import_progress', dataType: 'json', cache: false})
            .done(function(d) {
                render(d);
                pollTimer = setTimeout(poll, d.running ? 3000 : (panel ? 10000 : 30000));
            })
            .fail(function() { pollTimer = setTimeout(poll, 30000); });
    }

    function pollLog() {
        clearTimeout(logTimer);
        var log = $('#ip_log');
        if (!log.length) return;
        if (!log.is(':visible')) { logTimer = setTimeout(pollLog, 5000); return; }
        $.ajax({url: 'import_logtail', dataType: 'json', cache: false,
                data: {lines: $('#ip_log_lines').val(), filter: $('#ip_log_filter').is(':checked') ? 'import' : 'all'}})
            .done(function(d) {
                var atBottom = log[0].scrollHeight - log.scrollTop() - log.outerHeight() < 30;
                log.text(d.lines && d.lines.length ? d.lines.join('\n') : (d.message || 'No matching log lines.'));
                if ($('#ip_log_follow').is(':checked') || atBottom) log.scrollTop(log[0].scrollHeight);
            })
            .always(function() { logTimer = setTimeout(pollLog, 5000); });
    }

    function action(url, btn) {
        $(btn).prop('disabled', true);
        $.ajax({url: url, dataType: 'json', cache: false})
            .done(function(d) {
                var msg = $('#ajaxMsg');
                msg.html("<div class='msg'><span class='ui-icon ui-icon-check'></span>" + esc(d.message) + "</div>");
                msg.addClass(d.status == 'success' ? 'success' : 'error').fadeIn().delay(3000).fadeOut(function() { msg.removeClass('success error'); });
            })
            .always(function() { $(btn).prop('disabled', false); poll(); });
    }

    $(document).ready(function() {
        $('#ip_stop').on('click', function() {
            var btn = this;
            Issuarr.ask('Stop the running ' + ($(this).text().indexOf('scan') > -1 ? 'library scan' : 'import') + '? An import stops after the current series; pending series can be resumed later.', { ok: 'Stop', danger: true }, function () {
                action('import_stop', btn);
            });
        });
        $('#ip_resume').on('click', function() {
            var btn = this;
            Issuarr.ask('Resume importing all pending (Not Imported) series?', { ok: 'Resume' }, function () { action('import_resume', btn); });
        });
        $('#ip_log_filter, #ip_log_lines').on('change', pollLog);
        if (window.importStatusInitial) {
            try { render(window.importStatusInitial); } catch (e) {}
        }
        poll();
        pollLog();
    });
})(jQuery);
