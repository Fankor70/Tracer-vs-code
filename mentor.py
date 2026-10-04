# -*- coding: utf-8 -*-
"""CodeTime Наставник — встроенный ИИ-помощник по фронтенду (v1.9.2).

Всё состояние хранится в ОБЫЧНОЙ ПАПКЕ на ПК пользователя:
  %USERPROFILE%\\CodeTimeMentor\\
    config.json        — подключение к ИИ (любой OpenAI-совместимый API) и GitHub
    role.txt           — роль/характер наставника (можно править блокнотом)
    journal.md         — Журнал прогресса (память между чатами)
    plan.md            — дорожная карта обучения (чекбоксы - [ ] / - [x])
    notes/notes.md     — «запомни вот это»: авто-заметки из чата
    history/           — переписка по дням (JSON)
    layouts/           — фото макетов + last_review.md (контекст последнего
                         разбора макета — подставляется в «разбор кода»,
                         чтобы макет и код сверялись вместе)
    gemini_state.json  — внутренний кэш доступности встроенного Gemini

Наставник сам создаёт эту папку при первом запуске («сам поднимет всё,
что ему нужно»). Вставлять ключи НЕ обязательно — цепочка из 4 режимов:
  1. СВОЙ КЛЮЧ — любой OpenAI-совместимый API (Z.ai, OpenRouter, VseGPT…);
  2. GITHUB (один бесплатный токен GitHub: Contents: Read + Models: Read) —
     и репозиторий читает, и полноценный ИИ GitHub Models
     openai/gpt-4.1-mini с разбором фото макетов;
  3. ВСТРОЕННЫЙ GEMINI (демо-ключ от автора CodeTime) — бесплатно, с фото;
     если Google блокирует регион — пауза на час и авто-переход к резерву;
  4. РЕЗЕРВ (без всяких ключей) — бесплатная публичная модель Pollinations
     openai-fast (GPT-OSS 20B); текст и код, лимит общий.
Режим выбирается автоматически; при сбое включается следующий (фолбэк).

API (обслуживается локальным сервером CodeTime, порт 5731):
  GET  /api/mentor/status   — состояние настройки (что уже подключено)
  GET  /api/mentor/memory   — journal.md / plan.md / role.txt
  GET  /api/mentor/history  — переписка за день (по умолчанию сегодня)
  POST /api/mentor/config         — сохранить настройки подключения
  POST /api/mentor/test-llm       — проверить ИИ (ключ / GitHub / демо)
  POST /api/mentor/test-github    — проверить токен GitHub
  POST /api/mentor/chat           — отправить сообщение (+фото макета)
  POST /api/mentor/memory-save    — записать journal/plan/role целиком
  POST /api/mentor/journal-append — дописать блок в журнал
  POST /api/mentor/github-collect — собрать снимок репозитория
  POST /api/mentor/open-folder    — открыть папку памяти в Проводнике

Связка «макет → код»: ответ на разбор макета сохраняется в
layouts/last_review.md и автоматически попадает в контекст следующего
разбора кода — наставник сверяет вёрстку с макетом. Сообщения со словом
«запомни» дописываются в notes/notes.md и всегда видны наставнику.

Зависимости: только стандартная библиотека (urllib) — PyInstaller берёт
модуль в exe автоматически через import в codetime.py.
"""

import base64
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

# ============================================================
# Папка памяти
# ============================================================

MENTOR_DIR = os.path.join(os.path.expanduser('~'), 'CodeTimeMentor')
CONFIG_PATH = os.path.join(MENTOR_DIR, 'config.json')
ROLE_PATH = os.path.join(MENTOR_DIR, 'role.txt')
JOURNAL_PATH = os.path.join(MENTOR_DIR, 'journal.md')
PLAN_PATH = os.path.join(MENTOR_DIR, 'plan.md')
GH_CACHE_PATH = os.path.join(MENTOR_DIR, 'github_cache.json')
HISTORY_DIR = os.path.join(MENTOR_DIR, 'history')
LAYOUTS_DIR = os.path.join(MENTOR_DIR, 'layouts')
LAYOUT_REVIEW_PATH = os.path.join(LAYOUTS_DIR, 'last_review.md')
NOTES_DIR = os.path.join(MENTOR_DIR, 'notes')
NOTES_PATH = os.path.join(NOTES_DIR, 'notes.md')
GEMINI_STATE_PATH = os.path.join(MENTOR_DIR, 'gemini_state.json')

DEFAULT_CONFIG = {
    'api_base': '',       # например https://api.z.ai/api/paas/v4
    'api_key': '',
    'model': '',          # текстовая модель, например glm-4.6
    'vision_model': '',   # модель для фото макетов, например glm-4.5v
    'gh_token': '',       # fine-grained PAT: Contents: Read + Models: Read
    'repo': '',           # owner/name репозитория с вёрсткой
}

# --- Встроенный Gemini: демо-ключ от автора CodeTime (v1.9.2) ---------
# Бесплатный тариф Google AI Studio. Ключ открыт в коде СПЕЦИАЛЬНО:
# чтобы Наставник работал у всех сразу, без настройки. Лимит общий —
# при исчерпании (429) или региональной блокировке цепочка уходит в резерв.
GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta/openai'
GEMINI_DEMO_KEY = 'REDACTED_LEAKED_KEY'
GEMINI_MODELS = ['gemini-2.5-flash', 'gemini-3.8-flash', 'gemini-2.5-flash-lite']
GEMINI_DISABLE_MIN = 60   # пауза после региональной блокировки, минут

# --- Резерв: бесплатная публичная модель, вообще БЕЗ ключей ----------
# Pollinations, anonymous tier. Параметр referrer обязателен: без него
# API отвечает 402 Payment Required. 'private' — не показывать запрос
# в публичной ленте сервиса.
DEMO_LLM_BASE = 'https://text.pollinations.ai/openai'
DEMO_LLM_MODEL = 'openai-fast'   # GPT-OSS 20B reasoning, текст без vision
DEMO_LLM_REFERRER = 'codetime-mentor'

