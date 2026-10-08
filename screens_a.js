/* screens_a.js — экраны «Обзор» и «Календарь».
 *
 * Разметка подчинена app.css и эталону SCREEN_MAP:
 *   — §4 левая колонка: `$ status` (дата, серия, полоса из глифов, цель,
 *     уровень), `$ calendar` (дни недели mo tu we th fr sa su), `$ contributions`
 *     (слева буквы m t w t f s s, сверху месяцы, легенда меньше ░▒▓█ больше);
 *   — §5 средняя колонка: строки-задачи с настоящими [ ] / [✓], иконкой,
 *     счётчиком справа, заголовками групп с иконкой, [n/m] и кареткой;
 *   — §6 правая колонка: секции с иконками ◇ ♨ ⊞ ⇶ ⊞ 🏆, окном данных в
 *     квадратных скобках [30д], строки данных видом «подпись: значение»
 *     и полосами ровно из 20 символов.
 *
 * Строгие правила:
 *   — никаких window.prompt / alert / confirm, только TUI.modal и TUI.confirm;
 *   — пользовательские данные вставляются через textContent / TUI.el,
 *     innerHTML не используется вовсе;
 *   — нет eval, нет модулей, нет top-level await, нет зависимостей;
 *   — префикс «// » рисует CSS у .cmt через ::before — в текст он не пишется;
 *   — видимые строки и комментарии на русском, идентификаторы латиницей;
 *   — экран обязан выжить на пустых данных: русское «пусто», никогда NaN.
 */
