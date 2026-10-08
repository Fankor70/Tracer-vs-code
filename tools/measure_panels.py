# -*- mode: python ; coding: utf-8 -*-
"""Точная геометрия эталонного скриншота: окно, колонки, панели, шаг текста.

    python tools/measure_panels.py [путь-к-png]
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


def window_box(im):
    """Прямоугольник окна: тёмные и несерые пиксели."""
    w, h = im.size
    px = im.load()
    xs0, xs1, ys0, ys1 = w, 0, h, 0
    step = 2
    for y in range(0, h, step):
        for x in range(0, w, step):
            p = px[x, y]
            if lum(p) < 45 and sat(p) < 30:
                if x < xs0: xs0 = x
                if x > xs1: xs1 = x
                if y < ys0: ys0 = y
                if y > ys1: ys1 = y
    return xs0, ys0, xs1, ys1


def runs(flags, min_len=3):
    """Непрерывные серии True -> (начало, длина)."""
    out, start = [], None
    for i, v in enumerate(flags):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out.append((start, i - start))
            start = None
    if start is not None and len(flags) - start >= min_len:
        out.append((start, len(flags) - start))
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    im = Image.open(path).convert('RGB')
    w, h = im.size
    px = im.load()

    x0, y0, x1, y1 = window_box(im)
    print('ОКНО: x %d..%d (ширина %d), y %d..%d (высота %d)'
          % (x0, x1, x1 - x0, y0, y1, y1 - y0))

    # --- фон внутри окна ---
    inner = Counter()
    for y in range(y0, y1 + 1, 3):
        for x in range(x0, x1 + 1, 3):
            inner[px[x, y]] += 1
    print('\nФОН ОКНА (топ-8):')
    for col, n in inner.most_common(8):
        print('  #%02x%02x%02x  L=%3d  %5.1f%%' % (
            col[0], col[1], col[2], lum(col), 100.0 * n / sum(inner.values())))

    # --- вертикальные линии рамок ---
    # Рамка — пиксель заметно светлее фона, но намного темнее текста.
    bg = inner.most_common(1)[0][0]
    def is_border(p):
        d = lum(p) - lum(bg)
        return 4 < d < 34 and sat(p) < 40

    hgt = y1 - y0
    colcount = []
    for x in range(x0, x1 + 1):
        c = 0
        for y in range(y0, y1 + 1, 2):
            if is_border(px[x, y]):
                c += 1
        colcount.append(c)
    thr = max(6, int(hgt * 0.12))
    vlines = [(x0 + s, ln) for s, ln in runs([c >= thr for c in colcount], 2)]
    print('\nВЕРТИКАЛЬНЫЕ ЛИНИИ (границы колонок), y-скорость > %d:' % thr)
    for x, ln in vlines:
        print('  x=%4d  длина %d' % (x, ln))

    # --- горизонтальные линии ---
    wid = x1 - x0
    rowcount = []
    for y in range(y0, y1 + 1):
        c = 0
        for x in range(x0, x1 + 1, 2):
            if is_border(px[x, y]):
                c += 1
        rowcount.append(c)
    rthr = max(6, int(wid * 0.08))
    hlines = [(y0 + s, ln) for s, ln in runs([c >= rthr for c in rowcount], 2)]
    print('\nГОРИЗОНТАЛЬНЫЕ ЛИНИИ, x-скорость > %d:' % rthr)
    for y, ln in hlines:
        print('  y=%4d  длина %d' % (y, ln))

    # --- шаг текстовых строк в левой колонке ---
    # Текст = пиксели заметно светлее фона и заметно ярче рамки.
    lx0, lx1 = x0 + 10, x0 + int((x1 - x0) * 0.30)
    def is_text(p):
        d = lum(p) - lum(bg)
        return d > 38 and sat(p) < 70
    rows = []
    for y in range(y0, y1 + 1):
        c = 0
        for x in range(lx0, lx1):
            if is_text(px[x, y]):
                c += 1
        rows.append(c)
    text_rows = [(y0 + s, ln) for s, ln in runs([c >= 2 for c in rows], 1)]
    print('\nТЕКСТОВЫЕ СТРОКИ в левой колонке (x %d..%d): %d шт.'
          % (lx0, lx1, len(text_rows)))
    tops = [t for t, _ in text_rows]
    deltas = [tops[i + 1] - tops[i] for i in range(len(tops) - 1)]
    good = [d for d in deltas if 4 <= d <= 30]
    if good:
        good.sort()
        print('  шаг строки: медиана %d, чаще всего %d, мин %d, макс %d'
              % (good[len(good) // 2], good[len(good) // 2], good[0], good[-1]))
    print('  первые 30 верхних краёв:', tops[:30])

    # --- цвета текста по яркости ---
    buckets = Counter()
    for y in range(y0, y1 + 1, 2):
        for x in range(x0, x1 + 1, 2):
            p = px[x, y]
            d = lum(p) - lum(bg)
            if d > 38:
                buckets[(p[0] // 32 * 32, p[1] // 32 * 32, p[2] // 32 * 32)] += 1
    print('\nЦВЕТА ТЕКСТА (грубо, топ-10):')
    for col, n in buckets.most_common(10):
        print('  #%02x%02x%02x  L=%3d  %6d' % (col[0], col[1], col[2], lum(col), n))
    return 0


if __name__ == '__main__':
    sys.exit(main())