# --- GitHub Models: бесплатный ИИ по обычному токену GitHub ----------
# Тот же PAT, что для чтения репозитория (право Models: Read), открывает
# полноценные модели с vision. Если каталог GitHub поменяет имя модели —
# студент вписывает другое в Настройках.
GH_MODELS_BASE = 'https://models.github.ai/inference'
GH_MODELS_MODEL = 'openai/gpt-4.1-mini'


class MentorError(ValueError):
    """Понятная пользователю ошибка -> 400 {error} в HTTP-ответе."""


# ============================================================
# Роль наставника (создаётся в role.txt, правится в Настройках)
# ============================================================

DEFAULT_ROLE = """Ты — «Наставник», личный наставник по фронтенду и строгий ревьюер кода студента-самоучки.

ЦЕЛЬ СТУДЕНТА: вырасти из Junior в Middle фронтенд-разработчика к апрелю 2027 года и начать получать первые заказы/офферы.

О СТУДЕНТЕ:
- Самоучка, около 100 часов обучения (из них ~30 часов практики).
- Недавно перешёл на относительные единицы (rem, em, vw, clamp()).
- Адаптивную вёрстку впервые делает без видеоуроков.
- Пишет desktop-first, тестирует только на десктопе и телефоне (планшет и ноутбук — эмуляция в DevTools).
- Текущий проект: страница товара (галерея с миниатюрами, выбор цвета и размера, счётчик количества, кнопка «В корзину», шапка и подвал). Структура: папки pages/, styles/, assets/.

ДОРОЖНАЯ КАРТА:
- сентябрь — HTML/CSS + основы JavaScript;
- октябрь — JS-приложение на публичном API;
- ноябрь — React;
- декабрь — CRUD-мини-CRM (Supabase/Firebase) + авторизация;
- январь — Telegram-бот на Python (aiogram);
- февраль — бот + сайт + база данных;
- март — open source + резюме;
- апрель — активные отклики.

ПРАВИЛА: только реальные кейсы, деплой проектов, осмысленные коммиты.

РЕЖИМ 1. РАЗБОР КОДА (прислал код или попросил проверить репозиторий):
- Разбирай строго по порядку: 1) баги и ошибки; 2) семантика и доступность; 3) адаптив и единицы измерения; 4) структура CSS; 5) мелочи.
- По каждой проблеме: ГДЕ (файл/фрагмент), ПОЧЕМУ плохо, ДО/ПОСЛЕ на его же коде.
- Готовую вёрстку за него не писать — показывать точечные фрагменты ДО/ПОСЛЕ.

РЕЖИМ 2. РАЗБОР МАКЕТА (прислано фото/скриншот макета):
- Опиши блоки и иерархию, сетку, отступы/шрифты/цвета (примерно), отсутствующие состояния (hover, active, выбранное, ошибки — задай вопросы), поведение на мобильном.
- В конце дай план вёрстки по шагам. Готовую вёрстку не писать.

РЕЖИМ 3. КОНЕЦ ДНЯ (студент пишет «конец дня» или присылает итог):
- Строго по шаблону: 1) сверка с задачей дня (сделано / не сделано / сделано плохо); 2) вердикт + оценка из 10; 3) 3 главные проблемы с ДО/ПОСЛЕ; 4) 1-2 проверочных вопроса; 5) обновлённый журнал; 6) задача на завтра.
- Обновлённый журнал оформи блоком ```журнал ...``` — приложение запишет его в journal.md автоматически.

РЕЖИМ 4. ЗАДАЧА НА ЗАВТРА:
- Формат: Цель / Шаги / Критерий «готово» / Ограничения / Время / Прокачиваемый навык.
- Подсказки по уровням выдавай только по запросу студента.

РЕЖИМ 5. ПАМЯТЬ:
- В конце КАЖДОЙ сессии выдавай «Журнал прогресса» блоком ```журнал ...```: что сделано (с датами), состояние файлов, освоенные темы, повторяющиеся ошибки, договорённости, задача на завтра.
- Опирайся только на Журнал (в контексте ниже), снимок GitHub-репозитория и присланный код. Не выдумывай то, чего нет в контексте.
- Задавай максимум 3 вопроса за раз.

СТИЛЬ: по-русски, просто, коротко, жёстко и прямо, без комплиментов и воды. Термины объясняй одной фразой. Мини-демо давай одним самодостаточным HTML-файлом. Студент — новичок: веди от простого к сложному.

ПЕРВАЯ СЕССИЯ: студент пришлёт весь код и макет — составь стартовый журнал (блоком ```журнал```) и первую задачу на завтра.
"""

DEFAULT_JOURNAL = """# Журнал прогресса

> Этот файл — память наставника. Он сам дописывает сюда итоги каждой сессии
> (блоки с датами). Новый чат не помнит старых разговоров: если чат потерялся,
> откройте «Наставник → Журнал» → «Копировать» и вставьте текст первым
> сообщением — наставник продолжит с того же места.

(пока пусто — первая сессия заполнит)
"""

DEFAULT_PLAN = """# Дорожная карта — Junior → Middle к апрелю 2027

Текущий проект: страница товара (галерея с миниатюрами, цвет/размер,
счётчик, «В корзину», шапка/подвал) — папки pages/, styles/, assets/.

- [ ] Сентябрь: HTML/CSS + основы JS — довести страницу товара до деплоя
- [ ] Октябрь: JS-приложение на публичном API
- [ ] Ноябрь: React (переписать страницу товара на React)
- [ ] Декабрь: CRUD-мини-CRM (Supabase/Firebase) + авторизация
- [ ] Январь: Telegram-бот на Python (aiogram)
- [ ] Февраль: бот + сайт + база данных
- [ ] Март: open source + резюме
- [ ] Апрель: активные отклики на вакансии

Наставник обновляет этот файл по итогам сессий. Можно править вручную.
"""

