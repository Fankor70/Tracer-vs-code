# -*- coding: utf-8 -*-
"""
make_icon.py — генерирует tracker/icon.ico для CodeTime.exe.

Рисует программно (PIL): тёмный скруглённый квадрат + зелёный круг-часы
со стрелками + белые фигурные скобки { }. Сохраняет icon.ico с размерами
16/32/48/64 пикселей.
"""

import os

from PIL import Image, ImageDraw

SIZE = 256          # рисуем в большом разрешении, потом уменьшаем
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64)]

DARK = (22, 27, 34, 255)        # тёмный скруглённый квадрат
BORDER = (48, 54, 61, 255)      # тонкая рамка
GREEN = (16, 185, 129, 255)     # акцент — круг-часы
WHITE = (255, 255, 255, 255)    # скобки { }


def draw_icon(size=SIZE):
    """Возвращает PIL.Image с иконкой CodeTime."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # --- тёмный скруглённый квадрат ---
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=size * 0.22,
                        fill=DARK, outline=BORDER,
                        width=max(1, int(size * 0.012)))

    # --- зелёный круг-стрелка часов (справа сверху) ---
    cx, cy, r = size * 0.70, size * 0.30, size * 0.20
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN)
    lw = max(2, int(size * 0.016))
    d.line([cx, cy, cx, cy - r * 0.62], fill=DARK, width=lw)          # часовая
    d.line([cx, cy, cx + r * 0.55, cy + r * 0.25], fill=DARK, width=lw)  # минутная

    # --- белые фигурные скобки { } (угловатые, из отрезков) ---
    bw, bh = size * 0.20, size * 0.52
    y0 = size * 0.30
    stroke = max(2, int(size * 0.035))

    # левая "{"
    x1 = size * 0.26
    left = [(x1 + bw, y0),
            (x1 + bw * 0.25, y0 + bh * 0.10),
            (x1 + bw * 0.75, y0 + bh * 0.50),
            (x1 + bw * 0.25, y0 + bh * 0.90),
            (x1 + bw, y0 + bh)]
    d.line(left, fill=WHITE, width=stroke, joint='curve')

    # правая "}" (зеркально)
    x2 = size * 0.56
    right = [(x2, y0),
             (x2 + bw * 0.75, y0 + bh * 0.10),
             (x2 + bw * 0.25, y0 + bh * 0.50),
             (x2 + bw * 0.75, y0 + bh * 0.90),
             (x2, y0 + bh)]
    d.line(right, fill=WHITE, width=stroke, joint='curve')

    return img


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.ico')
    img = draw_icon(SIZE)
    img.save(out, format='ICO', sizes=ICO_SIZES)
    print('Иконка сохранена: %s (%s)' % (out, ', '.join('%dx%d' % s for s in ICO_SIZES)))


if __name__ == '__main__':
    main()
