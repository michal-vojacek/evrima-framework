'use strict';

/* Evrima admin: all page behaviour. The Content-Security-Policy forbids inline
 * scripts and inline event handlers, so every behaviour hangs off data-*
 * attributes and lives here. Taken over from an earlier admin design of the
 * author and trimmed to what the admin needs.
 *
 *  1) data-confirm on <form>: a confirmation <dialog> instead of window.confirm()
 *  2) data-autosubmit on <select>: changing the value submits the form
 *  3) data-dropdown: the user menu
 *  4) DataTables: table.js-datatable (data in the HTML) and table[data-source]
 *     (data from the server over POST, optionally paged and refreshed)
 *  5) data-copy: copies text to the clipboard
 *  6) data-height: bar heights of CSS charts
 *  7) data-tip: tooltip on hover and focus
 *  8) time.dt: dates and times in the browser's time zone and language
 *  9) data-modal: forms in dialogs, re-opened after a rejected submit
 * 10) data-slug-from: URL slug filled from a title
 * 11) data-check: live field validation over POST
 * 12) data-tag-picker: tag chips with suggestions
 * 13) data-rows: repeatable form rows
 * 14) data-kind-switch: field groups shown according to a select
 * 15) data-upload: drop zone, checks and background upload with progress
 * 16) data-sortable: reordering by drag or move buttons
 * 17) busy state of submitted POST forms (no double submits)
 * 18) data-counter: characters used of maxlength
 * 19) data-demo: sample links on /admin/design that do not navigate
 * 20) data-nav-toggle: the menu button of the sidebar on phones
 * 21) data-editor: the minimal rich-text editor
 *
 * Texts: the page hands its texts over in <body data-i18n="{...}"> in the
 * user's language (evrima.i18n, keys under admin.js.*), so this file contains
 * no user-facing strings. Values from the server are always rendered as text
 * (escaped); only the RENDER functions below build HTML.
 */

