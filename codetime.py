# -*- coding: utf-8 -*-
"""
CodeTime — тихий фоновый трекер времени, проводимого в VS Code (Windows).

Как это работает:
  * Поток-движок раз в секунду смотрит foreground-окно:
      - VS Code в фокусе            -> активная секунда;
      - VS Code запущен, но не в фокусе (свёрнут / другое окно / второй
        монитор)                    -> секунда паузы;
      - VS Code закрыт              -> секунда не считается НИКУДА.
  * Глобальные хуки pynput считают клики/символы/слова ТОЛЬКО когда
    VS Code в фокусе.
  * Данные копятся в памяти и раз в 10 секунд сбрасываются (UPSERT) в
    SQLite: %APPDATA%\\CodeTime\\codetime.db
  * Языки: из заголовка окна берётся имя файла ('index.ts - my-app - ...'
    → TypeScript) и копится в таблицу lang_stats — для топа языков.
  * Локальный веб-сервер http://localhost:5731 отдаёт дашборд и JSON API.
  * Трей-иконка (pystray): открыть статистику, пауза, автозапуск, выход.
  * 100 достижений (порт src/lib/achievements.ts) пересчитываются раз в 60 сек.
  * План обучения («План»): цель с датой и шаги, СИНХРОНИЗИРОВАННЫЕ с
    активным временем из «Обзора» — активные секунды с даты старта плана
    последовательно «заливаются» в шаги, у каждого шага виден прогресс.
  * Задачи («Задачи»): по дням, с группировкой сегодня/завтра/послезавтра/
    через неделю/позже, режим массового удаления.
  * Самообновление через GitHub Releases: приложение само проверяет
    последний релиз, скачивает новый CodeTime.exe и подменяет себя
    (Настройки → Обновление).

Всё Windows-специфичное обёрнуто в try/except: на других ОС приложение
хотя бы поднимет сервер для отладки.
"""

import atexit
import json
import logging
import math
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections import defaultdict
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

# ============================================================
# Константы
# ============================================================

APP_NAME = 'CodeTime'
APP_VERSION = '1.8.0'
WINDOW_TITLE = 'CodeTime'   # заголовок нативного окна (и цель FindWindow)
PORT = 5731
BASE_URL = 'http://localhost:%d' % PORT

IS_WINDOWS = (os.name == 'nt')

VSCODE_PROCESSES = {
    'code.exe',
    'code - insiders.exe',
    'code - oss.exe',
    'vscodium.exe',
}
VS_SUFFIXES = (' - visual studio code', ' - vscodium')

# Настройки по умолчанию (хранятся в таблице meta)
DEFAULT_SETTINGS = {
    'daily_goal_min': 120,      # дневная цель, минут (30..480)
    'track_clicks': 1,          # считать клики
    'track_keys': 1,            # считать клавиши/символы/слова
    'autostart': 0,             # автозапуск с Windows
    'paused': 0,                # пауза из трея (ручная)
}

# Сессия считается оборванной, если активной секунды не было дольше этого
# времени (порог простоя из настроек больше не используется).
SESSION_BREAK_SEC = 300

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'

# Репозиторий GitHub для проверки обновлений (формат 'user/CodeTime').
# Можно переопределить прямо в приложении: Настройки → Обновление.
GITHUB_REPO_DEFAULT = 'Fankor70/Tracer-vs-code'

H = 3600  # секунд в часе (для целей достижений)


def data_dir():
    """Папка данных: %APPDATA%/CodeTime (или ~/CodeTime вне Windows)."""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, APP_NAME)


def db_path():
    return os.path.join(data_dir(), 'codetime.db')


# ============================================================
# 100 достижений — ПОРТ 1-в-1 из src/lib/achievements.ts
# (те же id, name, desc, category, icon, target, unit)
# ============================================================

CATEGORY_LABELS = {
    'time': 'Время',
    'actions': 'Действия',
    'streaks': 'Серии',
    'projects': 'Проекты',
    'mode': 'Режим дня',
    'special': 'Особые',
}

ACHIEVEMENTS = [
    # ---------- ВРЕМЯ (20) ----------
    {'id': 'time_total_1h', 'name': 'Первый час', 'desc': 'Провести 1 час активного кодинга суммарно', 'category': 'time', 'icon': 'Clock', 'target': 1 * H, 'unit': 'seconds'},
    {'id': 'time_total_10h', 'name': 'Втянулся', 'desc': '10 часов активного кодинга суммарно', 'category': 'time', 'icon': 'Clock', 'target': 10 * H, 'unit': 'seconds'},
    {'id': 'time_total_50h', 'name': 'Серьёзный подход', 'desc': '50 часов активного кодинга суммарно', 'category': 'time', 'icon': 'Clock', 'target': 50 * H, 'unit': 'seconds'},
    {'id': 'time_total_100h', 'name': 'Сотня часов кода', 'desc': '100 часов активного кодинга суммарно', 'category': 'time', 'icon': 'Hourglass', 'target': 100 * H, 'unit': 'seconds'},
    {'id': 'time_total_250h', 'name': 'Четверть тысячи', 'desc': '250 часов активного кодинга суммарно', 'category': 'time', 'icon': 'Hourglass', 'target': 250 * H, 'unit': 'seconds'},
    {'id': 'time_total_500h', 'name': 'Мастер времени', 'desc': '500 часов активного кодинга суммарно', 'category': 'time', 'icon': 'Timer', 'target': 500 * H, 'unit': 'seconds'},
    {'id': 'time_total_1000h', 'name': 'Тысячник', 'desc': '1000 часов активного кодинга суммарно', 'category': 'time', 'icon': 'Timer', 'target': 1000 * H, 'unit': 'seconds'},
    {'id': 'time_total_2500h', 'name': 'Профи', 'desc': '2500 часов активного кодинга суммарно', 'category': 'time', 'icon': 'Crown', 'target': 2500 * H, 'unit': 'seconds'},
    {'id': 'time_total_5000h', 'name': 'Ветеран клавиатуры', 'desc': '5000 часов активного кодинга суммарно', 'category': 'time', 'icon': 'Crown', 'target': 5000 * H, 'unit': 'seconds'},
    {'id': 'time_day_1h', 'name': 'Первый рабочий день', 'desc': '1 час активности за один день', 'category': 'time', 'icon': 'Sun', 'target': 1 * H, 'unit': 'seconds'},
    {'id': 'time_day_4h', 'name': 'Продуктивный день', 'desc': '4 часа активности за один день', 'category': 'time', 'icon': 'Sun', 'target': 4 * H, 'unit': 'seconds'},
    {'id': 'time_day_8h', 'name': 'Полный рабочий день', 'desc': '8 часов активности за один день', 'category': 'time', 'icon': 'Briefcase', 'target': 8 * H, 'unit': 'seconds'},
    {'id': 'time_day_12h', 'name': 'Неразлучники', 'desc': '12 часов активности за один день', 'category': 'time', 'icon': 'Flame', 'target': 12 * H, 'unit': 'seconds'},
    {'id': 'time_day_16h', 'name': 'Марафонец', 'desc': '16 часов активности за один день', 'category': 'time', 'icon': 'Flame', 'target': 16 * H, 'unit': 'seconds'},
    {'id': 'time_week_40h', 'name': 'Неделя кода', 'desc': '40 часов за любые 7 дней подряд', 'category': 'time', 'icon': 'CalendarRange', 'target': 40 * H, 'unit': 'seconds'},
    {'id': 'idle_total_10m', 'name': 'Перерывчик', 'desc': 'Накопить первые 10 минут паузы', 'category': 'time', 'icon': 'Coffee', 'target': 10 * 60, 'unit': 'seconds'},
    {'id': 'idle_total_10h', 'name': 'Кофе-брейк', 'desc': 'Накопить 10 часов паузы суммарно', 'category': 'time', 'icon': 'Coffee', 'target': 10 * H, 'unit': 'seconds'},
    {'id': 'idle_total_100h', 'name': 'Мастер релакса', 'desc': 'Накопить 100 часов паузы суммарно', 'category': 'time', 'icon': 'Armchair', 'target': 100 * H, 'unit': 'seconds'},
    {'id': 'time_night_1h', 'name': 'Полуночник', 'desc': '1 час активности ночью (00:00–05:00) за один день', 'category': 'time', 'icon': 'Moon', 'target': 1 * H, 'unit': 'seconds'},
    {'id': 'time_early_1h', 'name': 'Жаворонок', 'desc': '1 час активности до 07:00 за один день', 'category': 'time', 'icon': 'Sunrise', 'target': 1 * H, 'unit': 'seconds'},

    # ---------- ДЕЙСТВИЯ (20) ----------
    {'id': 'clicks_100', 'name': 'Первая сотня', 'desc': 'Сделать 100 кликов в VS Code', 'category': 'actions', 'icon': 'MousePointerClick', 'target': 100, 'unit': 'count'},
    {'id': 'clicks_1k', 'name': 'Кликер', 'desc': 'Сделать 1 000 кликов', 'category': 'actions', 'icon': 'MousePointerClick', 'target': 1000, 'unit': 'count'},
    {'id': 'clicks_10k', 'name': 'Мастер мыши', 'desc': 'Сделать 10 000 кликов', 'category': 'actions', 'icon': 'MousePointerClick', 'target': 10000, 'unit': 'count'},
    {'id': 'clicks_100k', 'name': 'Снайпер', 'desc': 'Сделать 100 000 кликов', 'category': 'actions', 'icon': 'Target', 'target': 100000, 'unit': 'count'},
    {'id': 'clicks_1m', 'name': 'Миллионер кликов', 'desc': 'Сделать 1 000 000 кликов', 'category': 'actions', 'icon': 'Target', 'target': 1000000, 'unit': 'count'},
    {'id': 'chars_1k', 'name': 'Первые буквы', 'desc': 'Ввести 1 000 символов', 'category': 'actions', 'icon': 'Keyboard', 'target': 1000, 'unit': 'count'},
    {'id': 'chars_10k', 'name': 'Наборщик', 'desc': 'Ввести 10 000 символов', 'category': 'actions', 'icon': 'Keyboard', 'target': 10000, 'unit': 'count'},
    {'id': 'chars_100k', 'name': 'Литератор', 'desc': 'Ввести 100 000 символов', 'category': 'actions', 'icon': 'Keyboard', 'target': 100000, 'unit': 'count'},
    {'id': 'chars_1m', 'name': 'Миллион символов', 'desc': 'Ввести 1 000 000 символов', 'category': 'actions', 'icon': 'FileText', 'target': 1000000, 'unit': 'count'},
    {'id': 'chars_10m', 'name': 'Библиотека', 'desc': 'Ввести 10 000 000 символов', 'category': 'actions', 'icon': 'Library', 'target': 10000000, 'unit': 'count'},
    {'id': 'words_100', 'name': 'Первые слова', 'desc': 'Ввести 100 слов', 'category': 'actions', 'icon': 'Type', 'target': 100, 'unit': 'count'},
    {'id': 'words_1k', 'name': 'Болтливый кодер', 'desc': 'Ввести 1 000 слов', 'category': 'actions', 'icon': 'Type', 'target': 1000, 'unit': 'count'},
    {'id': 'words_10k', 'name': 'Словарный запас', 'desc': 'Ввести 10 000 слов', 'category': 'actions', 'icon': 'BookOpen', 'target': 10000, 'unit': 'count'},
    {'id': 'words_100k', 'name': 'Писатель', 'desc': 'Ввести 100 000 слов', 'category': 'actions', 'icon': 'BookOpen', 'target': 100000, 'unit': 'count'},
    {'id': 'clicks_day_500', 'name': 'Активный день', 'desc': '500 кликов за один день', 'category': 'actions', 'icon': 'Zap', 'target': 500, 'unit': 'count'},
    {'id': 'chars_day_5k', 'name': 'Поток сознания', 'desc': '5 000 символов за один день', 'category': 'actions', 'icon': 'Zap', 'target': 5000, 'unit': 'count'},
    {'id': 'words_day_1k', 'name': 'Тысяча слов в день', 'desc': '1 000 слов за один день', 'category': 'actions', 'icon': 'Feather', 'target': 1000, 'unit': 'count'},
    {'id': 'chars_day_20k', 'name': 'Скорость мысли', 'desc': '20 000 символов за один день', 'category': 'actions', 'icon': 'Gauge', 'target': 20000, 'unit': 'count'},
    {'id': 'sessions_100', 'name': 'Сотня подходов', 'desc': '100 сессий (подходов к коду)', 'category': 'actions', 'icon': 'Repeat', 'target': 100, 'unit': 'count'},
    {'id': 'sessions_1000', 'name': 'Тысяча подходов', 'desc': '1000 сессий (подходов к коду)', 'category': 'actions', 'icon': 'Repeat', 'target': 1000, 'unit': 'count'},

    # ---------- СЕРИИ (12) ----------
    {'id': 'streak_2', 'name': 'Два дня подряд', 'desc': 'Кодить 2 дня подряд', 'category': 'streaks', 'icon': 'Flame', 'target': 2, 'unit': 'days'},
    {'id': 'streak_3', 'name': 'Тройка', 'desc': 'Кодить 3 дня подряд', 'category': 'streaks', 'icon': 'Flame', 'target': 3, 'unit': 'days'},
    {'id': 'streak_7', 'name': 'Неделя без пропусков', 'desc': 'Кодить 7 дней подряд', 'category': 'streaks', 'icon': 'Flame', 'target': 7, 'unit': 'days'},
    {'id': 'streak_14', 'name': 'Две недели', 'desc': 'Кодить 14 дней подряд', 'category': 'streaks', 'icon': 'Flame', 'target': 14, 'unit': 'days'},
    {'id': 'streak_21', 'name': 'Привычка', 'desc': 'Кодить 21 день подряд', 'category': 'streaks', 'icon': 'Flame', 'target': 21, 'unit': 'days'},
    {'id': 'streak_30', 'name': 'Месяц дисциплины', 'desc': 'Кодить 30 дней подряд', 'category': 'streaks', 'icon': 'Medal', 'target': 30, 'unit': 'days'},
    {'id': 'streak_60', 'name': 'Два месяца', 'desc': 'Кодить 60 дней подряд', 'category': 'streaks', 'icon': 'Medal', 'target': 60, 'unit': 'days'},
    {'id': 'streak_90', 'name': 'Квартал кода', 'desc': 'Кодить 90 дней подряд', 'category': 'streaks', 'icon': 'Trophy', 'target': 90, 'unit': 'days'},
    {'id': 'streak_100', 'name': 'Сотня дней', 'desc': 'Кодить 100 дней подряд', 'category': 'streaks', 'icon': 'Trophy', 'target': 100, 'unit': 'days'},
    {'id': 'streak_180', 'name': 'Полгода', 'desc': 'Кодить 180 дней подряд', 'category': 'streaks', 'icon': 'Award', 'target': 180, 'unit': 'days'},
    {'id': 'streak_365', 'name': 'Год кода', 'desc': 'Кодить 365 дней подряд', 'category': 'streaks', 'icon': 'Crown', 'target': 365, 'unit': 'days'},
    {'id': 'streak_7_hard', 'name': 'Неделя ударного труда', 'desc': '7 дней подряд по 2+ часа', 'category': 'streaks', 'icon': 'Rocket', 'target': 7, 'unit': 'days'},

    # ---------- ПРОЕКТЫ (12) ----------
    {'id': 'proj_first', 'name': 'Первый проект', 'desc': 'Начать отслеживать свой первый проект', 'category': 'projects', 'icon': 'FolderGit2', 'target': 1, 'unit': 'count'},
    {'id': 'proj_3', 'name': 'Тройной удар', 'desc': '3 разных проекта за всю историю', 'category': 'projects', 'icon': 'FolderGit2', 'target': 3, 'unit': 'count'},
    {'id': 'proj_5', 'name': 'Мультизадачность', 'desc': '5 разных проектов за всю историю', 'category': 'projects', 'icon': 'Layers', 'target': 5, 'unit': 'count'},
    {'id': 'proj_10', 'name': 'Десятка', 'desc': '10 разных проектов за всю историю', 'category': 'projects', 'icon': 'Layers', 'target': 10, 'unit': 'count'},
    {'id': 'proj_20', 'name': 'Коллекционер проектов', 'desc': '20 разных проектов за всю историю', 'category': 'projects', 'icon': 'Boxes', 'target': 20, 'unit': 'count'},
    {'id': 'proj_10h', 'name': 'Верность проекту', 'desc': '10 часов в одном проекте', 'category': 'projects', 'icon': 'Heart', 'target': 10 * H, 'unit': 'seconds'},
    {'id': 'proj_100h', 'name': 'Главный проект', 'desc': '100 часов в одном проекте', 'category': 'projects', 'icon': 'Heart', 'target': 100 * H, 'unit': 'seconds'},
    {'id': 'proj_day_3', 'name': 'Жонглёр', 'desc': '3 разных проекта за один день', 'category': 'projects', 'icon': 'Shuffle', 'target': 3, 'unit': 'count'},
    {'id': 'proj_day_5h', 'name': 'Глубокое погружение', 'desc': '5 часов в одном проекте за день', 'category': 'projects', 'icon': 'Anchor', 'target': 5 * H, 'unit': 'seconds'},
    {'id': 'proj_week_3', 'name': 'Командный игрок', 'desc': '3+ проекта за одну неделю', 'category': 'projects', 'icon': 'Users', 'target': 3, 'unit': 'count'},
    {'id': 'proj_day_8h', 'name': 'Один проект — один день', 'desc': '8 часов в одном проекте за день', 'category': 'projects', 'icon': 'Anchor', 'target': 8 * H, 'unit': 'seconds'},
    {'id': 'proj_30d', 'name': 'Долгосрочный', 'desc': 'Проект живёт 30+ дней (от первой до последней активности)', 'category': 'projects', 'icon': 'CalendarClock', 'target': 30, 'unit': 'days'},

    # ---------- РЕЖИМ ДНЯ (10) ----------
    {'id': 'mode_weekend_3h', 'name': 'Выходной кодер', 'desc': '3 часа в субботу или воскресенье', 'category': 'mode', 'icon': 'Palmtree', 'target': 3 * H, 'unit': 'seconds'},
    {'id': 'mode_saturday_5h', 'name': 'Субботний марафон', 'desc': '5 часов в субботу', 'category': 'mode', 'icon': 'Palmtree', 'target': 5 * H, 'unit': 'seconds'},
    {'id': 'mode_monday_3h', 'name': 'Понедельник — день тяжёлый', 'desc': '3 часа в понедельник', 'category': 'mode', 'icon': 'CalendarDays', 'target': 3 * H, 'unit': 'seconds'},
    {'id': 'mode_all_week', 'name': 'Без выходных', 'desc': 'Быть активным все 7 дней недели (пн–вс)', 'category': 'mode', 'icon': 'CalendarCheck', 'target': 1, 'unit': 'count'},
    {'id': 'mode_6am', 'name': 'Кто рано встаёт', 'desc': 'Активность до 06:00 утра', 'category': 'mode', 'icon': 'AlarmClock', 'target': 1, 'unit': 'count'},
    {'id': 'mode_after23', 'name': 'Ночной дозор', 'desc': 'Активность после 23:00', 'category': 'mode', 'icon': 'MoonStar', 'target': 1, 'unit': 'count'},
    {'id': 'mode_midnight', 'name': 'За полночь', 'desc': 'Активность между 00:00 и 04:00', 'category': 'mode', 'icon': 'Moon', 'target': 1, 'unit': 'count'},
    {'id': 'mode_span_12h', 'name': 'Длинный день', 'desc': 'Активность с разбросом 12+ часов за день', 'category': 'mode', 'icon': 'Clock4', 'target': 12, 'unit': 'hours'},
    {'id': 'mode_weekend_streak_4', 'name': 'Мастер выходных', 'desc': '4 выходных подряд с активностью', 'category': 'mode', 'icon': 'Tent', 'target': 4, 'unit': 'days'},
    {'id': 'mode_jan1', 'name': 'Праздничный код', 'desc': 'Кодить 1 января', 'category': 'mode', 'icon': 'PartyPopper', 'target': 1, 'unit': 'count'},

    # ---------- ОСОБЫЕ (26) ----------
    {'id': 'first_record', 'name': 'Самый первый день', 'desc': 'Первая зафиксированная сессия', 'category': 'special', 'icon': 'Sprout', 'target': 1, 'unit': 'days'},
    {'id': 'days_10', 'name': 'Десять дней в строю', 'desc': '10 активных дней (не обязательно подряд)', 'category': 'special', 'icon': 'CalendarCheck', 'target': 10, 'unit': 'days'},
    {'id': 'days_50', 'name': 'Полсотни дней', 'desc': '50 активных дней', 'category': 'special', 'icon': 'CalendarCheck', 'target': 50, 'unit': 'days'},
    {'id': 'days_100', 'name': 'Сто активных дней', 'desc': '100 активных дней', 'category': 'special', 'icon': 'CalendarCheck', 'target': 100, 'unit': 'days'},
    {'id': 'days_365', 'name': 'Год в строю', 'desc': '365 активных дней', 'category': 'special', 'icon': 'Landmark', 'target': 365, 'unit': 'days'},
    {'id': 'month_100h', 'name': 'Месяц-рекорд', 'desc': '100 часов за один календарный месяц', 'category': 'special', 'icon': 'Trophy', 'target': 100 * H, 'unit': 'seconds'},
    {'id': 'week_60h', 'name': 'Полторы рабочей недели', 'desc': '60 часов за любые 7 дней подряд', 'category': 'special', 'icon': 'Trophy', 'target': 60 * H, 'unit': 'seconds'},
    {'id': 'comeback', 'name': 'Возвращение', 'desc': 'Вернуться к коду после паузы 7+ дней', 'category': 'special', 'icon': 'RotateCcw', 'target': 1, 'unit': 'count'},
    {'id': 'stable_30', 'name': 'Стабильность', 'desc': '30 дней подряд по 1+ часу', 'category': 'special', 'icon': 'LineChart', 'target': 30, 'unit': 'days'},
    {'id': 'goal_first', 'name': 'Цель дня', 'desc': 'Выполнить дневную цель — 2 часа', 'category': 'special', 'icon': 'Target', 'target': 2 * H, 'unit': 'seconds'},
    {'id': 'goal_week_14', 'name': 'Две недели по плану', 'desc': '14 дней подряд по 2+ часа', 'category': 'special', 'icon': 'ListChecks', 'target': 14, 'unit': 'days'},
    {'id': 'hours_8_distinct', 'name': 'Разносторонний день', 'desc': 'Активность в 8 разных часах за день', 'category': 'special', 'icon': 'Grid3x3', 'target': 8, 'unit': 'hours'},
    {'id': 'hours_12_distinct', 'name': 'Весь день в деле', 'desc': 'Активность в 12 разных часах за день', 'category': 'special', 'icon': 'Grid3x3', 'target': 12, 'unit': 'hours'},
    {'id': 'quiet_day', 'name': 'Тихий день', 'desc': '2+ часа активности и меньше 100 кликов за день', 'category': 'special', 'icon': 'VolumeX', 'target': 1, 'unit': 'count'},
    {'id': 'click_storm', 'name': 'Скорострел', 'desc': '5 000 кликов за один день', 'category': 'special', 'icon': 'Zap', 'target': 5000, 'unit': 'count'},
    {'id': 'before_noon_5h', 'name': 'До обеда — главное', 'desc': '5 часов активности до 12:00 за день', 'category': 'special', 'icon': 'Sunrise', 'target': 5 * H, 'unit': 'seconds'},
    {'id': 'friday_3h', 'name': 'Пятничный код', 'desc': '3 часа в пятницу', 'category': 'special', 'icon': 'PartyPopper', 'target': 3 * H, 'unit': 'seconds'},
    {'id': 'night_scribe', 'name': 'Ночной снайпер', 'desc': '500+ символов между 01:00 и 05:00 за день', 'category': 'special', 'icon': 'MoonStar', 'target': 500, 'unit': 'count'},
    {'id': 'early_10', 'name': 'Ранний старт', 'desc': '10 дней со стартом до 08:00', 'category': 'special', 'icon': 'AlarmClock', 'target': 10, 'unit': 'days'},
    {'id': 'double_10h', 'name': 'Двойная нагрузка', 'desc': '2 дня с 10+ часами', 'category': 'special', 'icon': 'Dumbbell', 'target': 2, 'unit': 'days'},
    {'id': 'legendary_day', 'name': 'Легендарный день', 'desc': '14 часов за один день', 'category': 'special', 'icon': 'Crown', 'target': 14 * H, 'unit': 'seconds'},
    {'id': 'long_session', 'name': 'Тотальная сессия', 'desc': 'Непрерывная сессия 3+ часа без паузы', 'category': 'special', 'icon': 'Timer', 'target': 3 * H, 'unit': 'seconds'},
    {'id': 'keeper_180', 'name': 'Хранитель времени', 'desc': '180 дней с момента первой записи', 'category': 'special', 'icon': 'Hourglass', 'target': 180, 'unit': 'days'},
    {'id': 'idle_zero_day', 'name': 'Без пауз', 'desc': '4+ часа активности и меньше 5 минут пауз за день', 'category': 'special', 'icon': 'CircleCheck', 'target': 1, 'unit': 'count'},
    {'id': 'idle_day_2h', 'name': 'Мастер перерывов', 'desc': '2 часа паузы за один день', 'category': 'special', 'icon': 'Armchair', 'target': 2 * H, 'unit': 'seconds'},
    {'id': 'deadline_push', 'name': 'Дедлайн', 'desc': '12+ часов за рабочий день (пн–пт)', 'category': 'special', 'icon': 'Flame', 'target': 12 * H, 'unit': 'seconds'},

]