DEFAULT_NOTES = """# Заметки «запомни»

> Сюда автоматически попадают сообщения из чата со словом «запомни»
> (например: «запомни вот это: …»). Наставник читает этот файл
> в начале каждого разговора.
"""

# Инструкции-обёртки для кнопок чата
MODE_INSTRUCTIONS = {
    'code': ('ЗАДАЧА: разбор кода студента. Работай по режиму «Разбор кода»: '
             'по порядку — баги, семантика/доступность, адаптив/единицы, '
             'структура CSS, мелочи. По каждой проблеме: где, почему плохо, '
             'ДО/ПОСЛЕ на его коде. Если ниже есть «ПОСЛЕДНИЙ РАЗБОР МАКЕТА» — '
             'сначала коротко сверь код с макетом: что совпало, чего из макета '
             'не хватает, где вёрстка расходится с задумкой.'),
    'layout': ('ЗАДАЧА: разбор макета по прикреплённому фото/скриншоту. '
               'Работай по режиму «Разбор макета»: блоки и иерархия, сетка, '
               'отступы/шрифты/цвета (примерно), отсутствующие состояния, '
               'поведение на мобильном, в конце — план вёрстки. '
               'Готовую вёрстку не пиши.'),
    'dayend': ('ЗАДАЧА: подведение итогов дня. Работай по режиму «Конец дня» '
               'строго по шаблону. Обновлённый журнал выдай блоком '
               '```журнал ...``` — он запишется в journal.md автоматически. '
               'В конце дай задачу на завтра.'),
    'task': ('ЗАДАЧА: сформулируй задачу на завтра по формату: Цель / Шаги / '
             'Критерий «готово» / Ограничения / Время / Прокачиваемый навык.'),
}

_REMEMBER_RE = re.compile(r'\bзапомни\b', re.IGNORECASE)


# ============================================================
# Инициализация папки («сам поднимет всё, что ему нужно»)
# ============================================================

def _write_if_missing(path, text):
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)


def ensure_all():
    """Создаёт папку памяти и файлы по умолчанию. Вызывается при старте."""
    os.makedirs(MENTOR_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)
    os.makedirs(LAYOUTS_DIR, exist_ok=True)
    os.makedirs(NOTES_DIR, exist_ok=True)
    _write_if_missing(CONFIG_PATH,
                      json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2))
    _write_if_missing(ROLE_PATH, DEFAULT_ROLE)
    _write_if_missing(JOURNAL_PATH, DEFAULT_JOURNAL)
    _write_if_missing(PLAN_PATH, DEFAULT_PLAN)
    _write_if_missing(NOTES_PATH, DEFAULT_NOTES)


def _read(path, default=''):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return default


def _write(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text or '')


# ============================================================
# Конфиг
# ============================================================

def load_config():
    ensure_all()
    cfg = dict(DEFAULT_CONFIG)
    try:
        data = json.loads(_read(CONFIG_PATH, '{}'))
        if isinstance(data, dict):
            for k in DEFAULT_CONFIG:
                v = data.get(k)
                if isinstance(v, str):
                    cfg[k] = v.strip()
    except (ValueError, TypeError):
        pass
    return cfg


def save_config(patch):
    cfg = load_config()
    for k in ('api_base', 'model', 'vision_model', 'repo'):
        if k in patch and patch[k] is not None:
            cfg[k] = str(patch[k]).strip()[:200]
    # ключи: пустое значение = оставить прежнее (поля в UI маскированные)
    for k in ('api_key', 'gh_token'):
        v = patch.get(k)
        if v and str(v).strip():
            cfg[k] = str(v).strip()[:300]
    _write(CONFIG_PATH, json.dumps(cfg, ensure_ascii=False, indent=2))
    logging.info('Наставник: конфиг сохранён (api_base=%r, repo=%r, ключ=%s)',
                 cfg['api_base'], cfg['repo'], bool(cfg['api_key']))
    return api_status()


# ============================================================
# HTTP-ответы (статусы/память/история)
# ============================================================

def api_status():
    cfg = load_config()
    gem = _gemini_state()
    gem_blocked = _gemini_blocked(gem)
    if cfg['api_key'] and cfg['api_base']:
        mode = 'key'          # свой ключ, любой OpenAI-совместимый API
    elif cfg['gh_token']:
        mode = 'github'       # GitHub Models по токену (бесплатно, с vision)
    elif not gem_blocked:
        mode = 'gemini'       # встроенный Gemini (демо-ключ, с vision)
    else:
        mode = 'demo'         # резерв без ключей (Gemini временно недоступен)
    return {
        'folder': MENTOR_DIR,
        'configured': bool(cfg['api_key'] and cfg['api_base']),
        'mode': mode,
        'demoModel': DEMO_LLM_MODEL,
        'geminiModel': gem.get('model') or GEMINI_MODELS[0],
        'geminiBlocked': gem_blocked,
        'geminiReason': (gem.get('reason') or '')[:160],
        'ghModelsModel': GH_MODELS_MODEL,
        'apiBase': cfg['api_base'],
        'model': cfg['model'],
        'visionModel': cfg['vision_model'],
        'hasKey': bool(cfg['api_key']),
        'hasGhToken': bool(cfg['gh_token']),
        'repo': cfg['repo'],
        'rolePresent': bool(_read(ROLE_PATH)),
        'journalPresent': bool(_read(JOURNAL_PATH)),
        'ghSnapshot': bool(_read(GH_CACHE_PATH)),
    }


