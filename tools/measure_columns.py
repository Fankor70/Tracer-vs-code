# -*- mode: python ; coding: utf-8 -*-
"""Колонки и зазоры: ищем промежутки пустого фона между текстом.

    python tools/measure_columns.py [путь-к-png]
"""
import os
import sys
from collections import Counter

from PIL import Image

DEFAULT = (r'C:\Users\Fankor\.zcode\cli\image-cache'
           r'\sess_fce40407-f3e2-4618-93bf-94a64aab90a0'
           r'\image-8fb55c328592af6196c3ed0357965fe1.png')

BG = (0x0f, 0x10, 0x15)


def lum(p):
    return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]


def sat(p):
    return max(p) - min(p)


def is_ink(p, thr=14):
    """Пиксель содержит что-то: текст, рамку или заливку."""
    d = lum(p) - lum(BG)
    return d > thr or sat(p) > 18


def runs(flags, min_len=1):
    out, start = [], None
    for i, v in enumerate(flags):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - start))
            start = None
    if start is not None:
        out.append((start, len(flags) - start))
    return [r for r in out if r[1] >= min_len]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    im = Image.open(path).convert('RGB')
    px = im.load()
    X0, X1, Y0, Y1 = 78, 1046, 50, 648

    # --- вертикальные промежутки между колонками ---
    print('ПУСТЫЕ ПРОМЕЖУТКИ ПО X (собираются по 60 строкам содержимого):')
    tally = Counter()
    for y in range(Y0 + 40, Y1 - 20, 3):
        flags = [is_ink(px[x, y]) for x in range(X0, X1 + 1)]
        for s, ln in runs([not f for f in flags], 18):
            tally[(X0 + s, ln)] += 1
    for (x, ln), n in sorted(tally.items(), key=lambda t: (-t[1], -t[0][1]))[:10]:
        if n >= 12:
            print('  x=%4d..%4d  ширина %3d  встречается в %d строках' % (x, x + ln, ln, n))

    # --- горизонтальные зазоры (между панелями) ---
    print('\nПУСТЫЕ ПРОМЕЖУТКИ ПО Y (собираются по 60 столбцам содержимого):')
    tally = Counter()
    for x in range(X0 + 20, X1 - 20, 3):
        flags = [is_ink(px[x, y]) for y in range(Y0, Y1 + 1)]
        for s, ln in runs([not f for f in flags], 8):
            tally[(Y0 + s, ln)] += 1
    for (y, ln), n in sorted(tally.items(), key=lambda t: (-t[1], -t[0][1]))[:10]:
        if n >= 10:
            print('  y=%4d..%4d  высота %3d  встречается в %d столбцах' % (y, y + ln, ln, n))

    # --- точная полоса прогресса: где в статус-панели ---
    print('\nПОИСК ПОЛОСЫ ПРОГРЕССА (яркий янтарный горизонтальный блоб):')
    best = []
    for y in range(Y0, Y0 + 260):
        run = 0
        for x in range(X0, X0 + 420):
            p = px[x, y]
            if lum(p) > 90 and sat(p) > 30 and p[0] > p[2] + 20:
                run += 1
            else:
                if run > 30:
                    best.append((y, x - run, run))
                run = 0
    for y, x, ln in best[:8]:
        print('  y=%4d  x=%4d..%4d  длина %3d' % (y, x, x + ln, ln))
    if best:
        y, x, ln = best[0]
        print('  цвет полосы: #%02x%02x%02x' % tuple(px[x + ln // 2, y]))

    # --- цвета акцентов в полном разрешении ---
    print('\nАКЦЕНТЫ (полное разрешение, насыщенные и яркие):')
    acc = Counter()
    for y in range(Y0, Y1 + 1, 2):
        for x in range(X0, X1 + 1, 2):
            p = px[x, y]
            if sat(p) > 45 and lum(p) > 70:
                acc[p] += 1
    groups = []
    for col, n in acc.most_common(400):
        near = False
        for g in groups:
            if (abs(g[0][0] - col[0]) < 26 and abs(g[0][1] - col[1]) < 26
                    and abs(g[0][2] - col[2]) < 26):
                g[1] += n
                near = True
                break
        if not near and len(groups) < 12:
            groups.append([col, n])
    for col, n in sorted(groups, key=lambda g: -g[1]):
        print('  #%02x%02x%02x  L=%3d S=%3d  пикселей ~%d' % (
            col[0], col[1], col[2], lum(col), sat(col), n))

    # --- высоты строк текста точно, по левой колонке ---
    print('\nШАГ ТЕКСТА (полосами по 40px левой колонки):')
    for band_start in range(Y0 + 20, Y0 + 240, 40):
        tops = []
        for y in range(band_start, band_start + 40):
            c = sum(1 for x in range(X0 + 15, X0 + 380)
                    if lum(px[x, y]) - lum(BG) > 34 and sat(px[x, y]) < 70)
            tops.append((y, c))
        rows = [y for y, c in tops if c >= 2]
        d = [rows[i + 1] - rows[i] for i in range(len(rows) - 1)]
        d = [v for v in d if 3 <= v <= 24]
        if d:
            d.sort()
            print('  y %d..%d: строк %2d, шаг медиана %d, набор %s'
                  % (band_start, band_start + 40, len(rows), d[len(d) // 2],
                     sorted(Counter(d).items(), key=lambda t: -t[1])[:4]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