# Сопоставление: id достижения -> ключ метрики в compute_metrics()
ACH_METRIC = {
    # Время
    'time_total_1h': 'total_active', 'time_total_10h': 'total_active', 'time_total_50h': 'total_active',
    'time_total_100h': 'total_active', 'time_total_250h': 'total_active', 'time_total_500h': 'total_active',
    'time_total_1000h': 'total_active', 'time_total_2500h': 'total_active', 'time_total_5000h': 'total_active',
    'time_day_1h': 'max_day_active', 'time_day_4h': 'max_day_active', 'time_day_8h': 'max_day_active',
    'time_day_12h': 'max_day_active', 'time_day_16h': 'max_day_active',
    'time_week_40h': 'best_rolling_7',
    'idle_total_10m': 'total_idle', 'idle_total_10h': 'total_idle', 'idle_total_100h': 'total_idle',
    'time_night_1h': 'max_day_night_sec', 'time_early_1h': 'max_day_early_sec',
    # Действия
    'clicks_100': 'total_clicks', 'clicks_1k': 'total_clicks', 'clicks_10k': 'total_clicks',
    'clicks_100k': 'total_clicks', 'clicks_1m': 'total_clicks',
    'chars_1k': 'total_chars', 'chars_10k': 'total_chars', 'chars_100k': 'total_chars',
    'chars_1m': 'total_chars', 'chars_10m': 'total_chars',
    'words_100': 'total_words', 'words_1k': 'total_words', 'words_10k': 'total_words',
    'words_100k': 'total_words',
    'clicks_day_500': 'max_day_clicks', 'chars_day_5k': 'max_day_chars',
    'words_day_1k': 'max_day_words', 'chars_day_20k': 'max_day_chars',
    'sessions_100': 'total_sessions', 'sessions_1000': 'total_sessions',
    # Серии
    'streak_2': 'best_streak', 'streak_3': 'best_streak', 'streak_7': 'best_streak',
    'streak_14': 'best_streak', 'streak_21': 'best_streak', 'streak_30': 'best_streak',
    'streak_60': 'best_streak', 'streak_90': 'best_streak', 'streak_100': 'best_streak',
    'streak_180': 'best_streak', 'streak_365': 'best_streak',
    'streak_7_hard': 'hard_streak_2h',
    # Проекты
    'proj_first': 'distinct_projects', 'proj_3': 'distinct_projects', 'proj_5': 'distinct_projects',
    'proj_10': 'distinct_projects', 'proj_20': 'distinct_projects',
    'proj_10h': 'max_project_active', 'proj_100h': 'max_project_active',
    'proj_day_3': 'max_day_projects', 'proj_day_5h': 'max_day_project_focus',
    'proj_week_3': 'max_week_projects', 'proj_day_8h': 'max_day_project_focus',
    'proj_30d': 'max_project_span_days',
    # Режим дня
    'mode_weekend_3h': 'max_weekend_active', 'mode_saturday_5h': 'max_saturday_active',
    'mode_monday_3h': 'max_monday_active', 'mode_all_week': 'mode_all_week',
    'mode_6am': 'mode_6am', 'mode_after23': 'mode_after23', 'mode_midnight': 'mode_midnight',
    'mode_span_12h': 'max_day_span_hours', 'mode_weekend_streak_4': 'max_weekend_streak',
    'mode_jan1': 'mode_jan1',
    # Особые
    'first_record': 'first_record', 'days_10': 'total_active_days', 'days_50': 'total_active_days',
    'days_100': 'total_active_days', 'days_365': 'total_active_days',
    'month_100h': 'best_month_active', 'week_60h': 'best_rolling_7', 'comeback': 'comeback',
    'stable_30': 'soft_streak_1h', 'goal_first': 'max_day_active', 'goal_week_14': 'hard_streak_2h',
    'hours_8_distinct': 'max_day_distinct_hours', 'hours_12_distinct': 'max_day_distinct_hours',
    'quiet_day': 'quiet_day', 'click_storm': 'max_day_clicks',
    'before_noon_5h': 'max_day_morning_sec', 'friday_3h': 'max_friday_active',
    'night_scribe': 'max_day_night_chars', 'early_10': 'early_start_days',
    'double_10h': 'double_10h_days', 'legendary_day': 'max_day_active',
    'long_session': 'max_session_sec', 'keeper_180': 'tracking_span_days',
    'idle_zero_day': 'idle_zero_day', 'idle_day_2h': 'max_day_idle',
    'deadline_push': 'max_weekday_active',
}


# ============================================================
# Windows API (ctypes) — безопасно отключается вне Windows
# ============================================================

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    try:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetForegroundWindow.argtypes = []
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    except Exception as e:  # pragma: no cover
        logging.exception('Не удалось настроить Windows API: %r', e)
        user32 = None
        kernel32 = None


def win_foreground_title():
    """Заголовок foreground-окна (или '' если не удалось)."""
    if not IS_WINDOWS or user32 is None:
        return ''
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ''
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value or ''
    except Exception as e:
        logging.debug('win_foreground_title: %r', e)
        return ''


def win_window_process_name(hwnd):
    """Имя exe-файла процесса, владеющего окном (lowercase)."""
    if not IS_WINDOWS or kernel32 is None:
        return ''
    try:
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ''
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return ''
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return (buf.value or '').replace('/', '\\').split('\\')[-1].lower()
            return ''
        finally:
            kernel32.CloseHandle(h)
    except Exception as e:
        logging.debug('win_window_process_name: %r', e)
        return ''


