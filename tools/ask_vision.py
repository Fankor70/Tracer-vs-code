# -*- mode: python ; coding: utf-8 -*-
"""Спросить у локальной визуальной модели, что на картинке.

Зачем этот скрипт существует. Зрения нет ни у меня, ни у агентов: модель
сессии изображения не принимает, а `visual-judge` падает с ошибкой провайдера.
Эмбеддинг тут не помогает — он даёт вектор, а не текст.

Но есть другой путь: **визуально-языковая модель, запущенная локально через
Ollama, превращает картинку в текст, а текст я прочитать могу.** Всё
считается на машине пользователя: ни ключей, ни отправки наружу.

    python tools/ask_vision.py --image снимок.png --ask "что здесь нарисовано"
    python tools/ask_vision.py --image снимок.png --task map
    python tools/ask_vision.py --image снимок.png --ask "..." --model minicpm-v4.6

Готовые задачи (`--task`):
  map      — подробная карта интерфейса: панели, колонки, подписи
  text     — только читаемый текст, построчно
  colors   — какие цвета и где
  layout   — геометрия: колонки, отступы, что где начинается
"""
import argparse
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request

OLLAMA = os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')
DEFAULT_MODEL = os.environ.get('CODETIME_VISION_MODEL', 'gemma4:e2b')

TASKS = {
    'map': ('Describe this screenshot in detail. It is a dark terminal-style app. '
            'List every column from left to right, every panel title exactly as '
            'written, and every line of text verbatim. Be precise, do not invent.'),
    'text': ('Transcribe ALL text in this image, line by line, in reading order, '
             'top to bottom and left to right. Keep punctuation and brackets. '
             'Output only the transcription.'),
    'colors': ('Which colours dominate this image, and where exactly is each used? '
               'Name the background, the panels, the accent colours and the text '
               'colours. Answer as a list.'),
    'layout': ('How many columns does this layout have? Estimate the width of each '
               'in pixels, the gaps between them, and the outer margins. Where do '
               'the panel titles sit? Answer with numbers.'),
}


def ask(image_path, question, model, timeout=600):
    with open(image_path, 'rb') as f:
        raw = f.read()
    # Крупные картинки тормозят и переполняют контекст: ужимаем заранее.
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert('RGB')
        if max(im.size) > 1400:
            im.thumbnail((1400, 1400), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format='JPEG', quality=90)
        raw = buf.getvalue()
    except Exception:
        pass                                   # без Pillow — шлём как есть

    body = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': question,
                      'images': [base64.b64encode(raw).decode('ascii')]}],
        'stream': False,
    }).encode('utf-8')
    req = urllib.request.Request(OLLAMA + '/api/chat', data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode('utf-8'))
    return (out.get('message') or {}).get('content', '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', required=True)
    ap.add_argument('--ask', help='свой вопрос')
    ap.add_argument('--task', choices=sorted(TASKS), help='готовая задача')
    ap.add_argument('--model', default=DEFAULT_MODEL)
    args = ap.parse_args()

    if not os.path.isfile(args.image):
        print('нет файла: %s' % args.image)
        return 2
    question = args.ask or TASKS.get(args.task or 'map', TASKS['map'])

    try:
        tags = json.loads(urllib.request.urlopen(OLLAMA + '/api/tags',
                                                 timeout=10).read())
    except Exception as e:
        print('Ollama не отвечает: %r' % e)
        return 2
    have = [m.get('name', '') for m in tags.get('models', [])]
    # Тег — часть имени: «gemma4:e2b» хранится именно так, без «:latest».
    # Раньше сравнение отбрасывало тег с обеих сторон и объявляло
    # установленную мододу отсутствующей.
    wanted = args.model.split(':')[0]
    if not any(n.split(':')[0] == wanted for n in have):
        print('модель %s не установлена. Есть: %s'
              % (args.model, ', '.join(have) or 'ничего'))
        print('Поставь: ollama pull %s' % args.model)
        return 2
    if not any(n == args.model for n in have):
        # Установлен другой тег той же модели — берём установленный.
        same = [n for n in have if n.split(':')[0] == wanted]
        if same:
            args.model = same[0]

    try:
        answer = ask(args.image, question, args.model)
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8', 'replace')[:400]
        except Exception:
            pass
        print('Ollama ответила ошибкой %d: %s' % (e.code, detail))
        return 3
    except Exception as e:
        print('не получилось спросить: %r' % e)
        return 3

    print(answer.strip())
    return 0


if __name__ == '__main__':
    sys.exit(main())