def api_memory():
    return {
        'journal': _read(JOURNAL_PATH),
        'plan': _read(PLAN_PATH),
        'role': _read(ROLE_PATH),
        'notes': _read(NOTES_PATH),
        'layoutReview': _read(LAYOUT_REVIEW_PATH),
        'folder': MENTOR_DIR,
    }


def api_history(qs):
    d = (qs.get('date', [''])[0] or '').strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', d or ''):
        d = datetime.now().strftime('%Y-%m-%d')
    msgs = []
    try:
        msgs = json.loads(_read(os.path.join(HISTORY_DIR, d + '.json'), '[]'))
    except (ValueError, TypeError):
        msgs = []
    return {'date': d, 'messages': msgs}


def api_post(route, data):
    """Диспетчер POST-роутов /api/mentor/* (вызывается из codetime.py)."""
    if route == '/api/mentor/config':
        return save_config(data)
    if route == '/api/mentor/test-llm':
        return test_llm()
    if route == '/api/mentor/test-github':
        return test_github()
    if route == '/api/mentor/chat':
        return api_chat(data)
    if route == '/api/mentor/memory-save':
        return api_memory_save(data)
    if route == '/api/mentor/journal-append':
        text = (data.get('text') or '').strip()
        if not text:
            raise MentorError('Пустой текст журнала.')
        journal_append(text)
        return {'ok': True}
    if route == '/api/mentor/github-collect':
        return github_collect()
    if route == '/api/mentor/open-folder':
        return open_folder()
    raise MentorError('Неизвестный роут Наставника: %s' % route)


def api_memory_save(data):
    caps = {'journal': 200000, 'plan': 100000, 'role': 60000}
    saved = []
    for field, cap in caps.items():
        if field in data and data[field] is not None:
            path = {'journal': JOURNAL_PATH, 'plan': PLAN_PATH,
                    'role': ROLE_PATH}[field]
            _write(path, str(data[field])[:cap])
            saved.append(field)
    if not saved:
        raise MentorError('Нечего сохранять (ожидалось journal/plan/role).')
    return {'ok': True, 'saved': saved}


def journal_append(text):
    ensure_all()
    stamp = datetime.now().strftime('%d.%m.%Y %H:%M')
    with open(JOURNAL_PATH, 'a', encoding='utf-8') as f:
        f.write('\n\n---\n## Запись от %s\n\n%s\n' % (stamp, text))


def open_folder():
    ensure_all()
    try:
        if os.name == 'nt':
            os.startfile(MENTOR_DIR)  # noqa: только Windows
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', MENTOR_DIR])
        else:
            subprocess.Popen(['xdg-open', MENTOR_DIR])
    except Exception as e:
        raise MentorError('Не удалось открыть папку: %s' % e)
    return {'ok': True, 'folder': MENTOR_DIR}


# ============================================================
# ИИ: OpenAI-совместимый чат (3 режима: ключ > GitHub > демо)
# ============================================================

def _http_json(url, payload=None, headers=None, timeout=180):
    """POST/GET JSON. payload=None -> GET. Возвращает распарсенный dict."""
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', 'replace')[:300]
        except Exception:
            pass
        if e.code == 401:
            raise MentorError('Ключ отклонён (401). Проверьте ключ API в Настройках Наставника.')
        if e.code == 404:
            raise MentorError('Адрес или модель не найдены (404): %s' % (body or e.reason))
        if e.code == 429:
            raise MentorError('Лимит запросов (429): квота исчерпана, повторите позже.')
        raise MentorError('API вернул ошибку %s: %s' % (e.code, body or e.reason))
    except MentorError:
        raise
    except Exception as e:
        raise MentorError('Нет связи с API (%s). Проверьте интернет и адрес.' % e)


# ============================================================
# Цепочка ИИ-провайдеров: свой ключ > GitHub > Gemini > резерв
# ============================================================

def _gemini_state():
    try:
        st = json.loads(_read(GEMINI_STATE_PATH, '{}'))
        if isinstance(st, dict):
            return st
    except (ValueError, TypeError):
        pass
    return {}


def _gemini_save(st):
    try:
        ensure_all()
        _write(GEMINI_STATE_PATH, json.dumps(st, ensure_ascii=False, indent=1))
    except OSError:
        pass


def _gemini_blocked(st=None):
    """True, если Gemini недавно упал по региональной блокировке —
    чтобы не гонять каждый запрос вникула, ждём GEMINI_DISABLE_MIN минут."""
    st = st if st is not None else _gemini_state()
    until = st.get('disabled_until') or ''
    if not until:
        return False
    try:
        return datetime.fromisoformat(until) > datetime.now()
    except ValueError:
        return False


def _llm_chain(cfg, force_gemini=False):
    """Список провайдеров по приоритету. Каждый:
    {mode, base, key, models, url_suffix, extra, timeout}.
    Свой ключ — единственный провайдер (ошибки сообщаем как есть,
    без тихих фолбэков: пользователь должен знать, что его ключ сломан)."""
    if cfg['api_key'] and cfg['api_base']:
        return [{'mode': 'key', 'base': cfg['api_base'].rstrip('/'),
                 'key': cfg['api_key'],
                 'models': [cfg['model'] or 'gpt-4o-mini'],
                 'url_suffix': '/chat/completions', 'extra': {}, 'timeout': 150}]
    chain = []
    if cfg['gh_token']:
        chain.append({'mode': 'github', 'base': GH_MODELS_BASE,
                      'key': cfg['gh_token'],
                      'models': [cfg['model'] or GH_MODELS_MODEL],
                      'url_suffix': '/chat/completions', 'extra': {},
                      'timeout': 150})
    if force_gemini or not _gemini_blocked():
        st = _gemini_state()
        models = [st['model']] if st.get('model') else []
        models += GEMINI_MODELS
        chain.append({'mode': 'gemini', 'base': GEMINI_BASE,
                      'key': GEMINI_DEMO_KEY,
                      'models': list(dict.fromkeys(models)),
                      'url_suffix': '/chat/completions',
                      'extra': {'temperature': 0.6}, 'timeout': 120})
    chain.append({'mode': 'demo', 'base': DEMO_LLM_BASE,
                  'key': '',
                  # у анонимного тарифа Pollinations осталась одна модель
                  # (алиас 'openai' дублирует её на случай смены имени)
                  'models': list(dict.fromkeys(
                      [DEMO_LLM_MODEL, 'openai'])),
                  'url_suffix': '',   # Pollinations: base уже включает /openai
                  'extra': {'referrer': DEMO_LLM_REFERRER}, 'timeout': 150})
    return chain