_ENUM_PROC = None   # тип WINFUNCTYPE создаётся один раз (после импорта ctypes)


def vscode_is_running():
    """Запущен ли VS Code прямо сейчас: есть ли хотя бы одно ВИДИМОЕ окно
    верхнего уровня, принадлежащее процессу Code.exe / VSCodium.exe и т.п.

    Отличается от detect_vscode() тем, что находит VS Code даже когда он
    НЕ на переднем плане (свёрнут, перекрыт другим окном). Свёрнутые окна
    в Win32 считаются видимыми — это нам и нужно."""
    if not IS_WINDOWS or user32 is None or kernel32 is None:
        return False
    import ctypes as _ct
    global _ENUM_PROC
    try:
        if _ENUM_PROC is None:
            _ENUM_PROC = _ct.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        found = []

        def _cb(hwnd, lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, _ct.byref(pid))
                if pid.value and win_window_process_name(hwnd) in VSCODE_PROCESSES:
                    found.append(hwnd)
                    return False          # нашли — прекращаем перечисление
            except Exception:
                pass
            return True

        user32.EnumWindows(_ENUM_PROC(_cb), 0)
        return bool(found)
    except Exception as e:
        logging.debug('vscode_is_running: %r', e)
        return False


def detect_vscode(process_name, title):
    """Это окно VS Code? По имени процесса ИЛИ по суффиксу заголовка."""
    p = (process_name or '').lower()
    if p in VSCODE_PROCESSES:
        return True
    t = (title or '').lower()
    return t.endswith(VS_SUFFIXES[0]) or t.endswith(VS_SUFFIXES[1])


def parse_project(title):
    """
    Имя проекта из заголовка VS Code.
    'index.ts - my-app - Visual Studio Code' -> 'my-app'
    Берём ПОСЛЕДНИЙ сегмент после удаления суффикса; пусто/Welcome -> 'VS Code'.
    """
    if not title:
        return 'VS Code'
    t = title.strip()
    low = t.lower()
    for suf in VS_SUFFIXES:
        if low.endswith(suf):
            t = t[:-len(suf)].strip()
            break
    parts = [p.strip() for p in t.split(' - ')]
    name = parts[-1] if parts and parts[-1] else ''
    # убираем маркеры несохранённых изменений
    changed = True
    while changed and name:
        changed = False
        for marker in ('● ', '• ', 'dot ', '◆ '):
            if name.startswith(marker):
                name = name[len(marker):].strip()
                changed = True
    if not name or name.lower() in ('get started', 'welcome'):
        name = 'VS Code'
    return name[:64]


# Расширение файла -> имя языка/типа (для top-панели «Язык»)
EXT_LANG_MAP = {
    'css': 'CSS', 'scss': 'CSS', 'sass': 'CSS', 'less': 'CSS',
    'js': 'JavaScript', 'mjs': 'JavaScript', 'cjs': 'JavaScript', 'jsx': 'JavaScript',
    'ts': 'TypeScript', 'tsx': 'TypeScript',
    'py': 'Python',
    'html': 'HTML', 'htm': 'HTML',
    'json': 'JSON', 'jsonc': 'JSON',
    'md': 'Markdown', 'markdown': 'Markdown',
    'vue': 'Vue', 'svelte': 'Svelte',
    'go': 'Go', 'rs': 'Rust', 'java': 'Java', 'cs': 'C#',
    'cpp': 'C++', 'cc': 'C++', 'cxx': 'C++', 'hpp': 'C++',
    'c': 'C', 'h': 'C',
    'php': 'PHP', 'rb': 'Ruby',
    'sh': 'Shell', 'bat': 'Shell', 'ps1': 'Shell',
    'sql': 'SQL',
    'yml': 'YAML', 'yaml': 'YAML',
    'toml': 'Config', 'ini': 'Config', 'cfg': 'Config', 'conf': 'Config',
    'txt': 'Text',
}

# Имя языка -> emoji (эмодзи в БД не хранится, подставляется на лету)
LANG_EMOJI = {
    'CSS': '🎨', 'JavaScript': '🟨', 'TypeScript': '🔷', 'Python': '🐍',
    'HTML': '🌐', 'JSON': '🧾', 'Markdown': '📝', 'Vue': '💚', 'Svelte': '🧡',
    'Go': '🐹', 'Rust': '🦀', 'Java': '☕', 'C#': '🟣', 'C++': '🔹', 'C': '🔹',
    'PHP': '🐘', 'Ruby': '💎', 'Shell': '🐚', 'SQL': '🗄', 'YAML': '⚙️',
    'Config': '⚙️', 'Text': '📄',
}

# «Прочее известное расширение»: латиница/цифры, 1–5 символов
_EXT_RE = re.compile(r'^[a-z0-9]{1,5}$')


def parse_language(title):
    """
    Язык/тип файла из заголовка VS Code.
    'index.ts - my-app - Visual Studio Code' -> 'TypeScript'
    Берём ПЕРВЫЙ сегмент (имя файла); если это не похоже на файл — None.
    Эмодзи отдельно: LANG_EMOJI[имя] (в БД хранится только имя).
    """
    if not title:
        return None
    t = title.strip()
    low = t.lower()
    for suf in VS_SUFFIXES:
        if low.endswith(suf):
            t = t[:-len(suf)].strip()
            break
    first = t.split(' - ')[0].strip()
    # снимаем маркеры несохранённых изменений
    changed = True
    while changed and first:
        changed = False
        for marker in ('● ', '• ', 'dot ', '◆ '):
            if first.startswith(marker):
                first = first[len(marker):].strip()
                changed = True
    if not first or len(first) >= 64:
        return None
    if '/' in first or '\\' in first:
        return None
    if '.' not in first:
        return None
    ext = first.rsplit('.', 1)[1].lower()
    if not ext:
        return None
    lang = EXT_LANG_MAP.get(ext)
    if lang:
        return lang
    if _EXT_RE.match(ext):        # прочее известное расширение -> DOCX, WEIRD...
        return ext.upper()
    return None


# ============================================================
# Логирование
# ============================================================

def setup_logging():
    try:
        os.makedirs(data_dir(), exist_ok=True)
        log_path = os.path.join(data_dir(), 'codetime.log')
        handlers = [logging.FileHandler(log_path, encoding='utf-8'),
                    logging.StreamHandler(sys.stderr)]
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=handlers,
        )
    except Exception:
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s [%(levelname)s] %(message)s')
    return logging.getLogger('codetime')


# ============================================================
# База данных (SQLite)
# ============================================================

SQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS day_stats (
    date            TEXT NOT NULL,
    project         TEXT NOT NULL,
    active_sec      INTEGER NOT NULL DEFAULT 0,
    idle_sec        INTEGER NOT NULL DEFAULT 0,
    clicks          INTEGER NOT NULL DEFAULT 0,
    chars           INTEGER NOT NULL DEFAULT 0,
    words           INTEGER NOT NULL DEFAULT 0,
    sessions        INTEGER NOT NULL DEFAULT 0,
    max_session_sec INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, project)
);
CREATE TABLE IF NOT EXISTS hour_stats (
    date       TEXT NOT NULL,
    hour       INTEGER NOT NULL,
    active_sec INTEGER NOT NULL DEFAULT 0,
    chars      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, hour)
);
CREATE TABLE IF NOT EXISTS achievements (
    ach_id      TEXT PRIMARY KEY,
    unlocked_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS lang_stats (
    date       TEXT NOT NULL,
    lang       TEXT NOT NULL,
    active_sec INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, lang)
);
CREATE INDEX IF NOT EXISTS idx_lang_stats_date ON lang_stats(date);
CREATE TABLE IF NOT EXISTS todos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,                 -- YYYY-MM-DD
    title      TEXT NOT NULL,
    minutes    INTEGER NOT NULL DEFAULT 0,
    done       INTEGER NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT 'manual', -- manual | photo
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_todos_date ON todos(date);
CREATE TABLE IF NOT EXISTS roadmap_goal (
    id          INTEGER PRIMARY KEY CHECK(id=1),
    title       TEXT NOT NULL DEFAULT '',
    target_date TEXT NOT NULL DEFAULT '',      -- YYYY-MM-DD или ''
    daily_hours REAL NOT NULL DEFAULT 0        -- 0 = авто по статистике
);
CREATE TABLE IF NOT EXISTS roadmap_steps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    hours      REAL NOT NULL DEFAULT 10,
    status     TEXT NOT NULL DEFAULT 'todo',   -- legacy: статус теперь считается сам
    order_idx  INTEGER NOT NULL DEFAULT 0,
    spent_sec  INTEGER NOT NULL DEFAULT 0,     -- закреплённые за шагом секунды
    created_at TEXT NOT NULL
);
"""


def init_db():
    """Открывает/создаёт БД и заполняет настройки по умолчанию."""
    os.makedirs(data_dir(), exist_ok=True)
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript(SQL_SCHEMA)
    conn.commit()
    # миграция для баз, созданных до v1.7.0: колонка spent_sec,
    # которая закрепляет набранное время за конкретным шагом
    try:
        conn.execute('ALTER TABLE roadmap_steps '
                     'ADD COLUMN spent_sec INTEGER NOT NULL DEFAULT 0')
        conn.commit()
    except sqlite3.OperationalError:
        pass   # колонка уже есть
    # first_date — дата первого запуска
    row = conn.execute("SELECT value FROM meta WHERE key='first_date'").fetchone()
    if not row:
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('first_date', ?)",
                     (datetime.now().strftime('%Y-%m-%d'),))
        conn.commit()
    return conn


def get_meta(conn, key, default=None):
    row = conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn, key, value):
    conn.execute('INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)', (key, str(value)))
    conn.commit()


def months_ago(d, months):
    """Дата `months` календарных месяцев назад (день обрезается по концу месяца)."""
    total = d.year * 12 + (d.month - 1) - months
    y, m0 = divmod(total, 12)
    m = m0 + 1
    nxt = date(y + (m // 12), (m % 12) + 1, 1)   # 1-е число следующего месяца
    last = nxt - timedelta(days=1)               # последний день нужного месяца
    return date(y, m, min(d.day, last.day))


# ============================================================
# План обучения и задачи по дням (Task 8)
# ============================================================

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Фронтенд-шаблон для /api/roadmap/template (заливается, только если шагов 0)
FRONTEND_TEMPLATE = [
    ('Верстка: HTML+CSS', 60, 'todo'),
    ('JavaScript основы', 80, 'todo'),
    ('JS практика: корзина и DOM', 40, 'todo'),
    ('Git и деплой', 12, 'todo'),
    ('React основы', 90, 'todo'),
]


def parse_date_or_none(s):
    """'YYYY-MM-DD' -> date, иначе None."""
    if not isinstance(s, str) or not DATE_RE.match(s.strip()):
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


def _need_str(data, key, max_len=200, allow_empty=False, default=''):
    """Строка из JSON-тела: валидация типа/пустоты, ошибки -> ValueError."""
    v = data.get(key, default)
    if not isinstance(v, str):
        raise ValueError('Поле "%s" должно быть строкой.' % key)
    v = v.strip()
    if not v and not allow_empty:
        raise ValueError('Поле "%s" не должно быть пустым.' % key)
    return v[:max_len]


def _need_num(data, key, lo, hi, default=None):
    """Число из JSON-тела с клампом [lo, hi]; bool числом не считается."""
    v = data.get(key, default)
    if v is None:
        raise ValueError('Не указано поле "%s".' % key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError('Поле "%s" должно быть числом.' % key)
    return max(lo, min(hi, float(v)))


def _need_id(data):
    """Целевой id из JSON-тела."""
    v = data.get('id')
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError('Не указан корректный id.')
    return int(v)


def renumber_steps(conn):
    """Перенумеровывает order_idx шагов 1..N (после добавления/удаления)."""
    rows = conn.execute(
        'SELECT id FROM roadmap_steps ORDER BY order_idx, id').fetchall()
    for i, (sid,) in enumerate(rows, 1):
        conn.execute('UPDATE roadmap_steps SET order_idx=? WHERE id=?', (i, sid))


def roadmap_since(conn):
    """Дата, с которой активное время «заливается» в шаги плана.
    Фиксируется при первом обращении; для старых баз — дата создания
    самого первого шага, чтобы прогресс не «прыгнул» после обновления."""
    d = parse_date_or_none(get_meta(conn, 'roadmap_since', '') or '')
    if d:
        return d
    row = conn.execute(
        "SELECT MIN(substr(created_at, 1, 10)) FROM roadmap_steps").fetchone()
    d = parse_date_or_none(row[0] or '') if row and row[0] else None
    if d is None:
        d = date.today()
    set_meta(conn, 'roadmap_since', d.isoformat())
    return d


def roadmap_sync_fill(conn):
    """Заливает новое активное время в шаги плана, ЗАКРЕПЛЯЯ его за шагами.

    Раньше время каждый раз заново разливалось по текущему порядку шагов —
    из-за этого после перемещения шагов часы и статус «в процессе» прыгали
    на тот шаг, который стоит первым. Теперь каждая залитая секунда
    хранится в самом шаге (roadmap_steps.spent_sec) и при перемещении
    остаётся с этим шагом. Статус «в процессе» прикреплён к факту, а не
    к позиции в списке.

    Правила заливки:
      • новое время идёт в «текущий» шаг: первый по порядку шаг с
        частичным прогрессом, а если его нет — первый неначатый;
      • когда шаг добрал свои часы — очередь следующего по порядку;
      • перемещение шагов НЕ переносит уже набранные часы.
    """
    since = roadmap_since(conn)
    pool_now = int(conn.execute(
        'SELECT COALESCE(SUM(active_sec),0) FROM day_stats WHERE date >= ?',
        (since.isoformat(),)).fetchone()[0])
    filled_raw = get_meta(conn, 'roadmap_filled', None)

    if filled_raw is None or str(filled_raw).strip() == '':
        # однократная миграция со старой модели: разливаем накопленное
        # время ПО ПОРЯДКУ СОЗДАНИЯ шагов (id) — так ближе всего к тому,
        # как шаги реально изучались, — и фиксируем результат навсегда
        left = pool_now
        for sid, cap in conn.execute(
                'SELECT id, CAST(round(hours * 3600) AS INTEGER) '
                'FROM roadmap_steps ORDER BY id').fetchall():
            if left <= 0:
                break
            add = min(left, cap)
            if add > 0:
                conn.execute('UPDATE roadmap_steps SET spent_sec=? WHERE id=?',
                             (add, sid))
                left -= add
        set_meta(conn, 'roadmap_filled', str(pool_now))
        return

    new_sec = pool_now - int(float(filled_raw))
    if new_sec <= 0:
        return

    while new_sec > 0:
        # «текущий» шаг: первый по порядку с частичным прогрессом…
        row = conn.execute(
            'SELECT id, spent_sec, CAST(round(hours * 3600) AS INTEGER) '
            'FROM roadmap_steps '
            'WHERE hours > 0 AND spent_sec > 0 '
            'AND spent_sec < CAST(round(hours * 3600) AS INTEGER) '
            'ORDER BY order_idx, id LIMIT 1').fetchone()
        if row is None:
            # …иначе первый неначатый по порядку
            row = conn.execute(
                'SELECT id, spent_sec, CAST(round(hours * 3600) AS INTEGER) '
                'FROM roadmap_steps '
                'WHERE hours > 0 AND spent_sec = 0 '
                'ORDER BY order_idx, id LIMIT 1').fetchone()
        if row is None:
            break   # все шаги закрыты — остаток времени не приписываем задним числом
        sid, spent, cap = int(row[0]), int(row[1] or 0), int(row[2])
        add = min(new_sec, max(0, cap - spent))
        if add <= 0:
            break
        conn.execute('UPDATE roadmap_steps SET spent_sec=? WHERE id=?',
                     (spent + add, sid))
        new_sec -= add
    set_meta(conn, 'roadmap_filled', str(pool_now))


def roadmap_state(conn):
    """GET /api/roadmap: план, синхронизированный с активным временем.

    Те же активные секунды, что считает «Обзор», с даты roadmap_since
    заливаются в шаги и ЗАКРЕПЛЯЮТСЯ за ними (roadmap_sync_fill):
    набранные часы и статус «в процессе» следуют за шагом, а не за
    позицией в списке — перемещение шагов ничего не переносит.
    Статус шага автоматический (по закреплённому времени):
      done  — время шага набрано полностью;
      doing — набрано частично (шаг сейчас в работе);
      todo  — до шага очередь ещё не дошла.
    Проекция дат (Таймлайн) идёт только по НЕЗАВЕРШЁННЫМ часам:
    days = max(1, ceil(остаток_часов / capacity)).
    fit.requiredHoursDay = остаток часов / дни до targetDate включительно.
    """
    today = date.today()
    roadmap_sync_fill(conn)
    row = conn.execute(
        'SELECT title, target_date, daily_hours FROM roadmap_goal WHERE id=1').fetchone()
    goal = {
        'title': row[0] if row else '',
        'targetDate': row[1] if row else '',
        'dailyHours': float(row[2] or 0.0) if row else 0.0,
    }
    steps_rows = conn.execute(
        'SELECT id, title, hours, status, order_idx, spent_sec FROM roadmap_steps '
        'ORDER BY order_idx, id').fetchall()

    since = roadmap_since(conn)
    today_active = conn.execute(
        'SELECT COALESCE(SUM(active_sec),0) FROM day_stats WHERE date=?',
        (today.isoformat(),)).fetchone()[0]

    # темп: среднее активных часов/день за последние 14 дней
    start14 = (today - timedelta(days=13)).isoformat()
    n_days, total_sec = conn.execute(
        'SELECT COUNT(DISTINCT date), COALESCE(SUM(active_sec),0) '
        'FROM day_stats WHERE date >= ?', (start14,)).fetchone()
    avg_hours = (total_sec / 3600.0 / 14.0) if n_days else 0.0
    if goal['dailyHours'] > 0:
        capacity = goal['dailyHours']
    elif n_days == 0:
        capacity = 2.0                        # нет данных вообще
    else:
        capacity = max(0.5, round(avg_hours * 4) / 4.0)

    steps = []
    cursor = today
    total_hours = 0.0
    spent_hours = 0.0
    total_days = 0
    finish = None
    for sid, title, hours, _status, oidx, spent in steps_rows:
        hours = float(hours or 0.0)
        cap_sec = int(round(hours * 3600))
        spent = int(max(0, min(int(spent or 0), cap_sec)))
        total_hours += hours
        spent_hours += spent / 3600.0
        if cap_sec > 0 and spent >= cap_sec:
            auto = 'done'
        elif spent > 0:
            auto = 'doing'
        else:
            auto = 'todo'
        entry = {'id': sid, 'title': title, 'hours': hours,
                 'orderIdx': oidx, 'status': auto,
                 'spentSec': spent,
                 'progress': round(spent * 100.0 / cap_sec, 1) if cap_sec else 0.0}
        if auto == 'done':                    # выполненные — вне проекции
            entry.update({'startDate': None, 'endDate': None, 'days': 0})
            steps.append(entry)
            continue
        days_left = 0
        if capacity > 0:
            hours_left = max(0.0, hours - spent / 3600.0)
            days_left = max(1, int(math.ceil(hours_left / capacity - 1e-9)))
        sd = cursor
        ed = cursor + timedelta(days=days_left - 1)
        entry.update({'startDate': sd.isoformat(), 'endDate': ed.isoformat(),
                      'days': days_left})
        steps.append(entry)
        cursor = ed + timedelta(days=1)
        total_days += days_left
        finish = ed

    hours_left_total = max(0.0, total_hours - spent_hours)
    fit = None
    if goal['targetDate'] and total_hours > 0:
        target = parse_date_or_none(goal['targetDate'])
        if target is not None:
            days_to_target = max(1, (target - today).days + 1)
            fit = {
                'ok': finish is not None and finish <= target,
                'missDays': max(0, (finish - target).days) if finish else 0,
                'requiredHoursDay': round(hours_left_total / days_to_target, 1),
            }
    return {
        'goal': goal,
        'steps': steps,
        'pace': {'planned': round(capacity, 2), 'actual14': round(avg_hours, 1)},
        'totals': {'hours': round(total_hours, 1),
                   'hoursDone': round(spent_hours, 1),
                   'hoursLeft': round(hours_left_total, 1),
                   'pctDone': round(spent_hours * 100.0 / total_hours, 1)
                              if total_hours else 0.0,
                   'days': total_days,
                   'finishDate': finish.isoformat() if finish else None,
                   'sinceDate': since.isoformat(),
                   'todayActiveSec': int(today_active or 0)},
        'fit': fit,
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
    }


# ============================================================
# Метрики достижений (все формулы)
# ============================================================

_metrics_cache = {'ts': 0.0, 'data': None}
_metrics_lock = threading.Lock()


def compute_metrics(conn, ttl=10.0):
    """
    Считает ВСЕ метрики для достижений из day_stats + hour_stats.
    Результат кэшируется на ttl секунд (0 — всегда пересчитывать).
    """
    with _metrics_lock:
        if ttl > 0 and _metrics_cache['data'] is not None \
                and time.monotonic() - _metrics_cache['ts'] < ttl:
            return _metrics_cache['data']

        M = {}

        # --- totals: суммы по всем дням ---
        r = conn.execute(
            "SELECT COALESCE(SUM(active_sec),0), COALESCE(SUM(idle_sec),0), "
            "COALESCE(SUM(clicks),0), COALESCE(SUM(chars),0), "
            "COALESCE(SUM(words),0), COALESCE(SUM(sessions),0) FROM day_stats"
        ).fetchone()
        M['total_active'], M['total_idle'], M['total_clicks'] = r[0], r[1], r[2]
        M['total_chars'], M['total_words'], M['total_sessions'] = r[3], r[4], r[5]

        # --- агрегаты по дням ---
        days = {}
        for d, a, i, c, ch, w in conn.execute(
                "SELECT date, SUM(active_sec), SUM(idle_sec), SUM(clicks), "
                "SUM(chars), SUM(words) FROM day_stats GROUP BY date"):
            days[d] = {'active': a, 'idle': i, 'clicks': c, 'chars': ch, 'words': w}

        M['max_day_active'] = max((v['active'] for v in days.values()), default=0)
        M['max_day_idle'] = max((v['idle'] for v in days.values()), default=0)
        M['max_day_clicks'] = max((v['clicks'] for v in days.values()), default=0)
        M['max_day_chars'] = max((v['chars'] for v in days.values()), default=0)
        M['max_day_words'] = max((v['words'] for v in days.values()), default=0)

        # «Активный день» = суммарно >= 60 секунд активности
        active_set = {d for d, v in days.items() if v['active'] >= 60}
        M['total_active_days'] = len(active_set)
        M['first_record'] = 1 if days else 0

        today = date.today()

        # --- данные по часам (из hour_stats) ---
        hours = {}
        for d, h, a, c in conn.execute(
                "SELECT date, hour, active_sec, chars FROM hour_stats "
                "WHERE active_sec > 0 OR chars > 0"):
            hours.setdefault(d, {})[h] = (a, c)

        M['max_day_distinct_hours'] = max((len(v) for v in hours.values()), default=0)

        # maxDayNightSec (0..4), maxDayEarlySec (0..6), maxDayMorningSec (5..11),
        # maxDayNightChars (1..4), разброс часов за день, ранние старты, флаги режима
        max_night = max_early = max_morning = max_night_chars = 0
        max_span_hours = 0
        early_start_days = 0
        mode_6am = mode_after23 = mode_midnight = 0
        for d, hh in hours.items():
            max_night = max(max_night, sum(a for h, (a, c) in hh.items() if h <= 4))
            max_early = max(max_early, sum(a for h, (a, c) in hh.items() if h <= 6))
            max_morning = max(max_morning,
                              sum(a for h, (a, c) in hh.items() if 5 <= h <= 11))
            max_night_chars = max(max_night_chars,
                                  sum(c for h, (a, c) in hh.items() if 1 <= h <= 4))
            if any(h < 6 for h in hh):        # активность в часе < 6 утра
                mode_6am = 1
            if 23 in hh:                       # активность в 23:xx
                mode_after23 = 1
            if any(h <= 3 for h in hh):        # активность 00:00–03:59
                mode_midnight = 1
            max_span_hours = max(max_span_hours, max(hh) - min(hh))
            if min(hh) <= 7:                   # первый активный час раньше 08:00
                early_start_days += 1
        M['max_day_night_sec'] = max_night
        M['max_day_early_sec'] = max_early
        M['max_day_morning_sec'] = max_morning
        M['max_day_night_chars'] = max_night_chars
        M['max_day_span_hours'] = max_span_hours  # unit 'hours' (для mode_span_12h)
        M['early_start_days'] = early_start_days
        M['mode_6am'] = mode_6am
        M['mode_after23'] = mode_after23
        M['mode_midnight'] = mode_midnight

        # --- проекты ---
        proj_rows = conn.execute(
            "SELECT project, SUM(active_sec), MIN(date), MAX(date) "
            "FROM day_stats GROUP BY project").fetchall()
        M['distinct_projects'] = len(proj_rows)
        M['max_project_active'] = max((a for _, a, _, _ in proj_rows), default=0)
        span_days = 0
        for _, _a, f, l in proj_rows:
            try:
                span_days = max(span_days,
                                (date.fromisoformat(l) - date.fromisoformat(f)).days)
            except ValueError:
                pass
        M['max_project_span_days'] = span_days
        M['max_day_project_focus'] = conn.execute(
            'SELECT COALESCE(MAX(active_sec),0) FROM day_stats').fetchone()[0]

        # разные проекты за день / за ISO-неделю (пн–вс)
        day_proj = defaultdict(set)
        week_proj = defaultdict(set)
        for d, p in conn.execute('SELECT DISTINCT date, project FROM day_stats'):
            day_proj[d].add(p)
            try:
                iso = date.fromisoformat(d).isocalendar()
                week_proj[(iso[0], iso[1])].add(p)
            except ValueError:
                pass
        M['max_day_projects'] = max((len(s) for s in day_proj.values()), default=0)
        M['max_week_projects'] = max((len(s) for s in week_proj.values()), default=0)

        # --- максимум за календарный месяц ---
        month_tot = defaultdict(int)
        for d, v in days.items():
            month_tot[d[:7]] += v['active']
        M['best_month_active'] = max(month_tot.values()) if month_tot else 0

        # --- максимумы по дням недели ---
        def max_active_on(pred):
            best = 0
            for d, v in days.items():
                try:
                    wd = date.fromisoformat(d).weekday()
                except ValueError:
                    continue
                if pred(wd):
                    best = max(best, v['active'])
            return best

        M['max_weekday_active'] = max_active_on(lambda wd: wd <= 4)   # пн–пт
        M['max_monday_active'] = max_active_on(lambda wd: wd == 0)
        M['max_friday_active'] = max_active_on(lambda wd: wd == 4)
        M['max_saturday_active'] = max_active_on(lambda wd: wd == 5)
        # «сб/вс»: максимум среди отдельных выходных дней
        # (так честно работает mode_weekend_3h «3 часа в субботу ИЛИ воскресенье»)
        M['max_weekend_active'] = max_active_on(lambda wd: wd >= 5)

        # --- стрики ---
        def best_streak_of(day_set):
            best = cur = 0
            prev = None
            for d in sorted(day_set):
                try:
                    dt = date.fromisoformat(d)
                except ValueError:
                    continue
                cur = cur + 1 if (prev is not None and (dt - prev).days == 1) else 1
                best = max(best, cur)
                prev = dt
            return best

        M['best_streak'] = best_streak_of(active_set)

        # текущий стрик: назад от сегодня; если сегодня ещё нет — начинаем со вчера
        cur = 0
        d = today
        if d.isoformat() not in active_set:
            d -= timedelta(days=1)
        while d.isoformat() in active_set:
            cur += 1
            d -= timedelta(days=1)
        M['current_streak'] = cur

        hard_set = {d for d, v in days.items() if v['active'] >= 7200}   # 2+ часа
        soft_set = {d for d, v in days.items() if v['active'] >= 3600}   # 1+ час
        M['hard_streak_2h'] = best_streak_of(hard_set)
        M['soft_streak_1h'] = best_streak_of(soft_set)
        M['double_10h_days'] = sum(1 for v in days.values() if v['active'] >= 36000)

        M['quiet_day'] = 1 if any(v['active'] >= 7200 and v['clicks'] < 100
                                  for v in days.values()) else 0
        M['idle_zero_day'] = 1 if any(v['active'] >= 14400 and v['idle'] < 300
                                      for v in days.values()) else 0

        # --- лучшая сумма за 7 подряд календарных дней (пропуски = 0) ---
        if days:
            first = min(min(days), get_meta(conn, 'first_date', min(days)))
            try:
                cur_d = date.fromisoformat(first)
            except ValueError:
                cur_d = date.fromisoformat(min(days))
            vals = []
            while cur_d <= today:
                vals.append(days.get(cur_d.isoformat(), {}).get('active', 0))
                cur_d += timedelta(days=1)
            if len(vals) <= 7:
                M['best_rolling_7'] = sum(vals)
            else:
                window = sum(vals[:7])
                best7 = window
                for k in range(7, len(vals)):
                    window += vals[k] - vals[k - 7]
                    best7 = max(best7, window)
                M['best_rolling_7'] = best7
        else:
            M['best_rolling_7'] = 0

        # --- comeback: два активных дня с разрывом >= 7 дней ---
        comeback = 0
        sorted_active = sorted(active_set)
        for i in range(1, len(sorted_active)):
            try:
                gap = (date.fromisoformat(sorted_active[i])
                       - date.fromisoformat(sorted_active[i - 1])).days
            except ValueError:
                continue
            if gap >= 7:
                comeback = 1
                break
        M['comeback'] = comeback

        # --- ISO-неделя со всеми 7 активными днями ---
        week_active = defaultdict(set)
        for d in active_set:
            try:
                iso = date.fromisoformat(d).isocalendar()
                week_active[(iso[0], iso[1])].add(d)
            except ValueError:
                pass
        M['mode_all_week'] = 1 if any(len(s) == 7 for s in week_active.values()) else 0

        # --- выходные подряд (по последовательности выходных дней) ---
        weekend_days = sorted(d for d in active_set
                              if date.fromisoformat(d).weekday() >= 5)
        run = best_run = 0
        prev_dt = None
        for d in weekend_days:
            dt = date.fromisoformat(d)
            # сб->вс = 1 день, вс->сб = 6 дней; пропуск выходных даёт >= 8
            if prev_dt is not None and (dt - prev_dt).days <= 6:
                run += 1
            else:
                run = 1
            best_run = max(best_run, run)
            prev_dt = dt
        M['max_weekend_streak'] = best_run

        M['mode_jan1'] = 1 if any(d.endswith('-01-01') for d in active_set) else 0

        # --- сессии и «возраст» трекинга ---
        M['max_session_sec'] = conn.execute(
            'SELECT COALESCE(MAX(max_session_sec),0) FROM day_stats').fetchone()[0]

        fd = get_meta(conn, 'first_date', None)
        if days:
            fd = min(fd, min(days)) if fd else min(days)
        if fd:
            try:
                M['tracking_span_days'] = (today - date.fromisoformat(fd)).days + 1
            except ValueError:
                M['tracking_span_days'] = 0
        else:
            M['tracking_span_days'] = 0

        _metrics_cache['ts'] = time.monotonic()
        _metrics_cache['data'] = M
        return M


def reset_metrics_cache():
    """Сбрасывает кэш метрик (после удаления всех данных)."""
    with _metrics_lock:
        _metrics_cache['data'] = None
        _metrics_cache['ts'] = 0.0


def metric_value(ach_id, M):
    """Текущее значение метрики для достижения."""
    key = ACH_METRIC.get(ach_id)
    if key is None:
        logging.warning('Нет метрики для достижения %s', ach_id)
        return 0
    return int(M.get(key, 0))


def check_achievements(app, force=False):
    """Анлочит новые достижения (INSERT OR IGNORE + timestamp)."""
    with app.db_lock:
        M = compute_metrics(app.conn, ttl=0.0 if force else 10.0)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new = []
        for ach in ACHIEVEMENTS:
            if metric_value(ach['id'], M) >= ach['target']:
                cur = app.conn.execute(
                    'SELECT 1 FROM achievements WHERE ach_id=?', (ach['id'],)).fetchone()
                if not cur:
                    app.conn.execute(
                        'INSERT OR IGNORE INTO achievements(ach_id, unlocked_at) '
                        'VALUES(?, ?)', (ach['id'], now))
                    new.append(ach['name'])
        if new:
            app.conn.commit()
            logging.info('Новое достижение: %s', ', '.join(new))
        return len(new)


# ============================================================
# Счётчики ввода (общие для хук-потоков и движка)
# ============================================================

class InputCounters:
    """Накопитель кликов/символов/слов между тиками движка."""

    def __init__(self):
        self._lock = threading.Lock()
        self._clicks = 0
        self._chars = 0
        self._words = 0

    def add_click(self):
        with self._lock:
            self._clicks += 1

    def add_char(self):
        with self._lock:
            self._chars += 1

    def add_word(self):
        with self._lock:
            self._words += 1

    def drain(self):
        """Забирает и обнуляет накопленное."""
        with self._lock:
            c, ch, w = self._clicks, self._chars, self._words
            self._clicks = self._chars = self._words = 0
            return c, ch, w


# Движок (поток, тик раз в секунду)
# ============================================================

class Engine(threading.Thread):

    def __init__(self, app):
        super().__init__(daemon=True, name='codetime-engine')
        self.app = app

    def run(self):
        while not self.app.stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                logging.exception('Ошибка в тике движка: %r', e)
            self.app.stop_event.wait(1.0)
        # финальный сброс буферов при остановке
        try:
            self.app.flush_now()
        except Exception:
            pass

    def tick(self):
        app = self.app
        now = datetime.now()
        date_s = now.strftime('%Y-%m-%d')
        hour = now.hour
        now_mono = time.monotonic()

        # --- что сейчас на экране ---
        title = win_foreground_title()
        hwnd = None
        proc = ''
        if IS_WINDOWS and user32 is not None:
            try:
                hwnd = user32.GetForegroundWindow()
                if hwnd:
                    proc = win_window_process_name(hwnd)
            except Exception as e:
                logging.debug('tick/foreground: %r', e)
        vscode = detect_vscode(proc, title)

        paused = bool(app.settings.get('paused', 0))

        # VS Code запущен (есть живое окно), даже если он НЕ в фокусе?
        # Если VS Code закрыт — время не идёт ни в актив, ни в паузу.
        vscode_open = vscode or vscode_is_running()

        # общее состояние для хуков (волатильные чтения под GIL)
        app.shared['vscode'] = vscode
        app.shared['vscode_open'] = vscode_open
        app.shared['paused'] = paused
        app.shared['date'] = date_s

        # язык активного файла: для топ-панели «Язык»
        lang_now = parse_language(title) if vscode else None
        app.shared['lang'] = lang_now or ''

        # АКТИВНО = VS Code в фокусе (сколько времени провели в VS Code).
        # ПАУЗА  = VS Code ЗАПУЩЕН, но не в фокусе: свёрнут / перекрыт другим
        #          окном / ушли на второй монитор. Порог простоя больше не
        #          используется — «пауза» больше не течёт сама по себе.
        active_second = vscode and not paused

        if active_second:
            project = parse_project(title)
            app.shared['project'] = project

            # --- сессии ---
            if not app.in_session:
                app.in_session = True
                app.session_sec = 0
                app.day_buf[(date_s, project)]['sessions'] += 1
            app.session_sec += 1
            app.last_active_mono = now_mono

            # --- активная секунда ---
            d = app.day_buf[(date_s, project)]
            d['active'] += 1
            if lang_now:
                app.lang_buf[(date_s, lang_now)] += 1
            d['max_session'] = max(d['max_session'], app.session_sec)
            h = app.hour_buf[(date_s, hour)]
            h[0] += 1

            # --- ввод (клики/символы/слова за эту секунду) ---
            c, ch, w = app.counters.drain()
            d['clicks'] += c
            d['chars'] += ch
            d['words'] += w
            h[1] += ch

        else:
            # VS Code не в фокусе.
            if vscode:
                project = parse_project(title)
                app.shared['project'] = project
            else:
                project = app.shared.get('project') or 'VS Code'

            # обрыв сессии: нет активной секунды дольше SESSION_BREAK_SEC
            if app.in_session and (now_mono - app.last_active_mono) > SESSION_BREAK_SEC:
                app.in_session = False
                app.session_sec = 0

            # ПАУЗА пишется ТОЛЬКО пока VS Code запущен (открыт). Закрыл
            # VS Code — таймер стоит целиком (и актив, и пауза).
            if not paused and vscode_open:
                app.day_buf[(date_s, project)]['idle'] += 1

        # --- периодический сброс в БД ---
        app.tick_count += 1
        if app.tick_count % 10 == 0:
            app.flush_now()
        # --- достижения раз в 60 секунд ---
        if app.tick_count % 60 == 0:
            check_achievements(app)


# ============================================================
# Хуки ввода (pynput)
# ============================================================

def start_hooks(app):
    """Запускает глобальные слушатели мыши/клавиатуры. Ошибки не фатальны."""
    try:
        from pynput import keyboard, mouse
    except Exception as e:
        logging.warning('pynput недоступен (%r) — клики/символы не считаются', e)
        return

    state = {'pending': []}  # незавершённое слово (работаем в одном хук-потоке)

    def allowed():
        """Считать ввод? Только когда VS Code в фокусе и не на паузе."""
        s = app.shared
        return s.get('vscode') and not s.get('paused')

    def flush_word():
        if state['pending']:
            if app.settings.get('track_keys', 1):
                app.counters.add_word()
            state['pending'] = []

    def on_click(x, y, button, pressed):
        try:
            if pressed and allowed() and app.settings.get('track_clicks', 1):
                app.counters.add_click()
        except Exception as e:
            logging.debug('on_click: %r', e)

    def on_press(key):
        try:
            if not allowed():
                state['pending'] = []
                return
            ch = getattr(key, 'char', None)
            if ch:  # печатный символ
                if app.settings.get('track_keys', 1):
                    app.counters.add_char()
                if ch.isalnum() or ch in ('_', '-'):
                    state['pending'].append(ch)
                else:
                    flush_word()
            else:   # специальная клавиша
                if key == keyboard.Key.backspace:
                    if state['pending']:
                        state['pending'].pop()
                elif key in (keyboard.Key.space, keyboard.Key.enter,
                             keyboard.Key.tab):
                    flush_word()
        except Exception as e:
            logging.debug('on_press: %r', e)

    try:
        mouse.Listener(on_click=on_click).start()
        kb = keyboard.Listener(on_press=on_press)
        kb.start()
        logging.info('Хуки ввода запущены')
    except Exception as e:
        logging.warning('Не удалось запустить хуки ввода: %r', e)


# ============================================================
# Приложение: состояние, буферы, сброс в БД
# ============================================================

class CodeTimeApp:

    def __init__(self):
        self.stop_event = threading.Event()
        self.db_lock = threading.RLock()
        self.conn = None
        self.settings = dict(DEFAULT_SETTINGS)
        self.counters = InputCounters()
        # волатильное состояние для хуков
        self.shared = {'vscode': False, 'vscode_open': False, 'paused': False,
                       'project': '', 'date': '', 'lang': ''}
        # буферы: (date, project) -> статистика; (date, hour) -> [active, chars]
        self.day_buf = defaultdict(lambda: {'active': 0, 'idle': 0, 'clicks': 0,
                                            'chars': 0, 'words': 0,
                                            'sessions': 0, 'max_session': 0})
        self.hour_buf = defaultdict(lambda: [0, 0])
        self.lang_buf = defaultdict(int)  # ключ (date, 'имя языка')
        self.tick_count = 0
        self.in_session = False
        self.session_sec = 0
        self.last_active_mono = time.monotonic()
        self.tray_icon = None

    # ---------- настройки ----------

    def load_settings(self):
        with self.db_lock:
            for key, default in DEFAULT_SETTINGS.items():
                raw = get_meta(self.conn, key, None)
                try:
                    self.settings[key] = int(raw) if raw is not None else default
                except (TypeError, ValueError):
                    self.settings[key] = default

    def save_settings(self):
        with self.db_lock:
            for key, value in self.settings.items():
                set_meta(self.conn, key, value)

    def clamp_settings(self):
        s = self.settings
        s['daily_goal_min'] = max(30, min(480, int(s['daily_goal_min'])))
        for k in ('track_clicks', 'track_keys', 'autostart', 'paused'):
            s[k] = 1 if s[k] else 0

    def toggle_pause(self):
        new = 0 if self.settings.get('paused', 0) else 1
        self.settings['paused'] = new
        self.clamp_settings()
        self.save_settings()
        # при паузе сразу сбрасываем накопленное в БД
        self.flush_now()
        logging.info('Отслеживание %s', 'на паузе' if new else 'возобновлено')

    # ---------- сброс буферов (UPSERT) ----------

    def flush_now(self):
        with self.db_lock:
            if self.conn is None:
                return
            day_rows = [(d, p, v['active'], v['idle'], v['clicks'], v['chars'],
                         v['words'], v['sessions'], v['max_session'])
                        for (d, p), v in list(self.day_buf.items()) if any(
                            (v['active'], v['idle'], v['clicks'], v['chars'],
                             v['words'], v['sessions'], v['max_session']))]
            hour_rows = [(d, h, v[0], v[1])
                         for (d, h), v in list(self.hour_buf.items()) if (v[0] or v[1])]
            lang_rows = [(d, lang, n)
                         for (d, lang), n in list(self.lang_buf.items()) if n]
            for row in day_rows:
                self.conn.execute(
                    "INSERT INTO day_stats(date, project, active_sec, idle_sec, "
                    "clicks, chars, words, sessions, max_session_sec) "
                    "VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(date, project) DO UPDATE SET "
                    "active_sec = active_sec + excluded.active_sec, "
                    "idle_sec = idle_sec + excluded.idle_sec, "
                    "clicks = clicks + excluded.clicks, "
                    "chars = chars + excluded.chars, "
                    "words = words + excluded.words, "
                    "sessions = sessions + excluded.sessions, "
                    "max_session_sec = MAX(max_session_sec, excluded.max_session_sec)",
                    row)
            for row in hour_rows:
                self.conn.execute(
                    "INSERT INTO hour_stats(date, hour, active_sec, chars) "
                    "VALUES(?,?,?,?) "
                    "ON CONFLICT(date, hour) DO UPDATE SET "
                    "active_sec = active_sec + excluded.active_sec, "
                    "chars = chars + excluded.chars",
                    row)
            for row in lang_rows:
                self.conn.execute(
                    "INSERT INTO lang_stats(date, lang, active_sec) VALUES(?,?,?) "
                    "ON CONFLICT(date, lang) DO UPDATE SET "
                    "active_sec = active_sec + excluded.active_sec",
                    row)
            self.conn.commit()
            self.day_buf.clear()
            self.hour_buf.clear()
            self.lang_buf.clear()


# ============================================================
# Автозапуск с Windows (HKCU ...\\Run)
# ============================================================

def autostart_command():
    """Команда для автозагрузки."""
    if getattr(sys, 'frozen', False):
        return '"%s" --no-browser' % sys.executable
    script = os.path.abspath(__file__)
    python_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(python_dir, 'pythonw.exe')
    exe = pythonw if os.path.exists(pythonw) else sys.executable
    return '"%s" "%s" --no-browser' % (exe, script)


def get_autostart_enabled():
    """Включён ли автозапуск (реестр; вне Windows — из meta)."""
    if IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except FileNotFoundError:
            return False
        except Exception as e:
            logging.debug('get_autostart_enabled: %r', e)
            return False
    return False


def set_autostart_enabled(enable):
    """Включить/выключить автозапуск (запись/удаление значения CodeTime)."""
    try:
        if IS_WINDOWS:
            import winreg
            if enable:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                                      autostart_command())
            else:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                        winreg.KEY_SET_VALUE) as key:
                        winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        logging.info('Автозапуск %s', 'включён' if enable else 'выключен')
        return True
    except Exception as e:
        logging.warning('Не удалось изменить автозапуск: %r', e)
        return False


# ============================================================
# Иконка (PIL) — та же рисуется программно, что и в make_icon.py
# ============================================================

def draw_app_icon(size=64, braces_color=(255, 255, 255, 255),
                  accent=(16, 185, 129, 255)):
    """Тёмный скруглённый квадрат + зелёные часы + скобки { }."""
    try:
        from PIL import Image, ImageDraw
    except Exception as e:
        logging.warning('Pillow недоступен: %r', e)
        return None
    S = 8  # рисуем в 8x больше и уменьшаем
    big = size * S
    img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # тёмный скруглённый квадрат
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=big * 0.22,
                        fill=(22, 27, 34, 255), outline=(48, 54, 61, 255),
                        width=max(1, big // 32))

    # зелёный круг-часы (справа сверху)
    cx, cy, r = big * 0.70, big * 0.30, big * 0.20
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent)
    hw = max(1, big // 40)
    d.line([cx, cy, cx, cy - r * 0.62], fill=(22, 27, 34, 255), width=hw)   # часовая
    d.line([cx, cy, cx + r * 0.55, cy + r * 0.25], fill=(22, 27, 34, 255), width=hw)

    # угловые фигурные скобки { }
    bw, bh = big * 0.20, big * 0.52
    y0 = big * 0.30
    lw = max(2, big // 22)
    x1 = big * 0.26            # левая скобка
    pts_l = [(x1 + bw, y0), (x1 + bw * 0.25, y0 + bh * 0.10),
             (x1 + bw * 0.75, y0 + bh * 0.5), (x1 + bw * 0.25, y0 + bh * 0.90),
             (x1 + bw, y0 + bh)]
    d.line(pts_l, fill=braces_color, width=lw, joint='curve')
    x2 = big * 0.56            # правая скобка (зеркально)
    pts_r = [(x2, y0), (x2 + bw * 0.75, y0 + bh * 0.10),
             (x2 + bw * 0.25, y0 + bh * 0.5), (x2 + bw * 0.75, y0 + bh * 0.90),
             (x2, y0 + bh)]
    d.line(pts_r, fill=braces_color, width=lw, joint='curve')

    return img.resize((size, size), Image.LANCZOS)


# ============================================================
# HTTP-сервер и API
# ============================================================

APP = None  # глобальная ссылка на приложение для обработчика запросов

# Состояние самообновления — фронтенд опрашивает GET /api/update/status
UPDATE_STATUS = {'state': 'idle', 'message': '', 'ts': 0.0}


def _upd_status(state, message):
    """Запоминает шаг обновления (для UI) и пишет его в update.log."""
    UPDATE_STATUS.update(state=state, message=str(message), ts=time.time())
    logging.info('UPDATE %s: %s', state, message)
    try:
        with open(os.path.join(data_dir(), 'update.log'), 'a',
                  encoding='utf-8', errors='replace') as f:
            f.write('%s  %-10s  %s\n' % (
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'), state, message))
    except Exception:
        pass


def resource_path(name):
    """Путь к ресурсу (в frozen-режиме — из sys._MEIPASS)."""
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def _ver_newer(a, b):
    """True, если версия a новее b (сравнение по числам: '1.6.0' vs '1.5.2')."""
    def tup(s):
        nums = re.findall(r'\d+', s or '')
        return tuple(int(x) for x in nums[:4]) if nums else (0,)
    return tup(a) > tup(b)


def _clean_release_notes(text):
    """Чистит заметки релиза: убирает служебную строку GitHub
    (**Full Changelog**: …) и лишние переводы строк."""
    out = []
    for line in (text or '').replace('\r\n', '\n').split('\n'):
        if 'full changelog' in line.lower():
            continue
        out.append(line.rstrip())
    res = '\n'.join(out).strip()
    while '\n\n\n' in res:
        res = res.replace('\n\n\n', '\n\n')
    return res


class Handler(BaseHTTPRequestHandler):
    server_version = 'CodeTime/' + APP_VERSION

    def log_message(self, fmt, *args):  # тихие логи доступа
        logging.debug('%s %s', self.address_string(), fmt % args)

    # ---------- помощники ----------

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        data = body if isinstance(body, bytes) else body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _guard(self, fn):
        try:
            fn()
        except Exception as e:
            logging.exception('Ошибка обработки запроса %s: %r', self.path, e)
            self._json({'error': str(e)}, code=500)

    # ---------- GET ----------

    def do_GET(self):
        self._guard(self._route_get)

    def _route_get(self):
        parsed = urlparse(self.path)
        route = parsed.path
        qs = parse_qs(parsed.query)

        if route in ('/', '/index.html', '/dashboard.html'):
            return self._serve_dashboard()
        if route == '/favicon.ico':
            return self._send(204, b'', 'text/plain')

        if route == '/api/overview':
            return self._api_overview(qs)
        if route == '/api/projects':
            return self._api_projects(qs)
        if route == '/api/calendar':
            return self._api_calendar(qs)
        if route == '/api/year':
            return self._api_year(qs)
        if route == '/api/todos':
            return self._api_todos(qs)
        if route == '/api/roadmap':
            return self._api_roadmap()
        if route == '/api/achievements':
            return self._api_achievements()
        if route == '/api/settings':
            return self._api_settings_get()
        if route == '/api/update/check':
            return self._api_update_check()
        if route == '/api/update/releases':
            return self._api_update_releases()
        if route == '/api/update/status':
            return self._api_update_status()
        return self._json({'error': 'Не найдено'}, code=404)

    def _serve_dashboard(self):
        try:
            with open(resource_path('dashboard.html'), 'rb') as f:
                html = f.read()
            self._send(200, html, 'text/html; charset=utf-8')
        except Exception as e:
            self._send(500, 'Не найден dashboard.html: %s' % e, 'text/plain; charset=utf-8')

    def _api_overview(self, qs):
        app = APP
        today = datetime.now().strftime('%Y-%m-%d')
        try:
            days = int(qs.get('days', ['30'])[0])
        except ValueError:
            days = 30
        days = max(7, min(365, days))   # неделя .. год
        start_d = date.today() - timedelta(days=days - 1)
        with app.db_lock:
            conn = app.conn
            row = conn.execute(
                'SELECT COALESCE(SUM(active_sec),0), COALESCE(SUM(idle_sec),0), '
                'COALESCE(SUM(clicks),0), COALESCE(SUM(chars),0), '
                'COALESCE(SUM(words),0), COALESCE(SUM(sessions),0) '
                'FROM day_stats WHERE date=?', (today,)).fetchone()
            yest = (date.today() - timedelta(days=1)).isoformat()
            row_y = conn.execute(
                'SELECT COALESCE(SUM(active_sec),0), COALESCE(SUM(idle_sec),0), '
                'COALESCE(SUM(clicks),0), COALESCE(SUM(chars),0), '
                'COALESCE(SUM(words),0) FROM day_stats WHERE date=?',
                (yest,)).fetchone()
            hourly = {h: 0 for h in range(24)}
            for h, a in conn.execute(
                    'SELECT hour, COALESCE(SUM(active_sec),0) FROM hour_stats '
                    'WHERE date=? GROUP BY hour', (today,)):
                if 0 <= h <= 23:
                    hourly[h] = a
            projects_today = conn.execute(
                'SELECT project, active_sec, idle_sec, clicks, chars, words '
                'FROM day_stats WHERE date=? AND active_sec > 0 '
                'ORDER BY active_sec DESC LIMIT 10', (today,)).fetchall()
            unlocked = conn.execute(
                'SELECT COUNT(*) FROM achievements').fetchone()[0]
            M = compute_metrics(conn)
            # серия за N дней (включая нулевые дни, по сегодня)
            by_date = {}
            for d, a, i in conn.execute(
                    'SELECT date, SUM(active_sec), SUM(idle_sec) FROM day_stats '
                    'WHERE date >= ? GROUP BY date', (start_d.isoformat(),)):
                by_date[d] = (a, i)
            # топ-5 языков за те же N дней
            langs = conn.execute(
                'SELECT lang, SUM(active_sec) AS s FROM lang_stats '
                'WHERE date >= ? GROUP BY lang ORDER BY s DESC LIMIT 5',
                (start_d.isoformat(),)).fetchall()
        series = []
        for i in range(days):
            ds = (start_d + timedelta(days=i)).isoformat()
            a, idle = by_date.get(ds, (0, 0))
            series.append({'date': ds, 'activeSec': a, 'idleSec': idle})
        languages = [{'name': lang, 'seconds': sec,
                      'emoji': LANG_EMOJI.get(lang, '📄')} for lang, sec in langs]
        return self._json({
            'today': {
                'activeSec': row[0], 'idleSec': row[1], 'clicks': row[2],
                'chars': row[3], 'words': row[4], 'sessions': row[5],
                'goalMin': app.settings.get('daily_goal_min', 120),
            },
            'yesterday': {
                'activeSec': row_y[0], 'idleSec': row_y[1], 'clicks': row_y[2],
                'chars': row_y[3], 'words': row_y[4],
            },
            'allTime': {'activeSec': M['total_active']},
            'hourly': [{'hour': h, 'activeSec': hourly[h]} for h in range(24)],
            'days': days,
            'series': series,
            'languages': languages,
            'projectsToday': [{'project': p[0], 'activeSec': p[1],
                               'idleSec': p[2], 'clicks': p[3],
                               'chars': p[4], 'words': p[5]}
                              for p in projects_today],
            'streak': {'current': M['current_streak'], 'best': M['best_streak']},
            'achievementsUnlocked': unlocked,
            'totalActiveAllTime': M['total_active'],
        })

    def _api_year(self, qs):
        """Все дни за N месяцев (включая пустые даты, нули) — для хитмапа."""
        app = APP
        try:
            months = int(qs.get('months', ['12'])[0])
        except ValueError:
            months = 12
        months = max(1, min(24, months))
        today_d = date.today()
        start_d = months_ago(today_d, months)
        by_date = {}
        with app.db_lock:
            for d, a, i in app.conn.execute(
                    'SELECT date, SUM(active_sec), SUM(idle_sec) FROM day_stats '
                    'WHERE date >= ? GROUP BY date', (start_d.isoformat(),)):
                by_date[d] = (a, i)
        days = []
        cur = start_d
        while cur <= today_d:
            ds = cur.isoformat()
            a, i = by_date.get(ds, (0, 0))
            days.append({'date': ds, 'activeSec': a, 'idleSec': i})
            cur += timedelta(days=1)
        return self._json({'today': today_d.isoformat(), 'months': months,
                           'days': days})

    def _api_projects(self, qs):
        app = APP
        try:
            days = int(qs.get('days', ['30'])[0])
        except ValueError:
            days = 30
        days = max(1, min(3650, days))
        since = (date.today() - timedelta(days=days - 1)).isoformat()
        with app.db_lock:
            rows = app.conn.execute(
                'SELECT project, SUM(active_sec), SUM(idle_sec), SUM(clicks), '
                'SUM(chars), SUM(words), COUNT(DISTINCT date), MIN(date), MAX(date) '
                'FROM day_stats WHERE date >= ? '
                'GROUP BY project ORDER BY SUM(active_sec) DESC', (since,)).fetchall()
        total = sum(r[1] for r in rows) or 1
        result = [{
            'project': r[0], 'activeSec': r[1], 'idleSec': r[2], 'clicks': r[3],
            'chars': r[4], 'words': r[5], 'daysActive': r[6], 'firstDate': r[7],
            'lastDate': r[8],
            'share': round(r[1] * 100.0 / total, 1),
        } for r in rows]
        return self._json(result)

    def _api_calendar(self, qs):
        app = APP
        month = qs.get('month', [datetime.now().strftime('%Y-%m')])[0]
        if not re.match(r'^\d{4}-\d{2}$', month):
            month = datetime.now().strftime('%Y-%m')
        like = month + '%'
        with app.db_lock:
            conn = app.conn
            per_day = {}
            for d, a, i, c, ch, w in conn.execute(
                    'SELECT date, SUM(active_sec), SUM(idle_sec), SUM(clicks), '
                    'SUM(chars), SUM(words) FROM day_stats '
                    "WHERE date LIKE ? GROUP BY date", (like,)):
                per_day[d] = {'date': d, 'activeSec': a, 'idleSec': i,
                              'clicks': c, 'chars': ch, 'words': w,
                              'projects': {}}
            for d, p, a in conn.execute(
                    'SELECT date, project, active_sec FROM day_stats '
                    "WHERE date LIKE ? AND active_sec > 0", (like,)):
                if d in per_day:
                    per_day[d]['projects'][p] = a
            M = compute_metrics(conn)
        days = [per_day[k] for k in sorted(per_day)]
        today = datetime.now().strftime('%Y-%m-%d')
        summary = {
            'monthTotal': sum(d['activeSec'] for d in days),
            'todayActive': per_day.get(today, {}).get('activeSec', 0),
            'currentStreak': M['current_streak'],
            'bestStreak': M['best_streak'],
        }
        return self._json({'month': month, 'days': days, 'summary': summary})

    def _api_achievements(self):
        app = APP
        check_achievements(app, force=True)  # пересчитать перед выдачей
        with app.db_lock:
            unlocked = {r[0]: r[1] for r in
                        app.conn.execute('SELECT ach_id, unlocked_at FROM achievements')}
            M = compute_metrics(app.conn)
        items = []
        for ach in ACHIEVEMENTS:
            cur = metric_value(ach['id'], M)
            is_unlocked = ach['id'] in unlocked
            items.append({
                'id': ach['id'], 'name': ach['name'], 'desc': ach['desc'],
                'category': ach['category'], 'icon': ach['icon'],
                'target': ach['target'], 'unit': ach['unit'],
                'current': cur if cur <= ach['target'] else ach['target'],
                'rawCurrent': cur,
                'unlocked': is_unlocked,
                'unlockedAt': unlocked.get(ach['id']),
            })
        return self._json({'items': items, 'count': len(unlocked),
                           'unlocked': len(unlocked), 'total': len(ACHIEVEMENTS)})

    def _api_settings_get(self):
        app = APP
        s = app.settings
        with app.db_lock:
            repo = get_meta(app.conn, 'github_repo', '') or ''
        return self._json({
            'dailyGoalMin': int(s.get('daily_goal_min', 120)),
            'trackClicks': bool(s.get('track_clicks', 1)),
            'trackKeys': bool(s.get('track_keys', 1)),
            'paused': bool(s.get('paused', 0)),
            'autostart': bool(get_autostart_enabled()),
            'githubRepo': str(repo),
            'dbPath': db_path(),
            'version': APP_VERSION,
        })

    def _api_todos(self, qs):
        """Задачи по дням: ?month=YYYY-MM или ?from=&to=YYYY-MM-DD
        (по умолчанию — текущий месяц). Сортировка date, id."""
        app = APP
        today = date.today()
        month = (qs.get('month', [''])[0] or '').strip()
        d_from = (qs.get('from', [''])[0] or '').strip()
        d_to = (qs.get('to', [''])[0] or '').strip()
        if re.match(r'^\d{4}-\d{2}$', month):
            y, m = int(month[:4]), int(month[5:7])
            first = date(y, m, 1)
            last = date(y + (m // 12), (m % 12) + 1, 1) - timedelta(days=1)
            d_from, d_to = first.isoformat(), last.isoformat()
        elif not (DATE_RE.match(d_from) and DATE_RE.match(d_to)):
            first = today.replace(day=1)
            last = date(today.year + (today.month // 12),
                        (today.month % 12) + 1, 1) - timedelta(days=1)
            d_from, d_to = first.isoformat(), last.isoformat()
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        with app.db_lock:
            rows = app.conn.execute(
                'SELECT id, date, title, minutes, done, source FROM todos '
                'WHERE date >= ? AND date <= ? ORDER BY date, id',
                (d_from, d_to)).fetchall()
        items = [{'id': r[0], 'date': r[1], 'title': r[2], 'minutes': r[3],
                  'done': bool(r[4]), 'source': r[5]} for r in rows]
        return self._json({'items': items})

    def _api_roadmap(self):
        """План обучения: цель, шаги с проекцией дат, темп, итоги, вердикт."""
        app = APP
        with app.db_lock:
            data = roadmap_state(app.conn)
        return self._json(data)

    # ---------- POST ----------

    def do_POST(self):
        self._guard(self._route_post)

    def _route_post(self):
        route = urlparse(self.path).path
        if route == '/api/settings':
            return self._api_settings_post()   # исторический роут (старый формат разбора)
        if route == '/api/update':
            return self._api_update()          # сырые байты exe, не JSON
        handler = self.POST_ROUTES.get(route)
        if handler is None:
            return self._json({'error': 'Не найдено'}, code=404)
        try:
            length = int(self.headers.get('Content-Length') or 0)
            data = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError) as e:
            return self._json({'error': 'Некорректный JSON: %r' % e}, code=400)
        if not isinstance(data, dict):
            return self._json({'error': 'Ожидался JSON-объект'}, code=400)
        try:
            return handler(self, data)
        except ValueError as e:
            # ошибки валидации тела -> 400 {error}
            return self._json({'error': str(e)}, code=400)

    def _api_settings_post(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
            data = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
            return self._json({'error': 'Некорректный JSON: %s' % e}, code=400)
        if not isinstance(data, dict):
            return self._json({'error': 'Ожидался объект настроек'}, code=400)

        app = APP
        s = app.settings
        if 'dailyGoalMin' in data:
            s['daily_goal_min'] = int(data['dailyGoalMin'])
        if 'trackClicks' in data:
            s['track_clicks'] = 1 if data['trackClicks'] else 0
        if 'trackKeys' in data:
            s['track_keys'] = 1 if data['trackKeys'] else 0
        if 'paused' in data:
            s['paused'] = 1 if data['paused'] else 0
        if 'githubRepo' in data:
            repo = str(data.get('githubRepo') or '').strip()[:120]
            with app.db_lock:
                set_meta(app.conn, 'github_repo', repo)
        app.clamp_settings()
        app.save_settings()
        # сброс буферов: пауза/возобновление и смена порога применяются сразу
        app.flush_now()
        if 'autostart' in data:
            set_autostart_enabled(bool(data['autostart']))
        logging.info('Настройки сохранены: %s', data)
        return self._json({'ok': True})

    # ---------- POST: задачи по дням ----------

    def _api_todos_add(self, data):
        app = APP
        d = parse_date_or_none(data.get('date'))
        if d is None:
            raise ValueError('Некорректная дата (ожидается ГГГГ-ММ-ДД).')
        title = _need_str(data, 'title')
        minutes = int(_need_num(data, 'minutes', 0, 1440, default=0))
        now = datetime.now().isoformat(timespec='seconds')
        with app.db_lock:
            cur = app.conn.execute(
                "INSERT INTO todos(date, title, minutes, done, source, created_at) "
                "VALUES(?,?,?,0,'manual',?)", (d.isoformat(), title, minutes, now))
            app.conn.commit()
            tid = cur.lastrowid
        logging.info('Задача добавлена: %s «%s» (%s мин)', d.isoformat(), title, minutes)
        return self._json({'item': {'id': tid, 'date': d.isoformat(),
                                    'title': title, 'minutes': minutes,
                                    'done': False, 'source': 'manual'}})

    def _api_todos_toggle(self, data):
        app = APP
        tid = _need_id(data)
        with app.db_lock:
            row = app.conn.execute('SELECT done FROM todos WHERE id=?', (tid,)).fetchone()
            if row is None:
                raise ValueError('Задача с id=%s не найдена.' % tid)
            new_done = 0 if row[0] else 1
            app.conn.execute('UPDATE todos SET done=? WHERE id=?', (new_done, tid))
            app.conn.commit()
        return self._json({'ok': True, 'done': bool(new_done)})

    def _api_todos_delete(self, data):
        app = APP
        tid = _need_id(data)
        with app.db_lock:
            app.conn.execute('DELETE FROM todos WHERE id=?', (tid,))
            app.conn.commit()
        return self._json({'ok': True})

    # ---------- POST: план обучения ----------

    def _api_roadmap_goal(self, data):
        app = APP
        with app.db_lock:
            row = app.conn.execute(
                'SELECT title, target_date, daily_hours '
                'FROM roadmap_goal WHERE id=1').fetchone()
            title = _need_str(data, 'title', max_len=200, allow_empty=True) \
                if 'title' in data else (row[0] if row else '')
            if 'targetDate' in data:
                raw = data.get('targetDate')
                if raw in (None, ''):
                    target_s = ''
                else:
                    d = parse_date_or_none(raw)
                    if d is None:
                        raise ValueError('Некорректная дата цели (ожидается ГГГГ-ММ-ДД).')
                    target_s = d.isoformat()
            else:
                target_s = row[1] if row else ''
            daily = _need_num(data, 'dailyHours', 0, 24, default=0) \
                if 'dailyHours' in data else (float(row[2] or 0.0) if row else 0.0)
            app.conn.execute(
                'INSERT OR REPLACE INTO roadmap_goal(id, title, target_date, daily_hours) '
                'VALUES(1,?,?,?)', (title, target_s, daily))
            app.conn.commit()
        logging.info('Цель плана сохранена: «%s» до %s, %s ч/день',
                     title, target_s or '—', daily)
        return self._json({'ok': True, 'goal': {'title': title,
                                                'targetDate': target_s,
                                                'dailyHours': daily}})

    def _api_roadmap_step_add(self, data):
        app = APP
        title = _need_str(data, 'title')
        hours = _need_num(data, 'hours', 0.5, 500, default=10)
        now = datetime.now().isoformat(timespec='seconds')
        with app.db_lock:
            nxt = app.conn.execute(
                'SELECT COALESCE(MAX(order_idx),0) + 1 FROM roadmap_steps').fetchone()[0]
            app.conn.execute(
                "INSERT INTO roadmap_steps(title, hours, status, order_idx, created_at) "
                "VALUES(?,?,'todo',?,?)", (title, hours, nxt, now))
            renumber_steps(app.conn)
            app.conn.commit()
        return self._json({'ok': True})

    def _api_roadmap_step_update(self, data):
        app = APP
        sid = _need_id(data)
        with app.db_lock:
            row = app.conn.execute('SELECT id FROM roadmap_steps WHERE id=?',
                                   (sid,)).fetchone()
            if row is None:
                raise ValueError('Шаг с id=%s не найден.' % sid)
            if 'title' in data:
                app.conn.execute('UPDATE roadmap_steps SET title=? WHERE id=?',
                                 (_need_str(data, 'title'), sid))
            if 'hours' in data:
                app.conn.execute('UPDATE roadmap_steps SET hours=? WHERE id=?',
                                 (_need_num(data, 'hours', 0.5, 500), sid))
            if 'status' in data:
                status = data['status']
                if status not in ('todo', 'doing', 'done'):
                    raise ValueError('Статус должен быть todo, doing или done.')
                app.conn.execute('UPDATE roadmap_steps SET status=? WHERE id=?',
                                 (status, sid))
            app.conn.commit()
        return self._json({'ok': True})

    def _api_roadmap_step_delete(self, data):
        app = APP
        sid = _need_id(data)
        with app.db_lock:
            app.conn.execute('DELETE FROM roadmap_steps WHERE id=?', (sid,))
            renumber_steps(app.conn)
            app.conn.commit()
        return self._json({'ok': True})

    def _api_roadmap_step_move(self, data):
        app = APP
        sid = _need_id(data)
        direction = data.get('dir')
        if direction not in ('up', 'down'):
            raise ValueError('Направление должно быть "up" или "down".')
        with app.db_lock:
            row = app.conn.execute('SELECT id FROM roadmap_steps WHERE id=?',
                                   (sid,)).fetchone()
            if row is None:
                raise ValueError('Шаг с id=%s не найден.' % sid)
            renumber_steps(app.conn)   # гарантируем плотные индексы 1..N
            cur_idx = app.conn.execute(
                'SELECT order_idx FROM roadmap_steps WHERE id=?', (sid,)).fetchone()[0]
            other_idx = cur_idx - 1 if direction == 'up' else cur_idx + 1
            other = app.conn.execute(
                'SELECT id FROM roadmap_steps WHERE order_idx=?',
                (other_idx,)).fetchone()
            if other is not None:
                app.conn.execute('UPDATE roadmap_steps SET order_idx=? WHERE id=?',
                                 (other_idx, sid))
                app.conn.execute('UPDATE roadmap_steps SET order_idx=? WHERE id=?',
                                 (cur_idx, other[0]))
                app.conn.commit()
        return self._json({'ok': True})

    def _api_roadmap_template(self, data):
        app = APP
        with app.db_lock:
            cnt = app.conn.execute('SELECT COUNT(*) FROM roadmap_steps').fetchone()[0]
            added = 0
            if cnt == 0:
                now = datetime.now().isoformat(timespec='seconds')
                for i, (title, hours, status) in enumerate(FRONTEND_TEMPLATE, 1):
                    app.conn.execute(
                        'INSERT INTO roadmap_steps(title, hours, status, order_idx, '
                        'created_at) VALUES(?,?,?,?,?)',
                        (title, hours, status, i, now))
                    added += 1
                app.conn.commit()
        return self._json({'ok': True, 'added': added})

    # ---------- POST: полный сброс ----------

    def _api_reset(self, data):
        """Удаляет ВСЮ статистику, задачи, план и достижения.
        Настройки (цель, счётчики, автозапуск) сохраняются."""
        app = APP
        with app.db_lock:
            app.flush_now()   # сначала сбросим буферы, потом всё удалим
            conn = app.conn
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name != 'meta'")]
            for table in tables:
                conn.execute('DELETE FROM "%s"' % table.replace('"', '""'))
            conn.execute("DELETE FROM meta WHERE key IN "
                         "('xp_state', 'roadmap_since', 'roadmap_filled')")
            conn.execute("INSERT OR REPLACE INTO meta(key, value) "
                         "VALUES('first_date', ?)",
                         (datetime.now().strftime('%Y-%m-%d'),))
            conn.commit()
        reset_metrics_cache()
        app.shared['project'] = ''
        logging.info('ВСЕ ДАННЫЕ удалены (сброс из дашборда)')
        return self._json({'ok': True})

    # ---------- POST: самообновление ----------

    def _api_update(self):
        """Принимает новый CodeTime.exe: тело запроса — сырые байты
        (Content-Type: application/octet-stream, X-Filename — имя файла).
        После ответа приложение в фоне заменяет свой exe и перезапускается."""
        if not getattr(sys, 'frozen', False):
            return self._json(
                {'error': 'Обновление работает только в собранном приложении '
                          '(CodeTime.exe). В режиме запуска из .py оно отключено.'},
                code=400)
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length < 1024 or length > 400 * 1024 * 1024:
            return self._json(
                {'error': 'Подозрительный размер файла обновления.'}, code=400)
        fname = os.path.basename(unquote(self.headers.get('X-Filename') or ''))
        if not fname.lower().endswith('.exe'):
            return self._json(
                {'error': 'Нужен файл .exe (например, CodeTime.exe).'}, code=400)
        tmp_path = os.path.join(data_dir(), 'update.tmp')
        try:
            remaining = length
            with open(tmp_path, 'wb') as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(1 << 16, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            if remaining:
                raise IOError('файл передался не полностью')
            with open(tmp_path, 'rb') as f:
                if f.read(2) != b'MZ':
                    raise ValueError('это не Windows-exe файл')
        except Exception as e:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return self._json(
                {'error': 'Не удалось принять обновление: %s' % e}, code=400)
        logging.info('Обновление принято: %s (%d байт). Устанавливаю…',
                     fname, length)
        _upd_status('installing', 'Устанавливаю обновление из файла…')
        # сначала отвечаем клиенту, установка — в отдельном потоке
        threading.Timer(0.7, self_update_apply, args=(tmp_path,)).start()
        return self._json({'ok': True,
                           'message': 'Обновление принято — приложение перезапустится'})

    # ---------- GET: проверка обновления на GitHub ----------

    def _api_update_check(self):
        """Смотрит последний релиз на GitHub Releases и сравнивает версии.
        GET /api/update/check — без ключей, репозиторий задаётся в Настройках."""
        app = APP
        with app.db_lock:
            repo = ((get_meta(app.conn, 'github_repo', '') or '').strip()
                    or GITHUB_REPO_DEFAULT.strip())
        if not repo or '/' not in repo:
            return self._json({'configured': False, 'current': APP_VERSION})
        url = 'https://api.github.com/repos/%s/releases/latest' % repo
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'CodeTime-updater',
                'Accept': 'application/vnd.github+json'})
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            return self._json({'configured': True, 'current': APP_VERSION,
                               'error': 'нет связи с GitHub (%s)' % e})
        tag = (data.get('tag_name') or '').strip()
        latest = tag.lstrip('vV') or tag
        asset = None
        for a in (data.get('assets') or []):
            n = (a.get('name') or '').lower()
            if n.endswith('.exe') and 'old' not in n and 'setup' not in n:
                asset = a
                if 'codetime' in n:
                    break
        res = {'configured': True, 'current': APP_VERSION, 'latest': latest,
               'tagName': tag, 'releaseUrl': data.get('html_url') or '',
               'notes': _clean_release_notes(data.get('body') or '')[:400],
               'available': _ver_newer(latest, APP_VERSION)}
        if asset:
            res['assetUrl'] = asset.get('browser_download_url') or ''
            res['assetName'] = asset.get('name') or ''
            res['assetSize'] = int(asset.get('size') or 0)
        return self._json(res)

    # ---------- GET: все версии репозитория (выбор и откат) ----------

    def _api_update_releases(self):
        """GET /api/update/releases — список ВСЕХ релизов репозитория.
        Позволяет поставить любую версию: и подняться, и откатиться назад.
        Репозиторий — из настроек или зашитая константа."""
        app = APP
        with app.db_lock:
            repo = ((get_meta(app.conn, 'github_repo', '') or '').strip()
                    or GITHUB_REPO_DEFAULT.strip())
        if not repo or '/' not in repo:
            return self._json({'configured': False, 'current': APP_VERSION})
        url = 'https://api.github.com/repos/%s/releases?per_page=50' % repo
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'CodeTime-updater',
                'Accept': 'application/vnd.github+json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            return self._json({'configured': True, 'current': APP_VERSION,
                               'error': 'нет связи с GitHub (%s)' % e})
        releases = []
        for rel in data:
            tag = (rel.get('tag_name') or '').strip()
            if not tag:
                continue
            ver = tag.lstrip('vV') or tag
            asset = None
            for a in (rel.get('assets') or []):
                n = (a.get('name') or '').lower()
                if n.endswith('.exe') and 'old' not in n and 'setup' not in n:
                    asset = a
                    if 'codetime' in n:
                        break
            releases.append({
                'tag': tag,
                'version': ver,
                'name': rel.get('name') or '',
                'date': (rel.get('published_at') or '')[:10],
                'notes': _clean_release_notes(rel.get('body') or '')[:400],
                'assetUrl': (asset or {}).get('browser_download_url') or '',
                'assetName': (asset or {}).get('name') or '',
                'assetSize': int((asset or {}).get('size') or 0),
                'relation': ('newer' if _ver_newer(ver, APP_VERSION)
                             else 'current' if ver == APP_VERSION else 'older'),
            })
        return self._json({'configured': True, 'current': APP_VERSION,
                           'releases': releases})

    def _api_update_status(self):
        """GET /api/update/status — шаг/ошибка последнего обновления."""
        return self._json(dict(UPDATE_STATUS))

    # ---------- POST: скачать обновление с GitHub и поставить ----------

    def _api_update_apply(self, data):
        """Скачивает exe-ассет последнего релиза и запускает установку.
        Тело: {assetUrl, assetName}. Ответ отдаётся сразу, скачивание
        идёт в фоне — фронтенд опрашивает /api/settings до перезапуска."""
        if not getattr(sys, 'frozen', False):
            return self._json(
                {'error': 'Обновление работает только в собранном приложении '
                          '(CodeTime.exe). В режиме запуска из .py оно отключено.'},
                code=400)
        url = str(data.get('assetUrl') or '').strip()
        host = urlparse(url).netloc.lower()
        if not url.lower().startswith('https://') or not (
                host == 'github.com' or host.endswith('.github.com')
                or host.endswith('githubusercontent.com')):
            raise ValueError('Скачивать обновление можно только с GitHub.')
        if not urlparse(url).path.lower().endswith('.exe'):
            raise ValueError('Файл обновления должен быть .exe.')
        tmp_path = os.path.join(data_dir(), 'update.tmp')

        def worker():
            try:
                _upd_status('downloading',
                            'Скачиваю обновление с GitHub — не закрывайте приложение…')
                req = urllib.request.Request(
                    url, headers={'User-Agent': 'CodeTime-updater'})
                with urllib.request.urlopen(req, timeout=300) as resp, \
                        open(tmp_path, 'wb') as f:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)
                with open(tmp_path, 'rb') as f:
                    if f.read(2) != b'MZ':
                        raise ValueError('это не Windows-exe файл')
                logging.info('Обновление с GitHub скачано (%d байт). Устанавливаю…',
                             os.path.getsize(tmp_path))
                self_update_apply(tmp_path)
            except Exception as e:
                logging.exception('Обновление с GitHub НЕ удалось: %r', e)
                _upd_status('error', 'Скачивание/установка не удалась: %r' % e)
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        threading.Thread(target=worker, daemon=True,
                         name='codetime-gh-updater').start()
        return self._json({'ok': True,
                           'message': 'Скачиваю обновление — приложение перезапустится'})

    # Диспетчер POST-роутов (JSON-тело); /api/settings и /api/update обрабатываются отдельно
    POST_ROUTES = {
        '/api/todos': _api_todos_add,
        '/api/todos/toggle': _api_todos_toggle,
        '/api/todos/delete': _api_todos_delete,
        '/api/reset': _api_reset,
        '/api/roadmap/goal': _api_roadmap_goal,
        '/api/roadmap/step': _api_roadmap_step_add,
        '/api/roadmap/step/update': _api_roadmap_step_update,
        '/api/roadmap/step/delete': _api_roadmap_step_delete,
        '/api/roadmap/step/move': _api_roadmap_step_move,
        '/api/roadmap/template': _api_roadmap_template,
        '/api/update/apply': _api_update_apply,
    }


def make_server():
    """Поднимает ThreadingHTTPServer на порту 5731 (только localhost)."""
    return ThreadingHTTPServer(('127.0.0.1', PORT), Handler)


# ============================================================
# Самообновление: замена exe через батник-обменник + перезапуск
# ============================================================

def _write_update_bat(exe_dir, exe_name, stage_name):
    """Пишет codetime_update.bat (строго ASCII + CRLF) рядом с exe.

    Батник живёт рядом с exe и работает с ОТНОСИТЕЛЬНЫМИ путями через
    cd /d "%~dp0" — поэтому в самом файле нет ни одного не-ASCII символа,
    даже если папка пользователя названа кириллицей.
    Алгоритм: цикл «попробовать скопировать новый exe поверх старого» —
    пока старый процесс жив, Windows не даёт перезаписать запущенный exe
    (копирование возвращает ошибку), как только приложение закрылось,
    копия проходит, батник стартует новый exe и удаляет сам себя.
    """
    bat = '\r\n'.join([
        '@echo off',
        'cd /d "%~dp0"',
        ':wait',
        'ping -n 2 127.0.0.1 >nul',
        'copy /y "%s" "%s" >nul 2>&1' % (stage_name, exe_name),
        'if errorlevel 1 goto wait',
        'del /f /q "%s" >nul 2>&1' % stage_name,
        'start "" "%s"' % exe_name,
        'del /f /q "%~f0" >nul 2>&1',
        '',
    ])
    bat_path = os.path.join(exe_dir, 'codetime_update.bat')
    with open(bat_path, 'w', encoding='ascii', newline='') as f:
        f.write(bat)
    return bat_path


def self_update_apply(tmp_path):
    """Ставит загруженный exe и перезапускает приложение.

    Работающий exe нельзя перезаписать — поэтому вместо хрупкой схемы
    «переименовать себя + скопировать на то же место» (падала молча из-за
    антивируса/залоченных файлов и приложение оставалось на старой версии)
    используется батник-обменник:
      1) новый exe кладём РЯДОМ как CodeTime_update.exe (3 попытки —
         антивирус может временно держать скачанный файл);
      2) пишем codetime_update.bat: он в цикле ждёт, пока наше приложение
         закроется, затем копирует новый exe поверх старого и запускает его;
      3) запускаем батник ОТДЕЛЬНО от приложения и закрываемся сами.
    Такой способ не требует переименований работающего exe и не ломается
    от повторных попыток обновления.
    """
    cur = os.path.abspath(sys.executable)
    exe_dir = os.path.dirname(cur) or '.'
    exe_name = os.path.basename(cur)
    root, ext = os.path.splitext(exe_name)
    stage_name = root + '_update' + (ext or '.exe')
    stage_path = os.path.join(exe_dir, stage_name)
    try:
        _upd_status('installing', 'Копирую новый exe рядом со старым…')
        last_err = None
        for _ in range(3):
            try:
                shutil.copyfile(tmp_path, stage_path)
                last_err = None
                break
            except Exception as e:
                last_err = e
                time.sleep(1.0)
        if last_err is not None:
            raise last_err
        bat_path = _write_update_bat(exe_dir, exe_name, stage_name)
        logging.info('Обновление: батник готов (%s)', bat_path)
        _upd_status('restarting', 'Закрываюсь — установщик подменит exe и запустит новую версию…')
    except Exception as e:
        logging.exception('Обновление НЕ удалось: %r', e)
        _upd_status('error', 'Не удалось подготовить обновление: %r' % e)
        return
    # финальный сброс в БД и выход — подмену сделает батник
    try:
        APP.flush_now()
    except Exception:
        pass
    try:
        APP.conn.close()
    except Exception:
        pass
    logging.info('Обновление: выходим, батник завершит установку…')
    try:
        flags = (0x00000008 | 0x08000000) if IS_WINDOWS else 0
        subprocess.Popen(['cmd', '/c', bat_path], close_fds=True,
                         cwd=exe_dir, creationflags=flags,
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception as e:
        logging.exception('Не удалось запустить установщик обновления: %r', e)
        _upd_status('error', 'Не удалось запустить установщик: %r' % e)
        return
    time.sleep(1.0)   # даём батнику стартовать, затем закрываемся
    os._exit(0)


def _cleanup_old_exe():
    """После обновления рядом с exe может остаться CodeTime.exe.old — убираем."""
    if not getattr(sys, 'frozen', False):
        return
    try:
        p = os.path.abspath(sys.executable) + '.old'
        if os.path.exists(p):
            os.remove(p)
            logging.info('Удалён старый exe после обновления: %s', p)
    except OSError:
        pass


# ============================================================
# Трей (pystray)
# ============================================================

def _wait_server(timeout=6.0):
    """Ждёт, пока локальный HTTP-сервер начнёт принимать соединения."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _find_browser_exe():
    """Путь к msedge.exe/chrome.exe: реестр (App Paths) + стандартные папки."""
    import winreg  # только Windows
    candidates = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (r'SOFTWARE\Microsoft\Windows\CurrentVersion'
                    r'\App Paths\msedge.exe',
                    r'SOFTWARE\Microsoft\Windows\CurrentVersion'
                    r'\App Paths\chrome.exe'):
            try:
                with winreg.OpenKey(root, sub) as k:
                    val = winreg.QueryValue(k, '')
                    if val:
                        candidates.append(val)
            except OSError:
                pass
    pf = os.environ.get('ProgramFiles', r'C:\Program Files')
    pf86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
    lad = os.environ.get('LocalAppData', '')
    for base in (pf, pf86, lad):
        if base:
            candidates.append(os.path.join(
                base, r'Microsoft\Edge\Application\msedge.exe'))
            candidates.append(os.path.join(
                base, r'Google\Chrome\Application\chrome.exe'))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


