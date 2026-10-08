# -*- coding: utf-8 -*-
"""
Стенд для разработки интерфейса CodeTime.

Зачем он нужен. У пользователя есть настоящие данные: база трекера лежит в
%APPDATA%\\CodeTime, а папка наставника — в %USERPROFILE%\\CodeTimeMentor
(там ключи OpenRouter и GitHub). Любой запуск для отладки не должен их
видеть. Поэтому ДО импорта codetime подменяются USERPROFILE, HOME, APPDATA
и LOCALAPPDATA на песочницу рядом с проектом, а потом проверяется, что
реально разрешилось внутрь неё. Если проверка не прошла — стенд отказывается
стартовать, а не стартует «как получится».

Запуск:

    python devserver.py --seed --port 5750

Что делает: поднимает ТОЛЬКО локальный HTTP-сервер с тем же обработчиком,
что и настоящее приложение. Без трея, без окна, без ярлыка, без перехвата
клавиатуры и мыши — иначе стенд сам стал бы вторым экземпляром трекера.
"""

import argparse
import os
import random
import shutil
import sqlite3
import sys
import threading
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SANDBOX = os.path.join(HERE, '.devsandbox')

# --- песочница ------------------------------------------------------------
# Именно это, а не только CODETIME_DATA_DIR: папка наставника в mentor.py
# вычислялась из os.path.expanduser('~'), а та на Windows берёт USERPROFILE.
os.environ['USERPROFILE'] = os.path.join(SANDBOX, 'User')
os.environ['HOME'] = os.environ['USERPROFILE']
os.environ['APPDATA'] = os.path.join(SANDBOX, 'User', 'AppData', 'Roaming')
os.environ['LOCALAPPDATA'] = os.path.join(SANDBOX, 'User', 'AppData', 'Local')
os.environ['CODETIME_DATA_DIR'] = os.path.join(SANDBOX, 'User', 'AppData',
                                              'Roaming', 'CodeTime')
os.environ['NO_COLOR'] = '1'

sys.path.insert(0, HERE)
import codetime  # noqa: E402  (импорт после подмены окружения — так и задумано)


def check_sandbox():
    """Убеждается, что ни БД, ни домашняя папка не ведут наружу песочницы."""
    problems = []
    real = os.path.realpath(SANDBOX)
    for label, path in (('БД трекера', codetime.data_dir()),
                        ('домашняя папка', os.path.expanduser('~'))):
        target = os.path.realpath(path)
        if not (target == real or target.startswith(real + os.sep)):
            problems.append('%s -> %s' % (label, target))
    if problems:
        sys.stderr.write(
            'СТЕНД НЕ ЗАПУЩЕН: пути выходят за песочницу.\n  '
            + '\n  '.join(problems) + '\nПесочница: %s\n' % real)
        raise SystemExit(2)
    return real


PROJECTS = [
    ('pdp-product-page', 5.2), ('tracer-vs-code', 3.4),
    ('my-app', 2.1), ('chat-app', 1.6), ('CodeTime', 1.1),
]
LANGS = [('TypeScript', 4.0), ('JavaScript', 3.0), ('HTML', 2.0),
         ('CSS', 1.6), ('Python', 1.0), ('JSON', 0.4)]
TASK_POOL = ['дописать отчёт', 'рефакторинг роутера', 'вёрстка шапки',
             'вычитать главу', 'починить тесты', 'нарисовать схему БД',
             'разобрать чужой код', 'залить на GitHub', 'собрать сборку',
             'свести заметки', 'позвонить наставнику', 'отдохнуть']