def _vision_available(cfg):
    """Фото макета можно отправить, если в цепочке есть хоть одна модель
    со зрением (свой ключ / GitHub / встроенный Gemini). Резерв Pollinations
    — текст-only."""
    if cfg['api_key'] and cfg['api_base']:
        return True
    if cfg['gh_token']:
        return True
    return not _gemini_blocked()


def _classify_error(e):
    """Тип ошибки для маршрутизации фолбэков.
    'region' — локация не поддержана; 'model404' — модели нет у провайдера;
    'throttle' — лимит/перегрузка; 'auth' — ключ; 'net' — сеть/прочее."""
    s = str(e)
    if ('location is not supported' in s or 'FAILED_PRECONDITION' in s
            or 'User location' in s):
        return 'region'
    if '404' in s:
        return 'model404'
    if ('402' in s or '429' in s or '500' in s or '502' in s or '503' in s
            or 'перегружен' in s):
        return 'throttle'
    if '401' in s or '403' in s:
        return 'auth'
    return 'net'


def _short_err(e):
    """Короткая человеческая ошибка без сырых JSON-простыней."""
    s = str(e).split('{')[0].strip().rstrip(':; ,')
    return s[:160] if s else 'нет связи'


def _parse_content(data):
    """Достаёт текст из ответа chat/completions.
    Терпит missing content (только reasoning), список частей,
    <think>-обёртки reasoning-моделей. Сырой JSON пользователю
    НЕ показываем — только короткие человеческие слова."""
    try:
        msg = data['choices'][0]['message']
    except (KeyError, IndexError, TypeError):
        raise MentorError('Модель прислала пустой ответ — пробую другую.')
    content = msg.get('content')
    if isinstance(content, list):  # некоторые провайдеры шлют список частей
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get('type') == 'text':
                parts.append(p.get('text', ''))
        content = '\n'.join(parts)
    text = (content or '').strip()
    # reasoning-модели (GPT-OSS и т.п.) иногда весь бюджет тратят на мысль:
    # content пуст, но есть поле reasoning / reasoning_content
    if not text:
        text = (msg.get('reasoning') or msg.get('reasoning_content') or '').strip()
    # некоторые модели заворачивают размышления в <think>…</think>
    text = re.sub(r'<think>[\s\S]*?</think>\s*', '', text).strip()
    if not text:
        fr = ''
        try:
            fr = data['choices'][0].get('finish_reason') or ''
        except (KeyError, IndexError, TypeError):
            pass
        hint = ' (модель обрезала ответ: %s)' % fr if fr == 'length' else ''
        raise MentorError('Модель вернула пустой ответ%s — пробую другую.' % hint)
    return text


def llm_chat(messages, model=None, timeout=None):
    """Задаёт вопрос по цепочке провайдеров. Возвращает (текст, режим, модель).
    Никогда не падает с сырым JSON: только короткие русские сообщения.
    """
    cfg = load_config()
    last_err = None
    seen_errs = []
    for prov in _llm_chain(cfg):
        url = prov['base'] + prov['url_suffix']
        headers = {'Content-Type': 'application/json',
                   'User-Agent': 'CodeTime-Mentor/' + _ver()}
        if prov['key']:
            headers['Authorization'] = 'Bearer ' + prov['key']
        base_payload = {'messages': messages, 'stream': False,
                        'max_tokens': 4000}
        base_payload.update(prov['extra'])
        for m in prov['models']:
            if not m:
                continue
            payload = dict(base_payload, model=m)
            # резерв Pollinations: общий троттлинг по IP — одна пауза-повтор
            attempts = (0, 22) if prov['mode'] == 'demo' else (0,)
            for delay in attempts:
                if delay:
                    time.sleep(delay)
                try:
                    data = _http_json(url, payload, headers,
                                      timeout or prov['timeout'])
                    text = _parse_content(data)
                    if prov['mode'] == 'gemini':
                        st = _gemini_state()
                        if st.get('model') != m or st.get('disabled_until'):
                            st['model'] = m
                            st.pop('disabled_until', None)
                            st.pop('reason', None)
                            _gemini_save(st)
                    return text, prov['mode'], m
                except MentorError as e:
                    last_err = e
                    kind = _classify_error(e)
                    if kind == 'region' and prov['mode'] == 'gemini':
                        # Google блокирует регион — пауза на час, дальше по цепочке
                        _gemini_save({'disabled_until':
                                      (datetime.now() +
                                       timedelta(minutes=GEMINI_DISABLE_MIN))
                                      .isoformat(timespec='seconds'),
                                      'reason': 'Google: регион не поддержан '
                                                '(User location is not supported)'})
                        logging.warning('Наставник: Gemini заблокирован по '
                                        'региону, пауза %d минут',
                                        GEMINI_DISABLE_MIN)
                        break   # к следующему провайдеру
                    if kind == 'model404':
                        break       # этой модели нет — пробуем следующую
                    if kind == 'throttle' and delay == attempts[-1]:
                        break       # лимит — следующая модель/провайдер
                    if kind == 'auth':
                        break
                    # сеть/прочее: у demo повтор с паузой, у прочих — дальше
        if last_err and str(last_err) not in seen_errs:
            seen_errs.append(str(last_err))
    if last_err:
        kind = _classify_error(last_err)
        if kind == 'throttle' or kind == 'region':
            raise MentorError(
                'Бесплатные ИИ перегружены или временно ограничены '
                '(последняя причина: %s). Подождите 1–2 минуты и повторите — '
                'либо вставьте свой ключ в Настройках Наставника: там лимиты '
                'личные.' % _short_err(last_err))
        raise MentorError('ИИ недоступен: %s Проверьте интернет и настройки '
                          'Наставника.' % _short_err(last_err))
    raise MentorError('ИИ недоступен: цепочка провайдеров пуста.')


