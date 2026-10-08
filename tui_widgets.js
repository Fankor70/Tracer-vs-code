/* =====================================================================
   tui_widgets.js — примитивы терминального интерфейса CodeTime.
   Загружается первым, экспортирует window.TUIW. Без зависимостей, без
   модулей, без top-level await. Chromium / WebView2 ~120.

   Ограничения DESIGN_SPEC §17: никаких браузерных окон, никакого
   innerHTML с данными (только createElement + textContent), никакого eval.

   Разметка подчинена app.css, глифы рисует CSS — JS их не дублирует:
     .cmt/.row-hint — текст без префикса `// `; .cbx — глиф из aria-pressed;
     .sec — <button aria-expanded> + сосед .sec-b; .chip активный — is-on;
     модалка — .modal-bd/.modal-card, подтверждение — .confirm-card;
     тосты — .toasts > .toast; полоса — .bar > .bar-f; бар-чарт — .wd.
   ===================================================================== */

(function () {
  'use strict';

  var doc = document;
  var WIN = window;
  var LS_COLLAPSED = 'codetime.collapsed';
  var DASH = '—';

  // ---- Мелкие утилиты ----
  function has(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
  }

  function isNode(value) {
    return !!value && typeof value === 'object' && typeof value.nodeType === 'number';
  }

  // Число из чего угодно; нечисловое значение заменяется на def.
  function num(value, def) {
    var n = typeof value === 'number' ? value : parseFloat(value);
    if (typeof n === 'number' && isFinite(n)) return n;
    return def === undefined ? 0 : def;
  }

  function cell(value) {
    return value === null || value === undefined ? '' : String(value);
  }

  function pad2(n) {
    return (n < 10 ? '0' : '') + n;
  }

  // localStorage может быть недоступен (приватный режим, file://) — не падаем.
  function lsGet(key, def) {
    try {
      var raw = WIN.localStorage.getItem(key);
      return raw === null ? def : raw;
    } catch (e) {
      return def;
    }
  }

  function lsSet(key, value) {
    try { WIN.localStorage.setItem(key, value);
    } catch (e) { /* хранилище закрыто — просто не сохраняем */ }
  }

  // el / text / frag — создание узлов
  // props: class, text, onclick, attrs, style, aria-*, data-*
  // children: узел, строка, число, массив, null

  var BOOLEAN_PROPS = { disabled: 1, checked: 1, selected: 1, readOnly: 1, required: 1,
                        autofocus: 1, autoFocus: 1, hidden: 1, multiple: 1, open: 1 };

  var VALUE_PROPS = { value: 1, type: 1, name: 1, placeholder: 1, title: 1, id: 1,
                       min: 1, max: 1, step: 1, maxLength: 1, minLength: 1, pattern: 1,
                       accept: 1, list: 1, rows: 1, cols: 1, src: 1, alt: 1 };

  function classValue(value) {
    if (!value) return '';
    if (Array.isArray(value)) {
      var out = [];
      for (var i = 0; i < value.length; i++) {
        if (value[i]) out.push(String(value[i]));
      }
      return out.join(' ');
    }
    return String(value);
  }

  function applyStyle(node, style) {
    if (typeof style === 'string') {
      node.style.cssText = style;
      return;
    }
    for (var k in style) {
      if (!has(style, k)) continue;
      var v = style[k];
      if (v === null || v === undefined) continue;
      // Пользовательские свойства (--foo) задаются только через setProperty.
      if (k.slice(0, 2) === '--') node.style.setProperty(k, String(v));
      else node.style[k] = v;
    }
  }

  function setProp(node, key, value) {
    if (value === null || value === undefined) return;

    if (key === 'class' || key === 'className') {
      node.className = classValue(value);
      return;
    }
    if (key === 'text') {
      node.textContent = String(value);
      return;
    }
    if (key === 'attrs') {
      for (var a in value) if (has(value, a)) node.setAttribute(a, String(value[a]));
      return;
    }
    if (key === 'style') {
      applyStyle(node, value);
      return;
    }
    // onclick / onkeydown / oninput / ... — любые обработчики через addEventListener.
    if (key.length > 2 && key.slice(0, 2) === 'on' && typeof value === 'function') {
      node.addEventListener(key.slice(2), value, false);
      return;
    }
    if (key.indexOf('aria-') === 0 || key.indexOf('data-') === 0) {
      node.setAttribute(key, String(value));
      return;
    }
    if (key === 'for' || key === 'htmlFor') {
      node.setAttribute('for', String(value));
      return;
    }
    if (has(BOOLEAN_PROPS, key)) {
      node[key] = !!value;
      return;
    }
    if (has(VALUE_PROPS, key)) {
      try {
        node[key] = value;
      } catch (e) {
        node.setAttribute(key, String(value));
      }
      return;
    }
    // Всё остальное (tabindex, colspan, headers…) — атрибутом.
    node.setAttribute(key, String(value));
  }

  function append(parent, children) {
    if (children === null || children === undefined || children === false || children === true) return;
    if (Array.isArray(children)) {
      for (var i = 0; i < children.length; i++) append(parent, children[i]);
      return;
    }
    if (isNode(children)) parent.appendChild(children);
    else parent.appendChild(doc.createTextNode(String(children)));
  }

  function el(tag, props, children) {
    var node = doc.createElement(tag || 'div');
    if (typeof props === 'string' || Array.isArray(props)) {
      node.className = classValue(props);
      props = null;
    }
    if (props) {
      for (var k in props) {
        if (!has(props, k)) continue;
        if (k === 'children') append(node, props[k]);
        else setProp(node, k, props[k]);
      }
    }
    if (children !== undefined) append(node, children);
    return node;
  }

  function text(value) {
    return doc.createTextNode(value === null || value === undefined ? '' : String(value));
  }

  function frag(children) {
    var f = doc.createDocumentFragment();
    append(f, children);
    return f;
  }

  // Полная очистка узла без innerHTML.
  function clear(node) {
    if (!node) return node;
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  // ---- Строки-пояснения ----
  // Комментарий из §6. Префикс `// ` рисует CSS через ::before — писать его
  // здесь нельзя, иначе получится `// // цель`.
  function note(value) {
    if (value === null || value === undefined || value === '') return null;
    return el('div', { class: 'cmt row-hint', text: cell(value) });
  }

  // Строка «пусто» для случаев, когда данных нет.
  function empty(value) {
    return el('div', { class: 'empty', text: cell(value) });
  }

  // ---- §5 — панель ----
  function setPanelCollapsed(panelEl, body, collapsed) {
    body.hidden = !!collapsed;
    panelEl.classList.toggle('is-collapsed', !!collapsed);
  }

  // Активная панель: класс is-focus (в app.css есть алиас .panel--focus).
  function setPanelFocus(panelEl, on) {
    if (!panelEl) return;
    panelEl.classList.toggle('is-focus', !!on);
    if (on) panelEl.setAttribute('data-focus', 'true');
    else panelEl.removeAttribute('data-focus');
  }

  function panel(opts) {
    opts = opts || {};
    var root = el('section', { class: 'panel' });
    if (opts.id) root.setAttribute('data-panel', opts.id);
    if (opts.flag) root.setAttribute('data-flag', opts.flag);
    if (opts.focused) setPanelFocus(root, true);

    var head = el('header', { class: 'panel-h' });
    head.appendChild(el('span', { class: 'panel-t' }, [
      el('i', { class: 'sig', text: '$' }),
      doc.createTextNode(' ' + cell(opts.title))
    ]));

    var right = el('span', { class: 'panel-x' });
    if (typeof opts.onClose === 'function') {
      right.appendChild(el('button', {
        class: 'panel-x btn-t', type: 'button', text: '×',
        title: opts.closeTitle || 'закрыть панель',
        'aria-label': opts.closeTitle || 'закрыть панель',
        onclick: function (ev) { opts.onClose(ev, root); }
      }));
    }
    append(right, opts.actions);
    head.appendChild(right);
    root.appendChild(head);

    var bodyEl = el('div', { class: 'panel-b' });
    append(bodyEl, opts.body);
    root.appendChild(bodyEl);

    // Сворачивание по заголовку — только если его явно попросили.
    var canCollapse = opts.collapsible !== undefined
      ? !!opts.collapsible
      : (opts.collapsed !== undefined && opts.collapsed !== null);
    if (canCollapse) {
      var toggle = function (ev) {
        if (ev && ev.target && ev.target.closest && ev.target.closest('.panel-x')) return;
        if (ev) ev.preventDefault();
        setPanelCollapsed(root, bodyEl, !bodyEl.hidden);
        head.setAttribute('aria-expanded', bodyEl.hidden ? 'false' : 'true');
      };
      head.setAttribute('role', 'button');
      head.setAttribute('tabindex', '0');
      head.setAttribute('aria-expanded', opts.collapsed ? 'false' : 'true');
      setPanelCollapsed(root, bodyEl, !!opts.collapsed);
      head.addEventListener('click', toggle, false);
      head.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') toggle(ev);
      }, false);
    }

    // Ссылки на части панели: удобно перерисовывать содержимое и менять фокус.
    root.panelBody = bodyEl;
    root.panelHead = head;
    root.setPanelFocus = function (on) { setPanelFocus(root, on); };
    return root;
  }

  // ---- §5 / §12 — заголовок секции со сворачиванием ----
  function collapsedMap() {
    var parsed = null;
    try { parsed = JSON.parse(lsGet(LS_COLLAPSED, '{}')); } catch (e) { parsed = null; }
    return (parsed && typeof parsed === 'object') ? parsed : {};
  }

  function rememberCollapsed(key, value) {
    var map = collapsedMap();
    map[key] = !!value;
    lsSet(LS_COLLAPSED, JSON.stringify(map));
  }

  // Секция возвращает <button class="sec">, а .sec-b обязан идти сразу за ним
  // соседом. Пока кнопка не вставлена в DOM, соседа вставить некуда, поэтому
  // берём его из очереди и ставим наблюдателем: он встанет сам.
  var pendingSections = [];
  var sectionObserver = null;

  function flushSections() {
    var i = 0;
    while (i < pendingSections.length) {
      var rec = pendingSections[i];
      if (!rec.btn.parentNode) { i++; continue; }
      rec.btn.parentNode.insertBefore(rec.box, rec.btn.nextSibling);
      pendingSections.splice(i, 1);
      if (!pendingSections.length && sectionObserver) {
        sectionObserver.disconnect();
        sectionObserver = null;
      }
    }
  }

  function watchSection(rec) {
    pendingSections.push(rec);
    if (!sectionObserver && doc.documentElement && WIN.MutationObserver) {
      sectionObserver = new WIN.MutationObserver(flushSections);
      sectionObserver.observe(doc.documentElement, { childList: true, subtree: true });
    }
    // Если кнопку уже вставили в DOM — сосед ставится сразу.
    flushSections();
    if (pendingSections.length > 64 && sectionObserver) {
      sectionObserver.disconnect();
      sectionObserver = null;
      pendingSections.length = 0;
    }
  }

  // sec(иконка, название, метка окна, тело) — метка окна выводится как [30д].
  // Возвращает <button>; контейнер тела доступен как кнопка .secBody,
  // а если тело передано аргументом — оно уже внутри .sec-b.
  function sec(icon, title, windowLabel, body) {
    var key = cell(title);
    var btn = el('button', { class: 'sec', type: 'button', attrs: { 'data-sec': key } });
    btn.appendChild(el('span', { class: 'sec-i', text: icon || '◇' }));
    btn.appendChild(el('span', { class: 'sec-t', text: key }));
    if (windowLabel) btn.appendChild(el('span', { class: 'sec-w', text: '[' + windowLabel + ']' }));

    var box = el('div', { class: 'sec-b' });
    if (body) append(box, body);

    var paint = function (isCollapsed) {
      btn.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
      btn.classList.toggle('is-collapsed', isCollapsed);
      box.hidden = isCollapsed;
    };
    paint(!!collapsedMap()[key]);

    var toggle = function (ev) {
      if (ev) ev.preventDefault();
      var next = btn.getAttribute('aria-expanded') === 'true';
      paint(next);
      rememberCollapsed(key, next);
    };
    btn.addEventListener('click', toggle, false);
    btn.secBody = box;
    btn.secToggle = toggle;
    watchSection({ btn: btn, box: box });
    return btn;
  }

  // ---- §6 — строка данных ----
  function row(opts) {
    opts = opts || {};
    var node = el('div', {
      class: 'row' + (opts.class ? ' ' + opts.class : ''), attrs: opts.attrs || null
    });

    if (typeof opts.onclick === 'function') {
      node.classList.add('is-clickable');
      node.setAttribute('role', 'button');
      node.setAttribute('tabindex', '0');
      node.addEventListener('click', opts.onclick, false);
      node.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
          ev.preventDefault();
          opts.onclick(ev);
        }
      }, false);
    }

    node.appendChild(el('span', { class: 'row-k', text: cell(opts.key) }));
    node.appendChild(el('span', { class: 'row-dim', text: cell(opts.dim) }));
    node.appendChild(el('span', {
      class: 'row-v tnum' + (opts.valueKind ? ' row-v--' + opts.valueKind : ''), text: cell(opts.value)
    }));

    // Пояснение идёт строкой ниже и растягивается на все три колонки.
    var hint = note(opts.hint);
    if (hint) {
      hint.style.gridColumn = '1 / -1';
      node.appendChild(hint);
    }
    return node;
  }

  // §8 — полоса прогресса
  // ok — цель достигнута, near — близко, over — перерасход,
  // dim — далеко от цели или ноль.

  var BAR_STATE = {
    ok: '', near: 'near', amber: 'near', warn: 'near',
    over: 'over', err: 'over', red: 'over', dim: 'dim'
  };

  // pct — уже процент от цели, поэтому «близко» определяем по нему самому.
  // goal/actual нужны только для подписи и для проверки перерасхода.
  function barKind(pct, opts) {
    if (opts.kind && has(BAR_STATE, opts.kind)) return opts.kind;
    if (opts.over === true) return 'over';
    if (opts.goal > 0 && opts.actual !== undefined && opts.actual !== null &&
        num(opts.actual, 0) > num(opts.goal, 0)) return 'over';
    if (pct >= 100) return 'ok';
    if (pct <= 0) return 'dim';
    if (pct >= 60) return 'near';
    return 'dim';
  }

  function barCaption(pct, opts) {
    var out = fmt.pct(pct);
    if (opts.caption !== undefined && opts.caption !== null) return String(opts.caption);
    if (opts.goal > 0 && opts.actual !== undefined && opts.actual !== null) {
      out += ' (' + fmt.sec(opts.actual) + ' / ' + fmt.hm(opts.goal) + ')';
    }
    return out;
  }

  function bar(pct, opts) {
    opts = opts || {};
    var value = num(pct, 0);
    if (value < 0) value = 0;
    var kind = barKind(value, opts);
    var state = BAR_STATE[kind] || '';
    var width = value > 100 ? 100 : value;

    var wrap = el('div', { class: 'bar-wrap' });

    var trackClass = 'bar' + (state ? ' bar--' + state : '') +
                     (opts.thin ? ' bar--thin' : '') + (kind === 'dim' ? ' is-dim' : '');
    var track = el('div', {
      class: trackClass,
      attrs: { role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100',
               'aria-valuenow': String(Math.round(value)),
               'aria-label': opts.ariaLabel || opts.caption || 'прогресс' }
    });
    // Цвет заливки задаёт CSS по классу состояния — инлайном ничего не дублируем.
    var fill = el('i', {
      class: 'bar-f' + (state ? ' bar--' + state : '') + (kind === 'dim' ? ' is-dim' : ''),
      style: { width: value.toFixed(2) + '%' }
    });
    track.appendChild(fill);
    wrap.appendChild(track);

    if (!opts.thin) {
      wrap.appendChild(el('span', { class: 'bar-cap tnum', text: barCaption(value, opts) }));
    }

    wrap.barTrack = track;
    wrap.barFill = fill;
    wrap.barKind = kind;
    return wrap;
  }

  // §7 — чекбокс в стиле оболочки
  // Глиф [✓] / [ ] / [·] рисует CSS по aria-pressed (true/false/mixed),
  // поэтому в содержимое кнопки ничего не кладём; тот же глиф дублируется
  // в aria-label — иначе он теряется для скринридера.

  var CBX_GLYPH = { done: '[✓]', part: '[·]', todo: '[ ]' };

  function cbxState(value) {
    if (value === true || value === 1 || value === 'done' || value === 'yes' || value === 'x') return 'done';
    if (value === 'part' || value === 'partial' || value === 'mid' || value === '·') return 'part';
    return 'todo';
  }

  function cbx(checked, onToggle, label) {
    var state = cbxState(checked);
    var pressed = state === 'done' ? 'true' : state === 'part' ? 'mixed' : 'false';
    var name = label ? String(label) : 'задача';
    var word = state === 'done' ? 'выполнено' : state === 'part' ? 'частично' : 'не выполнено';

    var node = el('button', {
      class: 'cbx', type: 'button', 'aria-pressed': pressed,
      'aria-label': CBX_GLYPH[state] + ' ' + name + ', ' + word,
      attrs: { 'data-state': state }, title: name
    });

    if (typeof onToggle === 'function') {
      node.addEventListener('click', function (ev) { onToggle(ev, state === 'done'); }, false);
    } else {
      node.disabled = true;
    }
    node.cbxState = state;
    return node;
  }

  // ---- §12 — пресет окна данных ----
  function chip(label, active, onClick) {
    var node = el('button', {
      class: 'chip' + (active ? ' is-on' : ''),
      type: 'button',
      text: cell(label),
      'aria-pressed': active ? 'true' : 'false',
      onclick: onClick
    });
    return node;
  }

  // ---- §11 — бар-чарт по дням недели ----
  var WBARS_LEN = 20;

  function wbarItem(raw, index) {
    if (Array.isArray(raw)) {
      return { label: cell(raw[0]), pct: num(raw[1], 0) };
    }
    if (raw && typeof raw === 'object') {
      return {
        label: cell(raw.label !== undefined ? raw.label : raw.name),
        pct: num(raw.pct !== undefined ? raw.pct : raw.value, 0)
      };
    }
    return { label: cell(raw), pct: 0, index: index };
  }

  function wbars(items, opts) {
    opts = opts || {};
    var wrap = el('div', { class: 'wbars' });
    if (!items || !items.length) return wrap;

    var list = [];
    var i;
    for (i = 0; i < items.length; i++) list.push(wbarItem(items[i], i));

    var best = null;
    var worst = null;

    for (i = 0; i < list.length; i++) {
      var it = list[i];
      var pct = it.pct;
      if (pct < 0) pct = 0;
      if (pct > 100) pct = 100;
      it.pct = pct;

      // При 0% — ноль символов заливки, а не один.
      var filled = Math.round((pct / 100) * WBARS_LEN);
      if (filled < 0) filled = 0;
      if (filled > WBARS_LEN) filled = WBARS_LEN;
      var barText = '';
      for (var a = 0; a < filled; a++) barText += '▓';
      for (var b = filled; b < WBARS_LEN; b++) barText += '░';

      if (!best || it.pct > best.pct) best = it;
      if (!worst || it.pct < worst.pct) worst = it;

      // Глифы полосы — обычный текст, CSS ставит white-space: pre.
      it.line = el('div', {
        class: 'wd',
        attrs: { 'data-label': it.label, 'data-pct': String(Math.round(pct)) }
      }, [
        el('span', { class: 'wd-lb', text: it.label }),
        el('span', { class: 'wd-bar', text: barText }),
        el('span', { class: 'wd-pct', text: Math.round(pct) + '%' })
      ]);
      wrap.appendChild(it.line);
    }

    // Крайние значения помечаем после прохода — иначе первая строка
    // успела бы оказаться и лучшей, и худшей.
    if (best) best.line.classList.add('wd--best');
    if (worst) worst.line.classList.add('wd--worst');

    if (opts.legend !== false && best && worst && best.pct > 0) {
      var legend = note(
        'лучший: ' + best.label + ' (' + fmt.pct(best.pct) + ')' +
        '   худший: ' + worst.label + ' (' + fmt.pct(worst.pct) + ')'
      );
      if (legend) wrap.appendChild(legend);
    }
    return wrap;
  }

  // ---- §16 — модалки, затемнение, стек ----
  var FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),' +
    'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

  var stack = [];
  var keyHandler = null;
  var scrollLocked = false;
  var savedOverflow = '';

  // Контейнер ищем и по id, и по классу: если разметка уже содержит
