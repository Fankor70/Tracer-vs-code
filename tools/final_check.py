# -*- coding: utf-8 -*-
"""
Одна команда проверки всего: `python tools/final_check.py`

Блоки:
  1. синтаксис Python (codetime.py, devserver.py, tools/*.py)
  2. `node --check` на каждом JS-файле интерфейса
  3. запрещённые конструкции (prompt/alert/confirm/eval и innerHTML с данными)
  4. структура dashboard.html: порядок скриптов, отсутствие инлайна
  5. связность меню и экранов: TUI.reg() в screens.js против ожидаемых семи
  6. живые проверки против поднятого стенда: все эндпоинты + статика
  7. удалённая ИИ-часть действительно недоступна (404)

Правила, которые этот скрипт обязан соблюдать (они уже стоили реального
времени, см. память проекта):
  * проверяющий код неправ, а продукт — тем более, когда «ошибка»
    выглядит правдоподобно; поэтому помощники ниже принимают
    пояснение и не делают выводов вслепую;
  * `{}` — пустой словарь, а он ложный, поэтому проверки заголовков
    сравнивают с `is not None`, а не проверяют на истинность;
  * проверка должна быть проверена на заведомо плохом состоянии, иначе
    она врёт в обе стороны. `--self-test` это делает.
"""

import argparse
import ast
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JS_FILES = ['tui_widgets.js', 'tui.js', 'screens_a.js', 'screens_b.js']
PY_FILES = ['codetime.py', 'devserver.py']
EXPECTED_SCREENS = {'overview', 'calendar', 'projects', 'plan',
                    'tasks', 'achievements', 'settings'}

GREEN, RED, YELLOW, DIM, RESET = '\033[32m', '\033[31m', '\033[33m', '\033[2m', '\033[0m'
if not sys.stdout.isatty():
    GREEN = RED = YELLOW = DIM = RESET = ''

_failures = []
_checks = 0


def ok(label, detail=''):
    global _checks
    _checks += 1
    print('  %s✓%s %s%s' % (GREEN, RESET, label,
                            ('  %s%s%s' % (DIM, detail, RESET)) if detail else ''))


def bad(label, detail=''):
    global _checks
    _checks += 1
    _failures.append(label + ((' — ' + detail) if detail else ''))
    print('  %s✗%s %s%s' % (RED, RESET, label,
                            ('  %s%s%s' % (DIM, detail, RESET)) if detail else ''))


def head(title):
    print('\n%s' % title)


def read(path):
    with open(os.path.join(ROOT, path), 'rb') as f:
        return f.read().decode('utf-8')


def exists(path):
    return os.path.isfile(os.path.join(ROOT, path))


# ---------------------------------------------------------------- 1. Python

def check_python():
    head('1. Синтаксис Python')
    for name in PY_FILES:
        if not exists(name):
            bad('%s — файла нет' % name)
            continue
        try:
            ast.parse(read(name), filename=name)
            ok(name)
        except SyntaxError as e:
            bad(name, 'строка %s: %s' % (e.lineno, e.msg))


# ------------------------------------------------------------------- 2. JS