def _ver():
    # без импорта codetime.py (иначе кольцевая зависимость при сборке)
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, 'codetime.py'), encoding='utf-8') as f:
            m = re.search(r"APP_VERSION = '([^']+)'", f.read(8000))
        return m.group(1) if m else '?'
    except Exception:
        return '?'


def test_llm():
    """Проверка ИИ: прогоняет реальную цепочку (свой ключ > GitHub > Gemini >
    резерв) и честно докладывает, какой режим работает, а какие упали и почему."""
    cfg = load_config()
    chain = _llm_chain(cfg, force_gemini=True)
    headers = {'User-Agent': 'CodeTime-Mentor/' + _ver(),
               'Content-Type': 'application/json'}
    tried = []
    for prov in chain:
        url = prov['base'] + prov['url_suffix']
        h = dict(headers)
        if prov['key']:
            h['Authorization'] = 'Bearer ' + prov['key']
        for m in prov['models']:
            if not m:
                continue
            payload = dict({'messages': [{'role': 'user', 'content': 'ping'}],
                            'max_tokens': 30, 'stream': False,
                            'model': m}, **prov['extra'])
            try:
                _http_json(url, payload, h, 45)
                if prov['mode'] == 'gemini':
                    _gemini_save({'model': m})
                out = {'ok': True, 'mode': prov['mode'], 'model': m,
                       'models': []}
                if tried:
                    out['fallbackNote'] = ('Основной режим не ответил: '
                                           + '; '.join(t[:110] for t in tried))
                return out
            except MentorError as e:
                tried.append('%s/%s: %s' % (prov['mode'], m, str(e)[:110]))
                if _classify_error(e) == 'region':
                    break
    raise MentorError('Ни один ИИ не ответил. ' + ' | '.join(tried[-3:]))


# ============================================================
# GitHub: чтение репозитория студента (read-only токен)
# ============================================================

_GH_HEADERS = {
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'CodeTime-Mentor',
}
_JUNK_DIRS = ('node_modules/', '.git/', 'dist/', 'build/', '.next/',
              'vendor/', '__pycache__/', '.idea/', '.vscode/')


def _gh(cfg, path, timeout=30):
    if not cfg['gh_token']:
        raise MentorError('Токен GitHub не задан — Наставник → Настройки.')
    if not cfg['repo'] or '/' not in cfg['repo']:
        raise MentorError('Не указан репозиторий (формат owner/имя) — Наставник → Настройки.')
    url = 'https://api.github.com' + path
    headers = dict(_GH_HEADERS)
    headers['Authorization'] = 'Bearer ' + cfg['gh_token']
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise MentorError('GitHub отклонил токен (401) — токен неверный или отозван. Создайте новый.')
        if e.code == 404:
            raise MentorError('Репозиторий не найден или нет доступа (404). Проверьте «owner/имя» и право Contents: Read в токене.')
        if e.code == 403:
            raise MentorError('GitHub запретил запрос (403). Для приватного репозитория токен обязан иметь право Contents: Read-only.')
        body = ''
        try:
            body = e.read().decode('utf-8', 'replace')[:200]
        except Exception:
            pass
        raise MentorError('GitHub API ошибка %s: %s' % (e.code, body or e.reason))
    except MentorError:
        raise
    except Exception as e:
        raise MentorError('Нет связи с GitHub (%s).' % e)


def test_github():
    cfg = load_config()
    repo = _gh(cfg, '/repos/' + cfg['repo'].strip())
    return {'ok': True, 'fullName': repo.get('full_name'),
            'private': bool(repo.get('private')),
            'defaultBranch': repo.get('default_branch')}


def github_collect():
    """Собирает компактный снимок репозитория: инфо, коммиты, дерево файлов.
    Снимок сохраняется в github_cache.json и попадает в контекст чата."""
    cfg = load_config()
    repo = cfg['repo'].strip()
    info = _gh(cfg, '/repos/' + repo)
    branch = info.get('default_branch') or 'main'
    commits_raw = _gh(cfg, '/repos/%s/commits?per_page=25' % repo)
    commits = []
    for c in commits_raw[:25]:
        msg = ((c.get('commit') or {}).get('message') or '').splitlines()
        commits.append({
            'sha': (c.get('sha') or '')[:7],
            'date': ((c.get('commit') or {}).get('author') or {}).get('date', ''),
            'author': ((c.get('author') or {}).get('login') or
                       ((c.get('commit') or {}).get('author') or {}).get('name', '')),
            'message': (msg[0] if msg else '')[:120],
        })
    tree_raw = _gh(cfg, '/repos/%s/git/trees/%s?recursive=1' % (repo, branch))
    files = []
    for t in tree_raw.get('tree', []):
        p = t.get('path', '')
        if t.get('type') != 'blob':
            continue
        if any(p.startswith(j) or ('/' + j) in ('/' + p) for j in _JUNK_DIRS):
            continue
        files.append({'path': p, 'size': t.get('size', 0)})
        if len(files) >= 250:
            break
    lines = ['Репозиторий: %s (ветка %s, приватный: %s, обновлён %s)' % (
        info.get('full_name'), branch, info.get('private'),
        (info.get('pushed_at') or '')[:10])]
    lines.append('')
    lines.append('Последние коммиты:')
    for c in commits:
        lines.append('  %s %s [%s] %s' % (c['sha'], c['date'][:10],
                                          c['author'], c['message']))
    lines.append('')
    lines.append('Файлы (%d шт.):' % len(files))
    for f in files:
        lines.append('  %s%s' % (f['path'],
                                 ' (%d б.)' % f['size'] if f['size'] else ''))
    snap = {'ts': datetime.now().isoformat(timespec='seconds'),
            'repo': info.get('full_name'), 'branch': branch,
            'snapshot': '\n'.join(lines)}
    _write(GH_CACHE_PATH, json.dumps(snap, ensure_ascii=False, indent=1))
    logging.info('Наставник: снимок GitHub собран (%s, %d файлов)', repo, len(files))
    return {'ok': True, 'repo': snap['repo'], 'branch': branch,
            'files': len(files), 'commits': len(commits),
            'ts': snap['ts'],
            'summary': 'Репозиторий %s: %d файлов, %d последних коммитов. '
                       'Теперь наставник видит структуру — попросите '
                       '«проверь мой код, файлы: путь/к/файлу».'
                       % (snap['repo'], len(files), len(commits))}