(function () {
  'use strict';

  var TUI = window.TUI;
  if (!TUI || !TUI.reg) {
    if (window.console && console.error) console.error('[screens_a] TUI не найден');
    return;
  }

  /* ================================================================== *
   *  1. Примитивы
   *
   *  Примитивы НЕ кэшируем в переменных на верхнем уровне: оболочка
   *  проставляет TUI.el и TUI.fmt при своей загрузке, а этот файл может
   *  разбираться раньше. Оборачиваем в функции — они ищут примитив в
   *  момент вызова.
   * ================================================================== */

  function el(tag, props, children) { return TUI.el(tag, props, children); }
  function txt(value) { return TUI.text(value); }
  function note(value) { return TUI.note(value); }
  function emptyMsg(value) { return TUI.empty(value); }
  function frag(children) { return TUI.frag(children); }

  /** Форматтер из контракта TUI.fmt с безопасным запасным путём. */
  function F(kind, value) {
    try {
      var f = TUI.fmt;
      if (f && typeof f[kind] === 'function') {
        var r = f[kind](num(value));
        if (r !== null && r !== undefined && r !== '') return String(r);
      }
    } catch (e) { /* форматтер упал — используем запасной */ }
    if (kind === 'pct') return Math.round(num(value)) + '%';
    return String(Math.round(num(value)));
  }

  /* ================================================================== *
   *  2. Числа: ни одного NaN наружу
   * ================================================================== */

  function num(v, fallback) {
    var n = typeof v === 'number' ? v : parseFloat(v);
    return isFinite(n) ? n : (fallback === undefined ? 0 : fallback);
  }

  /** Процент с защитой от деления на ноль. */
  function ratio(a, b) {
    b = num(b);
    if (b <= 0) return 0;
    var r = (num(a) / b) * 100;
    if (!isFinite(r) || r < 0) return 0;
    return r > 100 ? 100 : r;
  }

  function clampN(v, lo, hi) {
    var n = num(v);
    return n < lo ? lo : (n > hi ? hi : n);
  }

  function plural(n, one, few, many) {
    n = Math.abs(Math.round(num(n)));
    var a = n % 10, b = n % 100;
    if (a === 1 && b !== 11) return one;
    if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return few;
    return many;
  }

  function daysWord(n) {
    return plural(n, 'день', 'дня', 'дней');
  }

  /* ================================================================== *
   *  3. Даты
   * ================================================================== */

  /* Дни недели экрана — латиницей в две буквы (§4.2 чек-листа). */
  var WD2 = ['mo', 'tu', 'we', 'th', 'fr', 'sa', 'su'];
  /* Одна буква на строку сетки вклада (§4.3). */
  var WD1 = ['m', 't', 'w', 't', 'f', 's', 's'];
  /* Русские длинные названия — только для подписи даты в `$ status`. */
  var WD_RU = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница',
               'суббота', 'воскресенье'];
  var MON = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
             'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
  var MON3 = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн',
              'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  var MONN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
              'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  var DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  function parseISO(s) {
    var m = DATE_RE.exec(String(s || ''));
    if (!m) return null;
    var d = new Date(+m[1], +m[2] - 1, +m[3]);
    return isNaN(d.getTime()) ? null : d;
  }

  function isoOf(dt) {
    return dt.getFullYear() + '-' + pad2(dt.getMonth() + 1) + '-' + pad2(dt.getDate());
  }

  function addDays(dt, n) {
    var x = new Date(dt.getTime());
    x.setDate(x.getDate() + n);
    return x;
  }

  function todayDT() {
    var n = new Date();
    return new Date(n.getFullYear(), n.getMonth(), n.getDate());
  }

  function todayISO() { return isoOf(todayDT()); }

  /** 0…6, понедельник первым. */
  function dowMon(dt) { return (dt.getDay() + 6) % 7; }

  function monthKey(dt) {
    return dt.getFullYear() + '-' + pad2(dt.getMonth() + 1);
  }

  function monthTitle(key) {
    var p = String(key || '').split('-');
    var y = +p[0], m = +p[1];
    if (!y || !m || m < 1 || m > 12) return String(key || '');
    return MON[m - 1] + ' ' + y;
  }

  function daysBetweenISO(a, b) {
    var da = parseISO(a), db = parseISO(b);
    if (!da || !db) return 0;
    return Math.round((db.getTime() - da.getTime()) / 86400000);
  }

  function shortDate(iso) {
    var d = parseISO(iso);
    if (!d) return String(iso || '—');
    return d.getDate() + ' ' + MON3[d.getMonth()];
  }

  /** «вторник, 4 августа 2026» — длинная дата для `$ status`. */
  function longDate(iso) {
    var d = parseISO(iso);
    if (!d) return String(iso || '—');
    return WD_RU[dowMon(d)] + ', ' + d.getDate() + ' ' + MONN[d.getMonth()] +
      ' ' + d.getFullYear();
  }

  /* ================================================================== *
   *  4. Арифметика над серией дней
   *
   *  Серия за окно (ov.series) и год (year.days) приходят с сервера уже
   *  отсортированными по дате; мы их только считаем.
   * ================================================================== */

  function seriesOf(d) {
    var ov = (d && d.ov) || {};
    return Array.isArray(ov.series) ? ov.series : [];
  }

  function yearDaysOf(d) {
    var y = (d && d.year) || {};
    return Array.isArray(y.days) ? y.days : [];
  }

  /** Дневная цель в секундах; 0 — цель не задана. */
  function goalSecOf(d) {
    var ov = (d && d.ov) || {};
    var t = ov.today || {};
    return num(t.goalMin) * 60;
  }

  /** Процент дневной цели за день; без цели — просто доля от максимума окна. */
  function dayScore(rec, goalSec, maxSec) {
    var a = num(rec && rec.activeSec);
    if (goalSec > 0) return ratio(a, goalSec);
    if (maxSec > 0) return ratio(a, maxSec) * 100;
    return 0;
  }

  function maxActive(series) {
    var m = 0;
    for (var i = 0; i < series.length; i++) {
      var a = num(series[i] && series[i].activeSec);
      if (a > m) m = a;
    }
    return m;
  }

  /* ================================================================== *
   *  5. Строители строк экрана
   * ================================================================== */

  /** Полоса из глифов ровно фиксированной ширины (по умолчанию 20). */
  function charBar(pct, width) {
    var w = width || 20;
    var f = Math.round(clampN(pct, 0, 100) / 100 * w);
    var s = '';
    for (var i = 0; i < f; i++) s += '▓';
    for (var j = f; j < w; j++) s += '░';
    return s;
  }

  /**
   * Строка данных вида «подпись: значение» (§6).
   * Значение идёт СРАЗУ после двоеточия, а не прижимается к правому краю:
   * поэтому это один поток текста в .trow-t, без правой колонки .trow-d.
   */
  function kv(label, value) {
    /* Подпись и значение — разными узлами: подпись остаётся нейтральной,
       значение получает градиент из `.row-v`. Собранные в одну строку
       текста, покрасить можно было бы только всё целиком, а в эталоне
       подписи как раз серые — красится лишь число после двоеточия. */
    return el('div', { class: 'trow' }, [
      el('span', { class: 'trow-t' }, [
        el('span', { class: 'row-k', text: label }),
        el('span', { class: 'row-sep', text: ': ' }),
        el('span', { class: 'row-v tnum', text: value })
      ])
    ]);
  }

  /** Полоса глифами и подпись справа в той же строке (§4.1). */
  function barRow(glyphs, caption) {
    return el('div', { class: 'trow' }, [
      el('span', { class: 'trow-t', text: glyphs }),
      el('span', { class: 'trow-d tnum', text: caption })
    ]);
  }

  /**
   * Заголовок секции §6: иконка + название + окно данных в квадратных
   * скобках. Тело идёт соседним .sec-b — этого ждёт оболочка (TUI.bindSections).
   */
  function secHead(key, icon, title, winLabel) {
    var head = el('div', { class: 'sec', attrs: { 'data-sec': key } }, [
      el('span', { class: 'sec-i', text: icon }),
      el('span', { class: 'sec-t', text: title }),
      winLabel ? el('span', { class: 'sec-w', text: '[' + winLabel + ']' }) : null
    ]);
    return { head: head, body: el('div', { class: 'sec-b' }) };
  }

  /** Заголовок + тело разом: [элемент, элемент] — вставить можно подряд. */
  function sec(key, icon, title, winLabel, build) {
    var s = secHead(key, icon, title, winLabel);
    try {
      if (typeof build === 'function') build(s.body);
      if (!s.body.firstChild) s.body.appendChild(emptyMsg('данных пока нет'));
    } catch (e) {
      s.body.appendChild(emptyMsg('раздел не удалось построить'));
    }
    return frag([s.head, s.body]);
  }

  /** Панель: заголовок `$ имя` над рамкой, тело внутри. */
  function panelEl(id, title, body, actions) {
    var p = null;
    try {
      p = TUI.panel({ id: id, title: title, body: body, actions: actions || null });
    } catch (e) { p = null; }
    return p || el('section', { class: 'panel' }, body);
  }

  /* ================================================================== *
   *  6. Строка-задача §5
   * ================================================================== */

  /** Иконка-эмодзи из первого символа названия, иначе нейтральный знак. */
  function taskIcon(title) {
    var s = String(title || '');
    if (!s.length) return '▸';
    var cp = s.codePointAt ? s.codePointAt(0) : s.charCodeAt(0);
    if (cp >= 0x1F300 && cp <= 0x1FAFF) return s.charAt(0);
    return '▸';
  }

  /**
   * Строка-задача по §5: [ ] / [✓] + иконка + название + приглушённый
   * счётчик справа. Чекбокс настоящий — глиф скобок рисует app.css из
   * aria-pressed (см. .cbx::before), в содержимое кнопки ничего не кладём.
   *
   * opts.counted — приглушённый счётчик справа (🔥6 либо ◐08:40).
   * opts.tag    — тег недельного прогресса вида [w 2/5].
   * opts.indent — сдвинуть строку вправо на два пробела (выполненная группа).
   */
  function taskRow(item, onToggle, opts) {
    opts = opts || {};
    var title = String((item && item.title) || '').trim() || '(без названия)';
    var done = !!(item && item.done);

    var props = {
      class: 'trow' + (done ? ' trow--done' : ''),
      attrs: { 'data-id': String((item && item.id) != null ? item.id : ''), 'data-row': 'task' }
    };
    /* Отступ вложенных строк — инлайном, новый класс не заводим:
       app.css правит .trow, инлайн-правило выше по приоритету. */
    if (opts.indent) props.style = { paddingLeft: 'calc(var(--sp-7) + 2ch)' };

    var row = el('div', props, [
      TUI.cbx(done, onToggle, title),
      el('span', { class: 'trow-i', text: taskIcon(title) }),
      el('span', { class: 'trow-t', text: title }),
      el('span', { class: 'trow-d tnum', text: opts.counted || '—' })
    ]);
    if (opts.tag) row.insertBefore(
      el('span', { class: 'trow-d faint', text: opts.tag }),
      row.lastChild
    );
    return row;
  }

  /**
   * Заголовок группы §5: иконка (янтарь для «утренней», фиолет для
   * «вечерней»), приглушённое имя, справа [n/m] и каретка ▾.
   * Каретка нарисована символом, а не ::before у .tgroup-a — так она
   * стоит справа, как в эталоне.
   */
  function groupHeader(name, doneN, total, evening, onToggle) {
    var icon = evening ? '☾' : '☀';
    var head = el('button', {
      class: 'tgroup-h',
      type: 'button',
      'aria-expanded': 'true',
      'aria-label': name + ': ' + doneN + ' из ' + total,
      attrs: { 'data-row': 'group' }
    }, [
      el('span', { class: evening ? 'violet' : 'gold', text: icon }),
      el('span', { class: 'tgroup-t', text: name }),
      el('span', { class: 'tgroup-c tnum', text: '[' + doneN + '/' + total + ']' }),
      el('span', { class: 'tgroup-c', text: '▾' })
    ]);
    if (typeof onToggle === 'function') head.addEventListener('click', onToggle, false);
    return head;
  }

  /* ================================================================== *
   *  7. Состояние окна данных и сети
   * ================================================================== */

  var WIN = { days: 30, from: '', to: '' };
  var CUR = {};   /* screenId -> данные экрана */
  var ROOT = {};  /* screenId -> корневой узел */
  var RENDER = {};

  function safeApi(path) {
    var p;
    try { p = TUI.api(path); } catch (e) { return Promise.resolve({}); }
    return Promise.resolve(p).then(function (r) {
      if (r && typeof r.json === 'function' && typeof r.ok === 'boolean') {
        if (!r.ok) return {};
        return r.json().catch(function () { return {}; });
      }
      return (r && typeof r === 'object') ? r : {};
    }, function () { return {}; });
  }

  function safePost(path, body) {
    var p;
    try { p = TUI.post(path, body); } catch (e) { return Promise.reject(e); }
    return Promise.resolve(p).then(function (r) {
      if (r && typeof r.json === 'function' && typeof r.ok === 'boolean') {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json().catch(function () { return {}; });
      }
      return (r && typeof r === 'object') ? r : {};
    });
  }

  function ovQuery() {
    var d = clampN(WIN.days, 1, 3650);
    return '/api/overview?days=' + Math.round(d);
  }

  function loadOverview() {
    var m = monthKey(todayDT());
    return Promise.all([
      safeApi(ovQuery()),
      safeApi('/api/year?months=12'),
      safeApi('/api/todos?month=' + m),
      safeApi('/api/calendar?month=' + m)
    ]).then(function (r) {
      return {
        kind: 'overview',
        days: Math.round(num(WIN.days)) || 30,
        ov: r[0] || {}, year: r[1] || {}, todos: r[2] || {}, cal: r[3] || {},
        calMonth: m
      };
    });
  }

  function loadCalendarScreen() {
    var m = monthKey(todayDT());
    return Promise.all([
      safeApi('/api/calendar?month=' + m),
      safeApi('/api/year?months=12'),
      safeApi(ovQuery())
    ]).then(function (r) {
      return {
        kind: 'calendar',
        days: Math.round(num(WIN.days)) || 30,
        cal: r[0] || {}, year: r[1] || {}, ov: r[2] || {}, calMonth: m
      };
    });
  }

  function renderInto(id) {
    var fn = RENDER[id], data = CUR[id], root = ROOT[id];
    if (!fn || !root) return;
    try { fn(data, root); } catch (e) { showBroken(root, e); }
  }

  function showBroken(root, err) {
    if (!root) return;
    TUI.clear(root);
    root.appendChild(emptyMsg('экран не удалось построить — обновите данные клавишей r'));
    if (window.console && console.error) console.error('[screens_a] отрисовка', err);
  }

  function setWindow(days, from, to) {
    WIN.days = Math.round(clampN(days, 1, 3650));
    WIN.from = from || '';
    WIN.to = to || '';
    var d = CUR.overview;
    if (!d) return Promise.resolve(null);
    d.days = WIN.days;
    return safeApi(ovQuery()).then(function (ov) {
      d.ov = ov || {};
      renderInto('overview');
      return d;
    });
  }

  function navMonth(id, delta) {
    var d = CUR[id];
    if (!d) return Promise.resolve(null);
    var base = parseISO((d.calMonth || monthKey(todayDT())) + '-01');
    if (!base) return Promise.resolve(null);
    var nd = new Date(base.getTime());
    nd.setMonth(nd.getMonth() + delta);
    var key = monthKey(nd);
    return safeApi('/api/calendar?month=' + key).then(function (cal) {
      d.cal = cal || {};
      d.calMonth = key;
      renderInto(id);
      return d;
    });
  }

  /** Короткая подпись активного окна для квадратных скобок: 30д / 365д / всё. */
  function winLabel() {
    if (WIN.from && WIN.to) {
      return shortDate(WIN.from) + '–' + shortDate(WIN.to);
    }
    var d = Math.round(num(WIN.days));
    if (d >= 3650) return 'all';
    return d + 'd';
  }

  var PRESETS = [[7, '7d'], [30, '30d'], [90, '90d'], [365, '365d'], [3650, 'all']];

  /* ================================================================== *
   *  8. Окно «своё» — своя модалка с двумя датами
   * ================================================================== */

  function openCustomWindow() {
    var from = el('input', { class: 'inp', type: 'date',
                             value: WIN.from || isoOf(addDays(todayDT(), -29)) });
    var to = el('input', { class: 'inp', type: 'date', value: WIN.to || todayISO() });
    TUI.modal({
      title: 'своё окно данных',
      body: [
        note('две даты включительно, слева направо'),
        el('div', { class: 'field' }, [
          el('label', { class: 'field-l', text: 'с' }), from
        ]),
        el('div', { class: 'field' }, [
          el('label', { class: 'field-l', text: 'по' }), to
        ])
      ],
      onOk: function () {
        var f = String(from.value || '').trim();
        var u = String(to.value || '').trim();
        if (!DATE_RE.test(f) || !DATE_RE.test(u)) {
          TUI.toast('даты нужны в виде ГГГГ-ММ-ДД', 'err');
          return false;
        }
        if (f > u) { var swap = f; f = u; u = swap; }
        var n = daysBetweenISO(f, u) + 1;
        if (n < 1) n = 1;
        setWindow(n, f, u);
        return true;
      }
    });
  }

  function presetChips() {
    var box = el('div', { class: 'chips' });
    PRESETS.forEach(function (p) {
      /* Пресеты пишем в квадратных скобках: [7д] [30д] [90д] [365д] [всё]. */
      box.appendChild(TUI.chip('[' + p[1] + ']',
        !WIN.from && Math.round(num(WIN.days)) === p[0],
        function () { setWindow(p[0]); }));
    });
    box.appendChild(TUI.chip('[своё]', !!WIN.from, openCustomWindow));
    return box;
  }

  /* ================================================================== *
   *  9. Общие блоки: календарь месяца и вклад
   * ================================================================== */

  /** Пороги интенсивности по квантилям — минимум и максимум из данных. */
  function intensityScale(values) {
    var v = [];
    for (var i = 0; i < (values || []).length; i++) {
      var x = num(values[i]);
      if (x > 0) v.push(x);
    }
    if (!v.length) return function () { return 0; };
    v.sort(function (a, b) { return a - b; });
    function q(p) {
      var i = (v.length - 1) * p;
      var lo = Math.floor(i), hi = Math.ceil(i);
      return num(v[lo]) + (num(v[hi]) - num(v[lo])) * (i - lo);
    }
    var t1 = q(0.2), t2 = q(0.4), t3 = q(0.6), t4 = q(0.8);
    return function (x) {
      x = num(x);
      if (x <= 0) return 0;
      if (x <= t1) return 1;
      if (x <= t2) return 2;
      if (x <= t3) return 3;
      if (x <= t4) return 4;
      return 5;
    };
  }

  /** Сетка 7×6 месяца, понедельник первым (§4.2). */
  function buildCalendar(data, monthKeyStr, onNav) {
    var cal = (data && data.cal) || {};
    var byDate = {};
    var days = Array.isArray(cal.days) ? cal.days : [];
    var vals = [];
    for (var i = 0; i < days.length; i++) {
      if (days[i] && days[i].date) {
        byDate[days[i].date] = days[i];
        vals.push(num(days[i].activeSec));
      }
    }
    var level = intensityScale(vals);

    var head = el('div', { class: 'cal-hd' }, [
      el('button', {
        class: 'cal-nav', type: 'button', text: '‹',
        title: 'предыдущий месяц', 'aria-label': 'предыдущий месяц',
        onclick: function () { if (onNav) onNav(-1); }
      }),
      el('span', { class: 'cal-t gold', text: monthTitle(monthKeyStr) }),
      el('button', {
        class: 'cal-nav', type: 'button', text: '›',
        title: 'следующий месяц', 'aria-label': 'следующий месяц',
        onclick: function () { if (onNav) onNav(1); }
      })
    ]);

    /* Дни недели — двумя строчными латинскими буквами: mo tu we th fr sa su. */
    var wd = el('div', { class: 'cal-wd' });
    for (var j = 0; j < 7; j++) {
      wd.appendChild(el('span', { class: 'cal-wd-c faint', text: WD2[j] }));
    }

    var first = parseISO(monthKeyStr + '-01') || todayDT();
    var start = addDays(first, -dowMon(first));
    var grid = el('div', { class: 'cal-grid' });
    var tIso = todayISO();

    for (var n = 0; n < 42; n++) {
      var dt = addDays(start, n);
      var iso = isoOf(dt);
      var outside = dt.getMonth() !== first.getMonth();
      var rec = byDate[iso] || null;
      var a = rec ? num(rec.activeSec) : 0;
      var cls = 'cal-cell' + (outside ? ' cal-cell--out' : '') +
                (a <= 0 ? ' cal-cell--zero' : '') + (iso === tIso ? ' cal-cell--today' : '');
      var tip = longDate(iso) + ' — ' + (a > 0 ? F('dur', a) : 'нет данных');

      var inner = [
        el('span', { class: 'cal-cell-n', text: String(dt.getDate()) }),
        el('span', { class: 'cal-bar i' + level(a) })
      ];

      if (outside) {
        grid.appendChild(el('div', { class: cls, attrs: { 'aria-hidden': 'true', title: tip } }, inner));
      } else {
        grid.appendChild(el('button', {
          class: cls, type: 'button', text: undefined, title: tip,
          attrs: { 'data-date': iso },
          onclick: (function (is, rr) {
            return function () { openDay(is, rr); };
          })(iso, rec)
        }, inner));
      }
    }

    var box = el('div', { class: 'cal' }, [head, wd, grid]);
    if (!days.length) {
      box.appendChild(emptyMsg('за этот месяц данных нет'));
    } else {
      var act = 0;
      for (var q2 = 0; q2 < days.length; q2++) if (num(days[q2].activeSec) > 0) act++;
      box.appendChild(note('дней с активностью: ' + act + ' из ' + days.length));
    }
    return box;
  }

  /**
   * Вклад §4.3: сверху месяцы, слева по одной строчной букве дня недели
   * (m t w t f s s, понедельник первым), пять ступеней интенсивности
   * и легенда «меньше ░▒▓█ больше». Префикс «//» у легенды рисует CSS.
   */
  function buildHeatmap(data) {
    var days = yearDaysOf(data || {});
    var map = {}, order = [], vals = [];
    for (var i = 0; i < days.length; i++) {
      var d = days[i];
      if (d && d.date) { map[d.date] = d; order.push(d.date); vals.push(num(d.activeSec)); }
    }
    var level = intensityScale(vals);

    var wrap = el('div', { class: 'hm-wrap' });
    var mos = el('div', { class: 'hm-mos' });
    var main = el('div', { class: 'hm-main' });
    var lbs = el('div', { class: 'hm-lbs' });
    var cells = el('div', { class: 'hm-cells' });

    for (var r = 0; r < 7; r++) {
      lbs.appendChild(el('span', { class: 'hm-lb faint', text: WD1[r] }));
    }

    var first = order.length ? parseISO(order[0]) : todayDT();
    if (!first) first = todayDT();
    var pad = dowMon(first);
    var prevMon = first.getMonth();
    var lastIso = order.length ? order[order.length - 1] : todayISO();
    var tIso = todayISO();

    for (var c = 0; c < pad; c++) {
      cells.appendChild(el('span', { class: 'hm-cell', attrs: { 'aria-hidden': 'true' } }));
    }

    var n = 0;
    for (var x = 0; x < order.length; x++) {
      var iso = order[x];
      var dt = parseISO(iso) || first;
      var col = Math.floor((pad + x) / 7);
      while (n < col) { mos.appendChild(el('span', { class: 'hm-mo faint' })); n++; }
      if (n === col) {
        var m = dt.getMonth();
        mos.appendChild(el('span', {
          class: 'hm-mo faint', text: (m !== prevMon) ? MON3[m] : ''
        }));
        prevMon = m;
        n++;
      }
      var rec = map[iso] || {};
      var a = num(rec.activeSec);
      var cls = 'hm-cell i' + level(a) + (iso === tIso ? ' hm-cell--today' : '');
      cells.appendChild(el('span', {
        class: cls,
        title: shortDate(iso) + ' — ' + (a > 0 ? F('dur', a) : 'нет данных')
      }));
    }
    /* Хвостовые колонки, чтобы последняя неделя не обрывалась. */
    while (n < Math.ceil((pad + order.length) / 7)) {
      mos.appendChild(el('span', { class: 'hm-mo faint' }));
      n++;
    }

    main.appendChild(lbs);
    main.appendChild(cells);
    wrap.appendChild(mos);
    wrap.appendChild(main);
    /* Легенда: префикс «//» подставляет CSS, в тексте его нет. */
    wrap.appendChild(note('меньше ░▒▓█ больше'));
    if (!order.length) wrap.appendChild(emptyMsg('данных за год нет'));
    return wrap;
  }

  /* ================================================================== *
   *  10. Модалка дня
   * ================================================================== */

  function openDay(iso, rec) {
    var body = el('div', { class: 'day' });
    body.appendChild(note(longDate(iso)));
    var a = rec ? num(rec.activeSec) : 0;
    var idle = rec ? num(rec.idleSec) : 0;
    body.appendChild(kv('активно', F('dur', a)));
    body.appendChild(kv('простой', F('dur', idle)));
    if (rec) {
      body.appendChild(kv('клики', String(Math.round(num(rec.clicks)))));
      body.appendChild(kv('символы', String(Math.round(num(rec.chars)))));
      body.appendChild(kv('слова', String(Math.round(num(rec.words)))));
    }

    var pr = (rec && rec.projects) ? rec.projects : null;
    var names = pr ? Object.keys(pr) : [];
    if (names.length) {
      body.appendChild(note('проекты за день'));
      var maxV = 0;
      names.forEach(function (n2) { maxV = Math.max(maxV, num(pr[n2])); });
      names.sort(function (x, y) { return num(pr[y]) - num(pr[x]); });
      for (var i = 0; i < names.length && i < 20; i++) {
        var v = num(pr[names[i]]);
        body.appendChild(barRow(charBar(ratio(v, maxV), 16), F('sec', v)));
      }
      if (names.length > 20) body.appendChild(note('показаны первые 20 из ' + names.length));
    } else {
      body.appendChild(emptyMsg('в этот день проектов не записано'));
    }
    if (!a) body.appendChild(emptyMsg('данных за этот день нет'));

    body.appendChild(el('button', {
      class: 'btn-t right', type: 'button', text: 'закрыть',
      onclick: function () { TUI.closeModal(); }
    }));

    TUI.modal({ title: 'день ' + longDate(iso), body: body });
  }

  /* ================================================================== *
   *  11. Обзор — левая колонка
   * ================================================================== */

  /**
   * `$ status` по §4.1:
   *   ☼ Вторник, 4 августа 2026
   *   7 дней + ● 4
   *   ▓▓▓░░░░░░░░  33% (4/14)
   *   // цель дня: 60%
   *   уровень: 9  [104xp до следующего]
   */
  function statusPanel(d) {
    var ov = (d && d.ov) || {};
    var t = ov.today || {};
    var body = el('div', { class: 'st' });

    /* Дата со знаком солнца или луны по времени суток. */
    var hour = new Date().getHours();
    body.appendChild(el('div', {
      class: 'cal-t gold',
      text: (hour >= 6 && hour < 18 ? '☼ ' : '☾ ') + longDate(todayISO())
    }));

    var streak = ov.streak || {};
    var cur = Math.max(0, Math.round(num(streak.current)));
    var clicks = Math.round(num(t.clicks));

    /* Строка серии целиком в одну, как в эталоне: `N дней + ● M`, где M —
       сколько дней цель была закрыта в окне. Раньше число после ● уезжало
       в правую колонку, а там стояли клики: висел голый индикатор ●. */
    var goalMinForRow = num(t.goalMin) * 60;
    var goalHit = 0;
    (ov.series || []).forEach(function (s) {
      if (goalMinForRow > 0 && num(s.activeSec, 0) >= goalMinForRow) goalHit++;
    });

    body.appendChild(el('div', { class: 'trow' }, [
      el('span', { class: 'trow-t' }, [
        el('span', { class: 'row-k', text: cur + ' ' + daysWord(cur) + ' + ●' }),
        el('span', { class: 'row-sep', text: ' ' }),
        el('span', { class: 'row-v tnum gold', text: String(goalHit) })
      ])
    ]));

    if (clicks > 0) body.appendChild(kv('клики', String(clicks)));

    var goalMin = num(t.goalMin);
    var goal = goalMin * 60;
    var act = num(t.activeSec);

    if (goal > 0) {
      var p = ratio(act, goal);
      /* Полоса глифами и подпись справа в той же строке. */
      body.appendChild(barRow(charBar(p, 14),
        Math.round(p) + '% (' + F('hm', act) + '/' + F('hm', goal) + ')'));
      body.appendChild(note('цель дня: ' + F('hm', goal)));
    } else {
      body.appendChild(barRow(charBar(0, 14), F('dur', act)));
      body.appendChild(note('дневная цель не задана — показан просто факт времени'));
    }

    /* Строка уровня: подпись слева, опыт в квадратных скобках. */
    var st = ov.streak || {};
    var lvl = num(st.level, 1 + Math.floor(num(st.best) / 10));
    var xp = Math.round(num(st.current) * 10 + num(st.best));
    var need = 100 - (xp % 100);
    body.appendChild(el('div', { class: 'trow' }, [
      el('span', { class: 'trow-t', text: 'уровень: ' + Math.round(num(lvl)) }),
      el('span', { class: 'trow-d tnum faint', text: '[' + need + 'xp до следующего]' })
    ]));

    var ach = Math.max(0, Math.round(num(ov.achievementsUnlocked)));
    if (ach) body.appendChild(note('открыто достижений: ' + ach));

    if (!act && !num(ov.totalActiveAllTime)) {
      body.appendChild(emptyMsg('данных пока нет — начните отслеживание'));
    }
    return panelEl('status', 'статус', body);
  }

  function calendarPanel(d, screenId) {
    var body = el('div');
    body.appendChild(buildCalendar(d, (d && d.calMonth) || monthKey(todayDT()),
      function (delta) { navMonth(screenId, delta); }));
    return panelEl('calendar', 'календарь', body);
  }

  function heatmapPanel(d) {
    var body = el('div');
    body.appendChild(buildHeatmap(d));
    return panelEl('hm', 'вклад', body);
  }

  /* ================================================================== *
   *  12. Обзор — средняя колонка §5
   * ================================================================== */

  function todoItems(d) {
    var t = (d && d.todos) || {};
    return Array.isArray(t.items) ? t.items : [];
  }

  function isDone(it) { return !!(it && it.done); }

  function titleOf(it) { return String((it && it.title) || '').trim() || '(без названия)'; }

  function sortTodos(list) {
    return list.slice().sort(function (a, b) {
      var dx = isDone(a) ? 1 : 0, dy = isDone(b) ? 1 : 0;
      if (dx !== dy) return dx - dy;
      return num(a.id) - num(b.id);
    });
  }

  function toggleTodo(it, d) {
    var was = !!it.done;
    it.done = !was;
    if (d) renderInto('overview');
    safePost('/api/todos/toggle', { id: it.id }).then(function () {
      TUI.toast(was ? 'задача возвращена в работу' : 'задача закрыта', 'ok');
    }, function () {
      it.done = was;
      renderInto('overview');
      TUI.toast('не удалось сохранить задачу', 'err');
    });
  }

  /** Счётчик справа: оценка минут как ◐, иначе счётчик выполнений. */
  function todoCounter(it) {
    var mins = num(it.minutes);
    if (mins > 0) return '◐' + F('hm', mins * 60);
    return '🔥0';
  }

  /**
   * Список задач §5: заголовок группы с иконкой, [n/m] и кареткой,
   * строки с [ ] / [✓], иконкой и счётчиком. У выполненной группы
   * дети уходят вправо на два пробела.
   */
  function taskList(items, d, opts) {
    opts = opts || {};
    var box = el('div', { class: 'tgroups' });
    if (!items.length) {
      box.appendChild(emptyMsg(opts.emptyText || 'задач пока нет'));
      return box;
    }

    sortTodos(items).forEach(function (it) {
      var total = 1, doneN = isDone(it) ? 1 : 0;
      var head = groupHeader(titleOf(it), doneN, total, false, function () {
        TUI.post('/api/todos/toggle', { id: it.id }).then(function () {
          return TUI.refresh();
        }, function (err) {
          TUI.toast('не удалось переключить: ' + err.message, 'err');
        });
      });
      var bodyEl = el('div', { class: 'tgroup-b' });
      head.addEventListener('click', function () {
        var open = head.getAttribute('aria-expanded') === 'true';
        head.setAttribute('aria-expanded', open ? 'false' : 'true');
        bodyEl.hidden = !open;
      }, false);
      bodyEl.appendChild(taskRow(it, function () { toggleTodo(it, d); },
        { counted: todoCounter(it), indent: doneN === total }));
      box.appendChild(el('div', { class: 'tgroup', attrs: { 'data-id': String(it.id) } },
        [head, bodyEl]));
    });
    return box;
  }

  /** Группа из нескольких задач: заголовок + дети (выполненные — с отступом). */
  function taskGroupBox(name, list, d, opts) {
    opts = opts || {};
    var total = list.length;
    var doneN = 0;
    for (var i = 0; i < total; i++) if (isDone(list[i])) doneN++;
    var closed = total > 0 && doneN === total;

    var bodyEl = el('div', { class: 'tgroup-b' });
    var head = groupHeader(name, doneN, total, !!opts.evening, null);
    head.addEventListener('click', function () {
      var open = head.getAttribute('aria-expanded') === 'true';
      head.setAttribute('aria-expanded', open ? 'false' : 'true');
      bodyEl.hidden = !open;
    }, false);

    if (!total) {
      bodyEl.appendChild(note('в этой группе задач нет'));
    } else {
      for (var j = 0; j < total; j++) {
        bodyEl.appendChild(taskRow(list[j], function () { toggleTodo(list[j], d); },
          { counted: todoCounter(list[j]), indent: closed }));
      }
    }
    return el('div', { class: 'tgroup' }, [head, bodyEl]);
  }

  /** Синие текстовые кнопки слева и приглушённое [переставить] справа. */
  function listFooter(addLabels) {
    var line = el('div', { class: 'plist-row' }, [
      el('span', {}),
      el('span', { class: 'btn-row' }, (addLabels || []).map(function (pair) {
        return el('button', {
          class: 'btn-t blue', type: 'button', text: pair[0],
          title: pair[1], 'aria-label': pair[1],
          onclick: pair[2]
        });
      })),
      el('span', { class: 'plist-v faint', text: '[переставить]' })
    ]);
    return line;
  }

  /** Группировка задач по дате, «сегодня» первым. */
  function groupByDate(items) {
    var map = {}, keys = [];
    for (var i = 0; i < items.length; i++) {
      var ds = String((items[i] && items[i].date) || '');
      if (!map[ds]) { map[ds] = []; keys.push(ds); }
      map[ds].push(items[i]);
    }
    keys.sort(function (a, b) {
      var af = a >= todayISO(), bf = b >= todayISO();
      if (af !== bf) return af ? -1 : 1;
      return a < b ? -1 : 1;
    });
    return { keys: keys, map: map };
  }

  function relDayLabel(iso) {
    var delta = daysBetweenISO(todayISO(), iso);
    if (delta === 0) return 'Сегодня';
    if (delta === 1) return 'Завтра';
    if (delta === 2) return 'Послезавтра';
    if (delta === -1) return 'Вчера';
    if (delta < 0) return 'Просрочено: ' + shortDate(iso);
    return shortDate(iso);
  }

  function addTaskDialog(defaultDate) {
    var title = el('input', { class: 'inp', type: 'text',
                               attrs: { placeholder: 'например: дописать отчёт' } });
    var mins = el('input', { class: 'inp', type: 'number', min: '0', max: '600',
                             value: '30' });
    var date = el('input', { class: 'inp', type: 'date',
                             value: String(defaultDate || todayISO()) });
    var quick = el('div', { class: 'chip-row' });
    [[0, 'сегодня'], [1, 'завтра'], [2, 'послезавтра'], [7, 'через неделю']].forEach(function (p) {
      quick.appendChild(TUI.chip(p[1], false, function () {
        date.value = isoOf(addDays(todayDT(), p[0]));
      }));
    });

    TUI.modal({
      title: 'новая задача',
      body: [
        el('div', { class: 'field' }, [el('label', { class: 'field-l', text: 'название' }), title]),
        el('div', { class: 'field' }, [el('label', { class: 'field-l', text: 'минут (0 — без оценки)' }), mins]),
        el('div', { class: 'field' }, [el('label', { class: 'field-l', text: 'дата' }), date]),
        note('или выберите день кнопкой выше'),
        quick
      ],
      onOk: function () {
        var name = String(title.value || '').trim();
        if (!name) { TUI.toast('введите название задачи', 'warn'); return false; }
        safePost('/api/todos', { title: name, minutes: num(mins.value, 0),
                                 date: String(date.value || '') }).then(function () {
          TUI.toast('задача добавлена', 'ok');
          return TUI.refresh();
        }, function (err) {
          TUI.toast('не удалось добавить задачу: ' + err.message, 'err');
        });
        return true;
      }
    });
  }

  /**
   * `$ сегодня` — центральная колонка §5.
   * Сверху список на сегодня, ниже активность и проекты дня.
   */
  function todayPanel(d) {
    var ov = (d && d.ov) || {};
    var t = ov.today || {};
    var all = todoItems(d);
    var today = all.filter(function (it) { return String(it.date || '') === todayISO(); });
    var rest = all.filter(function (it) { return String(it.date || '') !== todayISO(); });
    var body = el('div');

    var doneToday = 0;
    for (var i = 0; i < today.length; i++) if (isDone(today[i])) doneToday++;

    body.appendChild(secHead('ov:list', '☰', 'сегодня').head);
    var listBody = el('div', { class: 'sec-b' });
    if (!all.length) {
      listBody.appendChild(emptyMsg('задач пока нет — добавьте первую'));
    } else {
      listBody.appendChild(taskGroupBox('Сегодня', today, d, { emptyText: 'на сегодня задач нет' }));
      var g = groupByDate(rest);
      for (var j = 0; j < g.keys.length; j++) {
        listBody.appendChild(taskGroupBox(relDayLabel(g.keys[j]), g.map[g.keys[j]], d,
          { evening: true }));
      }
      listBody.appendChild(listFooter([
        ['+ привычка', 'добавить задачу', function () { addTaskDialog(todayISO()); }],
        ['+ рутина', 'добавить повторяющуюся задачу', function () { addTaskDialog(todayISO()); }]
      ]));
      listBody.appendChild(note('всего: ' + all.length + ' · закрыто сегодня: ' + doneToday));
    }
    body.appendChild(listBody);

    /* Активность по часам — из hourly[24]. */
    body.appendChild(sec('ov:hourly', '🕐', 'активность по часам', null, function (b) {
      var hourly = Array.isArray(ov.hourly) ? ov.hourly : [];
      var vals = [], max = 0, peak = -1, sum = 0;
      for (var h = 0; h < hourly.length; h++) {
        var a = num(hourly[h] && hourly[h].activeSec);
        vals.push(a);
        sum += a;
        if (a > max) { max = a; peak = h; }
      }
      if (max <= 0) { b.appendChild(emptyMsg('сегодня активности не записано')); return; }
      for (var k = 0; k < vals.length; k++) {
        if (vals[k] <= 0) continue;
        b.appendChild(barRow(charBar(ratio(vals[k], max), 16),
          F('clock', k * 3600) + ' ' + F('sec', vals[k])));
      }
      b.appendChild(note('пик активности — ' + F('clock', peak * 3600) +
                         ', всего ' + F('dur', sum)));
    }));

    /* Проекты сегодня. */
    body.appendChild(sec('ov:projects', '▣', 'проекты сегодня', null, function (b) {
      var ps = Array.isArray(ov.projectsToday) ? ov.projectsToday : [];
      if (!ps.length) { b.appendChild(emptyMsg('сегодня проектов не записано')); return; }
      var maxP = 0, tot = 0;
      for (var p = 0; p < ps.length; p++) {
        var v = num(ps[p].activeSec);
        tot += v;
        if (v > maxP) maxP = v;
      }
      for (var q = 0; q < ps.length; q++) {
        b.appendChild(barRow(charBar(ratio(num(ps[q].activeSec), maxP), 16),
          F('sec', ps[q].activeSec)));
      }
      b.appendChild(note('проектов: ' + ps.length + ', всего ' + F('dur', tot)));
    }));

    body.appendChild(kv('клики', String(Math.round(num(t.clicks)))));
    body.appendChild(kv('символы', String(Math.round(num(t.chars)))));
    body.appendChild(kv('слова', String(Math.round(num(t.words)))));
    body.appendChild(kv('сессии', String(Math.round(num(t.sessions)))));

    return panelEl('tasks', 'сегодня', body);
  }

  /* ================================================================== *
   *  13. Обзор — правая колонка §6
   * ================================================================== */

  /** Проекты по окну, склеенные из series[].projects. */
  function projectsInWindow(series) {
    var agg = {};
    for (var i = 0; i < series.length; i++) {
      var pr = series[i] && series[i].projects;
      if (!pr) continue;
      for (var name in pr) {
        if (!Object.prototype.hasOwnProperty.call(pr, name)) continue;
        agg[name] = (agg[name] || 0) + num(pr[name]);
      }
    }
    return agg;
  }

  /** Самая длинная серия дней подряд у одного проекта. */
  function topProjectStreak(yearDays) {
    var seen = {};
    for (var i = 0; i < yearDays.length; i++) {
      var d = yearDays[i];
      var pr = d && d.projects;
      if (!pr) continue;
      var iso = String(d.date || '');
      if (!iso) continue;
      for (var name in pr) {
        if (!Object.prototype.hasOwnProperty.call(pr, name)) continue;
        if (num(pr[name]) <= 0) continue;
        var cell = seen[name] || (seen[name] = { last: '', run: 0, best: 0 });
        var gap = cell.last ? daysBetweenISO(cell.last, iso) : 99;
        cell.run = (gap === 1) ? cell.run + 1 : 1;
        if (cell.run > cell.best) cell.best = cell.run;
        cell.last = iso;
      }
    }
    var best = null;
    for (var n in seen) {
      if (!Object.prototype.hasOwnProperty.call(seen, n)) continue;
      if (!best || seen[n].best > best.best) best = { name: n, best: seen[n].best };
    }
    return best;
  }

  /**
   * Правая колонка §6. Порядок секций и иконки — как в эталоне:
   * ◇ обзор · ♨ серии · ⊞ окно данных · ⇶ доли выполнения · ⊞ дни недели · 🏆 итоги.
   */
  function statsPanel(d) {
    var ov = (d && d.ov) || {};
    var series = seriesOf(d);
    var year = yearDaysOf(d);
    var goalSec = goalSecOf(d);
    var win = winLabel();
    var maxSec = maxActive(series);
    var body = el('div');

    /* ---- ◇ обзор за всё время ---- */
    body.appendChild(sec('ov:all', '⏱', 'обзор за всё время', null, function (b) {
      b.appendChild(note('your overall tracking summary'));

      var tracked = 0, met = 0, sumScore = 0, completions = 0;
      for (var i = 0; i < year.length; i++) {
        var a = num(year[i] && year[i].activeSec);
        if (a <= 0) continue;
        tracked++;
        if (goalSec > 0) {
          var sc = ratio(a, goalSec);
          sumScore += sc;
          if (sc >= 100) met++;
          completions += Math.floor(a / goalSec);
        }
      }
      var avgAll = maxActive(year);
      var avg = tracked ? Math.round(sumScore / tracked) : 0;
      if (goalSec <= 0 && tracked) {
        /* Без цели «среднее выполнение» = доля от лучшего дня. */
        var s2 = 0;
        for (var k = 0; k < year.length; k++) s2 += ratio(num(year[k].activeSec), avgAll);
        avg = Math.round(s2 / tracked);
      }

      b.appendChild(kv('отслеживается', tracked + ' ' + daysWord(tracked)));
      b.appendChild(kv('среднее выполнение', avg + '%'));
      b.appendChild(kv('цель дня достигнута', met + ' ' + daysWord(met)));
      b.appendChild(kv('всего выполнено', String(completions)));
      if (!tracked) b.appendChild(emptyMsg('данных за год нет'));
    }));

    /* ---- ♨ серии ---- */
    body.appendChild(sec('ov:streak', '🔥', 'серии', null, function (b) {
      b.appendChild(note('consecutive days hitting your daily goal'));
      var st = ov.streak || {};
      var cur = Math.max(0, Math.round(num(st.current)));
      var best = Math.max(0, Math.round(num(st.best)));
      b.appendChild(kv('текущая серия', cur + ' ' + daysWord(cur)));
      b.appendChild(kv('лучшая серия', best + ' ' + daysWord(best)));
      var top = topProjectStreak(year);
      if (top) {
        b.appendChild(kv('топ по серии', top.name + ' — ' + top.best + ' ' + daysWord(top.best)));
      } else {
        b.appendChild(kv('топ по серии', '—'));
        b.appendChild(note('ни у одного проекта нет дней подряд'));
      }
    }));

    /* ---- ⊞ окно данных ---- */
    body.appendChild(sec('ov:win', '📅', 'окно данных', null, function (b) {
      b.appendChild(note('choose from presets, or select a custom range'));
      b.appendChild(presetChips());
      b.appendChild(note(WIN.from && WIN.to
        ? ('окно: ' + WIN.from + ' … ' + WIN.to)
        : ('активное окно: ' + Math.round(num(WIN.days)) + ' дн.')));
    }));

    /* ---- ⇶ доли выполнения [окно] ---- */
    body.appendChild(sec('ov:rates', '📊', 'доли выполнения', win, function (b) {
      b.appendChild(note('how often you complete your scheduled habits'));
      var withData = 0, sumScore = 0, met = 0;
      var wdSum = [0, 0, 0, 0, 0, 0, 0], wdN = [0, 0, 0, 0, 0, 0, 0];
      for (var i = 0; i < series.length; i++) {
        var rec = series[i];
        if (!rec || num(rec.activeSec) <= 0) continue;
        var sc = dayScore(rec, goalSec, maxSec);
        withData++;
        sumScore += sc;
        if (sc >= 100) met++;
        var dt = parseISO(rec.date);
        if (!dt) continue;
        var w = dowMon(dt);
        wdSum[w] += sc;
        wdN[w]++;
      }
      var avg = withData ? Math.round(sumScore / withData) : 0;
      var wkSum = 0, wkN = 0, weSum = 0, weN = 0, i2;
      for (i2 = 0; i2 < 5; i2++) { wkSum += wdSum[i2]; wkN += wdN[i2]; }
      for (i2 = 5; i2 < 7; i2++) { weSum += wdSum[i2]; weN += wdN[i2]; }

      b.appendChild(kv('за ' + win, avg + '%'));
      b.appendChild(kv('идеальных дней', met + '/' + withData));
      b.appendChild(kv('в будни', (wkN ? Math.round(wkSum / wkN) : 0) + '%'));
      b.appendChild(kv('в выходные', (weN ? Math.round(weSum / weN) : 0) + '%'));
      if (!withData) b.appendChild(emptyMsg('в окне нет ни одного дня с данными'));
    }));

    /* ---- ⊞ дни недели [окно] ---- */
    body.appendChild(sec('ov:wdays', '📅', 'дни недели', win, function (b) {
      b.appendChild(note('completion rates broken down by day'));
      var sums = [0, 0, 0, 0, 0, 0, 0], counts = [0, 0, 0, 0, 0, 0, 0];
      for (var i = 0; i < series.length; i++) {
        var rec = series[i];
        if (!rec || num(rec.activeSec) <= 0) continue;
        var dt = parseISO(rec.date);
        if (!dt) continue;
        var w = dowMon(dt);
        sums[w] += dayScore(rec, goalSec, maxSec);
        counts[w]++;
      }
      var items = [];
      for (var k = 0; k < 7; k++) {
        items.push({ label: WD2[k], pct: counts[k] ? Math.round(sums[k] / counts[k]) : 0 });
      }
      /* Полосы ровно из 20 символов: их рисует TUI.wbars. */
      b.appendChild(TUI.wbars(items, { legend: false }));
      var bi = -1, wi = -1;
      for (var j = 0; j < 7; j++) {
        if (counts[j] <= 0) continue;
        if (bi < 0 || items[j].pct > items[bi].pct) bi = j;
        if (wi < 0 || items[j].pct < items[wi].pct) wi = j;
      }
      if (bi >= 0) b.appendChild(kv('лучший день', WD2[bi] + ' (' + items[bi].pct + '%)'));
      if (wi >= 0) b.appendChild(kv('худший день', WD2[wi] + ' (' + items[wi].pct + '%)'));
      if (bi < 0) b.appendChild(emptyMsg('в окне нет активности'));
    }));

    /* ---- 🏆 итоги привычек [окно] ---- */
    body.appendChild(sec('ov:high', '🏆', 'итоги привычек', win, function (b) {
      b.appendChild(note('standouts and trouble spots in this window'));
      var agg = projectsInWindow(series);
      var names = Object.keys(agg);
      if (!names.length) {
        b.appendChild(emptyMsg('в окне проекты не записаны'));
        return;
      }
      names.sort(function (x, y) { return agg[y] - agg[x]; });
      var tot = 0;
      for (var n = 0; n < names.length; n++) tot += agg[names[n]];
      for (var i3 = 0; i3 < names.length && i3 < 8; i3++) {
        var v = agg[names[i3]];
        b.appendChild(barRow(charBar(ratio(v, agg[names[0]]), 16),
          F('sec', v) + ' · ' + Math.round(ratio(v, tot)) + '%'));
      }
      if (names.length > 8) b.appendChild(note('ещё проектов: ' + (names.length - 8)));
    }));

    return panelEl('stats', 'статистика', body);
  }

  /* ================================================================== *
   *  14. Каркас колонок
   * ================================================================== */

  /**
   * Три колонки лежат в корне #tuiBody, который оболочка уже создала.
   * Используем именно его: так не появляется второй .tui-body и не ломается
   * TUI.cols() / фокус панели.
   */
  function colHost(root, cols) {
    var host = root;
    if (!host) {
      var list = TUI.cols();
      host = list[0] && list[0].parentNode ? list[0].parentNode : document.body;
    }
    TUI.clear(host);
    for (var i = 0; i < cols.length; i++) host.appendChild(cols[i]);
    return host;
  }

  function renderOverview(data, root) {
    var d = (data && typeof data === 'object') ? data : {};
    d.ov = d.ov || {};
    d.year = d.year || {};
    d.todos = d.todos || {};
    d.cal = d.cal || {};
    d.calMonth = d.calMonth || monthKey(todayDT());
    d.days = Math.round(num(d.days)) || Math.round(num(WIN.days)) || 30;
    CUR.overview = d;
    if (root) ROOT.overview = root;
    if (!root) return;
    colHost(root, [
      el('div', { class: 'tui-col tui-col--left' }, [
        statusPanel(d), calendarPanel(d, 'overview'), heatmapPanel(d)
      ]),
      el('div', { class: 'tui-col tui-col--mid' }, [todayPanel(d)]),
      el('div', { class: 'tui-col tui-col--right' }, [statsPanel(d)])
    ]);
  }

  /* ================================================================== *
   *  15. Экран «календарь»
   * ================================================================== */

  function summaryPanel(d) {
    var cal = (d && d.cal) || {};
    var sum = cal.summary || {};
    var days = Array.isArray(cal.days) ? cal.days : [];
    var goalSec = goalSecOf(d);
    var body = el('div');

    body.appendChild(el('div', { class: 'cal-t gold', text: monthTitle(d && d.calMonth) }));
    body.appendChild(note('итоги месяца'));

    var withData = 0, bestSec = 0, bestDate = '', met = 0, sumScore = 0, tot = 0;
    for (var i = 0; i < days.length; i++) {
      var a = num(days[i] && days[i].activeSec);
      tot += a;
      if (a <= 0) continue;
      withData++;
      sumScore += goalSec > 0 ? ratio(a, goalSec) : 0;
      if (goalSec > 0 && a >= goalSec) met++;
      if (a > bestSec) { bestSec = a; bestDate = String(days[i].date || ''); }
    }
    var maxSec = 0;
    for (var m = 0; m < days.length; m++) maxSec = Math.max(maxSec, num(days[m].activeSec));

    body.appendChild(kv('всего за месяц', F('dur', num(sum.monthTotal) || tot)));
    body.appendChild(kv('сегодня', F('dur', num(sum.todayActive))));
    var cur = Math.max(0, Math.round(num(sum.currentStreak)));
    var best = Math.max(0, Math.round(num(sum.bestStreak)));
    body.appendChild(kv('текущая серия', cur + ' ' + daysWord(cur)));
    body.appendChild(kv('рекорд', best + ' ' + daysWord(best)));
    body.appendChild(kv('дней с активностью', withData + ' из ' + days.length));
    body.appendChild(kv('среднее выполнение', (withData ? Math.round(sumScore / withData) : 0) + '%'));
    body.appendChild(kv('цель закрыта', met + ' из ' + withData));
    body.appendChild(kv('лучший день', bestDate ? shortDate(bestDate) + ' — ' + F('hm', bestSec) : '—'));

    /* Проекты месяца. */
    var agg = {}, names = [];
    for (var j = 0; j < days.length; j++) {
      var pr = days[j] && days[j].projects;
      if (!pr) continue;
      for (var nm in pr) {
        if (!Object.prototype.hasOwnProperty.call(pr, nm)) continue;
        if (!(nm in agg)) { agg[nm] = 0; names.push(nm); }
        agg[nm] += num(pr[nm]);
      }
    }
    body.appendChild(note('проекты месяца'));
    if (names.length) {
      names.sort(function (x, y) { return agg[y] - agg[x]; });
      for (var n = 0; n < names.length && n < 8; n++) {
        body.appendChild(barRow(charBar(ratio(agg[names[n]], agg[names[0]]), 16),
          F('sec', agg[names[n]])));
      }
      if (names.length > 8) body.appendChild(note('ещё проектов: ' + (names.length - 8)));
    } else {
      body.appendChild(emptyMsg('за месяц проектов не записано'));
    }
    if (!days.length) body.appendChild(emptyMsg('за этот месяц данных нет'));
    else if (!tot) body.appendChild(emptyMsg('в этом месяце активности не было'));

    return panelEl(null, 'сводка', body);
  }

  function renderCalendarScreen(data, root) {
    var d = (data && typeof data === 'object') ? data : {};
    d.cal = d.cal || {};
    d.year = d.year || {};
    d.ov = d.ov || {};
    d.calMonth = d.calMonth || monthKey(todayDT());
    d.days = Math.round(num(d.days)) || 30;
    CUR.calendar = d;
    if (root) ROOT.calendar = root;
    if (!root) return;
    colHost(root, [
      el('div', { class: 'tui-col tui-col--left' }, [
        calendarPanel(d, 'calendar'), heatmapPanel(d)
      ]),
      el('div', { class: 'tui-col tui-col--mid' }, [summaryPanel(d)]),
      el('div', { class: 'tui-col tui-col--right' }, [statsPanel(d)])
    ]);
  }

  RENDER.overview = renderOverview;
  RENDER.calendar = renderCalendarScreen;

  /* ================================================================== *
   *  16. Общий доступ для screens_b.js
   *
   *  Экран «задачи» показывает тот же список §5 и те же окна данных,
   *  поэтому переиспользуем уже проверенные строители.
   * ================================================================== */

  var SHARED = {
    el: el, txt: txt, note: note, empty: emptyMsg, frag: frag,
    num: num, ratio: ratio, clampN: clampN, plural: plural, daysWord: daysWord,
    charBar: charBar, kv: kv, barRow: barRow,
    secHead: secHead, sec: sec, panelEl: panelEl,
    taskRow: taskRow, groupHeader: groupHeader, taskGroupBox: taskGroupBox,
    listFooter: listFooter, groupByDate: groupByDate, relDayLabel: relDayLabel,
    taskIcon: taskIcon, isDone: isDone, titleOf: titleOf, sortTodos: sortTodos,
    WD2: WD2, WD1: WD1, MON3: MON3,
    parseISO: parseISO, isoOf: isoOf, addDays: addDays, todayDT: todayDT,
    todayISO: todayISO, dowMon: dowMon, monthKey: monthKey, monthTitle: monthTitle,
    shortDate: shortDate, longDate: longDate, daysBetweenISO: daysBetweenISO,
    setWindow: setWindow, winLabel: winLabel, presetChips: presetChips,
    openCustomWindow: openCustomWindow, PRESETS: PRESETS,
    seriesOf: seriesOf, yearDaysOf: yearDaysOf, goalSecOf: goalSecOf,
    intensityScale: intensityScale, F: F,
    addTaskDialog: addTaskDialog
  };
  window.ScreensA = SHARED;

  /* ================================================================== *
   *  17. Регистрация экранов
   * ================================================================== */

  TUI.reg('overview', {
    title: 'обзор',
    load: function () { return loadOverview(); },
    render: function (data, root) {
      try { renderOverview(data, root); }
      catch (e) { showBroken(root, e); }
    },
    onAdd: function () { addTaskDialog(todayISO()); },
    keymap: {
      'r': function () { TUI.refresh(); },
      'c': function () { navMonth('overview', -1); },
      'n': function () { navMonth('overview', 1); }
    }
  });

  TUI.reg('calendar', {
    title: 'календарь',
    load: function () { return loadCalendarScreen(); },
    render: function (data, root) {
      try { renderCalendarScreen(data, root); }
      catch (e) { showBroken(root, e); }
    },
    keymap: {
      'r': function () { TUI.refresh(); },
      'c': function () { navMonth('calendar', -1); },
      'n': function () { navMonth('calendar', 1); }
    }
  });

}());