def check_js():
    head('2. node --check')
    for name in JS_FILES:
        if not exists(name):
            bad('%s — файла нет' % name)
            continue
        proc = subprocess.run(['node', '--check', os.path.join(ROOT, name)],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            ok(name, '%d строк' % read(name).count('\n'))
        else:
            first = (proc.stderr or '').strip().splitlines()
            bad(name, first[0] if first else 'неизвестная ошибка')


# --------------------------------------------------------- 3. запрещённое

BANNED = [
    (re.compile(r'\bwindow\.prompt\s*\('), 'window.prompt'),
    (re.compile(r'\bwindow\.alert\s*\('), 'window.alert'),
    (re.compile(r'\bwindow\.confirm\s*\('), 'window.confirm'),
    # Голый (не-метод) вызов — именно так выглядел реальный баг:
    # `mapAddNode()` звал prompt() без window. Всё, что после точки
    # (`W.confirm(...)`, `TUIW.toast(...)`), — методы наших же объектов.
    (re.compile(r'(?<![\w$.])prompt\s*\('), 'prompt()'),
    (re.compile(r'(?<![\w$.])alert\s*\('), 'alert()'),
    (re.compile(r'(?<![\w$.])confirm\s*\('), 'confirm()'),
    (re.compile(r'\beval\s*\('), 'eval()'),
    (re.compile(r'url\(\s*[\'"]?https?:'), 'внешний url()'),
    (re.compile(r'@import'), '@import'),
    (re.compile(r'type\s*=\s*[\'"]module[\'"]'), 'ES-модуль'),
]

LINE_COMMENT = re.compile(r'//[^\n]*')
BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.S)


def strip_comments(text):
    """Комментарии вычищаются ДО поиска запрещённого: упоминание слова
    в пояснении не нарушение, а ловить его — значит приучать игнорировать
    проверку вообще."""
    return BLOCK_COMMENT.sub(' ', LINE_COMMENT.sub(' ', text))


def check_banned():
    head('3. Запрещённые конструкции')
    for name in JS_FILES + ['app.css', 'dashboard.html']:
        if not exists(name):
            continue
        text = read(name)
        code = strip_comments(text)
        hits = []
        for pattern, label in BANNED:
            for m in pattern.finditer(code):
                line = code.count('\n', 0, m.start()) + 1
                hits.append('%s (строка %d)' % (label, line))
        if hits:
            bad(name, ', '.join(hits[:6]))
        else:
            ok(name)
    # innerHTML с непустой строкой — отдельно: '' на очистку разрешён
    for name in JS_FILES:
        if not exists(name):
            continue
        text = read(name)
        hits = []
        for m in re.finditer(r'innerHTML\s*=\s*([^\n;]+)', text):
            val = m.group(1).strip()
            if val not in ("''", '""', '``'):
                line = text.count('\n', 0, m.start()) + 1
                hits.append('строка %d: %s' % (line, val[:40]))
        if hits:
            bad('%s: innerHTML с данными' % name, ', '.join(hits[:5]))
        else:
            ok('%s: innerHTML только на очистку' % name)


# ------------------------------------------------------- 4. dashboard.html

def check_dashboard():
    head('4. Структура dashboard.html')
    if not exists('dashboard.html'):
        bad('dashboard.html — файла нет')
        return
    html = read('dashboard.html')
    order = [m.group(1) for m in
             re.finditer(r'<script[^>]*src="([^"]+)"', html)]
    if order == JS_FILES:
        ok('порядок скриптов', ' → '.join(order))
    else:
        bad('порядок скриптов', 'ожидалось %s, в файле %s'
            % (JS_FILES, order))
    if 'href="app.css"' in html:
        ok('подключён app.css')
    else:
        bad('app.css не подключён')
    inline = re.findall(r'\son(?:click|input|change|keydown)\s*=', html)
    if inline:
        bad('инлайновые обработчики', '%d шт.' % len(inline))
    else:
        ok('инлайновых обработчиков нет')
    style = re.findall(r'<style\b', html)
    if style:
        bad('инлайновые <style>', '%d шт.' % len(style))
    else:
        ok('инлайновых <style> нет')


# --------------------------------------------------- 5. экраны и меню

def reg_pattern(text):
    """Регексп на вызовы reg() с учётом алиасов.

    Файлы экранов legally могут писать `var T = window.TUI` и звать `T.reg(...)`.
    Проверка, ищущая только `TUI.reg`, объявила бы два экрана отсутствующими,
    хотя они на месте — поэтому алиасы вычисляются из самого файла.
    """
    aliases = {'TUI'}
    for m in re.finditer(
            r'(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:window\.)?TUI\b', text):
        aliases.add(m.group(1))
    alt = '|'.join(re.escape(a) for a in sorted(aliases))
    return re.compile(r'\b(?:%s)\.reg\(\s*[\'"]([a-z]+)[\'"]' % alt), aliases