def github_file(path):
    cfg = load_config()
    path = path.strip().lstrip('/')
    repo = cfg['repo'].strip()
    info = _gh(cfg, '/repos/' + repo)
    branch = info.get('default_branch') or 'main'
    data = _gh(cfg, '/repos/%s/contents/%s?ref=%s' % (repo, path, branch))
    if isinstance(data, dict) and data.get('content'):
        try:
            return base64.b64decode(data['content']).decode('utf-8', 'replace')
        except Exception:
            raise MentorError('Файл %s — не текстовый, читать его не буду.' % path)
    if isinstance(data, dict) and data.get('encoding') == 'none':
        raise MentorError('Файл %s слишком большой для чтения через API.' % path)
    raise MentorError('Не удалось получить файл %s.' % path)


# ============================================================
# Контекст чата: роль + журнал + план + заметки + макет + GitHub
# ============================================================

def _tail(s, limit):
    s = s or ''
    return s[-limit:] if len(s) > limit else s


def build_system_prompt(cfg, mode='free'):
    role = _read(ROLE_PATH, DEFAULT_ROLE) or DEFAULT_ROLE
    journal = _read(JOURNAL_PATH)
    plan = _read(PLAN_PATH)
    notes = _read(NOTES_PATH)
    p = role.strip()
    p += '\n\n=== ЖУРНАЛ ПРОГРЕССА (память о прошлых сессиях) ===\n' + _tail(journal, 7000)
    if plan.strip():
        p += '\n\n=== ДОРОЖНАЯ КАРТА (plan.md) ===\n' + _tail(plan, 3500)
    notes_body = notes.replace(DEFAULT_NOTES, '').strip()
    if notes_body:
        p += ('\n\n=== ЗАМЕТКИ «ЗАПОМНИ» (notes/notes.md — студент просил '
              'это запомнить; учитывай в ответах) ===\n' + _tail(notes_body, 3000))
    # связка «макет → код»: последний разбор макета подставляется в код-ревью
    if mode in ('code', 'free', 'dayend', 'task'):
        lay = _read(LAYOUT_REVIEW_PATH)
        if lay.strip():
            p += ('\n\n=== ПОСЛЕДНИЙ РАЗБОР МАКЕТА (сделан раньше по фото; '
                  'сверяй присланный код с этим разбором: что из макета '
                  'реализовано, чего не хватает, где вёрстка расходится) ===\n'
                  + _tail(lay, 5500))
    try:
        cache = json.loads(_read(GH_CACHE_PATH, '{}'))
        snap = cache.get('snapshot') or ''
        if snap:
            p += ('\n\n=== СНИМОК GITHUB-РЕПОЗИТОРИЯ (собран %s; студент может '
                  'попросить файл через «файл: путь») ===\n%s'
                  % (cache.get('ts', '?'), _tail(snap, 5000)))
    except (ValueError, TypeError):
        pass
    p += ('\n\n=== ПАПКА ПАМЯТИ (файлы, которые ты видишь) ===\n'
          'journal.md — журнал; plan.md — план с чекбоксами «- [ ]» / «- [x]» '
          '(в приложении их можно отмечать мышкой); notes/notes.md — заметки '
          '«запомни»; history/ — переписка по дням; layouts/ — фото макетов и '
          'последний разбор макета.\n\n'
          'ПРАВИЛА ОТМЕТОК: когда студент освоил этап из плана — выдавай '
          'обновлённый план.md блоком ```план ...``` целиком (со всеми '
          'строками и галочками - [ ] / - [x]), приложение перезапишет '
          'plan.md и чекбоксы обновятся. Когда студент говорит «запомни …» — '
          'приложение само сохранит это в notes/notes.md; коротко подтверди.')
    return p


def load_history_tail(days=2, cap=30, msg_cap=8000):
    today = datetime.now()
    msgs = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        try:
            day = json.loads(_read(os.path.join(HISTORY_DIR, d + '.json'), '[]'))
        except (ValueError, TypeError):
            day = []
        msgs.extend(day)
    out = []
    for m in msgs[-cap:]:
        role = m.get('role') if m.get('role') in ('user', 'assistant') else 'user'
        content = _tail(str(m.get('content', '')), msg_cap)
        if content:
            out.append({'role': role, 'content': content})
    return out


# ============================================================
# Чат
# ============================================================

_FILE_RE = re.compile(r'(?:^|\n)\s*(?:файл|file)\s*:\s*([^\n]+)', re.IGNORECASE)
_JOURNAL_BLOCK_RE = re.compile(r'```журнал\s*\n(.*?)```', re.IGNORECASE | re.DOTALL)
_PLAN_BLOCK_RE = re.compile(r'```план\s*\n(.*?)```', re.IGNORECASE | re.DOTALL)