def seed(db_file, days=150):
    """Наполняет базу правдоподобными данными: будни — работа, выходные — мало.

    Идемпотентна: таблицы чистятся перед заполнением, иначе второй запуск
    падает на UNIQUE-ограничении — стенд должен переживать перезапуск.
    """
    rnd = random.Random(42)
    conn = sqlite3.connect(db_file)
    for table in ('day_stats', 'hour_stats', 'lang_stats', 'todos',
                  'roadmap_steps', 'roadmap_goal'):
        conn.execute('DELETE FROM "%s"' % table)
    conn.commit()
    today = date.today()
    lang_names = [n for n, _ in LANGS]
    lang_w = [w for _, w in LANGS]
    proj_names = [n for n, _ in PROJECTS]
    proj_w = [w for _, w in PROJECTS]

    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        iso = d.isoformat()
        weekend = d.weekday() >= 5
        if rnd.random() < (0.18 if weekend else 0.06):
            continue                      # день без данных — ноль в интерфейсе
        total_h = rnd.uniform(0.6, 2.4) if weekend else rnd.uniform(3.0, 9.5)
        total_h = min(total_h, 11.0)
        n_proj = rnd.randint(1, 3)
        weights = [rnd.random() * w for w in proj_w]
        picked = rnd.sample(range(len(proj_names)), n_proj)
        share = sum(weights[p] for p in picked) or 1.0
        first_hour = 8 if not weekend else 11
        last_hour = min(23, first_hour + int(total_h) + 2)
        for p in picked:
            hours = total_h * weights[p] / share
            active = int(hours * 3600)
            idle = int(active * rnd.uniform(0.05, 0.28))
            conn.execute(
                'INSERT OR REPLACE INTO day_stats (date, project, active_sec, '
                'idle_sec, clicks, chars, words, sessions, max_session_sec) '
                'VALUES (?,?,?,?,?,?,?,?,?)',
                (iso, proj_names[p], active, idle,
                 int(active / rnd.uniform(4, 9)),
                 int(active * rnd.uniform(2.0, 4.5)),
                 int(active * rnd.uniform(0.3, 0.7)),
                 rnd.randint(2, 9), int(active * 0.4)))
        # почасовка: неравномерно, пик днём
        remain = int(total_h * 3600)
        for h in range(first_hour, last_hour + 1):
            if remain <= 0:
                break
            peak = 1.0 if 10 <= h <= 18 else 0.35
            sec = min(remain, int(3600 * peak * rnd.uniform(0.5, 1.0)))
            remain -= sec
            if sec > 0:
                conn.execute(
                    'INSERT OR REPLACE INTO hour_stats (date, hour, active_sec,'
                    ' chars) VALUES (?,?,?,?)',
                    (iso, h, sec, int(sec * 3)))
        # языки
        for name, w in rnd.sample(list(zip(lang_names, lang_w)),
                                  rnd.randint(2, 4)):
            conn.execute(
                'INSERT INTO lang_stats (date, lang, active_sec) VALUES (?,?,?)',
                (iso, name, int(total_h * 3600 * w / 4.0)))

    # задачи: сегодня, завтра и ещё пара дней
    for offset, count in ((0, 3), (1, 2), (2, 1), (-1, 2), (4, 1)):
        d = (today + timedelta(days=offset)).isoformat()
        for k in range(count):
            conn.execute(
                'INSERT INTO todos (date, title, minutes, done, source, '
                'created_at) VALUES (?,?,?,?,?,?)',
                (d, TASK_POOL[(offset * 3 + k) % len(TASK_POOL)],
                 rnd.choice([0, 20, 30, 45, 60, 90]),
                 1 if (offset < 0 or (offset == 0 and k == 0)) else 0,
                 'manual', datetime_now()))

    # план обучения
    conn.execute(
        'INSERT OR REPLACE INTO roadmap_goal (id, title, target_date, daily_hours)'
        ' VALUES (1,?,?,?)',
        ('Дойти до Junior/Middle', (today + timedelta(days=180)).isoformat(), 4.0))
    for idx, (title, hours) in enumerate([
            ('HTML и CSS, вёрстка', 30), ('JavaScript: основы', 40),
            ('Git и командная работа', 10), ('Асинхронность и fetch', 20),
            ('React: компоненты', 45), ('Тесты и отладка', 25)]):
        conn.execute(
            'INSERT INTO roadmap_steps (title, hours, status, order_idx, '
            'spent_sec, created_at) VALUES (?,?,?,?,?,?)',
            (title, hours, 'todo', idx,
             int(hours * 3600) if idx < 2 else int(hours * 3600 * 0.3),
             datetime_now()))
    conn.commit()
    conn.close()


def datetime_now():
    from datetime import datetime
    return datetime.now().isoformat(timespec='seconds')


def main():
    ap = argparse.ArgumentParser(description='Стенд CodeTime в песочнице')
    ap.add_argument('--port', type=int, default=5750)
    ap.add_argument('--seed', action='store_true',
                    help='заполнить базу демо-данными')
    ap.add_argument('--days', type=int, default=150,
                    help='сколько дней заполнять при --seed')
    ap.add_argument('--reset', action='store_true',
                    help='снести песочницу целиком перед стартом')
    args = ap.parse_args()

    if args.reset and os.path.isdir(SANDBOX):
        shutil.rmtree(SANDBOX, ignore_errors=True)

    real = check_sandbox()
    for sub in ('User/AppData/Roaming/CodeTime', 'User/AppData/Local'):
        os.makedirs(os.path.join(SANDBOX, sub), exist_ok=True)

    app = codetime.CodeTimeApp()
    codetime.APP = app
    app.conn = codetime.init_db()
    app.load_settings()
    app.clamp_settings()

    if args.seed:
        seed(app.conn.execute('PRAGMA database_list').fetchone()[2], args.days)
        codetime.reset_metrics_cache()
        print('Демо-данные заполнены: %d дней' % args.days)

    from http.server import ThreadingHTTPServer
    try:
        httpd = ThreadingHTTPServer(('127.0.0.1', args.port), codetime.Handler)
    except OSError as e:
        sys.stderr.write('Порт %d занят: %s\n' % (args.port, e))
        raise SystemExit(1)

    print('Стенд: http://127.0.0.1:%d/' % args.port)
    print('Песочница: %s' % real)
    print('БД: %s' % codetime.db_path())
    print('Ctrl+C — остановить')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nОстановлено')
    finally:
        try:
            app.conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
