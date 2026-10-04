# -*- coding: utf-8 -*-
"""CodeTime Наставник — встроенная ИИ-команда по фронтенду (v2.1.0).

Всё состояние хранится в ОБЫЧНОЙ ПАПКЕ на ПК пользователя:
  %USERPROFILE%\\CodeTimeMentor\\
    config.json        — подключение к ИИ (OpenRouter / свой API / GitHub)
    role.txt           — роль/характер наставника (можно править блокнотом)
    journal.md         — Журнал прогресса (память между чатами)
    plan.md            — план обучения (чекбоксы - [ ] / - [x])
    notes/notes.md     — «запомни вот это»: авто-заметки из чата
    chats/             — чаты: index.json + <id>.json (сообщения)
    runs/              — протоколы запусков команды (index.json + .md)
    layouts/           — фото макетов + last_review.md
    github_tree.json   — кэш дерева файлов репозитория (10 минут)
    gemini_state.json  — внутренний кэш доступности встроенного Gemini

ИИ-КОМАНДА (как в эталоне): агенты работают конвейером и передают
результат друг другу. Типы задач:
  code   → Кодер-ревьюер → Контролёр → Наставник
  layout → Зрение (фото) → Наставник
  day    → Планировщик   → Наставник
  repo   → Гит-аналитик  → Наставник
  free   → Наставник (один агент)
Провайдеры (первый доступный отвечает, при сбое — следующий):
  1. OPENROUTER — один ключ, команда на бесплатных моделях
     (по умолчанию у каждой роли своя модель, см. FREE_MODEL_CATALOG);
  2. СВОЙ КЛЮЧ — любой OpenAI-совместимый API (Z.ai, Gemini, VseGPT…);
  3. GITHUB MODELS — бесплатный ИИ по обычному токену GitHub (с фото);
  4. ВСТРОЕННЫЙ GEMINI (демо-ключ) — если Google не заблокировал;
  5. РЕЗЕРВ (без всяких ключей) — Pollinations openai-fast, текст и код.
Без ключей команда тоже работает: каждого агента играет резервная модель
(промпты и конвейер те же, лимит общий).

API (обслуживается локальным сервером CodeTime, порт 5731):
  GET  /api/mentor/status        — состояние настройки
  GET  /api/mentor/memory        — journal.md / plan.md / role.txt / notes
  GET  /api/mentor/history       — legacy-переписка за день
  GET  /api/mentor/chats         — список чатов (?id= — сообщения чата)
  GET  /api/mentor/journal       — журнал {content, updatedAt}
  GET  /api/mentor/plan          — план с чекбоксами {items}
  GET  /api/or/settings          — ключ OpenRouter + модели ролей + каталог
  GET  /api/github/tree          — дерево файлов репозитория (?path=)
  GET  /api/team/history         — история запусков команды
  POST /api/mentor/config        — сохранить настройки подключения
  POST /api/mentor/chats         — создать чат / chats/delete — удалить
  POST /api/mentor/send          — отправить сообщение в чат (+фото/+файлы)
  POST /api/mentor/upload        — сохранить фото макета (dataURL)
  POST /api/mentor/journal       — записать журнал целиком
  POST /api/mentor/journal-ai    — наставник обновляет журнал по переписке
  POST /api/mentor/plan          — отметить пункт плана {id, done}
  POST /api/mentor/plan-ai       — наставник пересобирает план
  POST /api/or/settings          — сохранить ключ OpenRouter/модели ролей
  POST /api/or/test              — проверить агента (роль)
  POST /api/github/settings      — сохранить/удалить GitHub-доступ
  POST /api/github/files         — содержимое файлов репозитория
  POST /api/team/run             — ЗАПУСК КОМАНДЫ {taskType, input, imagePath}
  POST /api/mentor/test-llm      — проверить цепочку ИИ
  POST /api/mentor/test-github   — проверить токен GitHub
  POST /api/mentor/memory-save   — записать journal/plan/role целиком
  POST /api/mentor/journal-append— дописать блок в журнал
  POST /api/mentor/chat          — legacy-чат (один запрос без команды)
  POST /api/mentor/github-collect— собрать снимок репозитория
  POST /api/mentor/open-folder   — открыть папку памяти в Проводнике

Связка «макет → код»: ответ на разбор макета сохраняется в
layouts/last_review.md и автоматически попадает в контекст разбора кода.
Сообщения со словом «запомни» дописываются в notes/notes.md и всегда
видны команде. В чате наставник может запросить файл строкой ровно вида
[НУЖЕН ФАЙЛ: путь/к/файлу] — файл подтянется из GitHub автоматически.

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
GH_TREE_CACHE_PATH = os.path.join(MENTOR_DIR, 'github_tree.json')
HISTORY_DIR = os.path.join(MENTOR_DIR, 'history')
LAYOUTS_DIR = os.path.join(MENTOR_DIR, 'layouts')
LAYOUT_REVIEW_PATH = os.path.join(LAYOUTS_DIR, 'last_review.md')
NOTES_DIR = os.path.join(MENTOR_DIR, 'notes')
NOTES_PATH = os.path.join(NOTES_DIR, 'notes.md')
GEMINI_STATE_PATH = os.path.join(MENTOR_DIR, 'gemini_state.json')
CHATS_DIR = os.path.join(MENTOR_DIR, 'chats')
CHATS_INDEX_PATH = os.path.join(CHATS_DIR, 'index.json')
RUNS_DIR = os.path.join(MENTOR_DIR, 'runs')
RUNS_INDEX_PATH = os.path.join(RUNS_DIR, 'index.json')

DEFAULT_CONFIG = {
    'api_base': '',       # например https://api.z.ai/api/paas/v4
    'api_key': '',
    'model': '',          # текстовая модель, например glm-4.6
    'vision_model': '',   # модель для фото макетов, например glm-4.5v
    'gh_token': '',       # fine-grained PAT: Contents: Read + Models: Read
    'repo': '',           # owner/name репозитория с вёрсткой
    'or_key': '',         # OpenRouter — один ключ на всю команду
}

# --- Встроенный Gemini: демо-ключ от автора CodeTime (v1.9.2) ---------
# Бесплатный тариф Google AI Studio. Ключ открыт в коде СПЕЦИАЛЬНО:
# чтобы Наставник работал у всех сразу, без настройки. Лимит общий —
# при исчерпании (429) или региональной блокировке цепочка уходит в резерв.
GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta/openai'
GEMINI_DEMO_KEY = 'REDACTED_LEAKED_KEY'
# Порядок моделей: та, что реально отвечает у большинства, — первая.
# Если Google сменит каталог — студент вписывает свою в Настройках.
GEMINI_MODELS = ['gemini-3.8-flash', 'gemini-2.5-flash',
                 'gemini-2.5-flash-lite', 'gemini-2.0-flash']
GEMINI_DISABLE_MIN = 60   # пауза после региональной блокировки/блокировки ключа, минут
GEMINI_GET_KEY_URL = 'aistudio.google.com/apikey'

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
    os.makedirs(CHATS_DIR, exist_ok=True)
    os.makedirs(RUNS_DIR, exist_ok=True)
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
            for k, v in data.items():
                # известные ключи + динамические or_model_<роль>
                if isinstance(v, str) and (k in DEFAULT_CONFIG
                                           or k.startswith('or_model_')):
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
    for k in ('api_key', 'gh_token', 'or_key'):
        v = patch.get(k)
        if v and str(v).strip():
            cfg[k] = str(v).strip()[:300]
    if patch.get('clear_or_key'):
        cfg['or_key'] = ''
    _write(CONFIG_PATH, json.dumps(cfg, ensure_ascii=False, indent=2))
    logging.info('Наставник: конфиг сохранён (api_base=%r, repo=%r, ключ=%s, OR=%s)',
                 cfg['api_base'], cfg['repo'], bool(cfg['api_key']),
                 bool(cfg['or_key']))
    return api_status()


# ============================================================
# HTTP-ответы (статусы/память/история)
# ============================================================

def api_status():
    cfg = load_config()
    gem = _gemini_state()
    gem_blocked = _gemini_blocked(gem)
    if cfg['or_key']:
        mode = 'openrouter'   # OpenRouter: команда на бесплатных моделях
    elif cfg['api_key'] and cfg['api_base']:
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
        'orKeySet': bool(cfg['or_key']),
        'orKeyMasked': _mask(cfg['or_key']),
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


def _mask(key):
    if not key:
        return ''
    if len(key) <= 12:
        return (key[:3] + '…') if len(key) > 4 else '…'
    return key[:7] + '…' + key[-4:]


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
    """Диспетчер POST-роутов /api/mentor/*, /api/or/*, /api/github/*,
    /api/team/* (вызывается из codetime.py)."""
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
    # ---- v2.1: чаты / команда / OpenRouter / GitHub-файлы ----
    if route == '/api/mentor/chats':
        if data.get('delete'):
            return chat_delete(str(data['delete']))
        return chat_create(data)
    if route == '/api/mentor/send':
        return api_send(data)
    if route == '/api/mentor/upload':
        return api_upload(data)
    if route == '/api/mentor/journal':
        return api_journal_put(data)
    if route == '/api/mentor/journal-ai':
        return api_journal_ai(data)
    if route == '/api/mentor/plan':
        return api_plan_patch(data)
    if route == '/api/mentor/plan-ai':
        return api_plan_ai()
    if route == '/api/or/settings':
        return or_settings_put(data)
    if route == '/api/or/test':
        return or_test(data)
    if route == '/api/github/settings':
        return github_settings_put(data)
    if route == '/api/github/files':
        return api_github_files(data)
    if route == '/api/team/run':
        return team_run(data)
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
    Свой ключ — первый; если он упал НЕ по причине неверного ключа
    (сеть, лимит, нет модели), цепочка честно уходит дальше по фолбэкам,
    чтобы Наставник продолжал отвечать. Автор отвечает в подписи модели."""
    chain = []
    if cfg['api_key'] and cfg['api_base']:
        chain.append({'mode': 'key', 'base': cfg['api_base'].rstrip('/'),
                      'key': cfg['api_key'],
                      'models': [cfg['model'] or 'gpt-4o-mini'],
                      'url_suffix': '/chat/completions', 'extra': {}, 'timeout': 150})
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
                  # анонимный тариф Pollinations: одна модель (алиас 'openai'
                  # теперь отдаёт 402 — не тратим на него время)
                  'models': [DEMO_LLM_MODEL],
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
    'region' — локация не поддержана; 'leak' — ключ помечен Google как утёкший;
    'model404' — модели нет у провайдера; 'throttle' — лимит/перегрузка;
    'auth' — ключ; 'net' — сеть/прочее."""
    s = str(e)
    if ('location is not supported' in s or 'FAILED_PRECONDITION' in s
            or 'User location' in s):
        return 'region'
    if 'reported as leaked' in s:
        return 'leak'
    if '404' in s:
        return 'model404'
    if ('402' in s or '429' in s or '500' in s or '502' in s or '503' in s
            or 'перегружен' in s or 'no space left' in s):
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


def _demo_messages(messages):
    """Сообщения для резерва (Pollinations, анонимный тариф): роль system
    там отдаёт 402 — склеиваем системный промпт в первое user-сообщение.
    Длинные промпты тоже режем: анонимный тариф ограничивает объём."""
    plain = [{'role': m.get('role') or 'user',
              'content': m['content'] if isinstance(m.get('content'), str)
              else ' '.join(p.get('text', '') for p in m['content']
                            if isinstance(p, dict) and p.get('type') == 'text')}
             for m in messages]
    sys_txt = '\n\n'.join(m['content'] for m in plain if m['role'] == 'system')
    if len(sys_txt) > 1600:
        sys_txt = sys_txt[:1600].rsplit('\n', 1)[0] + \
            '\n…(контекст сокращён, чтобы уложиться в бесплатный лимит)'
    rest = [m for m in plain if m['role'] != 'system']
    if sys_txt and rest:
        rest[0] = dict(rest[0],
                       content='[Инструкция]\n' + sys_txt +
                               '\n\n[Сообщение]\n' + rest[0]['content'])
    return rest


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
        base_payload = {'messages': (messages if prov['mode'] != 'demo'
                                     else _demo_messages(messages)),
                        'stream': False, 'max_tokens': 4000}
        base_payload.update(prov['extra'])
        for m in prov['models']:
            if not m:
                continue
            payload = dict(base_payload, model=m)
            # резерв Pollinations: общий троттлинг по IP — серия пауз-повторов
            attempts = (0, 12, 30) if prov['mode'] == 'demo' else (0,)
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
                    if kind == 'leak':
                        # демо-ключ попал в открытый доступ — Google его отключил.
                        # Ставим паузу, чтобы каждый запрос не бился о 403.
                        if prov['mode'] == 'gemini':
                            _gemini_save({'disabled_until':
                                          (datetime.now() +
                                           timedelta(minutes=GEMINI_DISABLE_MIN))
                                          .isoformat(timespec='seconds'),
                                          'reason': 'Демо-ключ заблокирован Google '
                                                    '(попал в открытый доступ). '
                                                    'Получите свой бесплатный '
                                                    'ключ: ' + GEMINI_GET_KEY_URL})
                            logging.warning('Наставник: демо-ключ Gemini '
                                            'заблокирован (leak), пауза %d минут',
                                            GEMINI_DISABLE_MIN)
                        if prov['mode'] == 'key':
                            raise   # свой ключ утёк/отключён — говорим как есть
                        break       # дальше по цепочке
                    if kind == 'model404':
                        break       # этой модели нет — пробуем следующую
                    if kind == 'auth':
                        # неверный ключ: свой — кричим сразу, остальные — дальше
                        if prov['mode'] == 'key':
                            raise
                        break
                    if kind == 'throttle' and delay == attempts[-1]:
                        break       # лимит — следующая модель/провайдер
                    # сеть/прочее: у demo повтор с паузой, у прочих — дальше
        if last_err and str(last_err) not in seen_errs:
            seen_errs.append(str(last_err))
    if last_err:
        kind = _classify_error(last_err)
        if kind == 'leak':
            raise MentorError(
                'Встроенный демо-ключ Gemini заблокирован Google (он попал в '
                'открытый доступ). Это лечится своим бесплатным ключом за '
                '2 минуты: ' + GEMINI_GET_KEY_URL + ' → «Create API key» → '
                'вставить в Настройках Наставника. До этого работает резерв '
                'без фото.')
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
    резерв) и честно докладывает, какой режим работает, а какие упали и почему.
    Для своего ключа попутно подтягивает список доступных моделей (/models)."""
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
                # свой ключ: покажем, какие модели вообще доступны —
                # чтобы студент выбрал лучшую вместо случайной 404-й
                if prov['mode'] == 'key':
                    try:
                        listing = _http_json(prov['base'] + '/models',
                                             headers=h, timeout=20)
                        ids = [str(x.get('id') or '')
                               for x in (listing.get('data') or [])
                               if isinstance(x, dict) and x.get('id')]
                        out['models'] = ids[:15]
                    except (MentorError, ValueError, TypeError, AttributeError):
                        pass
                if tried:
                    out['fallbackNote'] = ('Основной режим не ответил: '
                                           + '; '.join(t[:110] for t in tried))
                return out
            except MentorError as e:
                tried.append('%s/%s: %s' % (prov['mode'], m, str(e)[:110]))
                kind = _classify_error(e)
                if kind == 'region':
                    break
                if kind == 'leak':
                    if prov['mode'] == 'gemini':
                        _gemini_save({'disabled_until':
                                      (datetime.now() +
                                       timedelta(minutes=GEMINI_DISABLE_MIN))
                                      .isoformat(timespec='seconds'),
                                      'reason': 'Демо-ключ заблокирован Google '
                                                '(попал в открытый доступ). '
                                                'Получите свой бесплатный '
                                                'ключ: ' + GEMINI_GET_KEY_URL})
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
        _append_history(today, 'assistant', reply,
                        model=used_model, mode=used_mode)
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


def _append_history(day, role, content, model=None, mode=None):
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
    if mode:
        entry['mode'] = mode
    arr.append(entry)
    _write(path, json.dumps(arr[-200:], ensure_ascii=False))


# ============================================================
# v2.1: ИИ-КОМАНДА — каталог бесплатных моделей OpenRouter
# ============================================================

# Собран из https://openrouter.ai/api/v1/models (фильтр price=0).
# Лимиты бесплатных моделей: 20 запросов/мин, 50 запросов/сутки
# (1000/сутки после разового пополнения $10).
FREE_MODEL_CATALOG = [
    {'id': 'nvidia/nemotron-3-ultra-550b-a55b:free', 'title': 'Nemotron 3 Ultra',
     'vendor': 'NVIDIA', 'ctx': '1M', 'vision': False,
     'note': 'Флагман-«мозг»: рассуждения, orchestration, главные вердикты.'},
    {'id': 'nvidia/nemotron-3-super-120b-a12b:free', 'title': 'Nemotron 3 Super',
     'vendor': 'NVIDIA', 'ctx': '262K', 'vision': False,
     'note': 'Сильный универсал для мульти-агентных связок, свежий взгляд.'},
    {'id': 'nvidia/nemotron-3.5-lightning:free', 'title': 'Nemotron 3.5 Lightning',
     'vendor': 'NVIDIA', 'ctx': '1M', 'vision': False,
     'note': 'Быстрый и лёгкий: жмёт большие выжимки (коммиты, деревья файлов).'},
    {'id': 'poolside/laguna-s-2.1:free', 'title': 'Laguna S 2.1',
     'vendor': 'Poolside', 'ctx': '262K', 'vision': False,
     'note': 'Заточен под код (Terminal-Bench 70.2%): первый тех-проход по коду.'},
    {'id': 'cohere/north-mini-code:free', 'title': 'North Mini Code',
     'vendor': 'Cohere', 'ctx': '256K', 'vision': False,
     'note': 'Лёгкая агентная код-модель, запасной ревьюер.'},
    {'id': 'qwen/qwen3.8-27b:free', 'title': 'Qwen3.8 27B',
     'vendor': 'Qwen', 'ctx': '262K', 'vision': True,
     'note': 'Зрение + код: описание макетов по фото, multimodal.'},
    {'id': 'google/gemma-4-31b-it:free', 'title': 'Gemma 4 31B',
     'vendor': 'Google', 'ctx': '262K', 'vision': True,
     'note': 'Multimodal-универсал с thinking-режимом, запасное зрение.'},
    {'id': 'thinkingmachines/inkling-small:free', 'title': 'Inkling Small',
     'vendor': 'Thinking Machines', 'ctx': '1M', 'vision': True,
     'note': 'Компактный рассуждающий MoE: планировщик, конец дня.'},
    {'id': 'thinkingmachines/inkling:free', 'title': 'Inkling',
     'vendor': 'Thinking Machines', 'ctx': '1M', 'vision': True,
     'note': 'Старший брат Inkling: 975B MoE, запасной «мозг».'},
    {'id': 'dots-studio/dots-3-note-preview:free', 'title': 'Dots3 Note',
     'vendor': 'Dots Studio', 'ctx': '512K', 'vision': True,
     'note': '280B MoE (16B активных), зрение + огромный контекст.'},
    {'id': 'google/gemma-4-26b-a4b-it:free', 'title': 'Gemma 4 26B A4B',
     'vendor': 'Google', 'ctx': '262K', 'vision': True,
     'note': 'Очень быстрый multimodal (3.8B активных), мелкие задачи.'},
    {'id': 'openrouter/free', 'title': 'Free Router',
     'vendor': 'OpenRouter', 'ctx': '200K', 'vision': True,
     'note': 'Авто-роутер: сам выбирает любую свободную бесплатную модель.'},
]

OR_BASE = 'https://openrouter.ai/api/v1'
OR_LIMITS_NOTE = ('Лимиты бесплатных моделей OpenRouter: 20 запросов/мин и 50 '
                  'запросов/сутки (или 1000/сутки, если на аккаунте есть $10 '
                  'кредитов). Один запуск команды — 1–3 запроса.')

AGENT_ROLES = ('mentor', 'coder', 'controller', 'vision', 'planner', 'gitanalyst')

ROLE_LABEL = {
    'mentor': 'Наставник', 'coder': 'Кодер-ревьюер', 'controller': 'Контролёр',
    'vision': 'Зрение', 'planner': 'Планировщик', 'gitanalyst': 'Гит-аналитик',
}

ROLE_DESC = {
    'mentor': 'Главный мозг команды: вердикты, разбор по правилам роли, задача на завтра.',
    'coder': 'Первый тех-проход по коду: баги, семантика, адаптив, CSS.',
    'controller': 'Свежий взгляд: проверяет ревью коллеги, добавляет пропущенное.',
    'vision': 'Смотрит на фото макета и описывает структуру для наставника.',
    'planner': 'Проверка конца дня: сверка с задачей, вердикт, оценка из 10.',
    'gitanalyst': 'Читает репозиторий: коммиты, динамика, чем ты занят.',
}

ROLE_DEFAULT_MODEL = {
    'mentor': 'nvidia/nemotron-3-ultra-550b-a55b:free',
    'coder': 'poolside/laguna-s-2.1:free',
    'controller': 'nvidia/nemotron-3-super-120b-a12b:free',
    'vision': 'qwen/qwen3.8-27b:free',
    'planner': 'thinkingmachines/inkling-small:free',
    'gitanalyst': 'nvidia/nemotron-3.5-lightning:free',
}

# модели со зрением: если у роли модель без vision, а нужно фото —
# пробуем их по порядку (внутри провайдера OpenRouter)
OR_VISION_FALLBACKS = ['qwen/qwen3.8-27b:free',
                       'dots-studio/dots-3-note-preview:free',
                       'google/gemma-4-31b-it:free',
                       'thinkingmachines/inkling-small:free',
                       'openrouter/free']


def _or_role_model(cfg, role):
    return cfg.get('or_model_' + role) or ROLE_DEFAULT_MODEL.get(role) \
        or ROLE_DEFAULT_MODEL['mentor']


def _catalog_vision(model_id):
    for m in FREE_MODEL_CATALOG:
        if m['id'] == model_id:
            return m['vision']
    return False


# ============================================================
# v2.1: системные промпты агентов (порт из эталона)
# ============================================================

CODER_SYSTEM = """Ты «Кодер-ревьюер» — первый технический проход в команде наставника по фронтенду. Ученик — самоучка, уровень junior-, работает над страницей товара (HTML/CSS/JS).
Твоя работа: найти проблемы в присланном коде строго по порядку важности:
1. Баги и то, что сломается.
2. Семантика HTML и доступность (alt, aria, контраст, фокус).
3. Адаптив и единицы измерения (px там, где нужен rem/clamp, переполнения, брейкпоинты).
4. Структура CSS: повторы, специфичность, нейминг.
5. Мелкий стиль.
Формат ответа: нумерованный список проблем, каждая в виде «[файл/селектор] проблема — почему это плохо (одной фразой) — как исправить (кратко)». Только то, что реально видно в присланном коде. Не пиши готовую вёрстку целиком. По-русски, без вступлений и без прощаний."""

CONTROLLER_SYSTEM = """Ты «Контролёр» — второй ревьюер в команде наставника, свежий взгляд. Тебе дают: код ученика и тех-ревью коллеги-кодера.
Задача:
1. Проверь ревью коллеги: что верно, где он ошибся или преувеличил (укажи прямо).
2. Найди то, что он ПРОПУСТИЛ — в первую очередь баги и проблемы адаптива.
3. Отметь 1–2 самые важные проблемы, с которых стоит начать.
Пиши кратко списком. Если ревью полное и точное — так и скажи одной строкой и добавь максимум 1–2 дополнения. По-русски, без вступлений."""

PLANNER_SYSTEM = """Ты «Планировщик» — агент проверки конца дня в команде наставника по фронтенду.
У тебя: отчёт ученика за день и «Журнал прогресса» с задачей на сегодня (ищи в журнале последний пункт «Задача на завтра»).
Выдай строго по шаблону:
1. Сверка с задачей дня: каждый пункт — «сделано / не сделано / сделано плохо».
2. Вердикт одной строкой и оценка по 10-балльной шкале (обосновать в одну фразу).
3. 3 главные проблемы в формате ДО (его код/подход) → ПОСЛЕ (как надо).
4. 1–2 проверочных вопроса ученику, чтобы понять, разобрался ли он, а не скопировал.
По-русски, жёстко и по делу, без комплиментов. Если в журнале нет задачи на сегодня — скажи об этом и проверь по присланным материалам."""

GITANALYST_SYSTEM = """Ты «Гит-аналитик» — агент команды наставника. Тебе дают структуру файлов и последние коммиты репозитория ученика.
Сделай краткое резюме для наставника:
1. Чем ученик занимался по коммитам (динамика по датам, паузы).
2. Что сейчас в фокусе (какие файлы/папки менялись, какие есть).
3. Качество истории коммитов: осмысленные сообщения или «правки»/«фиксы».
4. На что наставнику обратить внимание в первую очередь.
По-русски, списками, кратко, без выдумок — только то, что видно в данных."""

VISION_SYSTEM = ('Ты «Зрение» — агент команды наставника. Твоя работа — точное '
                 'структурированное описание изображений для ревьюера. '
                 'Без оценок, только описание.')

LAYOUT_VISION_PROMPT = """Ты помогаешь ревьюить вёрстку по макету. Опиши изображение максимально подробно и структурированно для ревьюера кода:
1) Что на картинке (макет страницы, скриншот кода, скриншот сайта, что-то иное).
2) Если макет/страница: перечисли блоки сверху вниз с иерархией (шапка, галерея, карточка, кнопки…), что в ряд/в колонку, примерные пропорции и отступы (пиши «примерно»), шрифты (размеры условно), цвета (примерно, словами или hex на глаз), все тексты, которые видно.
3) Если скриншот кода — извлеки код целиком, без сокращений.
4) Замеченные визуальные проблемы (перекрытия, выравнивание, контраст).
Отвечай по-русски, кратко по пунктам, без вступлений."""

ENV_RULES = """# СРЕДА (технические детали интерфейса)
- Это приложение «Наставник». Вкладка «Команда» — конвейер агентов, вкладка «Чат» — личный чат с наставником.
- Фото макета разбирает агент «Зрение» и передаёт описание наставнику.
- Кнопка «GitHub» в чате прикрепляет файлы из репозитория ученика — их содержимое придёт вместе с сообщением.
- Если нужен файл, которого нет в сообщении, закончи ответ строкой ровно вида:
[НУЖЕН ФАЙЛ: путь/к/файлу]
(до 3 таких строк за ответ). Файл подтянется автоматически. Не проси файлы, которые уже видишь в сообщении.
- Вкладка «План» показывает план обучения — ученик отмечает этапы выполненными.
- Вкладка «Журнал» хранит «Журнал прогресса»: он подставляется тебе в начало каждой сессии. Когда выдаёшь обновлённый журнал — выдай его целиком в формате из пункта 5, он сохранится."""


# ============================================================
# v2.1: провайдер OpenRouter + вызов агента по цепочке
# ============================================================

def _or_chat(key, model, messages, timeout=150):
    """Один вызов OpenRouter. Возвращает текст. Бросает MentorError."""
    payload = {'model': model, 'messages': messages, 'stream': False}
    headers = {'Content-Type': 'application/json',
               'Authorization': 'Bearer ' + key,
               'HTTP-Referer': 'https://github.com/Fankor70/Tracer-vs-code',
               'X-Title': 'CodeTime Mentor Team',
               'User-Agent': 'CodeTime-Mentor/' + _ver()}
    data = _http_json(OR_BASE + '/chat/completions', payload, headers, timeout)
    return _parse_content(data)


def call_agent(role, messages, need_vision=False):
    """Вызов агента по роли через цепочку провайдеров.
    Возвращает (text, provider, model, ms). Провайдеры:
    openrouter → свой ключ → github → gemini(демо) → резерв(без ключей).
    Бросает MentorError с человеческим текстом, если никто не ответил."""
    started = time.time()
    cfg = load_config()
    errors = []
    last_kind = None

    def try_provider(tag, fn):
        nonlocal last_kind
        try:
            return fn()
        except MentorError as e:
            kind = _classify_error(e)
            last_kind = kind
            errors.append('%s: %s' % (tag, _short_err(e)))
            logging.warning('Наставник: агент %s, провайдер %s упал (%s): %s',
                            role, tag, kind, _short_err(e))
            return None

    # 1) OpenRouter
    if cfg['or_key']:
        models = [_or_role_model(cfg, role)]
        if need_vision:
            models += [m for m in OR_VISION_FALLBACKS if m not in models]
        for m in models:
            res = try_provider('openrouter/' + m,
                               lambda mm=m: _or_chat(cfg['or_key'], mm, messages))
            if res is not None:
                return res, 'openrouter', m, time.time() - started
        if cfg['or_key'] and not (cfg['api_key'] and cfg['api_base']) \
                and not cfg['gh_token'] and last_kind == 'auth':
            raise MentorError('OpenRouter отклонил ключ (401). Проверьте его в '
                              'Настройках: openrouter.ai/keys.')

    # 2) свой ключ (любой OpenAI-совместимый API)
    if cfg['api_key'] and cfg['api_base']:
        model = cfg['vision_model'] if (need_vision and cfg['vision_model']) \
            else (cfg['model'] or 'gpt-4o-mini')
        payload = {'messages': messages, 'stream': False, 'max_tokens': 4000}
        headers = {'Content-Type': 'application/json',
                   'Authorization': 'Bearer ' + cfg['api_key'],
                   'User-Agent': 'CodeTime-Mentor/' + _ver()}

        def _own():
            url = cfg['api_base'].rstrip('/') + '/chat/completions'
            return _parse_content(_http_json(url, payload, headers, 150))
        res = try_provider('свой ключ', _own)
        if res is not None:
            return res, 'key', model, time.time() - started

    # 3) GitHub Models
    if cfg['gh_token']:
        payload = {'messages': messages, 'stream': False, 'max_tokens': 4000}
        headers = {'Content-Type': 'application/json',
                   'Authorization': 'Bearer ' + cfg['gh_token'],
                   'User-Agent': 'CodeTime-Mentor/' + _ver()}

        def _ghm():
            url = GH_MODELS_BASE + '/chat/completions'
            return _parse_content(_http_json(url, payload, headers, 150))
        res = try_provider('github', _ghm)
        if res is not None:
            return res, 'github', GH_MODELS_MODEL, time.time() - started

    # 4) встроенный Gemini (демо-ключ; состояние блокировок кэшируется)
    if not _gemini_blocked():
        st = _gemini_state()
        models = ([st['model']] if st.get('model') else []) + GEMINI_MODELS

        def _gem():
            last = None
            for m in models:
                payload = {'messages': messages, 'stream': False,
                           'max_tokens': 4000, 'temperature': 0.6, 'model': m}
                headers = {'Content-Type': 'application/json',
                           'Authorization': 'Bearer ' + GEMINI_DEMO_KEY,
                           'User-Agent': 'CodeTime-Mentor/' + _ver()}
                try:
                    text = _parse_content(_http_json(
                        GEMINI_BASE + '/chat/completions', payload,
                        headers, 120))
                    _gemini_save({'model': m})
                    return text
                except MentorError as e:
                    last = e
                    if _classify_error(e) in ('region', 'leak', 'auth'):
                        raise
            if last:
                raise last
            raise MentorError('Список моделей Gemini пуст.')
        res = try_provider('gemini', _gem)
        if res is not None:
            return res, 'gemini', (st.get('model') or GEMINI_MODELS[0]), \
                time.time() - started

    # 5) резерв без всяких ключей (Pollinations, текст-only)
    if need_vision:
        raise MentorError(
            'Фото макета некому разобрать: у резервной модели нет «зрения». '
            'Подключите бесплатный ключ OpenRouter (модель Qwen3.8 — со '
            'зрением) или GitHub-токен в Настройках — и фото заработает. '
            'Детали: ' + ('; '.join(errors[-2:]) if errors else 'нет связи'))
    # у анонимного тарифа Pollinations роль system отдаёт 402 — см. _demo_messages
    payload = {'messages': _demo_messages(messages),
               'stream': False, 'model': DEMO_LLM_MODEL,
               'referrer': DEMO_LLM_REFERRER}

    def _demo():
        last = None
        for delay in (0, 12, 30):
            if delay:
                time.sleep(delay)
            try:
                headers = {'Content-Type': 'application/json',
                           'Referer': DEMO_LLM_REFERRER,
                           'User-Agent': 'CodeTime-Mentor/' + _ver()}
                return _parse_content(_http_json(
                    DEMO_LLM_BASE, payload, headers, 150))
            except MentorError as e:
                last = e
                if _classify_error(e) == 'throttle':
                    continue
                raise
        if last:
            raise last
        raise MentorError('Резерв не ответил.')
    res = try_provider('резерв', _demo)
    if res is not None:
        return res, 'demo', DEMO_LLM_MODEL, time.time() - started

    raise MentorError('ИИ-команда недоступна (последняя причина: %s). '
                      'Проверьте интернет и Настройки.'
                      % (errors[-1] if errors else 'нет связи'))


def call_mentor_text(user_text, history=None, need_vision=False):
    """Быстрый вызов наставника одним сообщением (журнал/план/тесты).
    history — готовые [{role, content}]; user_text ставится в конец."""
    system = build_system_prompt(load_config(), 'free')
    system += '\n\n' + ENV_RULES
    msgs = [{'role': 'assistant', 'content': system}]
    msgs.extend(history or [])
    msgs.append({'role': 'user', 'content': user_text})
    text, provider, model, _ms = call_agent('mentor', msgs, need_vision)
    return text, provider, model


# ============================================================
# v2.1: чаты (папка chats/)
# ============================================================

def _chats_index():
    try:
        arr = json.loads(_read(CHATS_INDEX_PATH, '[]'))
        if isinstance(arr, list):
            return arr
    except (ValueError, TypeError):
        pass
    return []


def _chats_index_save(arr):
    ensure_all()
    _write(CHATS_INDEX_PATH, json.dumps(arr[:200], ensure_ascii=False, indent=1))


def chats_list():
    ensure_all()
    arr = _chats_index()
    arr.sort(key=lambda c: c.get('updatedAt') or '', reverse=True)
    out = []
    for c in arr:
        msgs = _chat_messages(c['id'])
        out.append({'id': c['id'], 'title': c.get('title') or 'Новый чат',
                    'updatedAt': c.get('updatedAt'),
                    'messageCount': len(msgs)})
    return {'chats': out}


def _chat_messages(chat_id):
    if not re.match(r'^[A-Za-z0-9_-]{4,40}$', chat_id or ''):
        return []
    try:
        arr = json.loads(_read(os.path.join(CHATS_DIR, chat_id + '.json'), '[]'))
        if isinstance(arr, list):
            return arr
    except (ValueError, TypeError):
        pass
    return []


def _chat_messages_save(chat_id, arr):
    ensure_all()
    _write(os.path.join(CHATS_DIR, chat_id + '.json'),
           json.dumps(arr[-400:], ensure_ascii=False))


def chat_create(data):
    ensure_all()
    cid = datetime.now().strftime('%Y%m%d%H%M%S') + \
        ('%04x' % (int(time.time() * 1000) & 0xffff))
    now = datetime.now().isoformat(timespec='seconds')
    chat = {'id': cid, 'title': (str(data.get('title') or 'Новый чат'))[:80],
            'createdAt': now, 'updatedAt': now}
    idx = _chats_index()
    idx.insert(0, chat)
    _chats_index_save(idx)
    _chat_messages_save(cid, [])
    return {'chat': {'id': cid, 'title': chat['title'], 'createdAt': now,
                     'updatedAt': now, 'messageCount': 0}}


def chat_get(chat_id):
    idx = _chats_index()
    meta = next((c for c in idx if c['id'] == chat_id), None)
    if not meta:
        raise MentorError('Чат не найден.')
    msgs = _chat_messages(chat_id)
    return {'chat': {'id': chat_id, 'title': meta.get('title') or 'Новый чат',
                     'updatedAt': meta.get('updatedAt')},
            'messages': msgs}


def chat_delete(chat_id):
    idx = _chats_index()
    idx = [c for c in idx if c['id'] != chat_id]
    _chats_index_save(idx)
    try:
        os.remove(os.path.join(CHATS_DIR, str(chat_id) + '.json'))
    except OSError:
        pass
    return {'ok': True}


def chat_rename(chat_id, title):
    idx = _chats_index()
    for c in idx:
        if c['id'] == chat_id:
            c['title'] = (title or '').strip()[:80] or c['title']
    _chats_index_save(idx)
    return {'ok': True}


NEED_FILE_RE = re.compile(r'\[\s*НУЖЕН ФАЙЛ\s*:\s*([^\]]+?)\s*\]', re.IGNORECASE)
MAX_MSG_CHARS = 24000


def _clip(s, mx=MAX_MSG_CHARS):
    s = s or ''
    return s[:mx] + '\n…(обрезано)' if len(s) > mx else s


def api_send(data):
    """Отправка сообщения в чат: фото → Зрение, файлы GitHub, история,
    [НУЖЕН ФАЙЛ] автоподтягивание. Ответ наставника с подписью модели."""
    chat_id = str(data.get('chatId') or '')
    text = (data.get('content') or '').strip()
    image_path = str(data.get('imagePath') or '')
    gh_paths = [str(p) for p in (data.get('githubPaths') or []) if p][:6]
    if not chat_id:
        raise MentorError('Не указан чат.')
    if not text and not image_path and not gh_paths:
        raise MentorError('Пустое сообщение.')
    idx = _chats_index()
    meta = next((c for c in idx if c['id'] == chat_id), None)
    if not meta:
        raise MentorError('Чат не найден.')

    cfg = load_config()

    # 1. Фото макета → агент «Зрение»
    image_note = ''
    if image_path:
        safe = os.path.basename(image_path)
        full = os.path.join(LAYOUTS_DIR, safe)
        if not os.path.exists(full):
            raise MentorError('Файл фото не найден — прикрепите заново.')
        ext = os.path.splitext(safe)[1].lower()
        mime = {'.png': 'image/png', '.webp': 'image/webp',
                '.gif': 'image/gif'}.get(ext, 'image/jpeg')
        with open(full, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')
        prompt = LAYOUT_VISION_PROMPT + \
            ('\n\nВопрос ученика к этому изображению: «%s»' % text if text else '')
        vision_content = [
            {'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': 'data:%s;base64,%s'
                                                % (mime, b64)}},
        ]
        try:
            image_note, _pr, _md, _ms = call_agent(
                'vision',
                [{'role': 'system', 'content': VISION_SYSTEM},
                 {'role': 'user', 'content': vision_content}],
                need_vision=True)
        except MentorError as e:
            image_note = '[vision-модель не смогла разобрать фото: %s]' % e

    # 2. Файлы GitHub, выбранные учеником
    attached = []
    if gh_paths:
        if not cfg['repo']:
            raise MentorError('Репозиторий не подключён (Настройки → GitHub).')
        attached = fetch_repo_files(cfg, gh_paths)

    # 3. Сообщение ученика
    now = datetime.now().isoformat(timespec='seconds')
    user_msg = {'id': 'm' + str(int(time.time() * 1000)), 'role': 'user',
                'content': text or '(без текста)',
                'imagePath': ('layouts/' + image_path) if image_path else '',
                'imageNote': image_note, 'createdAt': now}
    msgs = _chat_messages(chat_id)
    msgs.append(user_msg)

    # автозаголовок
    if (meta.get('title') or 'Новый чат') == 'Новый чат' and text:
        meta['title'] = text[:48]

    # 4. Системный промпт: роль + журнал + план + репозиторий + среда
    system = build_system_prompt(cfg, 'free')
    system += '\n\n' + ENV_RULES
    system += '\n\n# СЕГОДНЯ\n' + \
        datetime.now().strftime('%d %B %Y (%A), %H:%M')

    # 5. История (последние 30 сообщений, включая только что созданное)
    history = msgs[-31:]
    llm_messages = [{'role': 'assistant', 'content': system}]
    for m in history:
        c = m.get('content') or ''
        if m.get('imageNote'):
            short = m['imageNote'][:1500] + ('…' if len(m['imageNote']) > 1500 else '')
            c += ('\n\n[Ученик приложил фото макета — описание от vision-модели]\n'
                  + short)
        if m is user_msg and attached:
            c += '\n\n[Файлы из GitHub, приложенные учеником]\n' + \
                files_to_blocks(attached)
        llm_messages.append({'role': 'assistant' if m['role'] == 'assistant'
                             else 'user', 'content': _clip(c)})

    # 6. Ответ наставника (агент mentor по цепочке провайдеров)
    reply, provider, model, _ms = call_agent('mentor', llm_messages)

    # 7. Авто-докачка файлов, если наставник попросил [НУЖЕН ФАЙЛ: …]
    if cfg['repo']:
        wanted = []
        for m in NEED_FILE_RE.finditer(reply):
            p = m.group(1).strip()
            if p and p not in wanted:
                wanted.append(p)
        already = set(gh_paths)
        for m in history:
            if m.get('role') == 'user':
                for mm in NEED_FILE_RE.finditer(m.get('content') or ''):
                    already.add(mm.group(1).strip())
        paths = [p for p in wanted if p not in already][:3]
        if paths:
            files = fetch_repo_files(cfg, paths)
            round2 = list(llm_messages)
            round2.append({'role': 'assistant', 'content': reply})
            round2.append({'role': 'user', 'content':
                           '[Система автоматически подтянула запрошенные файлы '
                           'из GitHub]\n\n' + files_to_blocks(files) +
                           '\n\nПродолжи разбор с учётом этих файлов. Не '
                           'повторяй запрос файлов заново.'})
            try:
                reply, provider, model, _ms = call_agent('mentor', round2)
            except MentorError:
                pass   # второй заход не удался — оставим первый ответ

    # 8. Сохраняем ответ
    a_now = datetime.now().isoformat(timespec='seconds')
    assistant_msg = {'id': 'm' + str(int(time.time() * 1000) + 1),
                     'role': 'assistant', 'content': reply,
                     'model': model, 'provider': provider, 'createdAt': a_now}
    msgs.append(assistant_msg)
    _chat_messages_save(chat_id, msgs)
    meta['updatedAt'] = a_now
    _chats_index_save(idx)

    # «запомни» → notes/notes.md
    note_saved = False
    if text and _REMEMBER_RE.search(text) and len(text) >= 12:
        try:
            ensure_all()
            stamp = datetime.now().strftime('%d.%m.%Y %H:%M')
            with open(NOTES_PATH, 'a', encoding='utf-8') as f:
                f.write('\n\n---\n## Запомнить · %s\n\n%s\n' % (stamp, text[:8000]))
            note_saved = True
        except OSError:
            logging.exception('Наставник: не сохранилась заметка «запомни»')

    # блоки ```журнал ...``` → journal.md, ```план ...``` → plan.md
    journal_saved = False
    for block in _JOURNAL_BLOCK_RE.findall(reply):
        journal_append(block.strip())
        journal_saved = True
    plan_saved = False
    for block in _PLAN_BLOCK_RE.findall(reply):
        body = block.strip()
        if body:
            _write(PLAN_PATH, body[:100000])
            plan_saved = True

    return {'userMessage': user_msg, 'assistantMessage': assistant_msg,
            'noteSaved': note_saved, 'journalSaved': journal_saved,
            'planSaved': plan_saved}


def files_to_blocks(files):
    out = []
    for f in files:
        if f.get('error'):
            out.append('--- %s ---\n[не удалось прочитать: %s]'
                       % (f['path'], f['error']))
        else:
            out.append('--- %s ---\n```\n%s\n```%s'
                       % (f['path'], f.get('content') or '',
                          '\n(файл обрезан по размеру)' if f.get('truncated')
                          else ''))
    return '\n\n'.join(out)


def api_upload(data):
    """dataURL картинки → файл в layouts/. Возвращает {imagePath}."""
    m = re.match(r'^data:([a-z/+.-]+);base64,(.+)$',
                 (data.get('dataUrl') or '').strip(), re.IGNORECASE)
    if not m:
        raise MentorError('Ожидается data URL картинки.')
    mime = m.group(1).lower()
    ext = {'image/png': '.png', 'image/jpeg': '.jpg',
           'image/webp': '.webp', 'image/gif': '.gif'}.get(mime)
    if not ext:
        raise MentorError('Формат %s не поддерживается (нужен png/jpeg/webp/gif)'
                          % mime)
    b64 = re.sub(r'\s', '', m.group(2))
    size = len(b64) * 3 // 4
    if size > 8 * 1024 * 1024:
        raise MentorError('Фото больше 8 МБ — сожмите и пришлите снова.')
    ensure_all()
    name = 'upload-%s-%s%s' % (datetime.now().strftime('%Y%m%d-%H%M%S'),
                               ('%04x' % (int(time.time() * 1000) & 0xffff)), ext)
    with open(os.path.join(LAYOUTS_DIR, name), 'wb') as f:
        f.write(base64.b64decode(b64))
    return {'imagePath': name, 'size': size}


# ============================================================
# v2.1: GitHub — дерево и файлы репозитория (read-only)
# ============================================================

BINARY_EXT = re.compile(r'\.(png|jpe?g|gif|webp|bmp|ico|svgz|pdf|zip|gz|rar'
                        r'|7z|tar|mp3|mp4|avi|mov|woff2?|ttf|eot|otf|exe|dll'
                        r'|db|sqlite3?)$', re.IGNORECASE)
MAX_FILE_BYTES = 150 * 1024
MAX_TOTAL_BYTES = 300 * 1024


def parse_repo(raw):
    if not raw:
        return None
    s = raw.strip().replace('.git', '').rstrip('/')
    s = re.sub(r'^https?://(www\.)?github\.com/', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^github\.com/', '', s, flags=re.IGNORECASE)
    m = re.match(r'^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$', s)
    return {'owner': m.group(1), 'name': m.group(2)} if m else None


def fetch_repo_tree(cfg):
    """Дерево файлов (10-минутный кэш в github_tree.json).
    Возвращает {ok, entries, truncated} или {ok:False, error}."""
    repo = parse_repo(cfg['repo'])
    if not repo:
        return {'ok': False,
                'error': 'Репозиторий не подключён (Настройки → GitHub)'}
    try:
        cache = json.loads(_read(GH_TREE_CACHE_PATH, '{}'))
        if (cache.get('repo') == cfg['repo'] and cache.get('ts')
                and time.time() - cache['ts'] < 600):
            return {'ok': True, 'entries': cache.get('entries') or [],
                    'truncated': bool(cache.get('truncated'))}
    except (ValueError, TypeError):
        pass
    try:
        info = _gh(cfg, '/repos/%s/%s' % (repo['owner'], repo['name']))
        branch = info.get('default_branch') or 'main'
        data = _gh(cfg, '/repos/%s/%s/git/trees/%s?recursive=1'
                   % (repo['owner'], repo['name'], branch))
    except MentorError as e:
        return {'ok': False, 'error': str(e)}
    entries = []
    for t in data.get('tree', []):
        if t.get('type') not in ('blob', 'tree'):
            continue
        p = t.get('path', '')
        if t['type'] == 'blob' and BINARY_EXT.search(p):
            continue
        entries.append({'path': p,
                        'type': 'tree' if t['type'] == 'tree' else 'blob',
                        'size': t.get('size') or 0})
        if len(entries) >= 800:
            break
    truncated = bool(data.get('truncated'))
    try:
        ensure_all()
        _write(GH_TREE_CACHE_PATH, json.dumps(
            {'repo': cfg['repo'], 'ts': time.time(), 'entries': entries,
             'truncated': truncated}, ensure_ascii=False))
    except OSError:
        pass
    return {'ok': True, 'entries': entries, 'truncated': truncated}


def api_github_tree(qs):
    cfg = load_config()
    tree = fetch_repo_tree(cfg)
    if not tree.get('ok'):
        raise MentorError(tree.get('error') or 'Не удалось прочитать дерево')
    prefix = (qs.get('path', [''])[0] or '').strip().strip('/')
    depth = len(prefix.split('/')) + 1 if prefix else 1
    out = []
    for e in tree['entries']:
        if prefix and not e['path'].startswith(prefix + '/'):
            continue
        if not prefix and '/' in e['path']:
            continue
        if len(e['path'].split('/')) != depth:
            continue
        out.append(e)
    if not out and tree['entries']:
        out = tree['entries'][:300]
    return {'entries': out, 'total': len(tree['entries']),
            'truncated': tree['truncated']}


def fetch_repo_file(cfg, path):
    clean = (path or '').strip().lstrip('/')
    if BINARY_EXT.search(clean):
        return {'path': clean, 'content': '', 'size': 0, 'truncated': False,
                'error': 'бинарный файл не читается'}
    repo = parse_repo(cfg['repo'])
    if not repo:
        return {'path': clean, 'content': '', 'size': 0, 'truncated': False,
                'error': 'репозиторий не подключён'}
    try:
        data = _gh(cfg, '/repos/%s/%s/contents/%s'
                   % (repo['owner'], repo['name'],
                      urllib.request.quote(clean)))
    except MentorError as e:
        return {'path': clean, 'content': '', 'size': 0, 'truncated': False,
                'error': str(e)}
    if not isinstance(data, dict) or data.get('type') != 'file':
        return {'path': clean, 'content': '', 'size': 0, 'truncated': False,
                'error': 'это не файл'}
    size = data.get('size') or 0
    if not data.get('content') or data.get('encoding') != 'base64':
        return {'path': clean, 'content': '', 'size': size,
                'truncated': False,
                'error': 'пустой файл или неизвестная кодировка'}
    try:
        raw = base64.b64decode(data['content'])
    except Exception:
        return {'path': clean, 'content': '', 'size': size,
                'truncated': False, 'error': 'не удалось декодировать файл'}
    truncated = len(raw) > MAX_FILE_BYTES
    if truncated:
        raw = raw[:MAX_FILE_BYTES]
    if b'\x00' in raw:
        return {'path': clean, 'content': '', 'size': size,
                'truncated': False, 'error': 'бинарный файл не читается'}
    return {'path': clean, 'content': raw.decode('utf-8', 'replace'),
            'size': size, 'truncated': truncated}


def fetch_repo_files(cfg, paths):
    out = []
    total = 0
    for p in list(paths)[:6]:
        f = fetch_repo_file(cfg, p)
        if not f.get('error'):
            total += len(f.get('content') or '')
            if total > MAX_TOTAL_BYTES:
                out.append({'path': f['path'], 'content': '', 'size': f['size'],
                            'truncated': True,
                            'error': 'пропущен: превышен общий лимит размера'})
                continue
        out.append(f)
    return out


def api_github_files(data):
    cfg = load_config()
    paths = [str(p) for p in (data.get('paths') or []) if p][:6]
    if not paths:
        raise MentorError('Не выбраны файлы.')
    if not cfg['repo']:
        raise MentorError('Репозиторий не подключён (Настройки → GitHub).')
    return {'files': fetch_repo_files(cfg, paths)}


def github_settings_put(data):
    """Сохранить/удалить GitHub-доступ. data: {repo, token} | {clear: true}."""
    if data.get('clear'):
        return save_config({'repo': '', 'gh_token': ''})
    repo = str(data.get('repo') or '').strip()[:200]
    if not parse_repo(repo):
        raise MentorError('Не похоже на репозиторий. Формат: owner/имя '
                          'или ссылка https://github.com/owner/имя')
    patch = {'repo': repo}
    token = str(data.get('token') or '').strip()
    if token:
        patch['gh_token'] = token[:300]
    status = save_config(patch)
    cfg = load_config()
    try:
        info = _gh(cfg, '/repos/%s/%s' % (parse_repo(repo)['owner'],
                                          parse_repo(repo)['name']))
    except MentorError as e:
        raise MentorError('%s Репозиторий сохранён, но проверка не прошла: '
                          'проверьте имя и токен.' % e)
    return {'ok': True, 'repo': info.get('full_name'),
            'private': bool(info.get('private')),
            'defaultBranch': info.get('default_branch'),
            'note': 'Репозиторий %s подключён — наставник читает файлы '
                    'и коммиты.' % info.get('full_name'),
            'status': status}


# ============================================================
# v2.1: OpenRouter — настройки и проверка агентов
# ============================================================

def or_settings_get():
    cfg = load_config()
    role_models = {}
    for r in AGENT_ROLES:
        role_models[r] = cfg.get('or_model_' + r) or ROLE_DEFAULT_MODEL[r]
    return {'keySet': bool(cfg['or_key']),
            'keyMasked': _mask(cfg['or_key']),
            'roleModels': role_models,
            'defaults': dict(ROLE_DEFAULT_MODEL),
            'catalog': FREE_MODEL_CATALOG,
            'limitsNote': OR_LIMITS_NOTE}


def or_settings_put(data):
    patch = {}
    key = str(data.get('key') or '').strip()
    if key:
        if len(key) < 20:
            raise MentorError('Ключ выглядит слишком коротким — скопируйте '
                              'строку sk-or-v1-… целиком.')
        patch['or_key'] = key
    if data.get('clearKey'):
        patch['clear_or_key'] = True
    role_models = data.get('roleModels')
    if isinstance(role_models, dict):
        for role, model in role_models.items():
            if role in AGENT_ROLES and isinstance(model, str):
                patch['or_model_' + role] = model.strip()[:120]
    save_config(patch)
    return or_settings_get()


def or_test(data):
    """Проверка связи: агент роли отвечает одной строкой.
    data.model — проверить конкретную модель (переопределяет роль)."""
    role = data.get('role') if data.get('role') in AGENT_ROLES else 'mentor'
    model_override = str(data.get('model') or '').strip()[:120]
    started = time.time()

    orig = _or_role_model

    def patched(cfg, r):
        if r == role and model_override:
            return model_override
        return orig(cfg, r)
    try:
        globals()['_or_role_model'] = patched
        text, provider, model, _ms = call_agent(
            role, [{'role': 'user', 'content':
                    'Ответь ровно одной строкой: «Связь есть, я на связи.» '
                    'и ничего больше.'}])
        return {'ok': True, 'role': role, 'provider': provider,
                'model': model, 'ms': int((time.time() - started) * 1000),
                'reply': text[:200]}
    except MentorError as e:
        return {'ok': False, 'role': role,
                'error': str(e)[:300], 'ms': int((time.time() - started) * 1000)}
    finally:
        globals()['_or_role_model'] = orig


# ============================================================
# v2.1: журнал и план (прямые роуты для нового UI)
# ============================================================

def api_journal_get():
    ensure_all()
    content = _read(JOURNAL_PATH)
    try:
        updated = datetime.fromtimestamp(
            os.path.getmtime(JOURNAL_PATH)).isoformat(timespec='seconds')
    except OSError:
        updated = None
    return {'content': content, 'updatedAt': updated,
            'notes': _read(NOTES_PATH),
            'layoutReview': _read(LAYOUT_REVIEW_PATH),
            'folder': MENTOR_DIR}


def api_journal_put(data):
    content = str(data.get('content') or '')[:200000]
    ensure_all()
    _write(JOURNAL_PATH, content)
    return api_journal_get()


JOURNAL_AI_INSTRUCTION = """Составь обновлённый «Журнал прогресса» по формату из раздела «Контекст и память» твоей роли:
- Сделано (по датам, коротко).
- Текущее состояние проекта: какие файлы есть и что в каждом.
- Темы, которые я уже освоил.
- Ошибки, которые повторяются.
- Договорённости и решения (например, «desktop-first», «БЭМ-нейминг»).
- Задача на завтра.

Опирайся ТОЛЬКО на переписку ниже и на прежний журнал. Ничего не выдумывай. Если данных за какую-то секцию нет — напиши там «нет данных за эту сессию». Задача на завтра — одна, конкретная.
В ответе выдай ТОЛЬКО текст журнала (можно с маркдауном), без вступлений и без «вот ваш журнал»."""


def api_journal_ai(data):
    """Наставник обновляет журнал по итогам последнего чата."""
    chat_id = str(data.get('chatId') or '')
    idx = sorted(_chats_index(), key=lambda c: c.get('updatedAt') or '',
                 reverse=True)
    if not chat_id:
        if not idx:
            raise MentorError('Нет ни одного чата — сначала поговорите с '
                              'наставником.')
        chat_id = idx[0]['id']
    msgs = [m for m in _chat_messages(chat_id)
            if m.get('role') in ('user', 'assistant')]
    if not msgs:
        raise MentorError('В чате нет сообщений — обновлять нечего.')
    transcript = '\n\n'.join(
        ('УЧЕНИК' if m['role'] == 'user' else 'НАСТАВНИК') + ': '
        + (m.get('content') or '')[:4000]
        + ('\n[к сообщению приложено фото макета]' if m.get('imageNote') else '')
        for m in msgs[-40:])[:90000]
    prev = _read(JOURNAL_PATH).strip() or '(журнала ещё нет — составь стартовый)'
    content, provider, model = call_mentor_text(
        JOURNAL_AI_INSTRUCTION
        + '\n\n# ПРЕЖНИЙ ЖУРНАЛ\n' + _clip(prev, 20000)
        + '\n\n# ПЕРЕПИСКА ПОСЛЕДНЕЙ СЕССИИ\n' + transcript)
    _write(JOURNAL_PATH, content[:200000])
    out = api_journal_get()
    out['model'] = model
    out['provider'] = provider
    return out


_PLAN_PERIOD_RE = re.compile(r'^([А-ЯЁA-Z][а-яёa-z]+(?:\s*\d{4})?)\s*[—:-]\s*(.+)$')


def _plan_items_from_md(md_text):
    """Парсит план.md в пункты {id: №строки, period, goal, done}."""
    items = []
    for i, line in enumerate((md_text or '').split('\n')):
        m = re.match(r'^\s*-\s*\[([ xX])\]\s*(.*)$', line)
        if not m:
            continue
        done = m.group(1).lower() == 'x'
        rest = m.group(2).strip()
        pm = _PLAN_PERIOD_RE.match(rest)
        if pm and len(pm.group(1)) <= 20:
            period, goal = pm.group(1).strip(), pm.group(2).strip()
        else:
            period, goal = '', rest
        items.append({'id': i, 'period': period, 'goal': goal, 'done': done})
    return items


def api_plan_get():
    ensure_all()
    return {'items': _plan_items_from_md(_read(PLAN_PATH)),
            'raw': _read(PLAN_PATH)}


def api_plan_patch(data):
    """Отметка пункта плана: {id: №строки, done: bool} — правит галочку."""
    ensure_all()
    lines = _read(PLAN_PATH).split('\n')
    try:
        idx = int(data.get('id'))
    except (TypeError, ValueError):
        raise MentorError('Не указан id пункта плана.')
    if not (0 <= idx < len(lines)):
        raise MentorError('Пункт плана не найден.')
    if not re.match(r'^\s*-\s*\[([ xX])\]', lines[idx]):
        raise MentorError('Строка плана без чекбокса.')
    done = bool(data.get('done'))
    lines[idx] = re.sub(r'^(\s*-\s*)\[([ xX])\]',
                        lambda m: m.group(1) + ('[x]' if done else '[ ]'),
                        lines[idx], count=1)
    _write(PLAN_PATH, '\n'.join(lines))
    return api_plan_get()


PLAN_AI_INSTRUCTION = """Обнови план обучения ученика (вкладка «План» в интерфейсе). Опирайся на роль, прежний план, журнал и сегодняшнюю дату: сдвинь этапы так, чтобы цель «Junior/Middle к апрелю 2027» была реалистичной с учётом того, что уже сделано.

Верни СТРОГО JSON-массив без пояснений и без markdown-обёртки, каждый элемент:
[{"period": "Месяц ГГГГ", "goal": "цель одной фразой", "details": "1-2 предложения: что конкретно делаем"}, ...]
Периоды — с текущего месяца по апрель 2027 включительно (уже пройденное не включай). От 4 до 10 пунктов. Только JSON."""


def api_plan_ai():
    import ast as _ast
    items_now = _plan_items_from_md(_read(PLAN_PATH))
    plan_text = '\n'.join('- [%s] %s %s' % ('x' if i['done'] else ' ',
                                            (i['period'] + ' — ') if i['period'] else '',
                                            i['goal'])
                          for i in items_now) or '(план пуст)'
    journal = _read(JOURNAL_PATH)
    raw, provider, model = call_mentor_text(
        PLAN_AI_INSTRUCTION
        + '\n\n# ПРЕЖНИЙ ПЛАН\n' + _clip(plan_text, 6000)
        + '\n\n# ЖУРНАЛ ПРОГРЕССА\n' + _clip(journal, 6000))
    s = raw.strip()
    fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', s)
    if fence:
        s = fence.group(1).strip()
    start, end = s.find('['), s.rfind(']')
    if start == -1 or end <= start:
        raise MentorError('Наставник вернул план не в JSON — попробуйте ещё раз.')
    try:
        arr = json.loads(s[start:end + 1])
    except ValueError:
        try:
            arr = _ast.literal_eval(s[start:end + 1])
        except (ValueError, SyntaxError):
            raise MentorError('Не удалось разобрать JSON плана.')
    if not isinstance(arr, list) or not arr:
        raise MentorError('Пустой план от наставника.')
    lines = ['# План обучения — Junior/Middle к апрелю 2027', '']
    for it in arr[:12]:
        if not isinstance(it, dict):
            continue
        period = str(it.get('period') or '').strip()[:60]
        goal = str(it.get('goal') or '').strip()[:300]
        details = str(it.get('details') or '').strip()[:2000]
        if not goal:
            continue
        lines.append('- [ ] %s%s' % ((period + ' — ') if period else '', goal))
        if details:
            lines.append('  %s' % details)
    lines.append('')
    lines.append('План составил наставник (%s, %s). Правьте вручную — '
                 'галочки кликабельны.' % (provider, model))
    _write(PLAN_PATH, '\n'.join(lines))
    return api_plan_get()


# ============================================================
# v2.1: КОМАНДА — конвейер агентов (порт из эталона)
# ============================================================

TASK_TYPES = [
    {'id': 'code', 'label': 'Разбор кода',
     'hint': 'Вставь код (или пришли файл с GitHub в чате) — Кодер найдёт '
             'проблемы, Контролёр проверит его, Наставник оформит итог.',
     'chain': ['coder', 'controller', 'mentor']},
    {'id': 'layout', 'label': 'Макет по фото',
     'hint': 'Приложи фото макета — Зрение опишет структуру, Наставник даст '
             'план вёрстки.',
     'chain': ['vision', 'mentor'], 'needsImage': True},
    {'id': 'day', 'label': 'Конец дня',
     'hint': 'Расскажи, что сделал за день. Планировщик сверит с задачей, '
             'Наставник выдаст вердикт, журнал и задачу на завтра.',
     'chain': ['planner', 'mentor']},
    {'id': 'repo', 'label': 'GitHub-обзор',
     'hint': 'Команда посмотрит подключённый репозиторий (Настройки → '
             'GitHub): коммиты, структура, что учить дальше.',
     'chain': ['gitanalyst', 'mentor'], 'needsRepo': True},
    {'id': 'free', 'label': 'Свободный вопрос',
     'hint': 'Прямой вопрос наставнику — один агент, минимум расход лимита.',
     'chain': ['mentor']},
]

AGENT_EMOJI = {'coder': '🛠', 'vision': '👁', 'planner': '📋',
               'gitanalyst': '🐙', 'controller': '🔍', 'mentor': '🎓'}

MAX_CTX = 14000


def _ctx_clip(s, mx=MAX_CTX):
    s = s or ''
    return s[:mx] + '\n…(обрезано)' if len(s) > mx else s


def _team_context():
    journal = _read(JOURNAL_PATH)
    plan = _read(PLAN_PATH)
    return journal, plan


def _context_block(journal, plan):
    return ('# ЖУРНАЛ ПРОГРЕССА (память о прошлых сессиях ученика)\n%s\n\n'
            '# ПЛАН ОБУЧЕНИЯ\n%s'
            % (_ctx_clip(journal.strip() or '(журнала пока нет — это первая '
                         'сессия)', 8000), _ctx_clip(plan, 4000)))


def _repo_digest():
    """Структура + коммиты репозитория (для Гит-аналитика)."""
    cfg = load_config()
    repo = parse_repo(cfg['repo'])
    if not repo:
        return None, ''
    parts = []
    try:
        tree = fetch_repo_tree(cfg)
        if tree.get('ok'):
            lines = [('- ' + e['path'] + ('/' if e['type'] == 'tree' else
                     ' (%d Б)' % e['size'] if e['size'] else ''))
                     for e in tree['entries'][:250]]
            parts.append('Структура файлов:\n' + '\n'.join(lines))
    except Exception:
        pass
    try:
        commits = _gh(cfg, '/repos/%s/%s/commits?per_page=20'
                      % (repo['owner'], repo['name']))
        lines = []
        for c in commits[:20]:
            d = ((c.get('commit') or {}).get('author') or {}).get('date', '')[:10]
            msg = (((c.get('commit') or {}).get('message') or '')
                   .split('\n')[0])[:100]
            lines.append('- %s %s' % (d or '?', msg))
        if lines:
            parts.append('Последние коммиты (новые сверху):\n' + '\n'.join(lines))
    except MentorError:
        pass
    return '%s/%s' % (repo['owner'], repo['name']), '\n\n'.join(parts)


def _agent_messages(role, prev, task_input, task_text, journal, plan,
                    image_b64=None, image_mime='image/jpeg'):
    """Сообщения для агента role: системный промпт + материал коллег."""
    material = '\n\n'.join('[Материал от агента «%s»]\n%s' % (k, _ctx_clip(v))
                           for k, v in prev.items())
    pupil = ('Ученик написал/прислал:\n%s' % _ctx_clip(task_input)) \
        if task_input.strip() else ''

    def base(extra):
        return [x for x in (material, pupil, extra) if x]

    if role == 'coder':
        return [{'role': 'system', 'content': CODER_SYSTEM},
                {'role': 'user', 'content':
                 'Общий контекст ученика:\n%s\n\n%s\n\nСделай технический '
                 'проход по коду.' % (_context_block(journal, plan),
                                      task_text or '')}]
    if role == 'controller':
        return [{'role': 'system', 'content': CONTROLLER_SYSTEM},
                {'role': 'user', 'content':
                 'Код ученика:\n%s\n\nТех-ревью коллеги:\n%s\n\nПроверь.'
                 % (_ctx_clip(task_input, 20000),
                    _ctx_clip(prev.get('Кодер-ревьюер') or '', MAX_CTX))}]
    if role == 'vision':
        content = LAYOUT_VISION_PROMPT + \
            ('\n\nВопрос ученика: %s' % task_input if task_input.strip()
             else '')
        if image_b64:
            content = [{'type': 'text', 'text': content},
                       {'type': 'image_url',
                        'image_url': {'url': 'data:%s;base64,%s'
                                      % (image_mime, image_b64)}}]
        return [{'role': 'system', 'content': VISION_SYSTEM},
                {'role': 'user', 'content': content}]
    if role == 'planner':
        return [{'role': 'system', 'content': PLANNER_SYSTEM},
                {'role': 'user', 'content':
                 'Контекст ученика:\n%s\n\nОтчёт за день:\n%s\n\nПроведи '
                 'проверку конца дня.'
                 % (_context_block(journal, plan),
                    _ctx_clip(task_input, 12000)
                    or '(ученик не написал отчёт — напомни, что нужен)')}]
    if role == 'gitanalyst':
        return [{'role': 'system', 'content': GITANALYST_SYSTEM},
                {'role': 'user', 'content':
                 'Данные репозитория:\n%s\n\nУченик добавил: %s\n\nСделай '
                 'резюме.' % (_ctx_clip(prev.get('_repo_digest') or '', 20000)
                              or '(репозиторий не подключён или пуст)',
                              _ctx_clip(task_input, 4000)
                              or '(нет комментария)')}]
    # mentor: финальный ответ по правилам роли
    sysrole = _read(ROLE_PATH, DEFAULT_ROLE) or DEFAULT_ROLE
    sysrole += '\n\n' + ENV_RULES
    sysrole += '\n\n# СЕГОДНЯ\n' + datetime.now().strftime('%d.%m.%Y')
    if prev.get('_repo_digest'):
        sysrole += ('\n\n=== СНИМОК РЕПОЗИТОРИЯ (от Гит-аналитика) ===\n%s'
                    % _ctx_clip(prev['_repo_digest'], 4000))
    system = sysrole + '\n\n=== ЖУРНАЛ И ПЛАН УЧЕНИКА ===\n' + \
        _context_block(journal, plan)
    by_type = {
        'coder': ('Оформи финальный разбор по своим правилам (порядок '
                  'важности из раздела 1 роли, для каждой проблемы: где, '
                  'почему плохо, ДО/ПОСЛЕ на его же коде). Учитывай находки '
                  'и правки контролёра. Ученику служебных слов про команду '
                  'не передавай.'),
        'vision': ('Vision-агент описал макет по фото. Дай разбор макета и '
                   'план вёрстки по разделу 2 своей роли: структура и теги, '
                   'сетка, примерные отступы/шрифты/цвета, вопросы про '
                   'отсутствующие состояния, поведение на мобилке, порядок '
                   'работы. Готовую вёрстку целиком не пиши.'),
        'planner': ('Планировщик сверил день с задачей. Теперь ты по своему '
                    'разделу 5 роли выдай обновлённый «Журнал прогресса» '
                    'целиком и «Задачу на завтра» (формат раздела 4). '
                    'Вердикт и оценку планировщика упомяни одной строкой. '
                    'Обновлённый журнал выдай блоком ```журнал ...``` — '
                    'приложение запишет его автоматически.'),
        'gitanalyst': ('Гит-аналитик просмотрел репозиторий. Скажи: что ты '
                       'думаешь о текущем состоянии и что учить дальше по '
                       'плану; дай одну конкретную задачу на сегодня '
                       '(формат раздела 4).'),
    }
    extra = by_type.get(task_text, 'Ответь по своим правилам роли.')
    parts = [x for x in (material, pupil, extra) if x]
    return [{'role': 'system', 'content': system},
            {'role': 'user', 'content': '\n\n'.join(parts)
             or 'Ответь по своим правилам роли.'}]


AGENT_TITLE = {'coder': 'Кодер-ревьюер', 'controller': 'Контролёр',
               'vision': 'Зрение', 'planner': 'Планировщик',
               'gitanalyst': 'Гит-аналитик', 'mentor': 'Наставник'}


def team_run(data):
    """Запуск конвейера команды. {taskType, input, imagePath}."""
    task_type = str(data.get('taskType') or 'free')
    type_def = next((t for t in TASK_TYPES if t['id'] == task_type),
                    TASK_TYPES[-1])
    task_input = str(data.get('input') or '')[:20000]
    image_path = str(data.get('imagePath') or '')
    if not task_input.strip() and not image_path:
        raise MentorError('Напишите задачу для команды.')

    image_b64, image_mime = '', 'image/jpeg'
    if image_path:
        safe = os.path.basename(image_path)
        full = os.path.join(LAYOUTS_DIR, safe)
        if not os.path.exists(full):
            raise MentorError('Файл фото не найден — прикрепите заново.')
        ext = os.path.splitext(safe)[1].lower()
        image_mime = {'.png': 'image/png', '.webp': 'image/webp',
                      '.gif': 'image/gif'}.get(ext, 'image/jpeg')
        with open(full, 'rb') as f:
            image_b64 = base64.b64encode(f.read()).decode('ascii')

    journal, plan = _team_context()
    repo = None
    repo_digest = ''
    if type_def['id'] == 'repo':
        repo, repo_digest = _repo_digest()
        if not repo:
            raise MentorError('Репозиторий не подключён (Настройки → GitHub).')

    prev = {'_repo_digest': repo_digest}
    steps = []
    for role in type_def['chain']:
        started = time.time()
        try:
            messages = _agent_messages(role, prev, task_input,
                                       type_def['id'], journal, plan,
                                       image_b64, image_mime)
            text, provider, model, _ms = call_agent(
                role, messages,
                need_vision=(role == 'vision' and bool(image_b64)))
            ms = int((time.time() - started) * 1000)
            steps.append({'agentKey': role, 'model': model,
                          'provider': provider, 'content': text,
                          'ms': ms, 'ok': True})
            prev[AGENT_TITLE[role]] = text
        except MentorError as e:
            steps.append({'agentKey': role, 'model': '', 'provider': '',
                          'content': str(e), 'ms': 0, 'ok': False})
            _team_persist(type_def, task_input, image_path,
                          steps, '', 'error', str(e))
            raise MentorError('Команда остановилась на шаге «%s»: %s'
                              % (ROLE_LABEL[role], e))

    final = steps[-1]['content'] if steps else ''
    return _team_persist(type_def, task_input, image_path, steps, final,
                         'ok', '')


def _team_persist(type_def, task_input, image_path, steps, final, status,
                  error):
    """Сохраняет протокол запуска в runs/ (index.json + .md файл)."""
    ensure_all()
    now = datetime.now()
    run_id = now.strftime('%Y%m%d-%H%M%S') + '-' + type_def['id']
    entry = {'id': run_id, 'taskType': type_def['id'],
             'input': task_input[:2000], 'imagePath': image_path,
             'final': final, 'status': status, 'error': error,
             'createdAt': now.isoformat(timespec='seconds'),
             'steps': [{'agentKey': s['agentKey'], 'model': s['model'],
                        'provider': s.get('provider') or '',
                        'ms': s['ms'], 'ok': s['ok'],
                        'content': s['content'][:6000]} for s in steps]}
    try:
        idx = json.loads(_read(RUNS_INDEX_PATH, '[]'))
        if not isinstance(idx, list):
            idx = []
    except (ValueError, TypeError):
        idx = []
    idx.insert(0, entry)
    _write(RUNS_INDEX_PATH, json.dumps(idx[:50], ensure_ascii=False))

    # человекочитаемый протокол
    stamp = now.strftime('%Y-%m-%d %H-%M-%S')
    log_name = '%s-%s.md' % (stamp, type_def['id'])
    lines = ['# Запуск команды — %s (%s)' % (stamp, type_def['id']), '',
             '**Задача ученика:** %s' % (task_input[:2000] or '(без текста)')]
    if image_path:
        lines.append('\n**Фото макета:** %s' % image_path)
    for s in steps:
        lines += ['---', '',
                  '## %s %s · `%s` · %.1fs'
                  % (AGENT_EMOJI.get(s['agentKey'], '🤖'),
                     ROLE_LABEL.get(s['agentKey'], s['agentKey']),
                     s.get('model') or '—', s['ms'] / 1000.0),
                  '', s['content'], '']
    if status == 'error':
        lines += ['---', '', '**ОШИБКА ЗАПУСКА:** %s' % error, '']
    lines += ['---', '', '## Финал наставника', '', final or '(нет)', '']
    try:
        _write(os.path.join(RUNS_DIR, log_name), '\n'.join(lines))
    except OSError:
        log_name = ''
    entry['logFile'] = log_name
    return entry


def team_history(qs):
    try:
        limit = max(1, min(50, int(qs.get('limit', ['15'])[0])))
    except ValueError:
        limit = 15
    try:
        idx = json.loads(_read(RUNS_INDEX_PATH, '[]'))
        if not isinstance(idx, list):
            idx = []
    except (ValueError, TypeError):
        idx = []
    return {'runs': idx[:limit]}