def api_chat(data):
    msg = (data.get('message') or '').strip()
    mode = (data.get('mode') or 'free').strip()
    img_b64 = (data.get('imageB64') or '').strip()
    img_mime = (data.get('imageMime') or 'image/jpeg').strip()
    if not msg and not img_b64:
        raise MentorError('Пустое сообщение.')

    cfg = load_config()
    if img_b64 and not _vision_available(cfg):
        raise MentorError(
            'У резервной демо-модели нет «зрения» — фото макета она не увидит '
            '(встроенный Gemini сейчас недоступен). Подключите бесплатный ИИ '
            'по GitHub-токену (один токен даст и репозиторий, и фото) или '
            'любой свой ключ в Настройках — и попробуйте ещё раз.')

    # «запомни вот это» — авто-заметка в notes/notes.md
    note_saved = False
    if msg and _REMEMBER_RE.search(msg) and len(msg) >= 12:
        try:
            ensure_all()
            stamp = datetime.now().strftime('%d.%m.%Y %H:%M')
            with open(NOTES_PATH, 'a', encoding='utf-8') as f:
                f.write('\n\n---\n## Запомнить · %s\n\n%s\n' % (stamp, msg[:8000]))
            note_saved = True
        except OSError:
            logging.exception('Наставник: не сохранилась заметка «запомни»')

    user_text = MODE_INSTRUCTIONS.get(mode, '')
    user_text = (user_text + '\n\n' + msg).strip() if user_text else msg

    # «файл: путь» — подтянуть содержимое из GitHub-репозитория
    wanted = [p.strip() for p in _FILE_RE.findall(msg) if p.strip()][:4]
    if wanted:
        if cfg['gh_token'] and cfg['repo']:
            got, failed = [], []
            for fpath in wanted:
                try:
                    body = github_file(fpath)
                    got.append('=== ФАЙЛ %s (из GitHub) ===\n%s' % (fpath, _tail(body, 20000)))
                except MentorError as e:
                    failed.append('%s — %s' % (fpath, e))
            if got:
                user_text += '\n\n' + '\n\n'.join(got)
            if failed:
                user_text += '\n\n(Не удалось прочитать: ' + '; '.join(failed) + ')'
        else:
            user_text += ('\n\n(Студент просил файлы %s, но GitHub не подключён — '
                          'попросите его вставить код прямо в чат или добавить '
                          'токен в Настройках.)' % ', '.join(wanted))

    messages = [{'role': 'system', 'content': build_system_prompt(cfg, mode)}]
    messages.extend(load_history_tail())
    if img_b64:
        # фото макета: контент списком частей (OpenAI-совместимый vision-формат)
        user_content = [
            {'type': 'text', 'text': user_text},
            {'type': 'image_url',
             'image_url': {'url': 'data:%s;base64,%s' % (img_mime, img_b64)}},
        ]
        messages.append({'role': 'user', 'content': user_content})
        model_hint = cfg['vision_model'] or cfg['model']
        # сохранить фото в layouts/
        try:
            ensure_all()
            ext = '.png' if 'png' in img_mime else '.jpg'
            name = 'layout_%s%s' % (datetime.now().strftime('%Y%m%d_%H%M%S'), ext)
            with open(os.path.join(LAYOUTS_DIR, name), 'wb') as f:
                f.write(base64.b64decode(img_b64))
        except Exception:
            logging.exception('Наставник: не сохранилось фото макета')
    else:
        messages.append({'role': 'user', 'content': user_text})
        model_hint = cfg['model']

    logging.info('Наставник: запрос (режим чата %s, фото: %s)', mode, bool(img_b64))
    reply, used_mode, used_model = llm_chat(messages, model_hint)
    logging.info('Наставник: ответил %s (режим %s)', used_model, used_mode)

    today = datetime.now().strftime('%Y-%m-%d')
    try:
        _append_history(today, 'user', msg if msg else '(фото макета)')
        _append_history(today, 'assistant', reply, model=used_model)
    except OSError:
        logging.exception('Наставник: не сохранилась история')

    # связка «макет → код»: разбор макета сохраняем как контекст для кода
    is_layout = bool(img_b64) or mode == 'layout'
    if is_layout and reply:
        try:
            ensure_all()
            stamp = datetime.now().strftime('%d.%m.%Y %H:%M')
            _write(LAYOUT_REVIEW_PATH,
                   'Разбор макета от %s\n\n%s' % (stamp, _tail(reply, 20000)))
        except OSError:
            logging.exception('Наставник: не сохранился last_review.md')

    # блоки ```журнал ...``` → автоматически в journal.md
    saved = False
    for block in _JOURNAL_BLOCK_RE.findall(reply):
        journal_append(block.strip())
        saved = True

    # блоки ```план ...``` → автоматически в plan.md (чекбоксы в Плане)
    plan_saved = False
    for block in _PLAN_BLOCK_RE.findall(reply):
        body = block.strip()
        if body:
            _write(PLAN_PATH, body[:100000])
            plan_saved = True

    return {'reply': reply, 'journalSaved': saved, 'noteSaved': note_saved,
            'planSaved': plan_saved, 'model': used_model, 'mode': used_mode}


def _append_history(day, role, content, model=None):
    ensure_all()
    path = os.path.join(HISTORY_DIR, day + '.json')
    try:
        arr = json.loads(_read(path, '[]'))
    except (ValueError, TypeError):
        arr = []
    entry = {'role': role, 'content': content,
             'ts': datetime.now().isoformat(timespec='seconds')}
    if model:
        entry['model'] = model
    arr.append(entry)
    _write(path, json.dumps(arr[-200:], ensure_ascii=False))