# Событие «пользователь просит окно статистики» + флаг деградации UI
_open_window_evt = threading.Event()
_native_broken = False


def open_dashboard():
    """Просит UI-поток открыть окно статистики (не блокирует вызывающего)."""
    _open_window_evt.set()


def _apply_window_icon():
    """Ставит иконку exe на нативное окно (WinForms сам её не берёт).
    Вызывается через webview.start(func=...) в отдельном потоке после
    старта GUI."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        time.sleep(1.2)  # ждём, пока окно реально появится
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if not hwnd:
            return
        hmod = kernel32.GetModuleHandleW(None)
        image_icon, lr_shared, lr_defsize = 1, 0x8000, 0x40
        big = user32.LoadImageW(hmod, 1, image_icon, 0, 0,
                                lr_defsize | lr_shared)
        small = user32.LoadImageW(hmod, 1, image_icon, 16, 16, lr_shared)
        wm_seticon = 0x80
        if big:
            user32.SendMessageW(hwnd, wm_seticon, 1, big)    # ICON_BIG
        if small:
            user32.SendMessageW(hwnd, wm_seticon, 0, small)  # ICON_SMALL
    except Exception:
        pass


def _open_native_window():
    """НАСТОЯЩЕЕ окно приложения: pywebview + WebView2 (системный движок
    Windows). Своё окно, своя иконка, никаких браузеров. Возвращает True,
    если окно открылось и было закрыто пользователем."""
    try:
        import webview  # необязательная зависимость
    except Exception as e:
        logging.info('pywebview недоступен (%r) — запасной режим окна.', e)
        return False
    try:
        _wait_server()
        webview.create_window(
            WINDOW_TITLE, BASE_URL,
            width=1180, height=760, min_size=(860, 560),
            background_color='#0f1114')
        webview.start(gui='edgechromium', func=_apply_window_icon)
        return True
    except Exception as e:
        logging.warning('Нативное окно не удалось (%r) — запасной режим.', e)
        return False


def _open_app_mode_window():
    """Запасной вариант: отдельное окно Edge/Chrome в режиме --app
    (без вкладок и адресной строки)."""
    if not IS_WINDOWS:
        return False
    try:
        exe = _find_browser_exe()
        if not exe:
            return False
        profile = os.path.join(data_dir(), 'ui-profile')
        os.makedirs(profile, exist_ok=True)
        subprocess.Popen([
            exe,
            '--app=' + BASE_URL,
            '--user-data-dir=' + profile,
            '--no-first-run',
            '--no-default-browser-check',
            '--window-size=1180,760',
        ])
        return True
    except Exception as e:
        logging.warning('Окно --app не открылось (%r).', e)
        return False


def ui_loop(app):
    """UI-поток: ждёт запроса окна (запуск/иконка в трее) и открывает
    нативное окно. Если pywebview недоступен — окно --app, затем браузер."""
    global _native_broken
    while not app.stop_event.is_set():
        if not _open_window_evt.wait(timeout=0.5):
            continue
        _open_window_evt.clear()
        if _native_broken or not _open_native_window():
            _native_broken = True
            if not _open_app_mode_window():
                try:
                    webbrowser.open(BASE_URL)
                except Exception:
                    pass


def create_desktop_shortcut():
    """Ярлык CodeTime.lnk на рабочем столе (иконка — иконка exe).
    Пересоздаётся при каждом запуске — путь сам обновится, если exe
    переносят в другую папку."""
    if not IS_WINDOWS:
        return False
    try:
        exe = os.path.abspath(sys.executable
                              if getattr(sys, 'frozen', False)
                              else sys.argv[0])
        target = exe.replace("'", "''")
        workdir = os.path.dirname(exe).replace("'", "''")
        script = (
            "$d=[Environment]::GetFolderPath('Desktop');"
            "$lnk=Join-Path $d 'CodeTime.lnk';"
            "$ws=New-Object -ComObject WScript.Shell;"
            "$s=$ws.CreateShortcut($lnk);"
            "$s.TargetPath='" + target + "';"
            "$s.WorkingDirectory='" + workdir + "';"
            "$s.IconLocation='" + target + ",0';"
            "$s.Description='CodeTime - VS Code time tracker';"
            "$s.Save()"
        )
        subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-Command', script],
            capture_output=True, timeout=20, check=False,
            creationflags=(0x08000000 if IS_WINDOWS else 0))  # без окна консоли
        logging.info('Ярлык на рабочем столе готов: CodeTime.lnk')
        return True
    except Exception as e:
        logging.warning('Ярлык не создан: %r', e)
        return False


def run_tray(app):
    """Блокирующий запуск трея в главном потоке. Если трей недоступен —
    просто ждём (сервер продолжает работать, для отладки вне Windows)."""
    try:
        import pystray
        image = draw_app_icon(64)
        if image is None:
            raise RuntimeError('PIL недоступна — нет иконки')

        menu = pystray.Menu(
            pystray.MenuItem('Открыть статистику',
                             lambda *_: open_dashboard(), default=True),
            pystray.MenuItem(
                lambda item: ('Продолжить отслеживание'
                              if app.settings.get('paused', 0)
                              else 'Пауза отслеживания'),
                lambda *_: app.toggle_pause()),
            pystray.MenuItem('Автозапуск с Windows',
                             lambda *_: set_autostart_enabled(
                                 not get_autostart_enabled()),
                             checked=lambda item: get_autostart_enabled()),
            pystray.MenuItem('Открыть папку данных',
                             lambda *_: open_data_folder()),
            pystray.MenuItem('Ярлык на рабочем столе',
                             lambda *_: create_desktop_shortcut()),
            pystray.MenuItem('Выход', lambda *_: request_exit(app)),
        )
        icon = pystray.Icon(APP_NAME, image,
                            'CodeTime — трекер времени в VS Code', menu)
        app.tray_icon = icon
        icon.run()
    except Exception as e:
        logging.warning('Трей недоступен (%r). Работаем в фоне; '
                        'остановка — Ctrl+C в консоли.', e)
        try:
            while not app.stop_event.wait(1.0):
                pass
        except KeyboardInterrupt:
            request_exit(app)


def open_data_folder():
    try:
        if IS_WINDOWS:
            os.startfile(data_dir())  # noqa: только Windows
        else:
            webbrowser.open('file://' + data_dir())
    except Exception as e:
        logging.warning('Не удалось открыть папку данных: %r', e)


def request_exit(app):
    """Выход: остановить движок, сбросить буферы, закрыть окна и трей."""
    app.stop_event.set()
    _open_window_evt.set()  # разбудить UI-поток, чтобы он увидел остановку
    try:
        import webview
        for w in list(getattr(webview, 'windows', [])):
            try:
                w.destroy()
            except Exception:
                pass
    except Exception:
        pass
    try:
        app.flush_now()
    except Exception:
        pass
    if app.tray_icon is not None:
        try:
            app.tray_icon.stop()
        except Exception:
            pass


# ============================================================
# Точка входа
# ============================================================

def main():
    global APP
    setup_logging()
    logging.info('CodeTime %s запускается...', APP_VERSION)

    app = CodeTimeApp()
    APP = app
    app.conn = init_db()
    app.load_settings()
    app.clamp_settings()

    # UI-поток: нативное окно статистики откроется по событию
    threading.Thread(target=ui_loop, args=(app,), daemon=True,
                     name='codetime-ui').start()

    # открыть окно приложения при обычном запуске (не --no-browser)
    if '--no-browser' not in sys.argv:
        open_dashboard()

    # движок (тишину держит, пишет в БД)
    Engine(app).start()


    # хуки ввода (лучшее усилие)
    try:
        start_hooks(app)
    except Exception as e:
        logging.warning('Хуки ввода не запустились: %r', e)

    # локальный сервер. Занятый порт — это уже запущенная копия ЛИБО порт
    # ещё не освободился после самообновления: пробуем привязаться несколько
    # раз, и только потом считаем, что CodeTime уже работает.
    server = None
    for attempt in range(8):
        try:
            server = make_server()
            break
        except OSError:
            if attempt == 0:
                logging.info('Порт %d занят — жду освобождения…', PORT)
            time.sleep(1.0)
    if server is None:
        logging.info('Порт %d так и занят — CodeTime уже запущен. Открываю окно.', PORT)
        if not _open_app_mode_window():
            try:
                webbrowser.open(BASE_URL)
            except Exception:
                pass
        return
    threading.Thread(target=server.serve_forever, daemon=True,
                     name='codetime-http').start()
    logging.info('Дашборд: %s | БД: %s', BASE_URL, db_path())

    atexit.register(app.flush_now)

    # после обновления убираем оставшийся CodeTime.exe.old (через 15 секунд)
    threading.Timer(15.0, _cleanup_old_exe).start()

    # ярлык на рабочем столе (тихо, в фоне; путь самообновится при переносе)
    threading.Timer(3.0, create_desktop_shortcut).start()

    try:
        run_tray(app)  # блокирует до «Выход» из трея (или Ctrl+C)
    finally:
        request_exit(app)
        try:
            app.conn.close()
        except Exception:
            pass
        logging.info('CodeTime остановлен')


if __name__ == '__main__':
    main()
