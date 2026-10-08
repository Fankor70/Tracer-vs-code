/* screens_b.js — экраны «Проекты», «План», «Задачи», «Достижения», «Настройки».
 *
 * АИ-часть приложения удалена, поэтому здесь нет ни чата, ни настройки ключей.
 *
 * Разметка подчинена app.css и эталону SCREEN_MAP:
 *   — все строки данных строятся видом «подпись: значение» (SC.A.kv), а не
 *     трёхколоночной сеткой TUI.row с прижатой вправо величиной;
 *   — экран «задачи» повторяет §5: заголовки групп с иконкой, [n/m] и кареткой
 *     ▾, строки с настоящими [ ] / [✓], иконкой и счётчиком справа, синие
 *     текстовые кнопки слева и приглушённое [переставить] справа;
 *   — окно данных и пресеты пишутся в квадратных скобках: [30д], [7д] … [всё];
 *   — префикс «// » рисует CSS у .cmt через ::before — в текст он не пишется.
 *
 * Строгие правила:
 *   — никаких window.prompt / alert / confirm, только TUI.modal и TUI.confirm;
 *   — пользовательские данные только через textContent / TUI.el, innerHTML нет;
 *   — нет eval, нет модулей, нет top-level await, нет зависимостей;
 *   — видимые строки и комментарии на русском, идентификаторы латиницей;
 *   — каждый экран обязан выжить на пустых данных: русское «пусто», никогда NaN.
 */