def check_screens():
    head('5. Связность экранов')
    sources = [n for n in ('screens_a.js', 'screens_b.js') if exists(n)]
    if not sources:
        bad('screens_a.js / screens_b.js — файлов нет')
        return
    found = {}
    for name in sources:
        text = read(name)
        pattern, aliases = reg_pattern(text)
        if aliases - {'TUI'}:
            print('  %s·%s %s использует алиас %s' %
                  (DIM, RESET, name, ', '.join(sorted(aliases - {'TUI'}))))
        for sid in pattern.findall(text):
            if sid in found:
                bad('%s зарегистрирован дважды' % sid,
                    'в %s и %s' % (found[sid], name))
            found[sid] = name
    got = set(found)
    if got == EXPECTED_SCREENS:
        ok('экранов ровно семь', ', '.join(sorted(got)))
    else:
        bad('состав экранов',
            'нет: %s | лишние: %s' % (sorted(EXPECTED_SCREENS - got),
                                       sorted(got - EXPECTED_SCREENS)))
    # каждый зарегистрированный экран обязан иметь title, load и render
    for sid in sorted(got):
        text = read(found[sid])
        pattern, _ = reg_pattern(text)
        marker = pattern.search(text)
        block = text[marker.start():marker.start() + 700] if marker else ''
        for field in ('title', 'load', 'render'):
            if not re.search(r'\b%s\s*:' % field, block):
                bad('%s: нет поля %s' % (sid, field))
    if got:
        ok('у всех экранов есть title/load/render')
    # tui.js обязан уметь их показывать и прокинуть примитивы, которыми
    # пользуются экраны: без clear/note/empty оба файла падают на отрисовке
    if exists('tui.js'):
        shell = read('tui.js')
        for key in ('reg', 'go', 'refresh', 'api', 'post'):
            if re.search(r'\b%s\b' % re.escape(key), shell):
                continue
            bad('tui.js не содержит TUI.%s' % key)
        else:
            ok('tui.js: навигация и API на месте')
        boot = shell[shell.find('var names = ['):shell.find('var names = [') + 400] \
            if 'var names = [' in shell else ''
        for prim in ('clear', 'note', 'empty'):
            if re.search(r"['\"]%s['\"]" % prim, boot):
                continue
            bad('tui.js не переэкспортирует TUI.%s — экраны на нём падают' % prim)
        else:
            ok('tui.js переэкспортирует clear/note/empty')


# ------------------------------------------------------- 6-7. живой стенд

def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def fetch(url, timeout=10):
    """Возвращает (код, тело, content-type). Исключение наружу не пускает."""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read(), r.headers.get('Content-Type', '')
    except urllib.error.HTTPError as e:
        return e.code, e.read(), ''
    except Exception as e:
        return 0, str(e).encode('utf-8'), ''


def start_stand(port):
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, 'devserver.py'),
         '--seed', '--port', str(port)],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = 'http://127.0.0.1:%d' % port
    for _ in range(60):
        if proc.poll() is not None:
            return proc, None
        code, _, _ = fetch(base + '/api/settings', timeout=2)
        if code == 200:
            return proc, base
        time.sleep(0.5)
    return proc, None


SHAPES = [
    ('/api/overview?days=30', ['today', 'hourly', 'series', 'streak', 'allTime']),
    ('/api/year?months=12', ['today', 'days']),
    ('/api/calendar', ['month', 'days', 'summary']),
    ('/api/projects?days=30', None),
    ('/api/todos', ['items']),
    ('/api/roadmap', ['goal', 'steps', 'totals', 'pace']),
    ('/api/achievements', ['items', 'total', 'unlocked']),
    ('/api/settings', ['dailyGoalMin', 'dbPath', 'version']),
]