// .toasts или .modal-host, второй контейнер создавать не надо.
  function hostFor(id, cls) {
    var host = doc.getElementById(id);
    if (!host && doc.querySelector) host = doc.querySelector('.' + cls);
    if (!host) {
      host = el('div', { class: cls, attrs: { id: id } });
      (doc.body || doc.documentElement).appendChild(host);
    }
    return host;
  }

  function lockScroll() {
    if (scrollLocked) return;
    scrollLocked = true;
    savedOverflow = doc.documentElement.style.overflow;
    doc.documentElement.style.overflow = 'hidden';
  }

  function unlockScroll() {
    if (!scrollLocked || stack.length) return;
    scrollLocked = false;
    doc.documentElement.style.overflow = savedOverflow;
  }

  // Esc ловим на window с захватом: до document дело не дойдёт, поэтому
  // горячие клавиши TUI поверх модалки не срабатывают.
  function attachKeys() {
    if (keyHandler) return;
    keyHandler = function (ev) {
      if (!stack.length) return;
      if (ev.key === 'Escape' || ev.key === 'Esc') {
        ev.preventDefault();
        ev.stopPropagation();
        if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
        stack[stack.length - 1].close();
        return;
      }
      if (ev.key === 'Tab') trapTab(ev, stack[stack.length - 1].card);
    };
    WIN.addEventListener('keydown', keyHandler, true);
  }

  function detachKeys() {
    if (!keyHandler) return;
    WIN.removeEventListener('keydown', keyHandler, true);
    keyHandler = null;
  }

  function trapTab(ev, card) {
    if (!card) return;
    var items = card.querySelectorAll(FOCUSABLE);
    if (!items.length) return;
    var active = doc.activeElement;
    var inside = card.contains(active);
    if (ev.shiftKey && (active === items[0] || !inside)) {
      ev.preventDefault();
      items[items.length - 1].focus();
    } else if (!ev.shiftKey && (active === items[items.length - 1] || !inside)) {
      ev.preventDefault();
      items[0].focus();
    }
  }

  function focusFirst(card) {
    if (!card) return;
    var input = card.querySelector('input:not([type="hidden"]), select, textarea');
    if (!input) {
      var items = card.querySelectorAll(FOCUSABLE);
      input = items.length ? items[0] : null;
    }
    if (input && input.focus) {
      try { input.focus(); } catch (e) { /* поле может быть только для чтения */ }
    }
  }

  // Общая оболочка: затемнение .modal-bd + карточка от build().
  function openDialog(build) {
    var backdrop = el('div', { class: 'modal-bd' });
    var prevFocus = doc.activeElement;
    var entry = { overlay: backdrop, card: null, body: null, close: null };

    entry.close = function () {
      var i = stack.indexOf(entry);
      if (i >= 0) stack.splice(i, 1);
      if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
      unlockScroll();
      if (prevFocus && prevFocus.focus) {
        try { prevFocus.focus(); } catch (e) { /* элемент мог исчезнуть */ }
      }
      if (typeof entry.onClose === 'function') entry.onClose();
      if (!stack.length) detachKeys();
    };

    var card = build(entry);
    entry.card = card;
    backdrop.appendChild(card);
    backdrop.addEventListener('click', function (ev) {
      if (ev.target === backdrop) entry.close();
    }, false);

    stack.push(entry);
    hostFor('tui-modal-host', 'modal-host').appendChild(backdrop);
    lockScroll();
    attachKeys();

    return {
      el: backdrop, card: card, body: entry.body, close: entry.close,
      focus: function () { focusFirst(card); }
    };
  }

  // modal({title, body, onOk, okText, footer}) — footer может быть функцией
  // (close, bodyNode), чтобы кнопки умели звать закрытие.
  function modal(opts) {
    opts = opts || {};
    return openDialog(function (entry) {
      var card = el('div', {
        class: 'modal-card',
        attrs: { role: 'dialog', 'aria-modal': 'true',
                 'aria-label': cell(opts.title) || 'диалог' }
      });

      var head = el('header', { class: 'modal-h' }, [
        el('span', { class: 'modal-t' }, [
          el('i', { class: 'sig', text: '$' }),
          doc.createTextNode(' ' + cell(opts.title))
        ]),
        el('button', {
          class: 'btn-t modal-x', type: 'button', text: '[закрыть]',
          onclick: function () { entry.close(); }
        })
      ]);
      card.appendChild(head);

      var bodyEl = el('div', { class: 'modal-b' });
      append(bodyEl, typeof opts.body === 'function' ? opts.body(card) : opts.body);
      entry.body = bodyEl;
      card.appendChild(bodyEl);

      if (opts.footer || typeof opts.onOk === 'function') {
        var foot = el('footer', { class: 'modal-f' });
        if (typeof opts.footer === 'function') {
          append(foot, opts.footer(entry.close, bodyEl));
        } else if (opts.footer) {
          append(foot, opts.footer);
        } else {
          foot.appendChild(el('button', {
            class: 'btn-t', type: 'button', text: '[отмена]',
            onclick: function () { entry.close(); }
          }));
          foot.appendChild(el('button', {
            class: 'btn-t btn-t--ok',
            type: 'button',
            text: '[' + (opts.okText || 'сохранить') + ']',
            onclick: function () {
              // Возврат false оставляет модалку открытой — удобно для валидации.
              if (opts.onOk(bodyEl, entry.close) !== false) entry.close();
            }
          }));
        }
        card.appendChild(foot);
      }

      if (opts.autofocus !== false) focusFirst(card);
      entry.onClose = opts.onClose;
      return card;
    });
  }

  function closeModal() {
    if (!stack.length) return false;
    stack[stack.length - 1].close();
    return true;
  }

  function hmModalOpen() {
    return stack.length > 0;
  }

  // Собственный диалог подтверждения: .confirm-card + .confirm-t.
  function askConfirm(message, onOk, opts) {
    opts = opts || {};
    return openDialog(function (entry) {
      var card = el('div', {
        class: 'confirm-card',
        attrs: { role: 'alertdialog', 'aria-modal': 'true',
                 'aria-label': cell(opts.title) || 'подтверждение' }
      });

      card.appendChild(el('header', { class: 'confirm-h modal-h' }, [
        el('span', { class: 'confirm-t modal-t' }, [
          el('i', { class: 'sig', text: '$' }),
          doc.createTextNode(' ' + cell(opts.title || 'подтверждение'))
        ])
      ]));
      card.appendChild(el('div', { class: 'confirm-b modal-b' }, [
        el('p', { class: 'confirm-t', text: cell(message) })
      ]));
      card.appendChild(el('footer', { class: 'confirm-f modal-f' }, [
        el('button', {
          class: 'btn-t ' + (opts.danger === false ? 'btn-t--ok' : 'btn-t--err'),
          type: 'button', text: '[' + (opts.okText || 'удалить') + ']',
          onclick: function () { if (onOk && onOk() !== false) entry.close(); }
        }),
        el('button', {
          class: 'btn-t', type: 'button', text: '[отмена]',
          onclick: function () { entry.close(); }
        })
      ]));

      focusFirst(card);
      entry.onClose = opts.onClose;
      return card;
    });
  }

  // ---- Уведомления ----
  var toastLive = 0;

  function toast(message, kind) {
    var host = hostFor('tui-toast-host', 'toasts');
    var node = el('div', {
      class: 'toast' + (kind ? ' toast--' + kind : ''),
      text: cell(message),
      attrs: { role: 'status', 'aria-live': 'polite' }
    });

    host.appendChild(node);
    toastLive++;
    // Больше пяти уведомлений одновременно не держим.
    while (toastLive > 5 && host.firstChild) {
      host.removeChild(host.firstChild);
      toastLive--;
    }

    WIN.setTimeout(function () {
      node.classList.add('is-out');
      WIN.setTimeout(function () {
        if (node.parentNode) node.parentNode.removeChild(node);
        toastLive--;
      }, 260);
    }, 3500);
    return node;
  }

  // ---- Форматтеры ----
  var fmt = {
    // 1ч30м — точная длительность, минуты всегда двузначные.
    sec: function (value) {
      var n = num(value, NaN);
      if (!isFinite(n) || n < 0) return DASH;
      var s = Math.round(n);
      var h = Math.floor(s / 3600);
      return h > 0 ? h + 'ч' + pad2(Math.floor((s % 3600) / 60)) + 'м' : Math.floor((s % 3600) / 60) + 'м';
    },

    // 45м / 1ч30м / 2ч — покороче, без нулей минут.
    hm: function (value) {
      var n = num(value, NaN);
      if (!isFinite(n) || n < 0) return DASH;
      var s = Math.round(n);
      var h = Math.floor(s / 3600);
      var m = Math.floor((s % 3600) / 60);
      if (h > 0) return m > 0 ? h + 'ч' + pad2(m) + 'м' : h + 'ч';
      return m + 'м';
    },

    // 2д 4ч — длинные интервалы.
    dur: function (value) {
      var n = num(value, NaN);
      if (!isFinite(n) || n < 0) return DASH;
      var s = Math.round(n);
      var d = Math.floor(s / 86400);
      var h = Math.floor((s % 86400) / 3600);
      if (d > 0) return h > 0 ? d + 'д ' + h + 'ч' : d + 'д';
      return fmt.hm(s);
    },

    // 08:40 — время суток.
    clock: function (value) {
      var n = num(value, NaN);
      if (!isFinite(n) || n < 0) return DASH;
      var minutes = Math.floor(Math.round(n) / 60) % 1440;
      return pad2(Math.floor(minutes / 60)) + ':' + pad2(minutes % 60);
    },

    // 68%
    pct: function (value) {
      var n = num(value, NaN);
      return isFinite(n) ? Math.round(n) + '%' : DASH;
    }
  };

  // ---- Экспорт ----
  // Экспорт называется confirm, но внутри это обычная функция askConfirm:
  // браузерных окон в этом приложении не существует.
  WIN.TUIW = {
    el: el, text: text, frag: frag, clear: clear, note: note, empty: empty,
    panel: panel, row: row, bar: bar, cbx: cbx, chip: chip, sec: sec,
    modal: modal, confirm: askConfirm, toast: toast,
    closeModal: closeModal, hmModalOpen: hmModalOpen, wbars: wbars, fmt: fmt
  };
})();