(function () {
  'use strict';

  var TUI = window.TUI;
  if (!TUI || !TUI.reg) {
    if (window.console && console.error) console.error('[screens_b] TUI не найден');
    return;
  }

  /* Примитивы НЕ кэшируем на верхнем уровне: оболочка проставляет TUI.el и
     TUI.fmt при своей загрузке, а этот файл может разбираться раньше. */
  function el(tag, props, children) { return TUI.el(tag, props, children); }
  function txt(value) { return TUI.text(value); }
  function note(value) { return TUI.note(value); }
  function emptyMsg(value) { return TUI.empty(value); }

  /* Общие строители из screens_a.js: те же строки «подпись: значение», те же
     глифы полос, тот же список §5. Если файл не загрузился — минимальный
     запасной вариант, чтобы экраны не падали целиком. */
  var S = window.ScreensA || {};
  function num(v, fallback) {
    if (typeof S.num === 'function') return S.num(v, fallback);
    var n = typeof v === 'number' ? v : parseFloat(v);
    return isFinite(n) ? n : (fallback === undefined ? 0 : fallback);
  }
  function ratio(a, b) {
    if (typeof S.ratio === 'function') return S.ratio(a, b);
    b = num(b);
    return b <= 0 ? 0 : Math.min(100, Math.max(0, (num(a) / b) * 100));
  }
  function kv(label, value) {
    if (typeof S.kv === 'function') return S.kv(label, value);
    return el('div', { class: 'trow' }, [
      el('span', { class: 'trow-t', text: label + ': ' + value })
    ]);
  }
  function barRow(glyphs, caption) {
    if (typeof S.barRow === 'function') return S.barRow(glyphs, caption);
    return el('div', { class: 'trow' }, [
      el('span', { class: 'trow-t', text: glyphs }),
      el('span', { class: 'trow-d tnum', text: caption })
    ]);
  }
  function sec(key, icon, title, winLabel, build) {
    if (typeof S.sec === 'function') return S.sec(key, icon, title, winLabel, build);
    var box = el('div');
    box.appendChild(el('div', { class: 'sec' }, [
      el('span', { class: 'sec-i', text: icon }),
      el('span', { class: 'sec-t', text: title }),
      winLabel ? el('span', { class: 'sec-w', text: '[' + winLabel + ']' }) : null
    ]));
    box.appendChild(el('div', { class: 'sec-b' }, typeof build === 'function' ? build() : null));
    return box;
  }
  function panelEl(id, title, body, actions) {
    try {
      return TUI.panel({ id: id, title: title, body: body, actions: actions || null });
    } catch (e) {
      return el('section', { class: 'panel' }, body);
    }
  }
  function charBar(pct, width) {
    if (typeof S.charBar === 'function') return S.charBar(pct, width);
    var w = width || 20;
    var f = Math.round(Math.min(100, Math.max(0, num(pct))) / 100 * w);
    var out = '';
    for (var i = 0; i < f; i++) out += '▓';
    for (var j = f; j < w; j++) out += '░';
    return out;
  }

  var WD2 = S.WD2 || ['mo', 'tu', 'we', 'th', 'fr', 'sa', 'su'];
  var MONTHS_SHORT = S.MON3 || ['янв', 'фев', 'мар', 'апр', 'мая', 'июн',
                               'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  var DASH = '—';

  function F(kind, value) {
    try {
      if (S.F) return S.F(kind, value);
      var f = TUI.fmt;
      if (f && typeof f[kind] === 'function') {
        var r = f[kind](num(value));
        if (r !== null && r !== undefined && r !== '') return String(r);
      }
    } catch (e) { /* форматтер упал — запасной путь */ }
    return String(Math.round(num(value)));
  }

  function plural(n, one, few, many) {
    if (typeof S.plural === 'function') return S.plural(n, one, few, many);
    n = Math.abs(Math.round(num(n)));
    var a = n % 10, b = n % 100;
    if (a === 1 && b !== 11) return one;
    if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return few;
    return many;
  }

  function daysWord(n) {
    return typeof S.daysWord === 'function' ? S.daysWord(n) : plural(n, 'день', 'дня', 'дней');
  }

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  function parseISO(s) {
    if (typeof S.parseISO === 'function') return S.parseISO(s);
    var p = String(s || '').split('-');
    if (p.length !== 3) return null;
    var d = new Date(+p[0], +p[1] - 1, +p[2]);
    return isNaN(d.getTime()) ? null : d;
  }

  function iso(d) {
    if (typeof S.isoOf === 'function') return S.isoOf(d);
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }

  function today() {
    if (typeof S.todayDT === 'function') return S.todayDT();
    var d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }

  function addDays(d, n) {
    if (typeof S.addDays === 'function') return S.addDays(d, n);
    var x = new Date(d.getTime());
    x.setDate(x.getDate() + n);
    return x;
  }

  function dow(d) { return (d.getDay() + 6) % 7; }

  function daysBetween(a, b) { return Math.round((b.getTime() - a.getTime()) / 86400000); }

  function currentMonth() { return iso(today()).slice(0, 7); }

  function shiftMonth(month, delta) {
    var p = String(month || '').split('-');
    var d = new Date(+p[0], +p[1] - 1 + delta, 1);
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1);
  }

  function shortDate(s) {
    var d = parseISO(s);
    if (!d) return String(s || DASH);
    return d.getDate() + ' ' + MONTHS_SHORT[d.getMonth()];
  }

  function field(label, control) {
    return el('div', { class: 'field' }, [
      el('label', { class: 'field-l', text: label }), control
    ]);
  }

  function btn(label, onClick, cls, title) {
    var o = { class: 'btn-t' + (cls ? ' ' + cls : ''), type: 'button', text: label };
    if (title) { o.title = title; o['aria-label'] = title; }
    o.onclick = onClick;
    return el('button', o);
  }

  /** Пороги интенсивности по квантилям. */
  function stepper(values) {
    if (typeof S.intensityScale === 'function') return S.intensityScale(values);
    var v = [];
    for (var i = 0; i < (values || []).length; i++) {
      var x = num(values[i]);
      if (x > 0) v.push(x);
    }
    if (!v.length) return function () { return 0; };
    v.sort(function (a, b) { return a - b; });
    var q = function (p) { return v[Math.floor((v.length - 1) * p)]; };
    var a2 = q(0.2), b2 = q(0.4), c2 = q(0.6), d2 = q(0.8);
    return function (value) {
      var x = num(value);
      if (x <= 0) return 0;
      if (x <= a2) return 1;
      if (x <= b2) return 2;
      if (x <= c2) return 3;
      if (x <= d2) return 4;
      return 5;
    };
  }

  /* ================================================================== *
   *  ПРОЕКТЫ
   * ================================================================== */

  var prjDays = 30;
  var prjSort = { key: 'activeSec', dir: -1 };

  var PRJ_COLUMNS = [
    { key: 'project', label: 'проект' },
    { key: 'activeSec', label: 'время' },
    { key: 'idleSec', label: 'простой' },
    { key: 'daysActive', label: 'дней' },
    { key: 'share', label: 'доля' }
  ];

  function projectsLoad() {
    return TUI.api('/api/projects?days=' + prjDays).then(function (list) {
      return { list: list || [] };
    }, function () { return { list: [] }; });
  }

  function sortProjects(list) {
    var key = prjSort.key, dir = prjSort.dir;
    return list.slice().sort(function (a, b) {
      var x, y;
      if (key === 'project') {
        x = String(a.project || '').toLowerCase();
        y = String(b.project || '').toLowerCase();
        return dir * (x < y ? -1 : (x > y ? 1 : 0));
      }
      x = num(a[key]); y = num(b[key]);
      return dir * (x - y);
    });
  }

  function projectsRender(data, root) {
    var cols = TUI.cols();
    cols.forEach(function (c) { TUI.clear(c); });
    var left = cols[0] || TUI.col('left');
    var mid = cols[1] || TUI.col('middle');
    var right = cols[2] || TUI.col('right');

    var list = (data && data.list) || [];
    var total = list.reduce(function (a, p) { return a + num(p.activeSec); }, 0);

    /* Окно данных — пресеты в квадратных скобках: [7д] [30д] [90д] [365д] [всё]. */
    var chipRow = el('div', { class: 'chip-row' });
    [[7, '7d'], [30, '30d'], [90, '90d'], [365, '365d'], [3650, 'all']].forEach(function (p) {
      chipRow.appendChild(TUI.chip('[' + p[1] + ']', prjDays === p[0], function () {
        prjDays = p[0];
        TUI.refresh();
      }));
    });

    var head = el('div', { class: 'plist-row plist-row--head' });
    PRJ_COLUMNS.forEach(function (c) {
      var arrow = prjSort.key === c.key ? (prjSort.dir < 0 ? ' ▾' : ' ▴') : '';
      head.appendChild(el('button', {
        class: 'plist-i', type: 'button', text: c.label + arrow,
        title: 'сортировать по «' + c.label + '»',
        'aria-label': 'сортировать по «' + c.label + '»',
        onclick: function () {
          if (prjSort.key === c.key) prjSort.dir = -prjSort.dir;
          else { prjSort.key = c.key; prjSort.dir = -1; }
          TUI.refresh();
        }
      }));
    });

    var box = el('div', { class: 'plist' }, [head]);
    if (!list.length) {
      box.appendChild(emptyMsg('за выбранное время проектов нет'));
    } else {
      var step = stepper(list.map(function (p) { return p.activeSec; }));
      var ordered = sortProjects(list);
      for (var i = 0; i < ordered.length; i++) {
        var p = ordered[i];
        box.appendChild(el('div', {
          class: 'plist-row', attrs: { 'data-project': String(p.project) }
        }, [
          el('span', { class: 'plist-n', text: String(p.project || '(без имени)') }),
          el('span', { class: 'plist-v tnum', text: F('hm', p.activeSec) }),
          el('span', { class: 'plist-v tnum faint', text: F('hm', p.idleSec) }),
          el('span', { class: 'plist-v tnum', text: String(Math.round(num(p.daysActive))) }),
          el('span', { class: 'plist-v tnum', text: F('pct', p.share) }),
          el('span', { class: 'plist-bar' }, [el('i', { class: 'bar-f i' + step(p.activeSec) })])
        ]));
      }
    }

    mid.appendChild(panelEl('projects', 'проекты', [
      chipRow,
      note('окно: [' + (prjDays >= 3650 ? 'all' : prjDays + 'd') + '] · проектов: ' + list.length),
      box,
      note('всего активного: ' + F('dur', total))
    ]));

    /* Слева — сводка строками «подпись: значение». */
    left.appendChild(panelEl('projects', 'итоги', [
      kv('проектов', String(list.length)),
      kv('всего времени', F('dur', total)),
      kv('среднее на проект', list.length ? F('hm', total / list.length) : DASH),
      kv('дней в окне', String(prjDays >= 3650 ? 'all' : prjDays)),
      note('доля считается от общего времени по окну'),
      list.length ? null : emptyMsg('проектов пока нет')
    ]));

    /* Справа — топ по времени, полосы ровно из 20 символов. */
    var top = sortProjects(list).slice(0, 10);
    var topBody = [];
    topBody.push(note('сколько времени ушло на каждый проект'));
    if (!top.length) {
      topBody.push(emptyMsg('топ пуст'));
    } else {
      var maxTop = num(top[0].activeSec);
      for (var k = 0; k < top.length; k++) {
        topBody.push(barRow(charBar(ratio(top[k].activeSec, maxTop), 20),
          F('sec', top[k].activeSec) + ' · ' + F('pct', top[k].share)));
      }
    }
    right.appendChild(panelEl('projects', 'топ-10', topBody));
  }

  TUI.reg('projects', {
    title: 'проекты',
    load: projectsLoad,
    render: projectsRender,
    keys: [{ keys: 'r', text: 'обновить' }]
  });

  /* ================================================================== *
   *  ПЛАН
   * ================================================================== */

  function planLoad() {
    return TUI.api('/api/roadmap').then(function (d) { return d || {}; },
      function () { return {}; });
  }

  function goalDialog(goal) {
    var title = el('input', { class: 'inp', type: 'text',
                               value: String((goal && goal.title) || '') });
    var target = el('input', { class: 'inp', type: 'date',
                               value: String((goal && goal.targetDate) || '') });
    var hours = el('input', { class: 'inp', type: 'number', min: '0', max: '16',
                              step: '0.5',
                              value: String(num((goal || {}).dailyHours)) });

    TUI.modal({
      title: 'цель обучения',
      body: [
        field('название цели', title),
        field('дата — к какому числу', target),
        field('часов в день (0 = авто)', hours)
      ],
      onOk: function () {
        TUI.post('/api/roadmap/goal', {
          title: String(title.value || '').trim(),
          targetDate: String(target.value || ''),
          dailyHours: num(hours.value)
        }).then(function () {
          TUI.toast('цель сохранена', 'ok');
          return TUI.refresh();
        }, function (err) {
          TUI.toast('не удалось сохранить цель: ' + err.message, 'err');
        });
        return true;
      }
    });
  }

  function stepDialog(step) {
    var isNew = !step;
    var title = el('input', { class: 'inp', type: 'text',
                               value: String((step && step.title) || ''),
                               attrs: { placeholder: 'например: Flexbox и Grid' } });
    var hours = el('input', { class: 'inp', type: 'number', min: '0.5', step: '0.5',
                              value: String(num((step || {}).hours, 10)) });

    TUI.modal({
      title: isNew ? 'новый шаг' : 'изменить шаг',
      body: [field('название', title), field('часов', hours)],
      onOk: function () {
        var name = String(title.value || '').trim();
        if (!name) { TUI.toast('введите название шага', 'warn'); return false; }
        var body = isNew
          ? { title: name, hours: num(hours.value, 10) }
          : { id: step.id, title: name, hours: num(hours.value, 10) };
        TUI.post(isNew ? '/api/roadmap/step' : '/api/roadmap/step/update', body)
          .then(function () {
            TUI.toast(isNew ? 'шаг добавлен' : 'шаг изменён', 'ok');
            return TUI.refresh();
          }, function (err) {
            TUI.toast('не удалось сохранить шаг: ' + err.message, 'err');
          });
        return true;
      }
    });
  }

  function deleteStep(step) {
    TUI.confirm('Удалить шаг «' + String(step.title || '') + '»?', function () {
      TUI.post('/api/roadmap/step/delete', { id: step.id }).then(function () {
        TUI.toast('шаг удалён', 'ok');
        return TUI.refresh();
      }, function (err) {
        TUI.toast('не удалось удалить шаг: ' + err.message, 'err');
      });
    });
  }

  function moveStep(step, dir) {
    TUI.post('/api/roadmap/step/move', { id: step.id, dir: dir }).then(function () {
      return TUI.refresh();
    }, function (err) {
      TUI.toast('не удалось переместить шаг: ' + err.message, 'err');
    });
  }

  var STEP_LABEL = { done: 'выполнен', doing: 'в работе', todo: 'не начат' };

  function planRender(data, root) {
    var cols = TUI.cols();
    cols.forEach(function (c) { TUI.clear(c); });
    var left = cols[0] || TUI.col('left');
    var mid = cols[1] || TUI.col('middle');
    var right = cols[2] || TUI.col('right');

    var d = data || {};
    var goal = d.goal || {};
    var totals = d.totals || {};
    var pace = d.pace || {};
    var fit = d.fit || null;
    var steps = Array.isArray(d.steps) ? d.steps : [];

    /* Цель — строки «подпись: значение». */
    left.appendChild(panelEl('plan', 'цель', [
      kv('название', goal.title ? String(goal.title) : 'не задана'),
      kv('срок', goal.targetDate ? shortDate(goal.targetDate) : DASH),
      kv('в день', num(goal.dailyHours) > 0
        ? num(goal.dailyHours) + ' ч' : F('hm', num(pace.planned) * 3600)),
      TUI.bar(ratio(totals.pctDone, 100), { goal: 100, caption: 'плана выполнено' }),
      kv('часов всего', F('hm', num(totals.hours) * 3600)),
      kv('осталось', F('hm', num(totals.hoursLeft) * 3600)),
      kv('финиш', totals.finishDate ? shortDate(totals.finishDate) : DASH),
      note('активные секунды заливаются в шаги по порядку, с даты старта плана'),
      goal.title ? null : emptyMsg('цель обучения ещё не задана')
    ], [btn('изменить', function () { goalDialog(goal); }, null, 'изменить цель обучения')]));

    /* Темп. */
    var verdict;
    if (!fit) {
      verdict = 'вердикт не считается: нужны цель с датой и хотя бы один шаг';
    } else if (fit.ok) {
      verdict = fit.missDays
        ? 'успеваете, но план закрывается с опозданием на ' +
          num(fit.missDays) + ' ' + daysWord(fit.missDays)
        : 'успеваете: план закрывается в срок';
    } else {
      verdict = 'не успеваете: не хватает ' + num(fit.missDays) + ' ' +
        daysWord(fit.missDays) + ', нужно ' + num(fit.requiredHoursDay) + ' ч в день';
    }
    right.appendChild(panelEl('plan', 'темп', [
      note('сколько часов в день нужно держать темп'),
      kv('плановый темп', num(pace.planned) + ' ч/день'),
      kv('факт за 14 дней', num(pace.actual14) + ' ч/день'),
      kv('нужно в день', fit ? num(fit.requiredHoursDay) + ' ч' : DASH),
      TUI.bar(ratio(num(pace.actual14), fit ? num(fit.requiredHoursDay) : 0),
              { goal: 100, caption: 'темп к сроку' }),
      note(verdict)
    ]));

    /* Шаги. */
    var stepBox = el('div', { class: 'psteps' });
    if (!steps.length) {
      stepBox.appendChild(emptyMsg('шагов пока нет — добавьте первый'));
    } else {
      for (var i = 0; i < steps.length; i++) {
        var s = steps[i] || {};
        var status = s.status === 'done' ? 'done' : (s.status === 'doing' ? 'doing' : 'todo');
        var row = el('div', {
          class: 'pstep pstep--' + status,
          attrs: { 'data-step': String(s.id), 'data-row': 'step' }
        }, [
          TUI.cbx(status === 'done' ? true : (status === 'doing' ? 'mixed' : false),
                  null, String(s.title || '')),
          el('span', { class: 'pstep-t', text: String(s.title || '(без названия)') }),
          el('span', { class: 'pstep-d tnum', text: F('hm', num(s.hours) * 3600) })
        ]);
        var pct = Math.min(100, Math.max(0, num(s.progress)));
        row.appendChild(TUI.bar(pct, { goal: 100, caption: Math.round(pct) + '%', thin: true }));
        var dates = [];
        if (s.startDate) dates.push(shortDate(s.startDate));
        if (s.endDate) dates.push(shortDate(s.endDate));
        if (dates.length) {
          row.appendChild(note(dates.join(' → ') + ' · ' + num(s.days) + ' ' + daysWord(s.days)));
        }
        row.appendChild(note(STEP_LABEL[status]));
        row.appendChild(el('div', { class: 'btn-row' }, [
          btn('↑', function () { moveStep(s, 'up'); }, null, 'выше'),
          btn('↓', function () { moveStep(s, 'down'); }, null, 'ниже'),
          btn('изменить', function () { stepDialog(s); }, null, 'изменить шаг'),
          btn('удалить', function () { deleteStep(s); }, 'red', 'удалить шаг')
        ]));
        stepBox.appendChild(row);
      }
    }

    mid.appendChild(panelEl('plan', 'шаги', [
      stepBox,
      note('шагов: ' + steps.length + ' · выполнено: ' +
        steps.filter(function (s) { return s.status === 'done'; }).length)
    ], [
      btn('+ шаг', function () { stepDialog(null); }, null, 'добавить шаг'),
      btn('шаблон', function () {
        TUI.post('/api/roadmap/template', {}).then(function () {
          TUI.toast('шаблон фронтенд-шагов применён', 'ok');
          return TUI.refresh();
        }, function (err) {
          TUI.toast('не удалось применить шаблон: ' + err.message, 'err');
        });
      }, null, 'применить шаблон шагов')
    ]));
  }

  TUI.reg('plan', {
    title: 'план',
    load: planLoad,
    render: planRender,
    keys: [{ keys: 'a', text: 'новый шаг' }],
    onAdd: function () { stepDialog(null); }
  });

  /* ================================================================== *
   *  ЗАДАЧИ — центральная колонка §5
   * ================================================================== */

  var taskMonth = currentMonth();

  function taskDialog(item, defaultDate) {
    var isNew = !item;
    var title = el('input', { class: 'inp', type: 'text',
                               value: String((item && item.title) || ''),
                               attrs: { placeholder: 'например: дописать отчёт' } });
    var mins = el('input', { class: 'inp', type: 'number', min: '0', max: '600',
                             value: String(num((item || {}).minutes, 30)) });
    var date = el('input', { class: 'inp', type: 'date',
                             value: String((item && item.date) || defaultDate || iso(today())) });

    var quick = el('div', { class: 'chip-row' });
    [[0, 'сегодня'], [1, 'завтра'], [2, 'послезавтра'], [7, 'через неделю'],
     [30, 'через месяц']].forEach(function (p) {
      quick.appendChild(TUI.chip(p[1], false, function () {
        date.value = iso(addDays(today(), p[0]));
      }));
    });

    TUI.modal({
      title: isNew ? 'новая задача' : 'изменить задачу',
      body: [
        field('название', title),
        field('минут (0 — без оценки)', mins),
        field('дата', date),
        note('или выберите день кнопкой выше'),
        quick
      ],
      onOk: function () {
        var name = String(title.value || '').trim();
        if (!name) { TUI.toast('введите название задачи', 'warn'); return false; }
        TUI.post('/api/todos', {
          title: name, minutes: num(mins.value), date: String(date.value || '')
        }).then(function () {
          TUI.toast('задача добавлена', 'ok');
          var mm = String(date.value || '').slice(0, 7);
          if (mm && mm !== taskMonth) taskMonth = mm;
          return TUI.refresh();
        }, function (err) {
          TUI.toast('не удалось добавить задачу: ' + err.message, 'err');
        });
        return true;
      }
    });
  }

  function deleteTask(item) {
    TUI.confirm('Удалить задачу «' + String((item && item.title) || '') + '»?', function () {
      TUI.post('/api/todos/delete', { id: item.id }).then(function () {
        TUI.toast('задача удалена', 'ok');
        return TUI.refresh();
      }, function (err) {
        TUI.toast('не удалось удалить: ' + err.message, 'err');
      });
    });
  }

  function toggleTask(item) {
    TUI.post('/api/todos/toggle', { id: item.id }).then(function () {
      return TUI.refresh();
    }, function (err) {
      TUI.toast('не удалось переключить: ' + err.message, 'err');
    });
  }

  function tasksLoad() {
    return TUI.api('/api/todos?month=' + taskMonth).then(function (d) {
      return { items: (d && d.items) || [] };
    }, function () { return { items: [] }; });
  }

  function dayLabel(dateStr) {
    var d = parseISO(dateStr);
    if (!d) return String(dateStr || DASH);
    var diff = daysBetween(today(), d);
    if (diff === 0) return 'Сегодня';
    if (diff === 1) return 'Завтра';
    if (diff === 2) return 'Послезавтра';
    if (diff === -1) return 'Вчера';
    return d.getDate() + ' ' + MONTHS_SHORT[d.getMonth()];
  }

  /** Счётчик справа: оценка минут как ◐, иначе счётчик выполнений. */
  function taskCounter(item) {
    var mins = num(item.minutes);
    if (mins > 0) return '◐' + F('hm', mins * 60);
    return '🔥0';
  }

  function isDone(it) { return !!(it && it.done); }

  function taskTitle(it) { return String((it && it.title) || '').trim() || '(без названия)'; }

  function sortTodos(list) {
    return list.slice().sort(function (a, b) {
      var dx = isDone(a) ? 1 : 0, dy = isDone(b) ? 1 : 0;
      if (dx !== dy) return dx - dy;
      return num(a.id) - num(b.id);
    });
  }

  /**
   * Группа задач по §5: иконка (золотая/фиолетовая), приглушённое имя,
   * справа [n/m] и каретка ▾. У полностью выполненной группы строки уходят
   * вправо на два пробела.
   */
  function taskGroup(name, list, evening) {
    var total = list.length;
    var doneN = 0;
    for (var i = 0; i < total; i++) if (isDone(list[i])) doneN++;
    var closed = total > 0 && doneN === total;

    var bodyEl = el('div', { class: 'tgroup-b' });
    var head = S.groupHeader
      ? S.groupHeader(name, doneN, total, !!evening, null)
      : el('button', { class: 'tgroup-h', type: 'button' }, [
          el('span', { class: evening ? 'violet' : 'gold', text: evening ? '☾' : '☀' }),
          el('span', { class: 'tgroup-t', text: name }),
          el('span', { class: 'tgroup-c tnum', text: '[' + doneN + '/' + total + ']' }),
          el('span', { class: 'tgroup-c', text: '▾' })
        ]);
    head.addEventListener('click', function () {
      var open = head.getAttribute('aria-expanded') === 'true';
      head.setAttribute('aria-expanded', open ? 'false' : 'true');
      bodyEl.hidden = !open;
    }, false);

    if (!total) {
      bodyEl.appendChild(note('в этой группе задач нет'));
    } else {
      var ordered = sortTodos(list);
      for (var j = 0; j < ordered.length; j++) {
        var it = ordered[j];
        var row = S.taskRow
          ? S.taskRow(it, function () { toggleTask(it); },
                      { counted: taskCounter(it), indent: closed })
          : el('div', { class: 'trow' }, [
              TUI.cbx(!!it.done, function () { toggleTask(it); }, taskTitle(it)),
              el('span', { class: 'trow-i', text: '▸' }),
              el('span', { class: 'trow-t', text: taskTitle(it) }),
              el('span', { class: 'trow-d tnum', text: taskCounter(it) })
            ]);
        /* Клик по строке (не по чекбоксу) открывает редактирование. */
        row.setAttribute('title', 'нажмите, чтобы изменить задачу');
        row.addEventListener('click', function (ev) {
          if (ev.target && ev.target.closest && ev.target.closest('.cbx')) return;
          taskDialog(it);
        }, false);
        bodyEl.appendChild(row);
      }
    }
    return el('div', { class: 'tgroup' }, [head, bodyEl]);
  }

  /** Синие текстовые кнопки слева и приглушённое [переставить] справа. */
  function listFooter(buttons) {
    if (S.listFooter) return S.listFooter(buttons);
    return el('div', { class: 'plist-row' }, [
      el('span', {}),
      el('span', { class: 'btn-row' }, buttons.map(function (pair) {
        return el('button', {
          class: 'btn-t blue', type: 'button', text: pair[0],
          title: pair[1], 'aria-label': pair[1], onclick: pair[2]
        });
      })),
      el('span', { class: 'plist-v faint', text: '[переставить]' })
    ]);
  }

  function tasksRender(data, root) {
    var cols = TUI.cols();
    cols.forEach(function (c) { TUI.clear(c); });
    var left = cols[0] || TUI.col('left');
    var mid = cols[1] || TUI.col('middle');
    var right = cols[2] || TUI.col('right');

    var items = (data && data.items) || [];
    var done = 0, mins = 0;
    for (var i = 0; i < items.length; i++) {
      if (isDone(items[i])) done++;
      mins += num(items[i].minutes);
    }

    /* Окно месяца — стрелки, как было. */
    var actions = [
      btn('‹', function () { taskMonth = shiftMonth(taskMonth, -1); TUI.refresh(); },
          null, 'предыдущий месяц'),
      btn('›', function () { taskMonth = shiftMonth(taskMonth, 1); TUI.refresh(); },
          null, 'следующий месяц')
    ];

    /* Центральная колонка — §5 целиком. */
    var listBox = el('div', { class: 'tgroups' });
    if (!items.length) {
      listBox.appendChild(emptyMsg('в этом месяце задач нет'));
    } else {
      var map = {}, keys = [];
      for (var k = 0; k < items.length; k++) {
        var ds = String(items[k].date || '');
        if (!map[ds]) { map[ds] = []; keys.push(ds); }
        map[ds].push(items[k]);
      }
      keys.sort(function (a, b) {
        var af = a >= iso(today()), bf = b >= iso(today());
        if (af !== bf) return af ? -1 : 1;
        return a < b ? -1 : 1;
      });
      for (var g = 0; g < keys.length; g++) {
        /* Ближайшие дни — «дневные» (иконка янтарная), дальние — вечерние. */
        var evening = g > 0;
        listBox.appendChild(taskGroup(dayLabel(keys[g]), map[keys[g]], evening));
      }
      listBox.appendChild(listFooter([
        ['+ привычка', 'добавить задачу на сегодня',
          function () { taskDialog(null, iso(today())); }],
        ['+ рутина', 'добавить повторяющуюся задачу',
          function () { taskDialog(null, iso(today())); }]
      ]));
      listBox.appendChild(note('всего: ' + items.length + ' · закрыто: ' + done));
    }

    mid.appendChild(panelEl('tasks', 'задачи', listBox, actions));

    /* Слева — сводка месяца. */
    left.appendChild(panelEl('tasks', 'сводка', [
      kv('месяц', taskMonth),
      TUI.bar(ratio(done, items.length), { goal: 100, caption: 'выполнено' }),
      kv('задач', String(items.length)),
      kv('выполнено', String(done)),
      kv('осталось', String(items.length - done)),
      kv('запланировано', F('hm', mins * 60)),
      note('оценка в минутах, реальное время — в обзоре'),
      items.length ? null : emptyMsg('задач в этом месяце нет')
    ]));

    /* Справа — §6: окно данных в скобках и дни недели с полосами по 20 символов. */
    var winLabel = (typeof S.winLabel === 'function') ? S.winLabel() : '30d';
    var sums = [0, 0, 0, 0, 0, 0, 0], counts = [0, 0, 0, 0, 0, 0, 0];
    for (var n = 0; n < items.length; n++) {
      var itd = parseISO(items[n].date);
      if (!itd) continue;
      var w = dow(itd);
      counts[w]++;
      if (isDone(items[n])) sums[w]++;
    }
    var bars = [];
    for (var z = 0; z < 7; z++) {
      bars.push({ label: WD2[z], pct: counts[z] ? Math.round(sums[z] / counts[z] * 100) : 0 });
    }

    var rightBody = [];
    rightBody.push(sec('tk:win', '📅', 'окно данных', null, function (b) {
      b.appendChild(note('choose from presets, or select a custom range'));
      if (S.presetChips) b.appendChild(S.presetChips());
      b.appendChild(note('окно календаря: ' + taskMonth));
    }));

    rightBody.push(sec('tk:rates', '📊', 'доли выполнения', winLabel, function (b) {
      b.appendChild(note('how often you complete your scheduled habits'));
      b.appendChild(kv('за ' + winLabel, Math.round(ratio(done, items.length)) + '%'));
      b.appendChild(kv('идеальных дней', '—'));
      b.appendChild(kv('в будни', (function () {
        var s = 0, c = 0, i2;
        for (i2 = 0; i2 < 5; i2++) { s += bars[i2].pct; if (counts[i2]) c++; }
        return (c ? Math.round(s / c) : 0) + '%';
      })()));
      b.appendChild(kv('в выходные', (function () {
        var s = 0, c = 0, i2;
        for (i2 = 5; i2 < 7; i2++) { s += bars[i2].pct; if (counts[i2]) c++; }
        return (c ? Math.round(s / c) : 0) + '%';
      })()));
    }));

    rightBody.push(sec('tk:wdays', '📅', 'дни недели', winLabel, function (b) {
      b.appendChild(note('completion rates broken down by day'));
      b.appendChild(TUI.wbars(bars, { legend: false }));
      var bi = -1, wi = -1;
      for (var q = 0; q < 7; q++) {
        if (counts[q] <= 0) continue;
        if (bi < 0 || bars[q].pct > bars[bi].pct) bi = q;
        if (wi < 0 || bars[q].pct < bars[wi].pct) wi = q;
      }
      if (bi >= 0) b.appendChild(kv('лучший день', WD2[bi] + ' (' + bars[bi].pct + '%)'));
      if (wi >= 0) b.appendChild(kv('худший день', WD2[wi] + ' (' + bars[wi].pct + '%)'));
      if (bi < 0) b.appendChild(emptyMsg('в окне нет задач'));
    }));

    right.appendChild(panelEl('tasks', 'статистика', rightBody));
  }

  TUI.reg('tasks', {
    title: 'задачи',
    load: tasksLoad,
    render: tasksRender,
    keys: [{ keys: 'a', text: 'новая задача' },
           { keys: '← →', text: 'месяц' }],
    onAdd: function () { taskDialog(null, iso(today())); },
    keymap: function (ev) {
      if (ev.key === 'ArrowLeft') { taskMonth = shiftMonth(taskMonth, -1); TUI.refresh(); return true; }
      if (ev.key === 'ArrowRight') { taskMonth = shiftMonth(taskMonth, 1); TUI.refresh(); return true; }
      return false;
    }
  });

  /* ================================================================== *
   *  ДОСТИЖЕНИЯ
   * ================================================================== */

  var achFilter = '';

  function achLoad() {
    return TUI.api('/api/achievements').then(function (d) { return d || {}; },
      function () { return {}; });
  }

  function achievementsRender(data, root) {
    var cols = TUI.cols();
    cols.forEach(function (c) { TUI.clear(c); });
    var left = cols[0] || TUI.col('left');
    var mid = cols[1] || TUI.col('middle');
    var right = cols[2] || TUI.col('right');

    var d = data || {};
    var items = Array.isArray(d.items) ? d.items : [];
    var total = Math.max(0, Math.round(num(d.total, items.length)));
    var unlocked = Math.max(0, Math.round(num(d.unlocked)));

    var cats = {};
    for (var i = 0; i < items.length; i++) {
      if (items[i] && items[i].category) cats[items[i].category] = (cats[items[i].category] || 0) + 1;
    }
    var catList = Object.keys(cats).sort();

    var chips = el('div', { class: 'chip-row' });
    chips.appendChild(TUI.chip('[все]', achFilter === '', function () {
      achFilter = ''; TUI.refresh();
    }));
    for (var c = 0; c < catList.length; c++) {
      (function (cat) {
        chips.appendChild(TUI.chip('[' + cat + ' (' + cats[cat] + ')]', achFilter === cat, function () {
          achFilter = cat; TUI.refresh();
        }));
      }(catList[c]));
    }

    var shown = achFilter
      ? items.filter(function (a) { return a && a.category === achFilter; })
      : items;

    var grid = el('div', { class: 'achgrid' });
    if (!shown.length) {
      grid.appendChild(emptyMsg(achFilter
        ? 'достижений в этой категории нет'
        : 'достижений пока нет'));
    } else {
      for (var k = 0; k < shown.length; k++) {
        var a = shown[k] || {};
        var open = !!a.unlocked;
        var pct = ratio(a.current, a.target);
        grid.appendChild(el('div', {
          class: 'ach-tile' + (open ? ' is-open' : ''),
          title: String(a.desc || ''),
          attrs: { 'data-ach': String(a.id) }
        }, [
          el('span', { class: 'ach-i', text: String(a.icon || '◇') }),
          el('span', { class: 'ach-t', text: String(a.name || '(без названия)') }),
          el('span', { class: 'ach-d', text: String(a.desc || '') }),
          TUI.bar(pct, { goal: 100, thin: true }),
          el('span', {
            class: 'ach-d tnum',
            text: F('pct', pct) + ' · ' + Math.round(num(a.current)) + ' / ' +
                  Math.round(num(a.target)) + ' ' + String(a.unit || '')
          }),
          open ? note('открыто ' + shortDate(String(a.unlockedAt || '').slice(0, 10))) : null
        ]));
      }
    }

    mid.appendChild(panelEl('achievements', 'достижения', [
      chips, grid,
      note('показано: ' + shown.length + ' из ' + items.length)
    ]));

    left.appendChild(panelEl('achievements', 'счёт', [
      TUI.bar(ratio(unlocked, total), { goal: 100, caption: 'открыто' }),
      kv('открыто', String(unlocked)),
      kv('всего', String(total)),
      kv('осталось', String(Math.max(0, total - unlocked))),
      note('достижения пересчитываются при открытии экрана'),
      items.length ? null : emptyMsg('достижений пока нет')
    ]));

    var byCat = [];
    for (var q2 = 0; q2 < catList.length; q2++) {
      var cat2 = catList[q2];
      var open2 = items.filter(function (x) {
        return x && x.category === cat2 && x.unlocked;
      }).length;
      byCat.push({ label: cat2, pct: ratio(open2, cats[cat2]) });
    }
    right.appendChild(panelEl('achievements', 'по категориям', [
      note('доля открытых внутри категории'),
      TUI.wbars(byCat, { legend: false }),
      byCat.length ? null : emptyMsg('категорий пока нет')
    ]));
  }

  TUI.reg('achievements', {
    title: 'достижения',
    load: achLoad,
    render: achievementsRender,
    keys: [{ keys: 'r', text: 'пересчитать' }]
  });

  /* ================================================================== *
   *  НАСТРОЙКИ
   * ================================================================== */

  function settingsLoad() {
    return TUI.api('/api/settings').then(function (d) { return d || {}; },
      function () { return {}; });
  }

  function switchRow(label, key, initial, onChange) {
    var input = el('input', { type: 'checkbox', attrs: { id: 'set-' + key } });
    input.checked = !!initial;
    var sw = el('label', { class: 'sw' }, [input, el('span', { class: 'slider-ui' })]);
    input.setAttribute('aria-checked', input.checked ? 'true' : 'false');
    input.addEventListener('change', function () {
      onChange(!!input.checked);
      sw.setAttribute('aria-checked', input.checked ? 'true' : 'false');
    }, false);
    return el('div', { class: 'set-row' }, [
      el('span', { class: 'set-k', text: label }), sw
    ]);
  }

  function settingsRender(data, root) {
    var cols = TUI.cols();
    cols.forEach(function (c) { TUI.clear(c); });
    var left = cols[0] || TUI.col('left');
    var mid = cols[1] || TUI.col('middle');
    var right = cols[2] || TUI.col('right');

    var d = data || {};
    var goal = num(d.dailyGoalMin, 120);

    function save(patch, message) {
      var body = {
        dailyGoalMin: goal, trackClicks: !!d.trackClicks,
        trackKeys: !!d.trackKeys, paused: !!d.paused, autostart: !!d.autostart
      };
      for (var k in patch) if (Object.prototype.hasOwnProperty.call(patch, k)) body[k] = patch[k];
      TUI.post('/api/settings', body).then(function () {
        TUI.toast(message || 'сохранено', 'ok');
        return TUI.refresh();
      }, function (err) {
        TUI.toast('не удалось сохранить: ' + err.message, 'err');
      });
    }

    var slider = el('input', { class: 'rng', type: 'range', min: '30', max: '480', step: '10' });
    slider.value = String(goal);
    var goalLabel = el('span', { class: 'set-v tnum', text: goal + ' мин' });
    slider.addEventListener('input', function () {
      goal = num(slider.value, 120);
      goalLabel.textContent = goal + ' мин';
    }, false);
    slider.addEventListener('change', function () { save({}, 'дневная цель сохранена'); }, false);

    left.appendChild(panelEl('settings', 'отслеживание', [
      el('div', { class: 'set-row set-row--col' }, [
        el('span', { class: 'set-k', text: 'дневная цель' }),
        slider, goalLabel,
        note('сколько активного времени в день вы хотите нарабатывать')
      ]),
      switchRow('считать клики', 'trackClicks', d.trackClicks,
        function (on) { save({ trackClicks: on }, 'настройка сохранена'); }),
      switchRow('считать клавиши и слова', 'trackKeys', d.trackKeys,
        function (on) { save({ trackKeys: on }, 'настройка сохранена'); }),
      switchRow('пауза', 'paused', d.paused,
        function (on) { save({ paused: on }, on ? 'учёт на паузе' : 'учёт возобновлён'); }),
      switchRow('автозапуск с Windows', 'autostart', d.autostart,
        function (on) { save({ autostart: on }, 'настройка сохранена'); })
    ]));

    mid.appendChild(panelEl('settings', 'путь', [
      kv('база данных', String(d.dbPath || DASH)),
      note('все данные лежат только на этом компьютере, в интернет ничего не уходит'),
      note('ИИ-часть приложения удалена: наставник, чат и конвейер агентов не работают')
    ]));

    var notes = el('div', { class: 'm-statusline', attrs: { 'data-note': 'update' } });
    notes.textContent = 'проверка обновлений ещё не выполнялась';
    mid.appendChild(panelEl('settings', 'версия', [
      kv('установлена', String(d.version || DASH)),
      notes,
      el('div', { class: 'btn-row' }, [
        btn('список версий', function () {
          TUI.api('/api/update/check').then(function (info) {
            notes.textContent = info && info.tag
              ? ('последняя в GitHub: ' + info.tag)
              : 'свежих релизов не найдено';
          }, function (err) {
            notes.textContent = 'не удалось проверить: ' + err.message;
          });
        }, null, 'проверить обновления'),
        /* Установка обновления перезаписывает exe на диске, поэтому заблокирована. */
        btn('нужно подтверждение', function () {
          TUI.toast('установка обновления требует подтверждения — файл exe не тронут', 'warn');
        }, 'btn-lock', 'установка обновления заблокирована')
      ]),
      note('проверка обновлений только читает GitHub Releases, файл не меняет')
    ]));

    right.appendChild(panelEl('settings', 'опасная зона', [
      note('удаляет всю статистику по дням и часам, проекты, задачи, план и достижения'),
      note('настройки — цель, счётчики, автозапуск — останутся'),
      note('отменить это нельзя'),
      btn('удалить все данные', function () {
        TUI.confirm('Удалить всю статистику, задачи, план и достижения? Отменить нельзя.',
          function () {
            TUI.post('/api/reset', {}).then(function () {
              TUI.toast('данные удалены', 'ok');
              return TUI.refresh();
            }, function (err) {
              TUI.toast('не удалось удалить: ' + err.message, 'err');
            });
          });
      }, 'btn-danger', 'удалить все данные')
    ]));
  }

  TUI.reg('settings', {
    title: 'настройки',
    load: settingsLoad,
    render: settingsRender,
    keys: [{ keys: 'd', text: 'пауза/продолжить' }]
  });
})();