(function () {

  // === Texts and language ====================================================
  var TEXTS = {};
  var LANG = document.documentElement.lang || 'cs';

  function loadTexts() {
    try { TEXTS = JSON.parse(document.body.dataset.i18n || '{}'); } catch (e) { TEXTS = {}; }
  }

  // t('copied') or t('remove', {name: 'x'}): a missing key shows the key itself,
  // which is easier to spot and fix than an empty label.
  function t(key, params) {
    var text = TEXTS[key] !== undefined ? TEXTS[key] : key;
    if (params) {
      Object.keys(params).forEach(function (name) {
        text = text.split('{' + name + '}').join(String(params[name]));
      });
    }
    return text;
  }

  // Submit buttons of a form, including those outside it tied with form="…"
  // (a delete button in a list row cannot sit in a form nested in another).
  function submitButtons(form) {
    return Array.prototype.filter.call(form.elements, function (el) {
      return el.tagName === 'BUTTON' && (el.type || 'submit') === 'submit';
    });
  }

  // === 1) data-confirm =========================================================
  var confirmDialog = null;
  var confirmParts = null;

  function buildConfirmDialog() {
    if (confirmDialog) return confirmDialog;
    var dlg = document.createElement('dialog');
    dlg.className = 'modal';
    dlg.setAttribute('aria-labelledby', 'confirm-title');
    var box = document.createElement('div');
    box.className = 'modal__box';
    var title = document.createElement('h2');
    title.className = 'modal__title';
    title.id = 'confirm-title';
    var body = document.createElement('p');
    body.className = 'modal__body';
    var actions = document.createElement('div');
    actions.className = 'modal__actions';
    var cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'btn btn--ghost';
    var ok = document.createElement('button');
    ok.type = 'button';
    actions.appendChild(cancel);
    actions.appendChild(ok);
    box.appendChild(title);
    box.appendChild(body);
    box.appendChild(actions);
    dlg.appendChild(box);
    document.body.appendChild(dlg);
    confirmDialog = dlg;
    confirmParts = { title: title, body: body, ok: ok, cancel: cancel };
    return dlg;
  }

  function askConfirm(form) {
    var dlg = buildConfirmDialog();
    var d = form.dataset;
    confirmParts.title.textContent = d.confirmTitle || t('confirm_title');
    confirmParts.body.textContent = d.confirm;
    confirmParts.ok.textContent = d.confirmOk || t('confirm_ok');
    confirmParts.cancel.textContent = t('cancel');
    // A destructive form (red submit button) gets a red confirm button too.
    // form.elements includes buttons outside the form tied to it with form="…".
    var submitBtn = submitButtons(form)[0];
    var danger = submitBtn && submitBtn.classList.contains('btn--danger');
    confirmParts.ok.className = 'btn ' + (danger ? 'btn--danger' : 'btn--primary');
    function cleanup() { confirmParts.ok.onclick = null; confirmParts.cancel.onclick = null; }
    confirmParts.cancel.onclick = function () { cleanup(); dlg.close(); };
    confirmParts.ok.onclick = function () {
      cleanup();
      dlg.close();
      form.dataset.confirmed = '1';
      if (form.requestSubmit) { form.requestSubmit(submitBtn || undefined); } else { form.submit(); }
    };
    dlg.showModal();
    // Focus starts on Cancel, so a stray Enter never confirms a destructive action.
    confirmParts.cancel.focus();
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    var msg = form && form.dataset && form.dataset.confirm;
    if (!msg) return;
    if (form.dataset.confirmed === '1') { delete form.dataset.confirmed; return; }
    e.preventDefault();
    e.stopPropagation();
    if (typeof HTMLDialogElement === 'undefined') {
      if (window.confirm(msg)) { form.dataset.confirmed = '1'; form.submit(); }
      return;
    }
    askConfirm(form);
  }, true);

  // === 2) data-autosubmit ======================================================
  document.addEventListener('change', function (e) {
    var el = e.target;
    if (!el || !el.dataset || el.dataset.autosubmit === undefined || !el.form) return;
    if (el.form.requestSubmit) { el.form.requestSubmit(); } else { el.form.submit(); }
  });

  // === 3) Dropdown menu ========================================================
  function setupDropdowns() {
    var dropdowns = document.querySelectorAll('[data-dropdown]');
    function closeAll(except) {
      dropdowns.forEach(function (dd) {
        if (dd === except) return;
        var panel = dd.querySelector('.user-menu__panel');
        var trigger = dd.querySelector('.user-menu__trigger');
        if (panel) panel.hidden = true;
        if (trigger) trigger.setAttribute('aria-expanded', 'false');
      });
    }
    dropdowns.forEach(function (dd) {
      var trigger = dd.querySelector('.user-menu__trigger');
      var panel = dd.querySelector('.user-menu__panel');
      if (!trigger || !panel) return;
      trigger.addEventListener('click', function (e) {
        e.stopPropagation();
        var isOpen = !panel.hidden;
        closeAll(dd);
        panel.hidden = isOpen;
        trigger.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
      });
    });
    document.addEventListener('click', function (e) {
      dropdowns.forEach(function (dd) { if (!dd.contains(e.target)) closeAll(null); });
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeAll(null); });
  }

  // === 4) DataTables ===========================================================
  // Only the table scrolls sideways (.dt-scroll); the search box, the page
  // length and the paging stay in place on a narrow screen.
  var DOM = "<'dt-toolbar'lf>r<'dt-scroll't><'dt-footer'ip>";

  function dataTablesLanguage() {
    return {
      search: '', searchPlaceholder: t('dt.search'),
      lengthMenu: t('dt.length_menu'),
      info: t('dt.info'),
      infoEmpty: t('dt.info_empty'),
      infoFiltered: t('dt.info_filtered'),
      paginate: { first: '«', last: '»', next: '›', previous: '‹' },
      zeroRecords: t('dt.zero_records'),
      emptyTable: t('dt.empty_table'),
      processing: t('loading'),
      loadingRecords: t('loading'),
      thousands: LANG === 'cs' ? ' ' : ','
    };
  }

  function esc(v) {
    if (v === null || v === undefined) return '';
    return String(v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function num(v) {
    if (v === null || v === undefined || v === '') return '';
    var n = Number(v);
    return isNaN(n) ? esc(v) : n.toLocaleString(LANG);
  }

  // Renderers chosen by data-render on <th>. Input: values from the server;
  // output: HTML in which every value has gone through esc().
  var RENDER = {
    text: function (v) { return esc(v); },
    mono: function (v) { return '<span class="mono">' + esc(v) + '</span>'; },
    num: function (v) { return num(v); },
    // {label, tone: ok|warn|bad|none}
    state: function (v) {
      if (!v) return '';
      return '<span class="dot dot--lg dot--' + esc(v.tone || 'none') + '" role="img" aria-label="' + esc(v.label) + '" data-tip="' + esc(v.label) + '"></span>';
    },
    // {label, cls}: .status pill
    status: function (v) {
      if (!v) return '';
      return '<span class="status status--' + esc(v.cls || 'na') + '">' + esc(v.label) + '</span>';
    },
    badges: function (v) {
      return (v || []).map(function (b) { return '<span class="badge">' + esc(b) + '</span>'; }).join(' ');
    },
    // {href, label}
    link: function (v) {
      if (!v) return '';
      return '<a href="' + esc(v.href) + '">' + esc(v.label) + '</a>';
    },
    // [{href, label, cls}]: buttons in the last column
    actions: function (v) {
      return (v || []).map(function (a) {
        return '<a class="btn btn--' + esc(a.cls || 'ghost') + ' btn--small" href="' + esc(a.href) + '">' + esc(a.label) + '</a>';
      }).join(' ');
    },
    dt: function (v) {
      if (!v) return '';
      return '<time class="dt" datetime="' + esc(v) + '" title="' + esc(utcTitle(v)) + '">' + esc(formatDT(v)) + '</time>';
    },
    tags: function (v) {
      if (!v || !v.length) return '';
      return '<span class="tags">' + v.map(pillHTML).join('') + '</span>';
    }
  };

  function columnsOf(table) {
    var cols = [];
    table.querySelectorAll('thead th').forEach(function (th) {
      var render = RENDER[th.dataset.render || 'text'];
      cols.push({
        data: th.dataset.key || null,
        orderable: th.dataset.orderable !== 'false',
        className: th.className || '',
        defaultContent: '',
        render: function (v, type, row) {
          // Objects sort by their "sort" value (or label) and filter by label,
          // so a status pill sorts by meaning, not by its HTML.
          if (type === 'sort' || type === 'type') {
            if (v && typeof v === 'object' && !Array.isArray(v)) return v.sort !== undefined ? v.sort : v.label;
            return v;
          }
          if (type === 'filter') {
            if (v && typeof v === 'object' && !Array.isArray(v)) return v.label;
            return Array.isArray(v) ? v.join(' ') : v;
          }
          return render(v, row);
        }
      });
    });
    return cols;
  }

  function csrfToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute('content') : '';
  }

  function setLive(indicator, state, text) {
    if (!indicator) return;
    indicator.classList.remove('live--stale', 'live--error');
    if (state) indicator.classList.add('live--' + state);
    var label = indicator.querySelector('.live__text');
    if (label) label.textContent = text;
  }

  // Server data: POST with the CSRF token in a header, never query parameters
  // in the URL (they end up in logs and browser history).
  function initServerTable(t) {
    var $ = jQuery;
    // Own attribute names must not collide with DataTables options: DataTables
    // reads data-* of the table (data-server-side, data-order) and would
    // override the options given here.
    var serverSide = t.dataset.paged !== undefined;
    var indicator = t.dataset.live ? document.getElementById(t.dataset.live) : null;
    var extra = t.dataset.form ? document.getElementById(t.dataset.form) : null;
    var errorBox = t.dataset.error ? document.getElementById(t.dataset.error) : null;
    // data-wait-form: until the filter form is submitted, the table asks for nothing.
    var waitForm = t.dataset.waitForm !== undefined;
    var empty = function (draw) { return { draw: draw, recordsTotal: 0, recordsFiltered: 0, data: [] }; };

    function payload(d) {
      if (extra) {
        new FormData(extra).forEach(function (value, key) { if (key !== 'csrf_token') d[key] = value; });
      }
      return JSON.stringify(d);
    }
    function received(json) {
      setLive(indicator, null, t('live.updated', { time: new Date().toLocaleTimeString(LANG) }));
      // The server sends "message", not "error": DataTables would show an
      // "error" key in a browser alert.
      if (errorBox) { errorBox.textContent = json.message || ''; errorBox.hidden = !json.message; }
      if (json.meta) $(t).trigger('meta.evrima', [json.meta]);
      return json.data;
    }

    var dt = $(t).DataTable({
      dom: DOM, language: dataTablesLanguage(), autoWidth: false,
      processing: serverSide, serverSide: serverSide, deferRender: true,
      pageLength: Number(t.dataset.pageLength || 25),
      lengthMenu: [10, 25, 50, 100],
      order: t.dataset.initialOrder ? JSON.parse(t.dataset.initialOrder) : [],
      searching: t.dataset.searching !== 'false',
      columns: columnsOf(t),
      ajax: function (data, callback) {
        if (waitForm && !t.dataset.armed) { callback(empty(data.draw)); return; }
        $.ajax({
          url: t.dataset.source, type: 'POST', contentType: 'application/json',
          headers: { 'X-CSRFToken': csrfToken() }, data: payload(data), dataType: 'json',
          success: function (json) { json.data = received(json); callback(json); },
          error: function () { setLive(indicator, 'error', t('live.failed')); callback(empty(data.draw)); }
        });
      }
    });
    t._dt = dt;

    if (extra) {
      extra.addEventListener('submit', function (e) {
        e.preventDefault();
        if (extra.reportValidity && !extra.reportValidity()) return;
        t.dataset.armed = '1';
        dt.ajax.reload();
      });
    }
    var every = Number(t.dataset.refresh || 0);
    if (every > 0) {
      window.setInterval(function () {
        // A background tab does not poll: no load on the server for nobody.
        if (document.hidden) { setLive(indicator, 'stale', t('live.paused')); return; }
        dt.ajax.reload(null, false);
      }, every * 1000);
    }
  }

  function setupTables() {
    if (!window.jQuery || !jQuery.fn.dataTable) return;
    var $ = jQuery;
    // Errors are shown by the page itself (data-error, .live), never in a browser alert.
    $.fn.dataTable.ext.errMode = 'none';

    $('table.js-datatable').each(function () {
      var table = this;
      $(table).DataTable({
        dom: DOM, language: dataTablesLanguage(),
        pageLength: Number(table.dataset.pageLength || 25),
        order: table.dataset.initialOrder ? JSON.parse(table.dataset.initialOrder) : [],
        lengthMenu: [10, 25, 50, 100],
        autoWidth: false
      });
    });

    $('table[data-source]').each(function () { initServerTable(this); });
  }

  // === 5) data-copy ============================================================
  document.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('[data-copy]') : null;
    if (!btn || !navigator.clipboard) return;
    navigator.clipboard.writeText(btn.dataset.copy).then(function () {
      var old = btn.textContent;
      btn.textContent = t('copied');
      window.setTimeout(function () { btn.textContent = old; }, 1500);
    });
  });

  // === 6) Bar heights (data-height in percent) =================================
  // Set through the CSSOM: allowed by the CSP, unlike a style="" attribute.
  function setupBars() {
    document.querySelectorAll('[data-height]').forEach(function (el) {
      el.style.height = Math.max(0, Math.min(100, Number(el.dataset.height) || 0)) + '%';
    });
  }

  // === 7) Tooltips: [data-tip] =================================================
  function setupTips() {
    var tip = document.createElement('div');
    tip.className = 'tip';
    tip.setAttribute('role', 'tooltip');
    tip.hidden = true;
    document.body.appendChild(tip);
    var current = null;
    function show(target) {
      current = target;
      tip.textContent = target.dataset.tip;
      tip.hidden = false;
      var r = target.getBoundingClientRect();
      var w = tip.offsetWidth, h = tip.offsetHeight;
      var left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
      var top = r.top - h - 8;
      // No room above: show it below the element instead.
      tip.classList.toggle('tip--below', top < 8);
      if (top < 8) top = r.bottom + 8;
      tip.style.left = left + 'px';
      tip.style.top = top + 'px';
    }
    function hide() { current = null; tip.hidden = true; }
    document.addEventListener('mouseover', function (e) {
      var target = e.target.closest ? e.target.closest('[data-tip]') : null;
      if (target && target !== current) show(target); else if (!target && current) hide();
    });
    document.addEventListener('focusin', function (e) {
      var target = e.target.closest ? e.target.closest('[data-tip]') : null;
      if (target) show(target); else hide();
    });
    window.addEventListener('scroll', hide, true);
  }

  // === 8) Dates and times in the browser's time zone ===========================
  // The server sends UTC (ISO 8601); people read local time in their language.
  function formatDT(value) {
    if (!value) return '';
    var d = value instanceof Date ? value : new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleString(LANG, { dateStyle: 'short', timeStyle: 'short' });
  }
  function utcTitle(value) {
    var d = new Date(value);
    return isNaN(d.getTime()) ? '' : 'UTC ' + d.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, '');
  }
  function localizeTimes(root) {
    (root || document).querySelectorAll('time.dt[datetime]').forEach(function (el) {
      el.textContent = formatDT(el.getAttribute('datetime'));
      el.title = utcTitle(el.getAttribute('datetime'));
    });
  }

  // <input type="datetime-local" data-utc-for="start"> shows local time; the
  // hidden field name="start" carries UTC in ISO form, which the server reads.
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function toLocalInput(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + 'T' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }
  function setupDateTimeInputs(root) {
    (root || document).querySelectorAll('input[data-utc-for]').forEach(function (input) {
      var hidden = input.form ? input.form.querySelector('input[type=hidden][name="' + input.dataset.utcFor + '"]') : null;
      if (!hidden) return;
      function fromHidden() { input.value = hidden.value ? toLocalInput(hidden.value) : ''; }
      function toHidden() {
        var d = input.value ? new Date(input.value) : null;
        hidden.value = d && !isNaN(d.getTime()) ? d.toISOString().replace(/\.\d{3}Z$/, 'Z') : '';
      }
      fromHidden();
      input.addEventListener('change', toHidden);
      input.addEventListener('input', toHidden);
      hidden.addEventListener('change', fromHidden);
      if (input.form) input.form.addEventListener('reset', function () { window.setTimeout(fromHidden, 0); });
    });
  }

  // === 9) Forms in dialogs =====================================================
  // [data-modal="id"] opens <dialog id>, optionally with data-fill (JSON of
  // field values) and data-modal-title. A dialog with data-autoopen (a rejected
  // form, see evrima/admin/modal.py) opens on page load.
  function fillForm(dlg, values) {
    var form = dlg.querySelector('form');
    if (!form) return;
    Object.keys(values).forEach(function (name) {
      var value = values[name];
      // Composite widgets (tag picker) take their value through a "fill" event.
      var widget = form.querySelector('[data-field="' + name + '"]');
      if (widget) { widget.dispatchEvent(new CustomEvent('fill', { detail: value })); return; }
      form.querySelectorAll('[name="' + name + '"]').forEach(function (el) {
        if (el.type === 'radio') { el.checked = el.value === String(value); }
        else if (el.type === 'checkbox') { el.checked = Array.isArray(value) ? value.indexOf(el.value) >= 0 : !!value; }
        else { el.value = value === null || value === undefined ? '' : value; }
        el.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });
  }

  function openModal(dlg, trigger) {
    if (!dlg || typeof dlg.showModal !== 'function') return;
    var form = dlg.querySelector('form');
    if (trigger && trigger.dataset.fill !== undefined && form) {
      form.reset();
      fillForm(dlg, JSON.parse(trigger.dataset.fill || '{}'));
    }
    var titleEl = dlg.querySelector('[data-modal-title]');
    if (titleEl) {
      if (!titleEl.dataset.original) titleEl.dataset.original = titleEl.textContent;
      titleEl.textContent = (trigger && trigger.dataset.modalTitle) || titleEl.dataset.original;
    }
    dlg.showModal();
    // After a rejected submit, focus the invalid field; otherwise the first one.
    var first = dlg.querySelector('.modal__error') ? dlg.querySelector('.is-invalid, input:not([type=hidden]), textarea, select')
      : dlg.querySelector('[autofocus], input:not([type=hidden]):not([readonly]), textarea, select');
    if (first) first.focus();
    dlg.dispatchEvent(new CustomEvent('modal:open'));
  }

  document.addEventListener('click', function (e) {
    var opener = e.target.closest ? e.target.closest('[data-modal]') : null;
    if (opener) { e.preventDefault(); openModal(document.getElementById(opener.dataset.modal), opener); return; }
    var closer = e.target.closest ? e.target.closest('[data-modal-close]') : null;
    if (closer) {
      var dlg = closer.closest('dialog');
      if (dlg) dlg.close();
    }
  });

  function setupModals() {
    document.querySelectorAll('dialog[data-autoopen]').forEach(function (dlg) { openModal(dlg, null); });
  }

  // === 10) Slug from a title: "Nová zakázka" -> nova-zakazka ====================
  function slugify(text) {
    return String(text).normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 63).replace(/-+$/, '');
  }

  function setupSlugs() {
    document.querySelectorAll('input[data-slug-from]').forEach(function (target) {
      var source = document.getElementById(target.dataset.slugFrom);
      if (!source) return;
      // The slug follows the title until the user edits it by hand, or it is locked.
      var follow = function () { return target.dataset.slugManual !== '1' && target.dataset.slugLocked !== '1'; };
      source.addEventListener('input', function () {
        if (!follow()) return;
        target.value = slugify(source.value);
        target.dispatchEvent(new Event('input', { bubbles: true }));
      });
      target.addEventListener('input', function (e) {
        if (e.isTrusted) target.dataset.slugManual = target.value ? '1' : '';
      });
      if (target.form) target.form.addEventListener('reset', function () { target.dataset.slugManual = ''; });
    });
  }

  // === 11) Live field validation over POST =====================================
  // <form data-check-url="…"> with <input data-check="field">: the server answers
  // {ok, message}. The check only helps; saving the form decides.
  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
      body: JSON.stringify(body)
    }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function feedbackOf(input) {
    var field = input.closest('.field');
    var fb = field ? field.querySelector('.field__feedback') : null;
    if (!fb && field) { fb = document.createElement('p'); fb.className = 'field__feedback'; input.insertAdjacentElement('afterend', fb); }
    return fb;
  }

  function showCheck(input, res) {
    var fb = feedbackOf(input);
    input.classList.toggle('is-invalid', !res.ok);
    input.classList.toggle('is-valid', !!res.ok && input.value !== '');
    if (fb) {
      fb.textContent = res.message || '';
      fb.className = 'field__feedback ' + (res.ok ? 'field__feedback--note' : 'field__feedback--bad');
    }
  }

  function setupChecks() {
    document.querySelectorAll('input[data-check]').forEach(function (input) {
      var form = input.form;
      if (!form || !form.dataset.checkUrl) return;
      var timer = null;
      var seq = 0;
      function run() {
        var value = input.value.trim();
        if (!value) { showCheck(input, { ok: true, message: '' }); input.classList.remove('is-valid'); return; }
        // Only the newest answer counts; a slow older one must not overwrite it.
        var mine = ++seq;
        postJSON(form.dataset.checkUrl, {
          field: input.dataset.check, value: value, original_id: form.dataset.originalId || ''
        }).then(function (res) { if (mine === seq) showCheck(input, res); })
          .catch(function () { /* the check is only a help; saving decides */ });
      }
      input.addEventListener('input', function () { window.clearTimeout(timer); timer = window.setTimeout(run, 300); });
      input.addEventListener('blur', run);
      form.addEventListener('reset', function () {
        input.classList.remove('is-invalid', 'is-valid');
        var fb = feedbackOf(input); if (fb) fb.textContent = '';
      });
    });
    document.addEventListener('submit', function (e) {
      var bad = e.target.querySelector && e.target.querySelector('input[data-check].is-invalid');
      if (bad) { e.preventDefault(); e.stopPropagation(); bad.focus(); }
    }, true);
  }

  // === 12) Tag picker ===========================================================
  function pillHTML(tag) {
    return '<span class="tag tag--' + esc(tag.color || 'slate') + '"><i class="fa-solid fa-' + esc(tag.icon || 'tag') + '"></i>' + esc(tag.name) + '</span>';
  }

  function setupTagPickers() {
    document.querySelectorAll('[data-tag-picker]').forEach(function (box) {
      var name = box.dataset.name;
      var options = JSON.parse(box.dataset.options || '[]');
      var initial = JSON.parse(box.dataset.selected || '[]');
      var input = box.querySelector('.tag-picker__input');
      var menu = document.createElement('ul');
      menu.className = 'tag-picker__menu';
      menu.hidden = true;
      box.appendChild(menu);
      var selected = [];
      var active = 0;

      function styleOf(n) {
        for (var i = 0; i < options.length; i++) if (options[i].name === n) return options[i];
        return { name: n, color: 'slate', icon: 'tag' };
      }
      // Each chosen tag is a pill plus a hidden input, so the form submits a
      // repeated field without any script on the server side.
      function render() {
        box.querySelectorAll('.tag, input[type=hidden]').forEach(function (el) { el.remove(); });
        selected.forEach(function (n) {
          var holder = document.createElement('span');
          holder.innerHTML = pillHTML(styleOf(n));
          var pill = holder.firstChild;
          var rm = document.createElement('button');
          rm.type = 'button'; rm.className = 'tag-picker__remove'; rm.setAttribute('aria-label', t('tags.remove', { name: n }));
          rm.textContent = '×';
          rm.addEventListener('click', function (e) { e.stopPropagation(); remove(n); });
          pill.appendChild(rm);
          box.insertBefore(pill, input);
          var hidden = document.createElement('input');
          hidden.type = 'hidden'; hidden.name = name; hidden.value = n;
          box.appendChild(hidden);
        });
      }
      function add(n) {
        n = n.replace(/\s+/g, ' ').trim().replace(/,/g, '');
        if (!n || selected.indexOf(n) >= 0) return;
        selected.push(n.slice(0, 40));
        input.value = '';
        render(); refresh();
      }
      function remove(n) { selected = selected.filter(function (x) { return x !== n; }); render(); refresh(); }
      function items() {
        var q = input.value.trim().toLowerCase();
        var list = options.filter(function (o) { return selected.indexOf(o.name) < 0 && o.name.toLowerCase().indexOf(q) >= 0; })
          .map(function (o) { return { name: o.name, opt: o }; });
        var exact = options.some(function (o) { return o.name.toLowerCase() === q; }) || selected.some(function (s) { return s.toLowerCase() === q; });
        if (q && !exact) list.push({ name: input.value.trim(), isNew: true });
        return list;
      }
      function refresh() {
        if (document.activeElement !== input) { menu.hidden = true; return; }
        var list = items();
        active = Math.min(active, Math.max(0, list.length - 1));
        menu.innerHTML = '';
        if (!list.length) {
          var li = document.createElement('li');
          li.className = 'tag-picker__empty';
          li.textContent = options.length ? t('tags.all_selected') : t('tags.type_new');
          menu.appendChild(li);
        }
        list.forEach(function (it, i) {
          var item = document.createElement('li');
          item.className = 'tag-picker__option' + (it.isNew ? ' tag-picker__option--new' : '') + (i === active ? ' is-active' : '');
          item.innerHTML = it.isNew ? '<i class="fa-solid fa-plus"></i> ' + esc(t('tags.new', { name: it.name })) : pillHTML(it.opt);
          item.addEventListener('mousedown', function (e) { e.preventDefault(); add(it.name); });
          menu.appendChild(item);
        });
        menu.hidden = false;
      }
      input.addEventListener('focus', refresh);
      input.addEventListener('blur', function () { menu.hidden = true; });
      input.addEventListener('input', function () { active = 0; refresh(); });
      input.addEventListener('keydown', function (e) {
        var list = items();
        if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, list.length - 1); refresh(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); refresh(); }
        else if (e.key === 'Enter' || e.key === ',') {
          if (list.length || input.value.trim()) { e.preventDefault(); add(list.length ? list[active].name : input.value); }
        } else if (e.key === 'Backspace' && !input.value && selected.length) { remove(selected[selected.length - 1]); }
        else if (e.key === 'Escape' && !menu.hidden) { e.preventDefault(); e.stopPropagation(); menu.hidden = true; }
      });
      box.addEventListener('click', function () { input.focus(); });
      box.addEventListener('fill', function (e) { selected = (e.detail || []).slice(); render(); });
      if (input.form) input.form.addEventListener('reset', function () { selected = initial.slice(); render(); });
      selected = initial.slice();
      render();
    });
  }

  // === 13) Repeatable form rows ([data-rows] + <template data-row-template>) ====
  function setupRows() {
    document.querySelectorAll('[data-rows]').forEach(function (box) {
      var body = box.querySelector('[data-rows-body]');
      var tpl = box.querySelector('template[data-row-template]');
      var addBtn = box.querySelector('[data-row-add]');
      if (!body || !tpl || !addBtn) return;
      var initial = body.innerHTML;
      addBtn.addEventListener('click', function () {
        body.appendChild(tpl.content.cloneNode(true));
        var rows = body.querySelectorAll('[data-row]');
        var last = rows[rows.length - 1];
        var field = last ? last.querySelector('input, select, textarea') : null;
        if (field) field.focus();
      });
      body.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-row-remove]');
        if (btn) btn.closest('[data-row]').remove();
      });
      var form = box.closest('form');
      if (form) form.addEventListener('reset', function () { body.innerHTML = initial; });
    });
  }

  // === 14) Field groups by type: select[data-kind-switch] + [data-kinds] =======
  // Hidden groups have their fields disabled: they are not submitted and their
  // "required" does not block the form.
  function setupKindSwitches() {
    document.querySelectorAll('select[data-kind-switch]').forEach(function (select) {
      var form = select.form;
      if (!form) return;
      function apply() {
        form.querySelectorAll('[data-kinds]').forEach(function (group) {
          var on = group.dataset.kinds.split(/\s+/).indexOf(select.value) >= 0;
          group.hidden = !on;
          group.querySelectorAll('input, select, textarea').forEach(function (el) { el.disabled = !on; });
        });
      }
      select.addEventListener('change', apply);
      form.addEventListener('reset', function () { window.setTimeout(apply, 0); });
      apply();
    });
  }

  // === 15) File uploads: [data-upload] ==========================================
  // A drop zone around a native <input type="file">. Two modes:
  //
  // - data-upload-url (the usual one): each chosen file is uploaded at once
  //   in the background with its own progress bar; the form then submits only
  //   hidden inputs with the ids the server returned. Already stored files
  //   come in data-files (JSON) and are shown the same way.
  // - without it: files stay in the input and go with the form.
  //
  // In both modes a wrong type or a file over data-max-size is marked and
  // never sent. The server checks everything again (evrima/media).
  // Uploads wait in one queue for the whole page, two at a time: each image
  // keeps a server worker busy while it is processed, so thirty dropped photos
  // must not occupy every worker and stall the public website meanwhile.
  var MAX_PARALLEL_UPLOADS = 2;
  var uploadQueue = [];
  var uploadsRunning = 0;
  function pumpUploads() {
    while (uploadsRunning < MAX_PARALLEL_UPLOADS && uploadQueue.length) {
      var start = uploadQueue.shift();
      uploadsRunning++;
      start(function () { uploadsRunning--; pumpUploads(); });
    }
  }

  function formatBytes(bytes) {
    var units = ['B', 'KB', 'MB', 'GB'];
    var i = 0;
    while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
    return bytes.toLocaleString(LANG, { maximumFractionDigits: i ? 1 : 0 }) + ' ' + units[i];
  }

  function setupUploads() {
    document.querySelectorAll('[data-upload]').forEach(function (box) {
      var input = box.querySelector('input[type=file]');
      var zone = box.querySelector('.upload__zone');
      var list = box.querySelector('.upload__list');
      if (!input || !zone || !list) return;
      var uploadUrl = box.dataset.uploadUrl || '';
      var fieldName = box.dataset.name || input.name;
      var maxSize = Number(box.dataset.maxSize || 0);
      var accept = (input.accept || '').split(',').map(function (a) { return a.trim().toLowerCase(); }).filter(Boolean);
      var items = [];      // {file?, stored?, problem, state: 'local'|'queued'|'uploading'|'done'|'failed', li, ...}
      // In background mode the raw files must not travel with the form again.
      if (uploadUrl) input.removeAttribute('name');

      function allowed(file) {
        if (!accept.length) return true;
        var type = (file.type || '').toLowerCase();
        var name = file.name.toLowerCase();
        return accept.some(function (a) {
          if (a.charAt(0) === '.') return name.slice(-a.length) === a;
          if (a.slice(-2) === '/*') return type.indexOf(a.slice(0, -1)) === 0;
          return type === a;
        });
      }
      function problemOf(file) {
        if (!allowed(file)) return t('upload.wrong_type');
        if (maxSize && file.size > maxSize) return t('upload.too_big', { max: formatBytes(maxSize) });
        return '';
      }
      // Without an upload URL the input itself carries the files: rebuild its
      // FileList from the ones that passed the checks.
      function syncInput() {
        if (uploadUrl || typeof DataTransfer === 'undefined') return;
        var transfer = new DataTransfer();
        items.forEach(function (it) { if (it.file && !it.problem) transfer.items.add(it.file); });
        input.files = transfer.files;
      }
      function pending() {
        return items.some(function (it) { return it.state === 'queued' || it.state === 'uploading'; });
      }
      box.uploadPending = pending;

      function renderItem(it) {
        var li = it.li || document.createElement('li');
        it.li = li;
        li.innerHTML = '';
        var busy = it.state === 'queued' || it.state === 'uploading';
        li.className = 'upload__item' + (it.problem ? ' is-invalid' : '') + (busy ? ' is-uploading' : '');
        var thumb = document.createElement('span');
        thumb.className = 'upload__thumb';
        var src = it.stored && it.stored.preview ? it.stored.preview : it.blobUrl;
        if (!it.problem && src) {
          var img = document.createElement('img');
          img.src = src;
          img.alt = '';
          thumb.appendChild(img);
        } else {
          var isPdf = (it.stored && it.stored.kind === 'document') || (it.file && /pdf$/i.test(it.file.name));
          thumb.innerHTML = '<i class="fa-solid ' + (it.problem ? 'fa-circle-exclamation' : isPdf ? 'fa-file-pdf' : 'fa-file') + '"></i>';
        }
        var text = document.createElement('span');
        text.className = 'upload__text';
        var name = document.createElement('strong');
        name.textContent = it.stored ? it.stored.name : it.file.name;
        var meta = document.createElement('span');
        meta.className = 'upload__meta';
        var size = it.stored ? it.stored.size : it.file.size;
        meta.textContent = it.problem || (it.state === 'queued' ? t('upload.queued')
          : it.state === 'uploading' ? t('upload.uploading', { percent: it.percent || 0 }) : formatBytes(size));
        text.appendChild(name);
        text.appendChild(meta);
        if (busy) {
          var bar = document.createElement('progress');
          bar.className = 'upload__progress';
          bar.max = 100;
          bar.value = it.percent || 0;
          bar.setAttribute('aria-label', meta.textContent);
          text.appendChild(bar);
          it.bar = bar;
          it.meta = meta;
        }
        var remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'btn btn--ghost btn--small upload__remove';
        remove.setAttribute('aria-label', t('upload.remove', { name: name.textContent }));
        remove.innerHTML = '<i class="fa-solid fa-xmark"></i>';
        remove.addEventListener('click', function () { removeItem(it); });
        li.appendChild(thumb);
        li.appendChild(text);
        li.appendChild(remove);
        if (it.stored) {
          // The id goes with the form; the module claims the file on save.
          var hidden = document.createElement('input');
          hidden.type = 'hidden';
          hidden.name = fieldName;
          hidden.value = it.stored.id;
          li.appendChild(hidden);
        }
        if (!li.parentNode) list.appendChild(li);
        list.hidden = !items.length;
      }
      function removeItem(it) {
        it.removed = true;     // a queued upload then never starts
        if (it.xhr && it.state === 'uploading') it.xhr.abort();
        items = items.filter(function (x) { return x !== it; });
        if (it.li) it.li.remove();
        if (it.blobUrl) URL.revokeObjectURL(it.blobUrl);
        list.hidden = !items.length;
        syncInput();
      }
      function upload(it) {
        it.state = 'queued';
        it.percent = 0;
        renderItem(it);
        uploadQueue.push(function (done) {
          if (it.removed) { done(); return; }
          send(it, done);
        });
        pumpUploads();
      }
      function send(it, done) {
        var data = new FormData();
        data.append('file', it.file);
        data.append('kinds', box.dataset.kinds || 'image');
        var xhr = new XMLHttpRequest();
        it.xhr = xhr;
        it.state = 'uploading';
        renderItem(it);
        xhr.open('POST', uploadUrl);
        xhr.setRequestHeader('X-CSRFToken', csrfToken());
        xhr.responseType = 'json';
        xhr.upload.addEventListener('progress', function (e) {
          if (!e.lengthComputable || !it.bar) return;
          it.percent = Math.round(e.loaded / e.total * 100);
          it.bar.value = it.percent;
          // All bytes sent: the server now cleans the image and makes its
          // variants, which takes a moment of its own.
          it.meta.textContent = it.percent === 100 ? t('upload.processing') : t('upload.uploading', { percent: it.percent });
        });
        xhr.addEventListener('load', function () {
          var res = xhr.response || {};
          if (xhr.status === 200 && res.ok) {
            it.state = 'done';
            it.stored = res.file;
          } else {
            it.state = 'failed';
            it.problem = res.message || (xhr.status === 413 ? t('upload.too_big', { max: formatBytes(maxSize) }) : t('upload.failed'));
          }
          renderItem(it);
        });
        xhr.addEventListener('error', function () {
          it.state = 'failed';
          it.problem = t('upload.failed');
          renderItem(it);
        });
        // Fires after load, error and abort alike: the next file may go.
        xhr.addEventListener('loadend', done);
        xhr.send(data);
      }
      function add(chosen) {
        if (!input.multiple) items.slice().forEach(removeItem);
        var files = Array.prototype.slice.call(chosen);
        if (!input.multiple) files = files.slice(-1);
        files.forEach(function (file) {
          var it = { file: file, problem: problemOf(file), state: 'local' };
          if (!it.problem && /^image\//.test(file.type)) {
            it.blobUrl = URL.createObjectURL(file);
          }
          items.push(it);
          if (uploadUrl && !it.problem) { upload(it); } else { renderItem(it); }
        });
        syncInput();
        if (uploadUrl) input.value = '';
      }

      // Files stored earlier (editing a saved record).
      try {
        JSON.parse(box.dataset.files || '[]').forEach(function (stored) {
          var it = { stored: stored, problem: '', state: 'done' };
          items.push(it);
          renderItem(it);
        });
      } catch (e) { /* no initial files */ }

      input.addEventListener('change', function () { add(input.files); });
      ['dragenter', 'dragover'].forEach(function (type) {
        zone.addEventListener(type, function (e) { e.preventDefault(); zone.classList.add('is-dragover'); });
      });
      ['dragleave', 'drop'].forEach(function (type) {
        zone.addEventListener(type, function () { zone.classList.remove('is-dragover'); });
      });
      zone.addEventListener('drop', function (e) {
        e.preventDefault();
        if (e.dataTransfer && e.dataTransfer.files.length) add(e.dataTransfer.files);
      });
      list.hidden = !items.length;
    });

    // A form must not go while a file is still on its way: its id would be
    // missing. Capture phase, so the busy state never starts in that case.
    document.addEventListener('submit', function (e) {
      var busy = Array.prototype.some.call(e.target.querySelectorAll('[data-upload]'), function (box) {
        return box.uploadPending && box.uploadPending();
      });
      if (!busy) return;
      e.preventDefault();
      e.stopPropagation();
      window.alert(t('upload.wait'));
    }, true);
  }

  // === 16) Ordering: [data-sortable] ============================================
  // Items ([data-sortable-item][data-id]) are reordered by dragging (mouse)
  // or with the move buttons ([data-move="up|down"]), which also work on
  // touch screens and from the keyboard. The order is written as a comma
  // list of ids into the hidden input named by data-sortable-input, and
  // announced to screen readers. [data-sortable-remove] takes an item out.
  function setupSortables() {
    document.querySelectorAll('[data-sortable]').forEach(function (list) {
      var form = list.closest('form');
      var input = form && list.dataset.sortableInput
        ? form.querySelector('input[name="' + list.dataset.sortableInput + '"]') : null;
      var live = document.createElement('p');
      live.className = 'sr-only';
      live.setAttribute('aria-live', 'polite');
      list.insertAdjacentElement('afterend', live);
      var grid = list.dataset.sortable === 'grid';
      var dragged = null;

      function items() { return Array.prototype.slice.call(list.querySelectorAll('[data-sortable-item]')); }
      function sync() {
        var all = items();
        all.forEach(function (item, i) {
          var up = item.querySelector('[data-move="up"]');
          var down = item.querySelector('[data-move="down"]');
          if (up) up.disabled = i === 0;
          if (down) down.disabled = i === all.length - 1;
        });
        if (input) input.value = all.map(function (item) { return item.dataset.id; }).join(',');
      }
      function announce(item) {
        var label = item.dataset.label || '';
        live.textContent = t('sortable.moved', { name: label, position: items().indexOf(item) + 1, count: items().length });
      }

      list.addEventListener('click', function (e) {
        var move = e.target.closest('[data-move]');
        var removeBtn = e.target.closest('[data-sortable-remove]');
        var item = e.target.closest('[data-sortable-item]');
        if (!item) return;
        if (move) {
          if (move.dataset.move === 'up' && item.previousElementSibling) list.insertBefore(item, item.previousElementSibling);
          if (move.dataset.move === 'down' && item.nextElementSibling) list.insertBefore(item.nextElementSibling, item);
          sync();
          announce(item);
          // Keep focus on a button that still works after the move.
          var again = item.querySelector('[data-move="' + move.dataset.move + '"]');
          (again && !again.disabled ? again : item.querySelector('[data-move]:not(:disabled)') || move).focus();
        } else if (removeBtn) {
          live.textContent = t('sortable.removed', { name: item.dataset.label || '' });
          item.remove();
          sync();
        }
      });
      list.addEventListener('dragstart', function (e) {
        dragged = e.target.closest ? e.target.closest('[data-sortable-item]') : null;
        if (!dragged) return;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', dragged.dataset.id || '');
        dragged.classList.add('is-dragging');
      });
      list.addEventListener('dragover', function (e) {
        if (!dragged) return;
        e.preventDefault();
        var over = e.target.closest ? e.target.closest('[data-sortable-item]') : null;
        if (!over || over === dragged) return;
        var r = over.getBoundingClientRect();
        var after = grid ? e.clientX > r.left + r.width / 2 : e.clientY > r.top + r.height / 2;
        list.insertBefore(dragged, after ? over.nextSibling : over);
      });
      list.addEventListener('dragend', function () {
        if (!dragged) return;
        dragged.classList.remove('is-dragging');
        announce(dragged);
        dragged = null;
        sync();
      });
      if (form) form.addEventListener('reset', function () { window.setTimeout(sync, 0); });
      sync();
    });
  }

  // === 17) Busy state of submitted forms ========================================
  // A submitted POST form disables its buttons and the pressed one shows a
  // spinner: no double submits while an upload runs or an e-mail is sent.
  // Forms opt out with data-busy="off". Runs after the confirm dialog and the
  // live checks, which stop the event when the form must not go yet.
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (e.defaultPrevented || form.dataset.busy === 'off' || (form.method || '').toLowerCase() !== 'post') return;
    var buttons = submitButtons(form);
    if (e.submitter) e.submitter.classList.add('is-busy');
    // Disabled a moment later: a button disabled right away would drop its
    // own name/value from the submitted data.
    window.setTimeout(function () {
      buttons.forEach(function (b) { b.disabled = true; b.setAttribute('aria-busy', 'true'); });
    }, 0);
  });
  // Coming back with the browser's Back button restores the page as it was
  // left, buttons disabled included; enable them again.
  window.addEventListener('pageshow', function (e) {
    if (!e.persisted) return;
    document.querySelectorAll('button[aria-busy="true"]').forEach(function (b) {
      b.disabled = false;
      b.classList.remove('is-busy');
      b.removeAttribute('aria-busy');
    });
  });

  // === 18) Character counter: [data-counter] with maxlength ======================
  function setupCounters() {
    document.querySelectorAll('[data-counter][maxlength]').forEach(function (field) {
      var max = Number(field.getAttribute('maxlength'));
      var counter = document.createElement('span');
      counter.className = 'field__counter';
      counter.id = (field.id || 'field') + '-counter';
      field.insertAdjacentElement('afterend', counter);
      var described = field.getAttribute('aria-describedby');
      field.setAttribute('aria-describedby', (described ? described + ' ' : '') + counter.id);
      function update() {
        var used = field.value.length;
        counter.textContent = t('counter', { used: used, max: max });
        counter.classList.toggle('is-near', used >= max * 0.9);
      }
      field.addEventListener('input', update);
      if (field.form) field.form.addEventListener('reset', function () { window.setTimeout(update, 0); });
      update();
    });
  }

  // === 19) Demo links of the design cookbook ==================================
  // On /admin/design, sample tabs, chips and cards can be clicked without the
  // page jumping to an anchor: a[data-demo] stays put, and inside a
  // [data-demo-group] it becomes the active item.
  document.addEventListener('click', function (e) {
    var link = e.target.closest ? e.target.closest('a[data-demo]') : null;
    if (!link) return;
    e.preventDefault();
    var group = link.closest('[data-demo-group]');
    if (!group) return;
    group.querySelectorAll('a[data-demo]').forEach(function (item) {
      var active = item === link;
      item.classList.toggle('is-active', active);
      if (active) { item.setAttribute('aria-current', 'page'); } else { item.removeAttribute('aria-current'); }
    });
  });

  // === 20) Menu button of the sidebar on phones ================================
  // Below the breakpoint in admin.css the navigation hides behind a button.
  // The pattern is a disclosure (not a modal): no focus trap, Esc or a click
  // outside closes it, and focus returns to the button after Esc.
  var NAV_BREAKPOINT = '(min-width: 901px)';   // keep in sync with admin.css (max-width: 900px)

  function setupNavToggle() {
    var sidebar = document.querySelector('[data-nav]');
    var toggle = sidebar ? sidebar.querySelector('[data-nav-toggle]') : null;
    if (!toggle) return;

    function isOpen() { return sidebar.classList.contains('is-open'); }
    function setOpen(open, returnFocus) {
      sidebar.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.setAttribute('aria-label', open ? t('nav.close') : t('nav.open'));
      if (!open && returnFocus) toggle.focus();
    }

    toggle.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(!isOpen());
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && isOpen()) setOpen(false, true);
    });
    document.addEventListener('click', function (e) {
      if (isOpen() && !sidebar.contains(e.target)) setOpen(false);
    });
    // A followed link closes the menu, so an in-page target (#section) is not
    // hidden behind it.
    sidebar.addEventListener('click', function (e) {
      if (e.target.closest && e.target.closest('a[href]')) setOpen(false);
    });
    // On a wide screen the navigation is always visible; drop the phone state
    // when the window grows (rotating a tablet, resizing a window).
    var wide = window.matchMedia(NAV_BREAKPOINT);
    var onChange = function (m) { if (m.matches) setOpen(false); };
    if (wide.addEventListener) { wide.addEventListener('change', onChange); } else { wide.addListener(onChange); }
  }


  // === 21) Rich-text editor: textarea[data-editor] ==============================
  // A minimal editor: headings, paragraphs, bold, links and lists, nothing
  // else (docs/framework.md). The textarea stays in the form, hidden, and
  // always holds the current HTML; without JavaScript it is simply a plain
  // textarea. The server cleans the HTML again on save (evrima/editor).
  var EDITOR_TOOLS = [
    // Headings show their level as text: two "H" icons would look the same.
    { cmd: 'formatBlock', value: 'h2', text: 'H2', label: 'editor.heading' },
    { cmd: 'formatBlock', value: 'h3', text: 'H3', label: 'editor.subheading' },
    { cmd: 'formatBlock', value: 'p', icon: 'paragraph', label: 'editor.paragraph' },
    { cmd: 'bold', icon: 'bold', label: 'editor.bold', key: 'b' },
    { cmd: 'createLink', icon: 'link', label: 'editor.link', key: 'k' },
    { cmd: 'unlink', icon: 'link-slash', label: 'editor.unlink' },
    { cmd: 'insertUnorderedList', icon: 'list-ul', label: 'editor.bullets' },
    { cmd: 'insertOrderedList', icon: 'list-ol', label: 'editor.numbers' }
  ];

  // Light cleanup while typing: the textarea should not carry what the
  // server would throw away anyway (style attributes, <div>, <span>).
  function tidyEditorHtml(area) {
    area.querySelectorAll('[style]').forEach(function (el) { el.removeAttribute('style'); });
    area.querySelectorAll('span, font').forEach(function (el) {
      while (el.firstChild) el.parentNode.insertBefore(el.firstChild, el);
      el.remove();
    });
    area.querySelectorAll('div').forEach(function (el) {
      var p = document.createElement('p');
      while (el.firstChild) p.appendChild(el.firstChild);
      el.replaceWith(p);
    });
    var html = area.innerHTML.replace(/<b>/g, '<strong>').replace(/<\/b>/g, '</strong>');
    return /^(<p>(<br>)?<\/p>)?$/.test(html.trim()) ? '' : html;
  }

  function setupEditors() {
    document.querySelectorAll('textarea[data-editor]').forEach(function (textarea) {
      var wrap = document.createElement('div');
      wrap.className = 'editor';
      var toolbar = document.createElement('div');
      toolbar.className = 'editor__toolbar';
      toolbar.setAttribute('role', 'toolbar');
      toolbar.setAttribute('aria-label', t('editor.toolbar'));
      var area = document.createElement('div');
      area.className = 'editor__area';
      area.contentEditable = 'true';
      area.setAttribute('role', 'textbox');
      area.setAttribute('aria-multiline', 'true');
      var label = textarea.id ? document.querySelector('label[for="' + textarea.id + '"]') : null;
      if (label) {
        label.id = label.id || textarea.id + '-label';
        area.setAttribute('aria-labelledby', label.id);
        // The label now points at the editor; clicking it focuses the area.
        label.addEventListener('click', function (e) { e.preventDefault(); area.focus(); });
      }
      if (textarea.getAttribute('aria-describedby')) area.setAttribute('aria-describedby', textarea.getAttribute('aria-describedby'));
      area.innerHTML = textarea.value;

      var buttons = EDITOR_TOOLS.map(function (tool) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'editor__button';
        btn.innerHTML = tool.text
          ? '<span class="editor__label" aria-hidden="true">' + tool.text + '</span>'
          : '<i class="fa-solid fa-' + tool.icon + '" aria-hidden="true"></i>';
        btn.setAttribute('aria-label', t(tool.label));
        btn.dataset.tip = t(tool.label) + (tool.key ? ' (Ctrl+' + tool.key.toUpperCase() + ')' : '');
        // mousedown keeps the selection in the area while the button is pressed.
        btn.addEventListener('mousedown', function (e) { e.preventDefault(); });
        btn.addEventListener('click', function () { run(tool); });
        toolbar.appendChild(btn);
        return { tool: tool, el: btn };
      });

      function run(tool) {
        area.focus();
        document.execCommand('styleWithCSS', false, false);
        if (tool.cmd === 'createLink') {
          var href = window.prompt(t('editor.link_prompt'), 'https://');
          if (!href || href === 'https://') return;
          if (!/^(https?:|mailto:|tel:)/i.test(href)) href = 'https://' + href;
          document.execCommand('createLink', false, href);
        } else if (tool.cmd === 'formatBlock') {
          document.execCommand('formatBlock', false, '<' + tool.value + '>');
        } else {
          document.execCommand(tool.cmd, false, null);
        }
        sync();
        refresh();
      }
      function sync() { textarea.value = tidyEditorHtml(area); }
      // Pressed state of the buttons follows the cursor.
      function refresh() {
        var selection = document.getSelection();
        if (!selection || !area.contains(selection.anchorNode)) return;
        var block = (document.queryCommandValue('formatBlock') || '').toLowerCase();
        buttons.forEach(function (b) {
          var on = null;
          if (b.tool.cmd === 'formatBlock') on = block === b.tool.value;
          // Headings look bold by themselves; "bold" there would only confuse.
          else if (b.tool.cmd === 'bold') on = !/^h[23]$/.test(block) && document.queryCommandState('bold');
          else if (b.tool.cmd.indexOf('insert') === 0) on = document.queryCommandState(b.tool.cmd);
          if (on !== null) b.el.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
      }

      // Typing into an empty editor (or after deleting everything) produces a
      // bare text node; turn the line into a paragraph, so the stored text is
      // always made of blocks the website's styles can address.
      function ensureBlock() {
        var selection = document.getSelection();
        var node = selection && selection.anchorNode;
        if (!node || !area.contains(node) || node === area) return;
        while (node.parentNode !== area) node = node.parentNode;
        if (node.nodeType === 3 || !/^(P|H2|H3|UL|OL)$/.test(node.nodeName)) {
          document.execCommand('formatBlock', false, '<p>');
        }
      }
      area.addEventListener('input', function () { ensureBlock(); sync(); });
      area.addEventListener('keyup', refresh);
      area.addEventListener('mouseup', refresh);
      area.addEventListener('focus', function () {
        // Enter makes paragraphs, not <div>s.
        document.execCommand('defaultParagraphSeparator', false, 'p');
      });
      area.addEventListener('keydown', function (e) {
        if (!(e.ctrlKey || e.metaKey)) return;
        var tool = EDITOR_TOOLS.filter(function (x) { return x.key === e.key.toLowerCase(); })[0];
        if (tool) { e.preventDefault(); run(tool); }
      });
      // Pasted text arrives without its formatting (Word, web pages), so the
      // website's own design decides how it looks.
      area.addEventListener('paste', function (e) {
        e.preventDefault();
        var text = (e.clipboardData || window.clipboardData).getData('text/plain');
        document.execCommand('insertText', false, text);
      });
      if (textarea.form) textarea.form.addEventListener('reset', function () {
        window.setTimeout(function () { area.innerHTML = textarea.value; }, 0);
      });

      // The textarea is not `hidden`: a required editor must still be
      // checkable by the browser, which needs a focusable field to point its
      // message at. It sits invisible under the area and hands focus over.
      textarea.classList.add('editor__source');
      textarea.tabIndex = -1;
      textarea.addEventListener('focus', function () { area.focus(); });
      if (textarea.required) area.setAttribute('aria-required', 'true');
      textarea.insertAdjacentElement('beforebegin', wrap);
      wrap.appendChild(toolbar);
      wrap.appendChild(area);
      wrap.appendChild(textarea);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    loadTexts();
    setupNavToggle();
    setupKindSwitches();
    setupRows();
    setupDropdowns();
    localizeTimes(document);
    setupDateTimeInputs(document);
    setupTables();
    setupBars();
    setupTips();
    setupSlugs();
    setupChecks();
    setupTagPickers();
    setupUploads();
    setupSortables();
    setupCounters();
    setupEditors();
    setupModals();
  });
})();
