# -*- mode: python ; coding: utf-8 -*-
"""Сравнение отрисовки с эталоном через эмбеддинг.

Зачем. Визуально я картинку не вижу, поэтому «похоже ли» — вопрос без
ответа. Эмбеддинг превращает изображение в вектор, и сходство становится
числом, которое можно гонять от итерации к итерации и ловить откат.

    python tools/compare_screenshot.py --ref эталон.png --shot мой.png
    python tools/compare_screenshot.py --ref эталон.png --shot мой.png --regions 3

ЧЕСТНО О ГРАНИЦАХ. Это смысловая, а не геометрическая мера. Два скриншота
с одинаковым текстом, но разными отступами, будут выглядеть для модели
почти одинаково. Она не скажет «колонка шире на 3 пикселя» — это умеет
Pillow (tools/measure_columns.py), и он точнее. Эмбеддинг отвечает на
другой вопрос: «это вообще тот же экран или я что-то сломал».

Требуется Ollama с моделью, принимающей картинки:

    ollama pull embeddinggemma-2      # тег latest = 740m, умеет Text+Image
    (270m и 570m — только текст, для картинок не годятся)

Всё считается локально: ни ключей, ни отправки наружу.
"""
import argparse
import base64
import io
import json
import math
import os
import sys
import urllib.request

OLLAMA = os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')
MODEL = os.environ.get('CODETIME_EMBED_MODEL', 'embeddinggemma-2')
DASH = '—'


def embed_image(path, size=512):
    """Отдаёт картинку в /api/embed как data-URL. Ollama принимает base64."""
    from PIL import Image
    im = Image.open(path).convert('RGB')
    im.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format='JPEG', quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    body = json.dumps({'model': MODEL,
                       'input': 'data:image/jpeg;base64,' + b64}).encode('utf-8')
    req = urllib.request.Request(OLLAMA + '/api/embed', data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.loads(r.read().decode('utf-8'))
    vecs = out.get('embeddings')
    if not vecs:
        raise RuntimeError('модель вернула пустой результат: %r' % out)
    return vecs[0]


def cosine(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def slice_columns(path, n, size=512):
    """Режет картинку на n вертикальных полос — чтобы найти худшую зону."""
    from PIL import Image
    im = Image.open(path).convert('RGB')
    w, h = im.size
    out = []
    for i in range(n):
        box = (w * i // n, 0, w * (i + 1) // n, h)
        part = im.crop(box)
        part.thumbnail((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        part.save(buf, format='JPEG', quality=92)
        b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        body = json.dumps({'model': MODEL,
                           'input': 'data:image/jpeg;base64,' + b64}).encode('utf-8')
        req = urllib.request.Request(OLLAMA + '/api/embed', data=body,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=300) as r:
            out.append(json.loads(r.read().decode('utf-8'))['embeddings'][0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref', required=True, help='эталон')
    ap.add_argument('--shot', required=True, help='моя отрисовка')
    ap.add_argument('--regions', type=int, default=0,
                    help='резать на N вертикальных зон и найти худшую')
    ap.add_argument('--base', type=float, default=0.0,
                    help='оценка, от которой считать откатом')
    args = ap.parse_args()

    try:
        tags = json.loads(urllib.request.urlopen(OLLAMA + '/api/tags',
                                                 timeout=10).read())
    except Exception as e:
        print('Ollama не отвечает на %s: %r' % (OLLAMA, e))
        print('Запусти её и выполни: ollama pull %s' % MODEL)
        return 2
    have = [m.get('name', '') for m in tags.get('models', [])]
    if not any(m.split(':')[0] == MODEL for m in have):
        print('модель %s не скачана. Есть: %s' % (MODEL, ', '.join(have) or 'ничего'))
        print('Поставь: ollama pull %s' % MODEL)
        return 2

    for p in (args.ref, args.shot):
        if not os.path.isfile(p):
            print('нет файла: %s' % p)
            return 2

    print('модель: %s' % MODEL)
    a = embed_image(args.ref)
    b = embed_image(args.shot)
    score = cosine(a, b)
    print('\nСХОДСТВО ЦЕЛИКОМ: %.4f' % score)
    print('  (вектор: %d измерений)' % len(a))
    if args.base and score < args.base:
        print('  ⚠ откат: было %.4f, стало %.4f' % (args.base, score))
    elif args.base:
        print('  ✓ не хуже прежнего (%.4f)' % args.base)

    if args.regions > 0:
        print('\nПО ЗОНАМ (%d вертикальных полос):' % args.regions)
        ra = slice_columns(args.ref, args.regions)
        rb = slice_columns(args.shot, args.regions)
        rows = []
        for i in range(args.regions):
            s = cosine(ra[i], rb[i])
            rows.append((s, i))
            print('  зона %d (слева направо): %.4f' % (i + 1, s))
        rows.sort()
        worst = rows[0]
        print('\n  худшая зона: №%d, сходство %.4f — правь её' % (worst[1] + 1, worst[0]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
