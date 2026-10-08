/* ===========================================================================
 * tui.js — оболочка терминального интерфейса CodeTime.
 *
 * Собирает window.TUI из примитивов window.TUIW (файл tui_widgets.js),
 * добавляя состояние, реестр экранов, верхнее меню, навигацию по панелям,
 * клавиатуру, футер, тему и сетевые обёртки.
 *
 * Порядок подключения фиксирован спецификацией: tui_widgets.js → tui.js →
 * screens.js. Обычные <script>, без модулей и без top-level await (§17).
 *
 * Внимание: window.prompt / alert / confirm в этом приложении не существуют
 * (§17.1) — используются только TUIW.modal и TUIW.confirm.
 *
 * Разметка верхнего меню, фокуса панели и курсора строки жёстко связана с
 * app.css: `.menu-brand > .brand`, `.beta`, `.menu-sep`, `.menu-list`, `.mi`,
 * `.menu-hints`, `.menu-more`, `panel is-focus`, `.trow--cur`.
 * Цвета нигде не хардкодятся — только классы и var(--x) из app.css.
 * =========================================================================== */
(function () {
  'use strict';

  /* =======================================================================
   * 0. Константы и мелкие утилиты
   * ===================================================================== */

  var W = window.TUIW || null;            // примитивы из tui_widgets.js
  var HAS_W = !!(W && typeof W.el === 'function');
  var THEME_KEY = 'codetime.theme';
  var COLLAPSED_KEY = 'codetime.collapsed';
  var MENU_MAX = 9;                       // цифры 1–9 в меню (§15)
  var PANEL_SEL = '.panel';
  /* Курсор получают только строки-задачи `.trow` и явная разметка `[data-row]`. */
  var ROW_SEL = '.trow, [data-row], .row[data-cursor]';
  var CMK_SEL = '.cmt, .row--cmt, .tui-cmt';

  function isCommentRow(el) {
    if (el.matches && el.matches(CMK_SEL)) return true;
    return (el.textContent || '').trim().indexOf('//') === 0;
  }

  function getStyle(el, prop) {
    try {
      return window.getComputedStyle(el).getPropertyValue(prop);
    } catch (e) {
      return '';
    }
  }

  function isVisible(el) {
    if (!el || !el.ownerDocument) return false;
    if (el.hidden) return false;
    var p = el.parentNode;
    while (p && p.nodeType === 1) {
      if (p.hidden) return false;
      if (getStyle(p, 'display') === 'none') return false;
      if (getStyle(p, 'visibility') === 'hidden') return false;
      p = p.parentNode;
    }
    return true;
  }

  function clampInt(v, min, max) {
    var n = Number(v);
    if (!isFinite(n)) return min;
    n = Math.round(n);
    if (n < min) return min;
    if (n > max) return max;
    return n;
  }

  function hasClass(el, name) {
    return (' ' + (el.className || '') + ' ').indexOf(' ' + name + ' ') >= 0;
  }

  function addClass(el, name) {
    if (!hasClass(el, name)) el.className = (el.className + ' ' + name).replace(/\s+/g, ' ').replace(/^\s/, '');
  }

  function delClass(el, name) {
    el.className = (' ' + (el.className || '') + ' ')
      .split(' ' + name + ' ').join(' ')
      .replace(/\s+/g, ' ').replace(/^\s+|\s+$/g, '');
  }

  /* Безопасная обёртка над localStorage: доступ может быть закрыт. */
  var store = {
    get: function (key, def) {
      try {
        var v = window.localStorage.getItem(key);
        return v === null ? def : v;
      } catch (e) {
        return def;
      }
    },
    set: function (key, val) {
      try {
        window.localStorage.setItem(key, val);
        return true;
      } catch (e) {
        return false;
      }
    }
  };

  /* Создание элемента. Основной путь — TUIW.el; аварийный минимум на случай,
   * если tui_widgets.js ещё не загружен (не даём оболочке упасть целиком). */
  function mkEl(tag, props, kids) {
    if (HAS_W) return W.el(tag, props, kids);
    var e = document.createElement(tag);
    if (props) {
      for (var k in props) {
        if (!Object.prototype.hasOwnProperty.call(props, k)) continue;
        var v = props[k];
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class' || k === 'className') e.className = v;
        else if (k === 'text') e.textContent = v;
        else if (k === 'style' && typeof v === 'object') { for (var s in v) e.style[s] = v[s]; }
        else if (k.indexOf('on') === 0 && typeof v === 'function') e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? '' : v);
      }
    }
    append(e, kids);
    return e;
  }

  function mkText(s) {
    if (HAS_W && typeof W.text === 'function') return W.text(s);
    return document.createTextNode(s === null || s === undefined ? '' : String(s));
  }

  function append(parent, kids) {
    if (!parent || kids === null || kids === undefined) return parent;
    if (!Array.isArray(kids)) kids = [kids];
    for (var i = 0; i < kids.length; i++) {
      var k = kids[i];
      if (k === null || k === undefined || k === false) continue;
      parent.appendChild(k.nodeType ? k : document.createTextNode(String(k)));
    }
    return parent;
  }

  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  function inField(t) {
    if (!t || !t.tagName) return false;
    var name = t.tagName.toLowerCase();
    if (name === 'input' || name === 'textarea' || name === 'select') return true;
    if (t.isContentEditable) return true;
    return !!(t.closest && t.closest('[contenteditable="true"],[contenteditable=""]'));
  }

  function isButtonish(t) {
    if (!t || !t.tagName) return false;
    var name = t.tagName.toLowerCase();
    if (name === 'button' || name === 'a' || name === 'summary') return true;
    return !!(t.closest && t.closest('button, a[href], summary'));
  }

  function report(err, where) {
    if (window.console && console.error) console.error('[TUI] ' + where + ':', err);
  }

  function normKey(ev) {
    var k = ev.key;
    if (k === ' ') return 'space';
    if (k === 'Escape') return 'esc';
    if (k === 'ArrowUp') return 'up';
    if (k === 'ArrowDown') return 'down';
    if (k === 'ArrowLeft') return 'left';
    if (k === 'ArrowRight') return 'right';
    if (k === 'Enter') return 'enter';
    if (k === 'Tab') return 'tab';
    return String(k || '').toLowerCase();
  }

  /* =======================================================================
   * 1. Состояние
   * ===================================================================== */

  var TUI = {
    state: {
      screen: null,      // id активного экрана
      settings: {},      // настройки (заполняет экран «настройки»)
      data: {},          // загруженные данные экранов: data[screenId]
      focus: { panel: 0, row: 0, on: true }
    },
    screens: {},         // id -> описание экрана
    order: [],          // id в порядке регистрации = порядок меню (§4)
    booted: false
  };

  /* =======================================================================
   * 2. Каркас страницы (§3)
   * ===================================================================== */

  function ensureSkeleton() {
    var host = document.getElementById('tui');
    if (!host) {
      host = mkEl('div', { id: 'tui', class: 'tui' });
      document.body.appendChild(host);
    }
    addClass(host, 'tui');

    var menu = document.getElementById('tuiMenu');
    if (!menu) {
      menu = mkEl('div', { id: 'tuiMenu', class: 'tui-menu', role: 'menubar' });
      host.appendChild(menu);
    }

    var body = document.getElementById('tuiBody');
    if (!body) {
      body = mkEl('div', { id: 'tuiBody', class: 'tui-body' });
      host.appendChild(body);
    }

    /* Три колонки. Класс `tui-col--mid` дублируется для совместимости с §3. */
    ['left', 'middle', 'right'].forEach(function (side) {
      var col = document.querySelector('#tuiBody .tui-col--' + side);
      if (!col) {
        col = mkEl('div', {
          class: 'tui-col tui-col--' + side + (side === 'middle' ? ' tui-col--mid' : '')
        });
        body.appendChild(col);
      }
    });

    var footer = document.getElementById('tuiFooter');
    if (!footer) {
      footer = mkEl('div', { id: 'tuiFooter', class: 'tui-footer' });
      host.appendChild(footer);
    }
    return { host: host, menu: menu, body: body, footer: footer };
  }

  var dom = { host: null, menu: null, body: null, footer: null, list: null, more: null };

  /* Доступ к колонкам: 'left' | 'middle' | 'right' (или l/m/r). */
  TUI.col = function (side) {
    var map = {
      l: 'left', left: 'left', m: 'middle', mid: 'middle', middle: 'middle',
      r: 'right', right: 'right'
    };
    var key = map[String(side === undefined ? 'm' : side).toLowerCase()] || 'middle';
    return document.querySelector('#tuiBody .tui-col--' + key);
  };
  TUI.cols = function () {
    return Array.prototype.slice.call(document.querySelectorAll('#tuiBody .tui-col'));
  };

  /* =======================================================================
   * 3. Тема (§2)
   * ===================================================================== */

  function prefersLight() {
    try {
      return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches);
    } catch (e) {
      return false;
    }
  }

  function currentTheme() {
    var t = store.get(THEME_KEY, null);
    if (t !== 'light' && t !== 'dark') t = prefersLight() ? 'light' : 'dark';
    return t;
  }

  function applyTheme(t) {
    if (t !== 'light' && t !== 'dark') t = prefersLight() ? 'light' : 'dark';
    var root = document.documentElement;
    if (root.setAttribute) root.setAttribute('data-theme', t);
    else root.dataTheme = t;
    store.set(THEME_KEY, t);
    TUI.state.theme = t;
    if (dom.host) dom.host.setAttribute('data-theme', t);
    var btn = document.querySelector('#tuiFooter .tui-theme');
    if (btn) {
      btn.textContent = t === 'dark' ? '☾ тёмная' : '☀ светлая';
      btn.setAttribute('title', 'сменить тему');
    }
    return t;
  }

  TUI.theme = function () { return TUI.state.theme || currentTheme(); };
  TUI.setTheme = applyTheme;
  TUI.toggleTheme = function () {
    var next = TUI.theme() === 'dark' ? 'light' : 'dark';
    toast('тема: ' + (next === 'dark' ? 'тёмная' : 'светлая'));
    return applyTheme(next);
  };

  /* Свернутые секции §12: localStorage['codetime.collapsed'] — переживает перезагрузку. */
  TUI.isCollapsed = function (key) {
    var raw = store.get(COLLAPSED_KEY, '') || '';
    if (!raw) return false;
    return raw.indexOf('|' + key + '|') >= 0;
  };

  TUI.setCollapsed = function (key, on) {
    var raw = store.get(COLLAPSED_KEY, '') || '';
    var parts = raw.split('|').filter(function (s) { return !!s; });
    var name = String(key);
    var at = parts.indexOf(name);
    if (on && at < 0) parts.push(name);
    if (!on && at >= 0) parts.splice(at, 1);
    store.set(COLLAPSED_KEY, '|' + parts.join('|') + '|');
    if (dom.body) applySectionState(dom.body, key, !!on);
    return !!on;
  };

  TUI.toggleCollapsed = function (key) {
    return TUI.setCollapsed(key, !TUI.isCollapsed(key));
  };

  /* Найти `.sec-b` рядом с кнопкой `.sec`. */
  function sectionBody(secBtn) {
    if (!secBtn) return null;
    var sib = secBtn.nextElementSibling;
    while (sib && !hasClass(sib, 'sec-b')) {
      if (sib.tagName && sib.tagName.toLowerCase() === 'button') break;
      sib = sib.nextElementSibling;
    }
    return (sib && hasClass(sib, 'sec-b')) ? sib : null;
  }

  function sectionKey(secBtn, key) {
    if (key) return String(key);
    if (secBtn && secBtn.getAttribute) {
      return secBtn.getAttribute('data-sec') ||
        secBtn.getAttribute('data-key') ||
        (secBtn.textContent || '').trim().replace(/\s+/g, '-').toLowerCase();
    }
    return 'sec';
  }

  /* Развернуть/свернуть секцию: aria-expanded на кнопке + показ `.sec-b`. */
  function applySectionState(root, key, collapsed) {
    var secs = (root || document).querySelectorAll('.sec');
    for (var i = 0; i < secs.length; i++) {
      if (sectionKey(secs[i]) !== String(key)) continue;
      secs[i].setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      secs[i].setAttribute('data-collapsed', collapsed ? '1' : '0');
      var b = sectionBody(secs[i]);
      if (b) {
        b.hidden = collapsed;
        b.style.display = collapsed ? 'none' : '';
        b.setAttribute('aria-hidden', collapsed ? 'true' : 'false');
      }
    }
  }

  /* Навесить сворачивание на все секции внутри контейнера. */
  TUI.bindSections = function (root, keys) {
    var scope = root || dom.body || document;
    var map = {};
    if (keys) {
      for (var k in keys) if (Object.prototype.hasOwnProperty.call(keys, k)) map[k] = keys[k];
    }
    var secs = scope.querySelectorAll('.sec');
    for (var i = 0; i < secs.length; i++) {
      (function (btn) {
        var key = sectionKey(btn);
        btn.setAttribute('aria-expanded', TUI.isCollapsed(key) ? 'false' : 'true');
        btn.setAttribute('data-collapsed', TUI.isCollapsed(key) ? '1' : '0');
        var b = sectionBody(btn);
        if (b) b.hidden = TUI.isCollapsed(key);
        if (btn.getAttribute('data-tui-bound') === '1') return;
        btn.setAttribute('data-tui-bound', '1');
        btn.setAttribute('type', 'button');
        btn.addEventListener('click', function (ev) {
          ev.preventDefault();
          var k2 = sectionKey(btn);
          var next = !TUI.isCollapsed(k2);
          TUI.setCollapsed(k2, next);
          applySectionState(btn.parentNode || dom.body, k2, next);
          if (typeof map[k2] === 'function') map[k2](next, btn);
        }, false);
      }(secs[i]));
    }
    return secs.length;
  };

  /* =======================================================================
   * 4. Сообщения: загрузка, ошибка, всплывающие уведомления
   * ===================================================================== */

  function toast(text, kind) {
    if (HAS_W && typeof W.toast === 'function') {
      try { return W.toast(text, kind || 'info'); } catch (e) { /* запасной путь */ }
    }
    var t = mkEl('div', { class: 'tui-toast' + (kind ? ' is-' + kind : ''), text: text });
    document.body.appendChild(t);
    window.setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 3500);
    return t;
  }
  TUI.toast = toast;

  function hostBox(cls, root) {
    var box = mkEl('div', { class: 'tui-msg ' + cls });
    var cols = TUI.cols();
    var target = cols.length ? cols[Math.min(1, cols.length - 1)] : (root || dom.body);
    if (target) target.appendChild(box);
    return box;
  }

  /* Строка загрузки — вместо пустого экрана (§19). */
  TUI.loading = function (root, text) {
    if (!dom.body) return null;
    var box = hostBox('tui-msg--load', root);
    box.appendChild(mkEl('div', { class: 'tui-msg-t dim', text: '~ ' + (text || 'загрузка данных…') }));
    return box;
  };

  /* Читаемая русская ошибка вместо исключения наружу (§19). */
  TUI.fail = function (root, err, retry) {
    if (!dom.body) return null;
    var box = hostBox('tui-msg--err', root);
    var msg = (err && err.message) ? err.message : String(err || 'неизвестная ошибка');
    box.appendChild(mkEl('div', { class: 'tui-msg-t red', text: '! ошибка загрузки данных' }));
    box.appendChild(mkEl('div', { class: 'tui-msg-s dim', text: msg }));
    if (typeof retry === 'function') {
      box.appendChild(mkEl('button', {
        class: 'btn-t tui-msg-b', type: 'button', text: 'повторить',
        onclick: function () { retry(); }
      }));
    }
    return box;
  };

  /* =======================================================================
   * 5. Реестр экранов и переходы (§4, §19)
   * ===================================================================== */

  TUI.reg = function (id, def) {
    if (!id) return null;
    def = def || {};
    def.id = id;
    if (!TUI.screens[id]) TUI.order.push(id);
    TUI.screens[id] = def;
    buildMenu();
    /* Экран зарегистрировался уже активным — показываем его сразу. */
    if (TUI.state.screen === id && dom.booted) TUI.go(id, true);
    return def;
  };

  TUI.unreg = function (id) {
    delete TUI.screens[id];
    var i = TUI.order.indexOf(id);
    if (i >= 0) TUI.order.splice(i, 1);
    buildMenu();
  };

  TUI.current = function () {
    return TUI.state.screen ? TUI.screens[TUI.state.screen] || null : null;
  };

  /* Ручная перезагрузка активного экрана — клавиша `r`. */
  TUI.refresh = function () {
    if (!TUI.state.screen) return Promise.resolve(null);
    return TUI.go(TUI.state.screen, true);
  };

  var loadToken = 0; /* защита от гонки при быстром переключении экранов */

  TUI.go = function (id, force) {
    var def = TUI.screens[id];
    if (!def) {
      toast('нет экрана «' + id + '»', 'err');
      return Promise.resolve(null);
    }

    TUI.state.screen = id;
    TUI.state.focus = { panel: 0, row: 0, on: true };
    if (dom.body) dom.body.setAttribute('data-screen', id);
    markMenu(id);
    TUI.setFooterKeys(null);

    var root = dom.body;
    var cached = TUI.state.data[id];

    /* Данные уже есть — перерисовываем без повторного запроса (§4). */
    if (!force && cached !== undefined && cached !== null) {
      safeRender(def, cached, root);
      TUI.layout();
      return Promise.resolve(cached);
    }

    TUI.loading(root, def.title ? 'загрузка: ' + def.title : 'загрузка данных…');
    var myToken = ++loadToken;

    var p;
    try {
      p = typeof def.load === 'function' ? def.load(TUI.state) : Promise.resolve(null);
    } catch (e) {
      return failScreen(def, root, e);
    }
    if (!p || typeof p.then !== 'function') p = Promise.resolve(p);

    return p.then(function (data) {
      if (myToken !== loadToken) return null;      /* экран успели переключить */
      TUI.state.data[id] = data;                  /* §19: кладём в state.data */
      safeRender(def, data, root);
      TUI.layout();
      return data;
    }, function (err) {
      if (myToken !== loadToken) return null;
      return failScreen(def, root, err);
    });
  };

  function failScreen(def, root, err) {
    var msg = (err && err.message) ? err.message : String(err || 'неизвестная ошибка');
    try {
      TUI.fail(root, err, function () { TUI.go(def.id, true); });
    } catch (e) { /* экран всё равно остаётся валидным */ }
    toast('не удалось загрузить «' + (def.title || def.id) + '»: ' + msg, 'err');
    report(err, 'экран ' + def.id);
    return null;
  }

  function safeRender(def, data, root) {
    if (typeof def.render !== 'function') {
      TUI.fail(root, new TypeError('экран «' + (def.title || def.id) + '» не умеет рисовать'));
      return;
    }
    try {
      def.render(data === undefined ? null : data, root, TUI);
    } catch (e) {
      var msg = (e && e.message) ? e.message : String(e);
      try {
        TUI.fail(root, e, function () { TUI.go(def.id, true); });
      } catch (e2) { /* пусто */ }
      toast('сбой отрисовки «' + (def.title || def.id) + '»: ' + msg, 'err');
      report(e, 'отрисовка ' + def.id);
      return;
    }
    /* Секции внутри отрисованного экрана получают сворачивание (§12). */
    try { TUI.bindSections(root); } catch (e3) { report(e3, 'секции ' + def.id); }
    /* Футер показывает клавиши активного экрана, если он их задал (§15). */
    TUI.setFooterKeys(keysOfDef(def));
  }

  /* =======================================================================
   * 6. Верхнее меню (§4) — разметка под app.css:
   *    .menu-brand > .brand (только буква h) + .beta + .menu-list > .mi
   * ===================================================================== */

  function buildMenu() {
    if (!dom.menu) return;
    clear(dom.menu);
    dom.list = mkEl('span', { class: 'menu-list' });
    dom.more = null;

    dom.menu.appendChild(mkEl('button', {
      class: 'menu-brand', type: 'button', title: 'справка (?)',
      onclick: function () { TUI.help(); }
    }, [
      /* Рамку `[ ]` рисует CSS — внутрь кладём только букву. */
      mkEl('span', { class: 'brand', text: 'h' }),
      mkText(' codetime '),
      mkEl('span', { class: 'beta', text: '[beta]' })
    ]));

    TUI.order.forEach(function (id, i) {
      var def = TUI.screens[id] || {};
      dom.list.appendChild(mkEl('span', { class: 'menu-sep', text: '·' }));
      dom.list.appendChild(mkEl('button', {
        class: 'mi', type: 'button', 'data-id': id, title: def.title || id,
        onclick: function () { TUI.go(id); }
      }, [
        mkText(def.title || id),
        i < MENU_MAX
          ? mkEl('span', { class: 'menu-hints' }, [mkEl('kbd', { text: String(i + 1) })])
          : null
      ]));
    });
    dom.menu.appendChild(dom.list);

    /* Узкий экран: список свёрнут, пока не нажата эта кнопка (<1000px). */
    dom.more = mkEl('button', {
      class: 'menu-more', type: 'button', title: 'меню', text: '≡ меню',
      onclick: function () { TUI.toggleMenu(); }
    });
    dom.menu.appendChild(dom.more);

    markMenu(TUI.state.screen);
    if (window.innerWidth < 1000) TUI.closeMenu();
  }

  function markMenu(id) {
    var items = document.querySelectorAll('#tuiMenu .mi');
    for (var i = 0; i < items.length; i++) {
      var on = items[i].getAttribute('data-id') === id;
      if (on) {
        addClass(items[i], 'is-on');
        items[i].setAttribute('aria-current', 'page');
      } else {
        delClass(items[i], 'is-on');
        items[i].removeAttribute('aria-current'); /* селектор [aria-current] в CSS */
      }
    }
  }

  /* Раскрытие/скрытие меню: только класс `is-open` на `.tui-menu`,
   * показом `.menu-list` занимается CSS. Инлайновые display не ставим. */
  TUI.toggleMenu = function () {
    if (!dom.menu) return;
    if (hasClass(dom.menu, 'is-open')) TUI.closeMenu();
    else addClass(dom.menu, 'is-open');
  };
  TUI.closeMenu = function () {
    if (dom.menu) delClass(dom.menu, 'is-open');
  };
  TUI.openMenu = function () {
    if (dom.menu) addClass(dom.menu, 'is-open');
  };

  TUI.gotoIndex = function (i) {
    var ids = TUI.order;
    if (!ids.length) return;
    /* Цифры 1–9 — прямой выбор, без циклического перебора (§15). */
    TUI.go(ids[clampInt(i, 0, Math.min(ids.length, MENU_MAX) - 1)]);
  };

  TUI.step = function (delta) {
    var ids = TUI.order;
    if (!ids.length) return;
    var cur = ids.indexOf(TUI.state.screen);
    if (cur < 0) cur = 0;
    var next = cur + (delta < 0 ? -1 : 1);
    if (next < 0) next = ids.length - 1;
    if (next >= ids.length) next = 0;
    TUI.go(ids[next]);
  };

  /* =======================================================================
   * 7. Фокус панели и курсор строки (§15) — оформление целиком в app.css:
   *    активная панель получает класс `is-focus`, строка — `trow--cur`.
   * ===================================================================== */

  TUI.panels = function (root) {
    var r = root || dom.body || document;
    var all = r.querySelectorAll(PANEL_SEL);
    var out = [];
    for (var i = 0; i < all.length; i++) {
      if (!isVisible(all[i])) continue;   /* скрытые app.css панели не в счёт */
      out.push(all[i]);
    }
    return out;
  };

  TUI.rowsOf = function (panel) {
    if (!panel) return [];
    var all = panel.querySelectorAll(ROW_SEL);
    var out = [];
    for (var i = 0; i < all.length; i++) {
      if (isCommentRow(all[i])) continue;
      if (all[i].getAttribute('data-nocursor') !== null) continue;
      if (!isVisible(all[i])) continue;
      out.push(all[i]);
    }
    return out;
  };

  var lastPanel = null;
  var lastRow = null;

  function setCursor(row, on) {
    if (!row) return;
    if (on) {
      addClass(row, 'trow--cur');
      row.setAttribute('aria-selected', 'true');
    } else {
      delClass(row, 'trow--cur');
      row.removeAttribute('aria-selected');
    }
  }

  function setFocusPanel(panel, on) {
    if (!panel) return;
    if (on) {
      addClass(panel, 'is-focus');
      panel.setAttribute('data-focus', '1');
    } else {
      delClass(panel, 'is-focus');
      panel.removeAttribute('data-focus');
    }
  }

  function paint() {
    var f = TUI.state.focus;
    var panels = TUI.panels();
    if (!panels.length) { clearFocus(); return; }

    if (lastPanel && lastPanel !== panels[f.panel]) setFocusPanel(lastPanel, false);
    var panel = panels[clampInt(f.panel, 0, panels.length - 1)];
    f.panel = panels.indexOf(panel);
    setFocusPanel(panel, true);

    var rows = TUI.rowsOf(panel);
    if (lastRow && rows.indexOf(lastRow) < 0) setCursor(lastRow, false);
    lastPanel = panel;

    if (!rows.length) {               /* панель без курсорных строк — только рамка */
      lastRow = null;
      f.row = 0;
      return;
    }
    var row = rows[clampInt(f.row, 0, rows.length - 1)];
    f.row = rows.indexOf(row);
    setCursor(row, true);
    scrollTo(row);
    lastRow = row;
  }

  function scrollTo(node) {
    if (!node || !node.scrollIntoView) return;
    try {
      node.scrollIntoView({ block: 'nearest' });
    } catch (e) {
      try { node.scrollIntoView(false); } catch (e2) { /* пусто */ }
    }
  }

  function clearFocus() {
    if (lastPanel) setFocusPanel(lastPanel, false);
    if (lastRow) setCursor(lastRow, false);
    lastPanel = null;
    lastRow = null;
    TUI.state.focus.on = false;
  }

  TUI.focusPanel = function (i) {
    var panels = TUI.panels();
    if (!panels.length) return;
    var cur = clampInt(TUI.state.focus.panel, 0, panels.length - 1);
    var want = (i === undefined ? cur + 1 : i);
    var next = ((want % panels.length) + panels.length) % panels.length;
    TUI.state.focus.panel = next;
    TUI.state.focus.row = 0;
    TUI.state.focus.on = true;
    paint();
  };

  TUI.movePane = function (delta) {
    TUI.state.focus.on = true;
    TUI.focusPanel((TUI.state.focus.panel || 0) + (delta < 0 ? -1 : 1));
  };

  TUI.moveRow = function (delta) {
    var panels = TUI.panels();
    if (!panels.length) return;
    var panel = panels[clampInt(TUI.state.focus.panel, 0, panels.length - 1)];
    var rows = TUI.rowsOf(panel);
    if (!rows.length) return;
    var cur = clampInt(TUI.state.focus.row, 0, rows.length - 1);
    TUI.state.focus.row = (cur + (delta < 0 ? -1 : 1) + rows.length) % rows.length;
    TUI.state.focus.on = true;
    paint();
  };

  TUI.focusedRow = function () {
    var panels = TUI.panels();
    if (!panels.length) return null;
    var panel = panels[clampInt(TUI.state.focus.panel, 0, panels.length - 1)];
    var rows = TUI.rowsOf(panel);
    if (!rows.length) return null;
    return rows[clampInt(TUI.state.focus.row, 0, rows.length - 1)];
  };

  /* Enter / Space — переключить строку в фокусе (§15). */
  TUI.activate = function () {
    var row = TUI.focusedRow();
    if (!row) return false;
    var ev = null;
    try {
      ev = new CustomEvent('tui:activate', {
        bubbles: true, cancelable: true, detail: { row: row }
      });
    } catch (e) { ev = null; }
    if (ev) {
      row.dispatchEvent(ev);
      if (ev.defaultPrevented) return true;   /* экран обработал сам */
    }
    var hit = row.querySelector('.cbx, [data-action], button, a[href]') ||
      (row.tagName === 'BUTTON' ? row : null);
    if (hit && typeof hit.click === 'function') { hit.click(); return true; }
    return false;
  };

  TUI.repaint = paint;

  /* =======================================================================
   * 8. Футер и подсказки (§15)
   * ===================================================================== */

  var GLOBAL_KEYS = [
    { keys: '1…9', text: 'экран' },
    { keys: '← →', text: 'соседний' },
    { keys: 'tab', text: 'панель' },
    { keys: '↑ ↓', text: 'строка' },
    { keys: 'enter', text: 'переключить' },
    { keys: 'esc', text: 'снять фокус' },
    { keys: 'a', text: 'задача' },
    { keys: 'd', text: 'пауза' },
    { keys: 'r', text: 'обновить' },
    { keys: 't', text: 'тема' },
    { keys: '?', text: 'помощь' }
  ];
  TUI.globalKeys = GLOBAL_KEYS;

  var footerKeys = null;

  function keyLine(list) {
    var line = mkEl('span', { class: 'tui-fk' });
    list.forEach(function (k, i) {
      if (i) line.appendChild(mkText('·'));
      line.appendChild(mkEl('kbd', { class: 'tui-k', text: k.keys || k.k || '' }));
      if (k.text) line.appendChild(mkEl('span', { class: 'dim', text: ' ' + k.text }));
      line.appendChild(mkText(' '));
    });
    return line;
  }

  function drawFooter() {
    if (!dom.footer) return;
    clear(dom.footer);
    dom.footer.appendChild(mkEl('span', { class: 'tui-footer-hints grow' }, [
      keyLine(footerKeys && footerKeys.length ? footerKeys : GLOBAL_KEYS)
    ]));
    dom.footer.appendChild(mkEl('button', {
      class: 'tui-theme btn-t', type: 'button', text: '',
      title: 'сменить тему',
      onclick: function () { TUI.toggleTheme(); }
    }));
    applyTheme(TUI.state.theme || currentTheme());
  }

  /* Экран может подменить подсказки своим keymap. */
  TUI.setFooterKeys = function (keys) {
    footerKeys = (keys && keys.length) ? keys : null;
    drawFooter();
  };

  function keysOfDef(def) {
    if (!def) return null;
    if (Array.isArray(def.keys) && def.keys.length) return def.keys;
    /* keymap — это обработчики нажатий, а не подписи для футера. Раньше отсюда
       брались ключи, из-за чего футер на экране с keymap показывал три буквы
       (`r · c · n` — навигация по месяцам) и терял все описания глобальных
       клавиш. Экран без своих `keys` получает глобальный список. */
    return null;
  }

  /* =======================================================================
   * 9. Модалки и справка `?` (§16) — только TUIW.modal/confirm, без alert (§17.1)
   * ===================================================================== */

  var ownModals = [];   /* наши запасные оверлеи, если TUIW.modal недоступен */

  function modalByWidgets() {
    if (HAS_W && typeof W.hmModalOpen === 'function') {
      try { return !!W.hmModalOpen(); } catch (e) { /* запасная проверка */ }
    }
    return false;
  }

  function modalOpen() {
    if (ownModals.length) return true;
    if (HAS_W) return modalByWidgets();
    return !!document.querySelector('.modal-bd.is-open, .tui-modal-back');
  }

  TUI.modalOpen = modalOpen;

  /* Запасной оверлей в разметке app.css: .modal-bd / .modal-card / .modal-h / .modal-b */
  function ownModal(opt) {
    var bd = mkEl('div', { class: 'modal-bd' });
    var card = mkEl('div', { class: 'modal-card' }, [
      mkEl('div', { class: 'modal-h' }, [
        mkEl('i', { class: 'sig gold', text: '$' }),
        mkEl('span', { class: 'modal-t', text: ' ' + (opt.title || '') }),
        mkEl('span', { class: 'grow' }),
        mkEl('button', {
          class: 'modal-x', type: 'button', text: '×', title: 'закрыть',
          onclick: function () { TUI.closeModal(); }
        })
      ]),
      mkEl('div', { class: 'modal-b' }, opt.body || null)
    ]);
    bd.appendChild(card);
    bd.addEventListener('mousedown', function (e) {
      if (e.target === bd) TUI.closeModal();
    });
    document.body.appendChild(bd);
    ownModals.push(bd);
    return bd;
  }

  TUI.modal = function (opt) {
    if (HAS_W && typeof W.modal === 'function') {
      try { return W.modal(opt); } catch (e) { /* запасной оверлей */ }
    }
    return ownModal(opt);
  };

  TUI.closeModal = function () {
    if (ownModals.length) {
      var m = ownModals.pop();
      if (m && m.parentNode) m.parentNode.removeChild(m);
      return;
    }
    if (HAS_W && typeof W.closeModal === 'function') {
      try { return W.closeModal(); } catch (e) { /* пусто */ }
    }
  };

  /* Ссылка на диалог подтверждения из TUIW хранится отдельно: в коде этого
   * файла нет ни одного вызова браузерных alert/prompt/confirm (§17.1, §20.2). */
  var askUser = (HAS_W && typeof W.confirm === 'function') ? W.confirm : null;

  TUI.confirm = function (text, onOk) {
    if (askUser) return askUser(text, onOk);
    return TUI.modal({
      title: 'подтверждение',
      body: [
        mkEl('div', { class: 'pre', text: text }),
        mkEl('div', { class: 'right' }, [
          mkEl('button', {
            class: 'btn-t', type: 'button', text: 'отмена',
            onclick: function () { TUI.closeModal(); }
          }),
          mkEl('button', {
            class: 'btn-t red', type: 'button', text: 'подтвердить',
            onclick: function () { TUI.closeModal(); if (onOk) onOk(); }
          })
        ])
      ]
    });
  };

  /* `?` — палитра подсказок со всеми сочетаниями (§15). */
  TUI.help = function () {
    var def = TUI.current();
    var body = mkEl('div', { class: 'tui-help' });
    body.appendChild(mkEl('div', { class: 'sec-t dim', text: 'общие клавиши' }));
    body.appendChild(keyTable(GLOBAL_KEYS));
    var own = keysOfDef(def);
    if (own && own.length) {
      body.appendChild(mkEl('div', {
        class: 'sec-t dim', text: 'экран «' + (def.title || def.id) + '»'
      }));
      body.appendChild(keyTable(own));
    }
    body.appendChild(mkEl('div', {
      class: 'faint', text: 'любое действие с клавиатуры дублируется мышью'
    }));
    TUI.modal({ title: 'справка', body: body });
  };

  function keyTable(list) {
    var t = mkEl('div', { class: 'tui-help-t' });
    list.forEach(function (k) {
      t.appendChild(mkEl('div', { class: 'tui-help-r' }, [
        mkEl('kbd', { class: 'tui-k', text: k.keys || k.k || '' }),
        mkEl('span', { class: 'dim', text: k.text || '' })
      ]));
    });
    return t;
  }

  /* =======================================================================
   * 10. Клавиатура (§15)
   *
   * Главные правила (§15, п. «Правила»):
   *   — внутри input/textarea/select глобальные клавиши НЕ перехватываются;
   *   — при открытой модалке работает только Esc.
   * ===================================================================== */

  var keySubs = [];

  TUI.onKey = function (fn) {
    if (typeof fn !== 'function') return function () { };
    keySubs.push(fn);
    return function () {
      var i = keySubs.indexOf(fn);
      if (i >= 0) keySubs.splice(i, 1);
    };
  };

  /* keymap экрана перекрывает глобальные клавиши. */
  function screenKeymap(def, ev) {
    var km = def && def.keymap;
    if (!km) return false;
    if (typeof km === 'function') {
      try { return !!km(ev, TUI); } catch (e) { report(e, 'keymap'); return false; }
    }
    if (typeof km === 'object') {
      var k = normKey(ev);
      var fn = km[k] || km[ev.key] || km[ev.code];
      if (typeof fn === 'function') {
        try { return !!fn(ev, TUI); } catch (e) { report(e, 'keymap'); return false; }
      }
    }
    return false;
  }

  function onKeyDown(ev) {
    /* Ctrl/Alt/Meta — это уже не «наши» клавиши. */
    if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
    if (ev.isComposing) return;

    /* Открыта модалка: работает только Esc (§15). */
    if (ownModals.length) {
      if (ev.key === 'Escape') { TUI.closeModal(); ev.preventDefault(); ev.stopPropagation(); }
      return;
    }
    /* При наличии TUIW доверяем его hmModalOpen(); иначе смотрим разметку. */
    if (HAS_W ? modalByWidgets() : !!document.querySelector('.modal-bd.is-open, .tui-modal-back')) {
      if (ev.key === 'Escape') ev.stopPropagation();  /* закрывает сама TUIW */
      return;
    }

    /* Фокус в поле ввода/выбора — глобальные клавиши молчат. */
    if (inField(ev.target)) {
      if (ev.key === 'Escape' && ev.target && typeof ev.target.blur === 'function') ev.target.blur();
      return;
    }

    var def = TUI.current();

    /* 1. keymap экрана. */
    if (screenKeymap(def, ev)) { ev.preventDefault(); return; }

    /* 2. Подписки экранов (TUI.onKey). */
    for (var i = 0; i < keySubs.length; i++) {
      var done = false;
      try { done = !!keySubs[i](ev, TUI); } catch (e) { report(e, 'onKey'); }
      if (done) { ev.preventDefault(); return; }
    }

    /* 3. Глобальные клавиши. */
    var k = normKey(ev);

    if (/^[1-9]$/.test(String(ev.key))) {
      TUI.gotoIndex(Number(ev.key) - 1);
      ev.preventDefault();
      return;
    }

    switch (k) {
      case 'left':
        TUI.step(-1);
        ev.preventDefault();
        return;
      case 'right':
        TUI.step(1);
        ev.preventDefault();
        return;
      case 'tab':
        TUI.movePane(ev.shiftKey ? -1 : 1);
        dropFocus();
        ev.preventDefault();
        return;
      case 'up':
        TUI.moveRow(-1);
        ev.preventDefault();
        return;
      case 'down':
        TUI.moveRow(1);
        ev.preventDefault();
        return;
      case 'enter':
      case 'space':
        /* На настоящей кнопке или ссылке работает нативное поведение. */
        if (isButtonish(ev.target)) return;
        if (TUI.activate()) ev.preventDefault();
        return;
      case 'esc':
        clearFocus();
        TUI.closeMenu();
        ev.preventDefault();
        return;
      case 'a':
        if (def && typeof def.onAdd === 'function') {
          def.onAdd(TUI);
          ev.preventDefault();
        } else {
          toast('экран «' + (def ? (def.title || def.id) : '?') + '» не умеет добавлять');
        }
        return;
      case 'd':
        TUI.trackingToggle();
        ev.preventDefault();
        return;
      case 'r':
        TUI.refresh();
        ev.preventDefault();
        return;
      case 't':
        TUI.toggleTheme();
        ev.preventDefault();
        return;
      case '?':
        TUI.help();
        ev.preventDefault();
        return;
      case '/':
        if (ev.shiftKey) { TUI.help(); ev.preventDefault(); }
        return;
      default:
        return;
    }
  }

  /* Убираем настоящий DOM-фокус с кнопок, чтобы Space не срабатывал повторно. */
  function dropFocus() {
    var a = document.activeElement;
    if (a && a !== document.body && dom.host && dom.host.contains(a)) {
      try { a.blur(); } catch (e) { /* пусто */ }
    }
  }

  /* Пауза / возобновление отслеживания — клавиша `d`. */
  TUI.trackingToggle = function () {
    var url = (TUI.state.settings && TUI.state.settings.trackingUrl) || '/api/tracking/toggle';
    TUI.post(url, {}).then(function (d) {
      var paused = d ? (d.paused !== undefined ? d.paused : !d.tracking) : false;
      TUI.toast(paused ? 'отслеживание остановлено' : 'отслеживание идёт');
      TUI.refresh();
    }, function (e) {
      TUI.toast(e.message, 'err');
    });
  };

  /* =======================================================================
   * 11. Раскладка и resize (§3)
   * ===================================================================== */

  var resizeSubs = [];
  var resizeTimer = 0;

  TUI.onResize = function (fn) {
    if (typeof fn === 'function') {
      resizeSubs.push(fn);
      return function () {
        var i = resizeSubs.indexOf(fn);
        if (i >= 0) resizeSubs.splice(i, 1);
      };
    }
    /* Без аргумента — пересчитать сейчас и оповестить подписчиков. */
    TUI.layout();
    fireResize();
  };

  function fireResize() {
    var b = TUI.bucket();
    for (var i = 0; i < resizeSubs.length; i++) {
      try { resizeSubs[i](b); } catch (e) { report(e, 'onResize'); }
    }
  }

  TUI.bucket = function () {
    var w = window.innerWidth || (document.documentElement.clientWidth || 0);
    if (w >= 1400) return 'lg';
    if (w >= 1000) return 'md';
    if (w >= 720) return 'sm';
    return 'xs';
  };

  /* Горизонтальной прокрутки быть не должно даже на 320px. */
  function guardOverflow(el, value) {
    if (!el) return;
    if (getStyle(el, 'overflow-x') === 'visible') el.style.overflowX = value;
  }

  TUI.layout = function () {
    if (!dom.host) return TUI.bucket();
    var b = TUI.bucket();
    dom.host.setAttribute('data-w', b);
    document.documentElement.setAttribute('data-w', b);

    TUI.cols().forEach(function (c) { c.style.minWidth = '0'; });
    guardOverflow(dom.body, 'hidden');
    guardOverflow(dom.host, 'hidden');
    if (dom.menu && getStyle(dom.menu, 'overflow-x') === 'visible') dom.menu.style.overflowX = 'auto';

    /* На широком экране список меню всегда раскрыт. */
    if (window.innerWidth >= 1000) TUI.closeMenu();

    paint();
    return b;
  };

  function onResize() {
    if (resizeTimer) window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(function () {
      resizeTimer = 0;
      TUI.layout();
      fireResize();
    }, 90);
  }

  /* =======================================================================
   * 12. Сеть: TUI.api / TUI.post (§17.3 — только локальный адрес)
   * ===================================================================== */

  var LOCAL_RE = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(\/|$|\?)/i;

  function safeUrl(path) {
    var p = String(path === null || path === undefined ? '' : path);
    if (/^https?:\/\//i.test(p)) {
      if (!LOCAL_RE.test(p)) {
        throw new TypeError('запрошен запрещённый адрес: приложение работает только с 127.0.0.1');
      }
      return p;
    }
    /* Любая другая схема (file:, python:, data:) — отклоняем (§17.3). */
    if (/^[a-z][a-z0-9+.\-]*:/i.test(p)) {
      throw new TypeError('запрещённая схема в адресе запроса: ' + p.split(':')[0]);
    }
    return p.charAt(0) === '/' ? p : '/' + p;
  }

  function netError(path, msg, status, payload) {
    var e = new TypeError(msg);
    e.tui = true;
    e.path = path;
    e.status = status || 0;
    e.payload = payload === undefined ? null : payload;
    return e;
  }

  function readBody(res) {
    return res.text().then(function (txt) {
      if (!txt) return null;
      try { return JSON.parse(txt); } catch (e) { return null; }
    });
  }

  function send(path, method, body, opts) {
    opts = opts || {};
    var url;
    try {
      url = safeUrl(path);
    } catch (e) {
      if (!opts.silent) toast(e.message, 'err');
      return Promise.reject(e);
    }

    var init = {
      method: method,
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    };
    if (body !== undefined && body !== null) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }

    return fetch(url, init).then(function (res) {
      return readBody(res).then(function (data) {
        if (!res.ok) {
          var detail = (data && (data.error || data.message))
            ? String(data.error || data.message) : ('HTTP ' + res.status);
          throw netError(path, 'сервер вернул ошибку ' + res.status + ' (' + detail + ')', res.status, data);
        }
        return data;
      }, function () {
        throw netError(path, 'сервер вернул не-JSON ответ', res.status, null);
      });
    }, function (err) {
      throw netError(path, 'нет связи с локальным сервером: ' +
        ((err && err.message) ? err.message : 'соединение отклонено'), 0, null);
    }).then(null, function (err) {
      /* Ошибку не глотаем: показываем тост и пробрасываем вызывающему (§19). */
      var e = (err && err.tui) ? err
        : netError(path, 'сетевая ошибка: ' + ((err && err.message) ? err.message : 'неизвестно'), 0, null);
      if (!opts.silent) toast(e.message, 'err');
      report(e, 'запрос ' + path);
      throw e;
    });
  }

  TUI.api = function (path, opts) { return send(path, 'GET', null, opts); };
  TUI.post = function (path, body, opts) { return send(path, 'POST', body, opts); };

  /* =======================================================================
   * 13. Запуск
   * ===================================================================== */

  function boot() {
    dom = ensureSkeleton();

    if (!HAS_W && window.console && console.warn) {
      console.warn('[TUI] tui_widgets.js не найден — используется аварийный минимум');
    }

    /* Переиспользуем примитивы: screens.js работает только с TUI (§19). */
    /* clear/note/empty обязаны быть в списке: экраны чистят колонки через
       TUI.clear, а пояснения и пустые состояния берут из note/empty.
       Без них оба файла экранов падают на первой же отрисовке. */
    var names = ['el', 'text', 'frag', 'clear', 'note', 'empty', 'panel', 'row',
      'bar', 'cbx', 'chip', 'sec', 'modal', 'confirm', 'toast', 'closeModal',
      'hmModalOpen', 'wbars', 'fmt'];
    names.forEach(function (k) {
      if (W && W[k] !== undefined) TUI[k] = W[k];
    });
    TUI.W = W;

    applyTheme(currentTheme());
    buildMenu();
    drawFooter();
    TUI.layout();
    document.addEventListener('keydown', onKeyDown, false);
    window.addEventListener('resize', onResize, false);

    /* Фокус в тело, чтобы глобальные клавиши ловились сразу. */
    try {
      if (!document.activeElement || document.activeElement === document.body) {
        document.body.setAttribute('tabindex', '-1');
        document.body.focus();
      }
    } catch (e) { /* пусто */ }

    /* Клик мышью по строке оставляет курсор на ней. */
    document.addEventListener('click', function (ev) {
      var row = ev.target && ev.target.closest ? ev.target.closest(ROW_SEL) : null;
      if (!row || isCommentRow(row)) return;
      var panels = TUI.panels();
      for (var i = 0; i < panels.length; i++) {
        if (panels[i].contains(row)) { TUI.state.focus.panel = i; break; }
      }
      var host = row.closest(PANEL_SEL) || dom.body;
      var rows = TUI.rowsOf(host);
      var idx = rows.indexOf(row);
      if (idx >= 0) TUI.state.focus.row = idx;
      TUI.state.focus.on = true;
      paint();
    }, false);

    dom.booted = true;
    TUI.state.theme = TUI.state.theme || currentTheme();

    /* Первый экран: запрошенный в разметке либо первый зарегистрированный. */
    var want = document.documentElement.getAttribute('data-screen') ||
      window.TUI_START || TUI.order[0];
    if (want && TUI.screens[want]) TUI.go(want);
    else if (TUI.order.length) TUI.go(TUI.order[0]);

    return TUI;
  }

  /* Автозапуск без модулей и без top-level await (§17.6).

     Ждём именно `load`, а не `DOMContentLoaded`: файлы экранов подключены
     после tui.js обычными <script>, и при DOMContentLoaded оболочка обязана
     уже видеть их. На `load` это гарантировано — все синхронные скрипты к
     этому моменту отработали. Иначе TUI.el и прочие примитивы ещё не
     выставлены, и первый экран падает с «el is not a function». */
  if (document.readyState === 'complete') {
    boot();
  } else {
    window.addEventListener('load', boot, false);
  }

  window.TUI = TUI;
})();