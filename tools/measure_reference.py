# -*- mode: python ; coding: utf-8 -*-
"""Измерение эталонного скриншота: реальные числа вместо догадок.

Картинку нечем «посмотреть» — ни мне, ни агентам. Зато её можно измерить
пикселями: ширины колонок, отступы, высоту строки, точные цвета. Это и есть
единственный способ приблизиться к «как на скриншоте».

    python tools/measure_reference.py [путь-к-png]
"""
import os
import sys
from collections import Counter

from PIL import Image

DEFAULT = (r'C:\Users\Fankor\.zcode\cli\image-cache'
           r'\sess_fce40407-f3e2-4618-93bf-94a64aab90a0'
           r'\image-8fb55c328592af6196c3ed0357965fe1.png')


def lum(p):
    return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]


def sat(p):
    return max(p) - min(p)


def hue_of(p):
    r, g, b = p
    mx, mn = max(p), min(p)
    if mx == mn:
        return 0.0
    d = mx - mn
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60


def ascii_map(im, cols=110, rows=44):
    """Карта яркости — видно, где окно, где колонки, где пусто."""
    w, h = im.size
    g = im.convert('L')
    small = g.resize((cols, rows), Image.LANCZOS)
    px = small.load()
    ramp = ' .:-=+*#%@'
    out = []
    for y in range(rows):
        out.append(''.join(ramp[min(9, px[x, y] * 10 // 256)] for x in range(cols)))
    return out


def column_profile(im, box):
    """Резкость перепадов по X — вертикальные границы колонок и панелей."""
    crop = im.crop(box).convert('L')
    w, h = crop.size
    px = crop.load()
    prof = []
    for x in range(w):
        col = [px[x, y] for y in range(h)]
        prof.append(max(col) - min(col))
    return prof


def row_profile(im, box):
    crop = im.crop(box).convert('L')
    w, h = crop.size
    px = crop.load()
    prof = []
    for y in range(h):
        row = [px[x, y] for x in range(w)]
        prof.append(max(row) - min(row))
    return prof


def edges(prof, thresh, min_gap=6):
    """Индексы локальных пиков выше порога — это границы."""
    hits = []
    for i, v in enumerate(prof):
        if v >= thresh:
            if hits and i - hits[-1] < min_gap:
                if v > prof[hits[-1]]:
                    hits[-1] = i
                continue
            hits.append(i)
    return hits


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not os.path.isfile(path):
        print('нет файла: %s' % path)
        return 1
    im = Image.open(path).convert('RGB')
    w, h = im.size
    print('РАЗМЕР: %d x %d' % (w, h))

    small = im.resize((max(1, w // 4), max(1, h // 4)), Image.LANCZOS)
    counts = Counter(small.getdata())
    print('\nПАЛИТРА (топ-15, уменьшенная копия):')
    for col, n in counts.most_common(15):
        print('  #%02x%02x%02x  %7d  %5.1f%%   L=%3d S=%3d' % (
            col[0], col[1], col[2], n, 100.0 * n / (small.size[0] * small.size[1]),
            lum(col), sat(col)))

    # Цветные акценты: насыщенные и не серые
    accents = [(col, n) for col, n in counts.items() if sat(col) > 40 and lum(col) > 55]
    accents.sort(key=lambda t: -t[1])
    print('\nАКЦЕНТЫ (насыщенные, не серые):')
    for col, n in accents[:12]:
        print('  #%02x%02x%02x  hue=%5.0f  %6d' % (col[0], col[1], col[2], hue_of(col), n))

    print('\nКАРТА ЯРКОСТИ (%d колонок):' % 110)
    for i, line in enumerate(ascii_map(im)):
        print('%3d %s' % (i, line))

    return 0


if __name__ == '__main__':
    sys.exit(main())