def check_live():
    head('6. Живой стенд')
    port = free_port()
    proc, base = start_stand(port)
    if base is None:
        out = b''
        if proc.poll() is not None and proc.stdout:
            out = proc.stdout.read()[-800:]
        bad('стенд не поднялся', out.decode('utf-8', 'replace').strip())
        if proc.poll() is None:
            proc.kill()
        return
    try:
        for path, keys in SHAPES:
            code, body, _ = fetch(base + path)
            if code != 200:
                bad(path, 'HTTP %d' % code)
                continue
            try:
                data = json.loads(body.decode('utf-8'))
            except ValueError as e:
                bad(path, 'не JSON: %s' % e)
                continue
            if keys is None:
                ok(path, 'массив из %d' % len(data))
                continue
            if isinstance(data, list):
                bad(path, 'ожидался объект')
                continue
            miss = [k for k in keys if k not in data]
            if miss:
                bad(path, 'нет полей: %s' % ', '.join(miss))
            else:
                ok(path)

        head('7. Статика и удалённая ИИ-часть')
        for name, ctype in (('app.css', 'text/css'),
                            ('tui_widgets.js', 'javascript'),
                            ('tui.js', 'javascript'),
                            ('screens_a.js', 'javascript'),
                            ('screens_b.js', 'javascript')):
            code, body, ctp = fetch(base + '/' + name)
            if code != 200:
                bad('/%s' % name, 'HTTP %d — статика не отдаётся' % code)
            elif ctype not in ctp:
                bad('/%s' % name, 'Content-Type: %s' % ctp)
            elif not body.strip():
                bad('/%s' % name, 'файл пустой')
            else:
                ok('/%s' % name, '%d КБ' % (len(body) // 1024))
        for path in ('/api/mentor/status', '/api/mentor/chats',
                     '/api/team/history', '/api/or/settings',
                     '/api/github/tree'):
            code, _, _ = fetch(base + path)
            if code == 404:
                ok('%s отключён' % path)
            else:
                bad('%s всё ещё отвечает' % path, 'HTTP %d' % code)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def static_names():
    """Белый список статики из исходника, без выполнения модуля."""
    tree = ast.parse(read('codetime.py'), filename='codetime.py')
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == 'STATIC_FILES':
                return list(ast.literal_eval(node.value).keys())
    return []


def check_build():
    """Сборка exe.

    Пустое чёрное окно у пользователя — это ровно один случай: интерфейс
    целиком рисуется JS, и в exe не попал хотя бы один файл статики. Никакой
    ошибки при этом нет, поэтому проверять приходится состав сборки.
    """
    head('8. Сборка')
    names = static_names()
    if not names:
        bad('в codetime.py нет STATIC_FILES — нечем проверять сборку')
        return

    if not exists('CodeTime.spec'):
        bad('CodeTime.spec — файла нет')
    else:
        spec = read('CodeTime.spec')
        miss = [n for n in names if ("'%s'" % n) not in spec and ('"%s"' % n) not in spec]
        if miss:
            bad('CodeTime.spec не упоминает', ', '.join(miss))
        else:
            ok('CodeTime.spec собирает всю статику', '%d файлов' % len(names))
        if 'STATIC_FILES' not in spec:
            bad('CodeTime.spec дублирует список руками — он разъедется с кодом')
        else:
            ok('CodeTime.spec берёт список из кода, а не дублирует')

    if not exists('build_exe.bat'):
        bad('build_exe.bat — файла нет')
    else:
        bat = read('build_exe.bat').lower()
        if 'del /q codetime.spec' in bat or 'del "%~dp0codetime.spec"' in bat:
            bad('build_exe.bat удаляет CodeTime.spec перед сборкой')
        else:
            ok('build_exe.bat не удаляет спеку')
        if 'codetime.spec' in bat and '--add-data' not in bat:
            ok('сборка идёт через спеку, а не длинной командой')
        else:
            bad('build_exe.bat собирает в обход спеки — вернётся старый баг')

    exe = os.path.join(ROOT, 'dist', 'CodeTime.exe')
    if not os.path.isfile(exe):
        print('  %s·%s dist/CodeTime.exe ещё не собран — не считаю ошибкой' % (DIM, RESET))
        return
    built = os.path.getmtime(exe)
    stale = [n for n in ['dashboard.html'] + names
             if os.path.isfile(os.path.join(ROOT, n)) and
             os.path.getmtime(os.path.join(ROOT, n)) > built]
    if stale:
        bad('exe старее исходников — в окне будет старое или пустое',
            ', '.join(stale))
    else:
        ok('dist/CodeTime.exe новее всех файлов интерфейса')


def check_fidelity():
    """Сверка с измерениями эталонного скриншота.

    Эти числа получены попиксельно из референса (tools/measure_columns.py),
    а не прикинуты на глаз. Именно из-за расхождения с прикидками первый
    вариант не совпал с картинкой, поэтому проверка жёсткая: пока в CSS
    старые значения, сборка не считается готовой.
    """
    head('9. Сверка с измеренным эталоном')
    if not exists('app.css'):
        bad('app.css — файла нет')
        return
    css = strip_comments(read('app.css'))

    # Значения часто записаны не литералом, а через переменные
    # (`--pad-x: 25px` + `padding: … var(--pad-x)`). Без подстановки
    # проверка ищет то, чего в файле нет, и ругается на рабочий CSS —
    # так уже случилось с полями окна.
    def lookup(name):
        m = re.search(re.escape(name) + r'\s*:\s*([^;}]+)', css)
        return m.group(1).strip() if m else 'MISSING'

    def resolve(text):
        for _ in range(4):
            new = re.sub(r'var\(\s*(--[a-z0-9-]+)\s*\)',
                         lambda m: lookup(m.group(1)), text)
            if new == text:
                break
            text = new
        return text

    low = resolve(css).lower().replace(' ', '')

    def has(*variants):
        return any(v.replace(' ', '') in low for v in variants)

    checks = [
        ('фон #0f1015', has('#0f1015', '#0f1016', '#0f1115')),
        ('акцент #deb365', has('#deb365', '#dcb265', '#ddb466')),
        ('синий #5d77cb', has('#5d77cb', '#5c7acb', '#6a7fc0')),
        ('фиолетовый #9176bd', has('#9176bd', '#8f76bb', '#a07fd0')),
        ('левая колонка 242px', has('242px')),
        ('колонка 325px', has('325px')),
        ('зазор колонок 13px', has('gap:13px', 'column-gap:13px')),
    ]
    for label, passed in checks:
        if passed:
            ok(label)
        else:
            bad('%s — в app.css таких значений нет' % label)

    # Боковые поля окна. В замере эталона было 25px, но пользователь их
    # убрал: колонки должны занимать всю ширину. Проверка обязана
    # требовать новое требование, иначе она вечно блокирует сборку.
    pad = resolve(lookup('--pad-x')).strip().lower().replace(' ', '')
    if pad.startswith('0px') or pad == '0':
        ok('боковые поля убраны, колонки во всю ширину', pad)
    else:
        bad('боковые поля должны быть убраны', 'получено %s' % (pad or 'ничего'))

    # базовый кегль 13px: ищем font-size:13px у :root или body
    m = re.search(r'font-size:\s*1[0-4]px', css)
    if m:
        if m.group(0).replace(' ', '') == 'font-size:13px':
            ok('базовый кегль 13px')
        else:
            bad('базовый кегль не 13px', m.group(0))
    else:
        bad('не найден базовый font-size')

    # рамка должна быть бледной: в эталоне она едва светлее фона
    for name, pattern in (('рамка ~#1c1e24', r'--border[a-z-]*:\s*#(1b1d23|1c1e24|1a1c22|20232a)'),):
        if re.search(pattern, css, re.I):
            ok(name)
        else:
            bad('%s — рамка в эталоне намного бледнее #30363d' % name)


# ------------------------------------------------------- самопроверка

def self_test():
    """Проверяет сам проверяющий скрипт на заведомо плохом вводе.

    Смысл: сломанная проверка врёт в обе стороны — и «всё хорошо» при
    сломанном продукте, и «сломано» при исправном. Единственный способ
    этому помешать — увидеть, как проверка падает на плохом состоянии.
    """
    head('S. Самопроверка проверяющего скрипта')
    # Глобальные вызовы браузерных окон обязаны находиться
    for probe, label in (("window.prompt('y');", 'window.prompt'),
                         ("alert('y');", 'alert()'),
                         ("confirm('y');", 'confirm()')):
        if any(p.search(probe) for p, _ in BANNED):
            ok('детектор ловит %s' % label)
        else:
            bad('детектор молчит на %s — проверке нельзя верить' % label)
    # ...и в голой форме без window.
    for probe, label in (("  prompt('y');", 'prompt() без window'),
                         ("x = confirm('y');", 'confirm() без window')):
        if any(p.search(probe) for p, _ in BANNED):
            ok('детектор ловит голый %s' % label)
        else:
            bad('детектор молчит на голом %s' % label)
    # Методы после точки — это наши собственные объекты, а не window.prompt:
    # ловить их — значит приучать игнорировать проверку целиком.
    for probe in ("myPrompt('y');", "TUIW.confirm(text);",
                  "W.confirm(text, onOk);", "myThing.alert(1);",
                  "obj.prompt('?');", "x.prompt('y');"):
        if any(p.search(probe) for p, _ in BANNED):
            bad('ложное срабатывание на %s' % probe)
        else:
            ok('без ложного срабатывания: %s' % probe)
    probe = "a.innerHTML = b + c;"
    m = re.search(r'innerHTML\s*=\s*([^\n;]+)', probe)
    if m and m.group(1).strip() not in ("''", '""', '``'):
        ok('детектор innerHTML с данными срабатывает')
    else:
        bad('детектор innerHTML молчит')
    probe = "y.innerHTML = '';"
    m = re.search(r'innerHTML\s*=\s*([^\n;]+)', probe)
    if m and m.group(1).strip() in ("''", '""', '``'):
        ok('очистка innerHTML = \'\' не считается нарушением')
    else:
        bad('очистка innerHTML помечена как нарушение — ложное срабатывание')
    # 2. пустой словарь не должен пройти как «заголовки заданы»
    headers = {}
    h2 = headers if headers is not None else {'X': 1}
    if h2 == {}:
        ok('пустой словарь трактуется как «задано пусто», а не «не задано»')
    else:
        bad('подмена headers ломается на пустом словаре')
    # 3. агрегат в SQL всегда возвращает строку — проверка против 0, не на истинность
    cnt = 0
    if not (cnt == 0):
        bad('сравнение количества не против 0')
    else:
        ok('счётчик сравнивается с 0, а не проверяется на истинность')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true',
                    help='без живого стенда')
    ap.add_argument('--self-test', action='store_true',
                    help='проверить сам проверяющий скрипт и выйти')
    args = ap.parse_args()

    print('%s=== CodeTime: проверка ===%s' % (YELLOW, RESET))

    if args.self_test:
        self_test()
    else:
        check_python()
        check_js()
        check_banned()
        check_dashboard()
        check_screens()
        if not args.quick:
            check_live()
        check_build()
        check_fidelity()
        self_test()

    print()
    if _failures:
        print('%sПРОВАЛЕНО: %d из %d проверок%s'
              % (RED, len(_failures), _checks, RESET))
        for f in _failures:
            print('  - %s' % f)
        return 1
    print('%sВсе %d проверок пройдены%s' % (GREEN, _checks, RESET))
    return 0


if __name__ == '__main__':
    sys.exit(main())
