# -*- coding: utf-8 -*-
"""CodeTime Наставник — встроенный ИИ-помощник по фронтенду (v1.9.1).

Всё состояние хранится в ОБЫЧНОЙ ПАПКЕ на ПК пользователя:
  %USERPROFILE%\\CodeTimeMentor\\
    config.json   — подключение к ИИ (любой OpenAI-совместимый API) и GitHub
    role.txt      — роль/характер наставника (можно править блокнотом)
    journal.md    — Журнал прогресса (память между чатами)
    plan.md       — дорожная карта обучения
    history/      — переписка по дням (JSON)
    layouts/      — присланные фото макетов

Наставник сам создаёт эту папку при первом запуске («сам поднимет всё,
что ему нужно»). Вставлять ключи НЕ обязательно — работают 3 режима:
  1. ДЕМО (без всяких ключей) — бесплатная публичная модель Pollinations
     openai-fast (GPT-OSS 20B); текст и код, лимит ~1 запрос/3 сек;
  2. GITHUB (один бесплатный токен GitHub: Contents: Read + Models: Read) —
     и репозиторий читает, и полноценный ИИ GitHub Models
     openai/gpt-4.1-mini с разбором фото макетов;
  3. СВОЙ КЛЮЧ — любой OpenAI-совместимый API (Z.ai, OpenRouter, VseGPT…).
Режим выбирается автоматически: свой ключ > GitHub-токен > демо.

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

DEFAULT_CONFIG = {
    'api_base': '',       # например https://api.z.ai/api/paas/v4
    'api_key': '',
    'model': '',          # текстовая модель, например glm-4.6
    'vision_model': '',   # модель для фото макетов, например glm-4.5v
    'gh_token': '',       # fine-grained PAT: Contents: Read + Models: Read
    'repo': '',           # owner/name репозитория с вёрсткой
}

# --- Демо-ИИ: бесплатная публичная модель, вообще БЕЗ ключей (v1.9.1) ---
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

# Инструкции-обёртки для кнопок чата
MODE_INSTRUCTIONS = {
    'code': ('ЗАДАЧА: разбор кода студента. Работай по режиму «Разбор кода»: '
             'по порядку — баги, семантика/доступность, адаптив/единицы, '
             'структура CSS, мелочи. По каждой проблеме: где, почему плохо, '
             'ДО/ПОСЛЕ на его коде.'),
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
    _write_if_missing(CONFIG_PATH,
                      json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2))
    _write_if_missing(ROLE_PATH, DEFAULT_ROLE)
    _write_if_missing(JOURNAL_PATH, DEFAULT_JOURNAL)
    _write_if_missing(PLAN_PATH, DEFAULT_PLAN)


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
    if cfg['api_key'] and cfg['api_base']:
        mode = 'key'          # свой ключ, любой OpenAI-совместимый API
    elif cfg['gh_token']:
        mode = 'github'       # GitHub Models по токену (бесплатно, с vision)
    else:
        mode = 'demo'         # демо-ИИ вообще без ключей
    return {
        'folder': MENTOR_DIR,
        'configured': bool(cfg['api_key'] and cfg['api_base']),
        'mode': mode,
        'demoModel': DEMO_LLM_MODEL,
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
            body = e.read().decode('utf-8', 'replace')[:400]
        except Exception:
            pass
        if e.code == 401:
            raise MentorError('Ключ отклонён (401). Проверьте ключ API в Настройках Наставника.')
        if e.code == 404:
            raise MentorError('Адрес API не найден (404). Проверьте «Адрес API» — обычно он заканчивается на /v1 или /api/paas/v4.')
        if e.code == 429:
            raise MentorError('Лимит запросов (429): на аккаунте закончился баланс/квота.')
        raise MentorError('API вернул ошибку %s: %s' % (e.code, body or e.reason))
    except MentorError:
        raise
    except Exception as e:
        raise MentorError('Нет связи с API (%s). Проверьте интернет и адрес.' % e)


def _llm_params(cfg, model):
    """Куда реально стучаться: (base, key, model, mode).
    Приоритет: свой ключ > GitHub Models по gh-токену > демо-ИИ без ключей."""
    if cfg['api_key'] and cfg['api_base']:
        return (cfg['api_base'].rstrip('/'), cfg['api_key'],
                model or cfg['model'] or '', 'key')
    if cfg['gh_token']:
        return (GH_MODELS_BASE, cfg['gh_token'],
                model or cfg['model'] or GH_MODELS_MODEL, 'github')
    return (DEMO_LLM_BASE, '', model or DEMO_LLM_MODEL, 'demo')


def _parse_content(data):
    """Достаёт текст из ответа chat/completions (content бывает списком)."""
    try:
        content = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        raise MentorError('Модель вернула неожиданный ответ: %s'
                          % json.dumps(data, ensure_ascii=False)[:300])
    if isinstance(content, list):  # некоторые провайдеры шлют список частей
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get('type') == 'text':
                parts.append(p.get('text', ''))
        content = '\n'.join(parts)
    content = (content or '').strip()
    if not content:
        # reasoning-модели иногда отдают весь бюджет размышлениям —
        # тогда хотя бы вернём сам ход мысли
        reasoning = ''
        try:
            reasoning = (data['choices'][0]['message'].get('reasoning')
                         or '').strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            pass
        content = reasoning
    if not content:
        raise MentorError('Модель вернула пустой ответ.')
    return content


def llm_chat(messages, model, timeout=240):
    cfg = load_config()
    base, key, model, mode = _llm_params(cfg, model)
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'CodeTime-Mentor/' + _ver(),
    }
    if mode == 'demo':
        # бесплатно и без ключей; referrer обязателен (иначе 402).
        # ВАЖНО: у анонимного тарифа жёсткий троттлинг по IP — при частых
        # запросах API отвечает 402, поэтому ждём и повторяем.
        payload = {'model': model, 'messages': messages,
                   'max_tokens': 4000, 'stream': False,
                   'referrer': DEMO_LLM_REFERRER}
        last_err = None
        # фолбэк-алиасы модели + паузы против троттлинга (402/429)
        for m in dict.fromkeys([model, DEMO_LLM_MODEL, 'openai']):
            for d in (0, 25):
                if d:
                    time.sleep(d)
                try:
                    data = _http_json(base, dict(payload, model=m),
                                      headers, timeout)
                    return _parse_content(data)
                except MentorError as e:
                    last_err = e
                    if '402' not in str(e) and '429' not in str(e):
                        break  # не троттлинг — пробуем следующую модель
        if last_err and ('402' in str(last_err) or '429' in str(last_err)):
            raise MentorError(
                'Демо-ИИ перегружен (общий бесплатный лимит на всех). '
                'Подождите 1–2 минуты и повторите — либо подключите '
                'GitHub-токен или свой ключ в Настройках: там лимиты личные.')
        raise last_err or MentorError('Демо-ИИ недоступен.')
    headers['Authorization'] = 'Bearer ' + key
    payload = {'model': model, 'messages': messages,
               'temperature': 0.6, 'max_tokens': 4000, 'stream': False}
    data = _http_json(base + '/chat/completions', payload, headers, timeout)
    return _parse_content(data)


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
    """Проверка ИИ: показывает, какой режим реально работает
    (свой ключ / GitHub Models / демо без ключей)."""
    cfg = load_config()
    base, key, model, mode = _llm_params(cfg, cfg['model'])
    headers = {'User-Agent': 'CodeTime-Mentor/' + _ver()}
    if mode == 'demo':
        payload = {'model': DEMO_LLM_MODEL,
                   'messages': [{'role': 'user', 'content': 'ping'}],
                   'max_tokens': 30, 'stream': False,
                   'referrer': DEMO_LLM_REFERRER}
        headers['Content-Type'] = 'application/json'
        _http_json(base, payload, headers, 60)
        return {'ok': True, 'via': 'chat', 'mode': 'demo',
                'model': DEMO_LLM_MODEL, 'models': []}
    headers['Authorization'] = 'Bearer ' + key
    url = base + '/models'
    try:
        data = _http_json(url, None, headers, 30)
        ids = sorted({(m.get('id') or '?') for m in data.get('data', [])
                      if isinstance(m, dict)})[:40]
        return {'ok': True, 'via': 'models', 'mode': mode,
                'model': model, 'models': ids}
    except MentorError as e:
        # /models есть не у всех — пробуем минимальный chat-запрос
        if '404' not in str(e):
            raise
    payload = {'model': model or 'glm-4.6',
               'messages': [{'role': 'user', 'content': 'ping'}],
               'max_tokens': 5, 'stream': False}
    headers['Content-Type'] = 'application/json'
    _http_json(base + '/chat/completions', payload, headers, 60)
    return {'ok': True, 'via': 'chat', 'mode': mode,
            'model': model, 'models': []}


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
# Контекст чата: роль + журнал + план + снимок GitHub
# ============================================================

def _tail(s, limit):
    s = s or ''
    return s[-limit:] if len(s) > limit else s


def build_system_prompt(cfg):
    role = _read(ROLE_PATH, DEFAULT_ROLE) or DEFAULT_ROLE
    journal = _read(JOURNAL_PATH)
    plan = _read(PLAN_PATH)
    p = role.strip()
    p += '\n\n=== ЖУРНАЛ ПРОГРЕССА (память о прошлых сессиях) ===\n' + _tail(journal, 7000)
    if plan.strip():
        p += '\n\n=== ДОРОЖНАЯ КАРТА (plan.md) ===\n' + _tail(plan, 3500)
    try:
        cache = json.loads(_read(GH_CACHE_PATH, '{}'))
        snap = cache.get('snapshot') or ''
        if snap:
            p += ('\n\n=== СНИМОК GITHUB-РЕПОЗИТОРИЯ (собран %s; студент может '
                  'попросить файл через «файл: путь») ===\n%s'
                  % (cache.get('ts', '?'), _tail(snap, 5000)))
    except (ValueError, TypeError):
        pass
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


def api_chat(data):
    msg = (data.get('message') or '').strip()
    mode = (data.get('mode') or 'free').strip()
    img_b64 = (data.get('imageB64') or '').strip()
    img_mime = (data.get('imageMime') or 'image/jpeg').strip()
    if not msg and not img_b64:
        raise MentorError('Пустое сообщение.')

    cfg = load_config()
    _base, _key, _model, llm_mode = _llm_params(cfg, cfg['model'])
    if img_b64 and llm_mode == 'demo':
        raise MentorError(
            'В демо-режиме (без ключей) у модели нет «зрения» — фото макета '
            'она не увидит. Подключите бесплатный ИИ по GitHub-токену '
            '(мастер настройки: один токен даст и репозиторий, и '
            'gpt-4.1-mini с фото) или любой свой ключ в Настройках.')

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

    messages = [{'role': 'system', 'content': build_system_prompt(cfg)}]
    messages.extend(load_history_tail())
    if img_b64:
        # фото макета: контент списком частей (OpenAI-совместимый vision-формат)
        user_content = [
            {'type': 'text', 'text': user_text},
            {'type': 'image_url',
             'image_url': {'url': 'data:%s;base64,%s' % (img_mime, img_b64)}},
        ]
        messages.append({'role': 'user', 'content': user_content})
        model = cfg['vision_model'] or cfg['model']
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
        model = cfg['model']

    logging.info('Наставник: запрос к модели %s (режим %s, фото: %s)',
                 model, mode, bool(img_b64))
    reply = llm_chat(messages, model)

    today = datetime.now().strftime('%Y-%m-%d')
    try:
        _append_history(today, 'user', msg if msg else '(фото макета)')
        _append_history(today, 'assistant', reply)
    except OSError:
        logging.exception('Наставник: не сохранилась история')

    # блоки ```журнал ...``` → автоматически в journal.md
    saved = False
    for block in _JOURNAL_BLOCK_RE.findall(reply):
        journal_append(block.strip())
        saved = True

    return {'reply': reply, 'journalSaved': saved}


def _append_history(day, role, content):
    ensure_all()
    path = os.path.join(HISTORY_DIR, day + '.json')
    try:
        arr = json.loads(_read(path, '[]'))
    except (ValueError, TypeError):
        arr = []
    arr.append({'role': role, 'content': content,
                'ts': datetime.now().isoformat(timespec='seconds')})
    _write(path, json.dumps(arr[-200:], ensure_ascii=False))
