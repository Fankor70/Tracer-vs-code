# -*- coding: utf-8 -*-
"""
layout_analyzer — офлайн-разбор скриншота макета веб-страницы на блоки.

Вход:  dataURL ('data:image/png;base64,...' | jpeg | webp)
Выход: {'blocks': [{'name', 'minutes', 'share', 'thumb'}, ...]}

Алгоритм (полностью офлайн, только Pillow, без numpy):
  1. Декодируем base64, открываем картинку, приводим к RGB,
     уменьшаем до ширины <= 560 px (thumbnail, пропорции сохраняются).
  2. Считаем среднюю яркость каждой строки (convert('L') + getdata).
  3. «Энергия» границы между соседними строками = среднее |a-b| по строке.
  4. Границы блоков — локальные пики энергии выше адаптивного порога
     (mean + 1.5*std по всем энергиям).
  5. Соседние полосы с ПОХОЖИМ средним цветом сливаем (повторяющиеся
     ряды карточек/полос не должны дробить одну секцию).
  6. Полосы ниже 4% высоты сливаем с соседью через самую слабую границу
     (от повторяющихся рядов защищает цветовое слияние из п. 5).
  7. Если блоков больше 8 — срезаем самые слабые границы.
  8. «Сложность» полосы (0..1.6) = нормированная энергия внутри полосы
     + разнообразие квантованных цветов RGB-сэмпла строки полосы.
  9. minutes = clamp(round(8 + 120*share*(0.6+0.8*complexity)), 8, 180).

Оценка приблизительная: это эвристика, а не нейросеть. Любая ошибка
разбора -> ValueError с русским сообщением.

Импорт Pillow — внутри функции: без Pillow остальной сервер продолжает
работать, а /api/plan/analyze вернёт понятную ошибку (PillowMissingError).
"""

import base64
import binascii
import io
import re
import math

__all__ = ['analyze_layout_dataurl', 'PillowMissingError']

MAX_DATAURL_BYTES = 8 * 1024 * 1024   # ~8 МБ на декодированное изображение
TARGET_WIDTH = 560                    # ширина рабочего изображения
MAX_HEIGHT = 4000                     # потолок высоты (защита от памяти)
MIN_SIZE = 16                         # минимальный размер стороны
MIN_BAND_FRAC = 0.04                  # полосы тоньше 4% высоты сливаем (хедер ~6% выживает)
MAX_BLOCKS = 8                        # максимум блоков (крупные блоки)
COLOR_MERGE_BITS = 4                  # средний цвет полосы квантуем >>4 (16 ступеней)

_DATAURL_RE = re.compile(
    r'^data:image/(png|jpe?g|webp);base64,([A-Za-z0-9+/=\s]+)$')

JPEG_MIME = {'jpeg': 'jpeg', 'jpg': 'jpeg', 'png': 'png', 'webp': 'webp'}


class PillowMissingError(Exception):
    """Pillow не установлена — разбор макета недоступен."""


def analyze_layout_dataurl(dataurl):
    """Разбирает dataURL скриншота макета на блоки.

    Возвращает {'blocks': [{'name': str, 'minutes': int,
                             'share': float, 'thumb': str}, ...]}.
    Бросает PillowMissingError (нет Pillow) или ValueError
    (некорректные данные/изображение).
    """
    try:
        from PIL import Image
    except Exception as e:
        raise PillowMissingError(
            'Разбор макета недоступен: не установлена Pillow (pip install pillow). %r' % e)

    if not isinstance(dataurl, str) or not dataurl.strip():
        raise ValueError('Не передано изображение (ожидался dataURL).')
    m = _DATAURL_RE.match(dataurl.strip())
    if not m:
        raise ValueError('Ожидается dataURL вида data:image/png|jpeg|webp;base64,...')
    fmt = JPEG_MIME[m.group(1)]
    b64 = re.sub(r'\s+', '', m.group(2))
    if len(b64) > MAX_DATAURL_BYTES:   # base64 ~4/3 от размера файла
        raise ValueError('Изображение слишком большое (лимит ~8 МБ).')
    try:
        raw = base64.b64decode(b64 + '=' * (-len(b64) % 4), validate=False)
    except (binascii.Error, ValueError) as e:
        raise ValueError('Не удалось декодировать base64: %r' % e)
    if not raw:
        raise ValueError('Пустое изображение.')
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:
        raise ValueError('Не удалось прочитать изображение (%s): %r' % (fmt, e))

    img = img.convert('RGB')
    w, h = img.size
    if w < MIN_SIZE or h < MIN_SIZE:
        raise ValueError('Изображение слишком маленькое (минимум %dx%d пикселей).'
                         % (MIN_SIZE, MIN_SIZE))
    img.thumbnail((TARGET_WIDTH, MAX_HEIGHT))   # только уменьшение, пропорции те же
    w, h = img.size

    energy = _boundary_energy(img, h)   # считаем один раз для всего кадра
    bands = _find_bands(energy, h)
    bands = _merge_similar_bands(img, bands, h)
    bands = _merge_small_final(img, bands, energy, h)
    blocks = _describe_bands(img, bands, h, energy)
    return {'blocks': blocks}


# ------------------------------------------------------------
# Шаги 2-6: границы и полосы
# ------------------------------------------------------------

def _boundary_energy(img, h):
    """energy[y] = среднее |строка_y - строка_{y-1}| по яркостям (y = 1..h-1)."""
    g = img.convert('L')
    w, _ = g.size
    px = list(g.getdata())
    energy = [0.0] * h
    prev = px[0:w]
    for y in range(1, h):
        cur = px[y * w:(y + 1) * w]
        s = 0
        for a, b in zip(prev, cur):
            s += a - b if a > b else b - a
        energy[y] = s / float(w)
        prev = cur
    return energy


def _find_bands(energy, h):
    """Разбивает высоту изображения на полосы-блоки: [(start, end), ...]."""
    # адаптивный порог по всем энергиям
    vals = energy[1:]
    mean = sum(vals) / float(len(vals)) if vals else 0.0
    var = sum((v - mean) ** 2 for v in vals) / float(len(vals)) if vals else 0.0
    threshold = mean + 1.5 * math.sqrt(var)

    # локальные пики выше порога -> кандидаты в границы
    bounds = []
    for y in range(1, h):
        if energy[y] <= threshold:
            continue
        left = energy[y - 1] if y - 1 >= 1 else 0.0
        right = energy[y + 1] if y + 1 < h else 0.0
        if energy[y] >= left and energy[y] >= right:
            bounds.append(y)

    bands = _bands_from_bounds(bounds, h)
    bands = _merge_small_bands(bands, bounds, energy, h)
    bands = _cap_block_count(bands, bounds, energy, h)
    return bands


def _merge_small_final(img, bands, energy, h):
    """Финальная добивка: полосы < MIN_BAND_FRAC сливаем с более ПОХОЖИМ
    по цвету соседом (после cap/similar могли остаться микрополосы)."""
    min_h = max(1, int(round(MIN_BAND_FRAC * h)))
    while len(bands) > 1:
        idx = min(range(len(bands)), key=lambda i: bands[i][1] - bands[i][0])
        s, e = bands[idx]
        if e - s >= min_h:
            break
        cands = []
        if idx > 0:
            cands.append(idx - 1)
        if idx < len(bands) - 1:
            cands.append(idx + 1)
        if not cands:
            break
        if len(cands) == 1:
            tgt = cands[0]
        else:
            my = _band_avg_color(img, s, e)

            def dist(c):
                return (abs(c[0] - my[0]) + abs(c[1] - my[1]) +
                        abs(c[2] - my[2]))

            ca = _band_avg_color(img, bands[cands[0]][0], bands[cands[0]][1])
            cb = _band_avg_color(img, bands[cands[1]][0], bands[cands[1]][1])
            tgt = cands[0] if dist(ca) <= dist(cb) else cands[1]
        lo, hi = min(idx, tgt), max(idx, tgt)
        bands[lo] = (bands[lo][0], bands[hi][1])
        del bands[hi]
    return bands


def _merge_similar_bands(img, bands, h):
    """Сливает соседние полосы с похожим СРЕДНИМ цветом (цепочно).
    Повторяющиеся ряды карточек/полос внутри одной секции дают почти
    одинаковый средний цвет — их склеиваем в один большой блок."""
    if len(bands) <= 1:
        return bands
    shift = COLOR_MERGE_BITS
    avg = [_band_avg_color(img, s, e) for s, e in bands]

    def same(a, b):
        return (a[0] >> shift, a[1] >> shift, a[2] >> shift) == \
               (b[0] >> shift, b[1] >> shift, b[2] >> shift)

    changed = True
    while changed and len(bands) > 1:
        changed = False
        for i in range(len(bands) - 1):
            if same(avg[i], avg[i + 1]):
                bands[i] = (bands[i][0], bands[i + 1][1])
                del bands[i + 1]
                del avg[i + 1]
                changed = True
                break
    return bands


def _band_avg_color(img, s, e):
    """Средний RGB полосы (сэмпл по сетке, без лишней работы)."""
    rgb = img.convert('RGB') if img.mode != 'RGB' else img
    w = rgb.size[0]
    band_h = max(1, e - s)
    step_y = max(1, band_h // 24)
    step_x = max(1, w // 48)
    px = rgb.load()
    rs = gs = bs = n = 0
    for y in range(s, e, step_y):
        for x in range(0, w, step_x):
            r, g, b = px[x, y]
            rs += r
            gs += g
            bs += b
            n += 1
    if not n:
        return (0, 0, 0)
    return (rs // n, gs // n, bs // n)


def _bands_from_bounds(bounds, h):
    """Границы (индексы строк) -> полосы [(start, end), ...]."""
    cuts = sorted(set(bounds))
    starts = [0] + cuts
    ends = cuts + [h]
    return [(s, e) for s, e in zip(starts, ends) if e > s]


def _merge_small_bands(bands, bounds, energy, h):
    """Слияние полос < 3.5% высоты (убираем самую слабую соседнюю границу)."""
    min_h = max(1, int(round(MIN_BAND_FRAC * h)))
    changed = True
    while changed and len(bands) > 1:
        changed = False
        # самая короткая полоса
        idx = min(range(len(bands)), key=lambda i: bands[i][1] - bands[i][0])
        s, e = bands[idx]
        if e - s >= min_h:
            break
        # какую границу убрать: слева или справа от полосы (слабее — лучше)
        left_b = s if s > 0 else None      # граница между idx-1 и idx
        right_b = e if e < h else None     # граница между idx и idx+1
        if left_b is None and right_b is None:
            break                          # единственная полоса
        if left_b is None:
            drop = right_b
        elif right_b is None:
            drop = left_b
        else:
            drop = left_b if energy[left_b] <= energy[right_b] else right_b
        bounds = [b for b in bounds if b != drop]
        bands = _bands_from_bounds(bounds, h)
        changed = True
    return bands


def _cap_block_count(bands, bounds, energy, h):
    """Не больше MAX_BLOCKS полос: срезаем самые слабые границы."""
    while len(bands) > MAX_BLOCKS and bounds:
        weakest = min(bounds, key=lambda b: energy[b])
        bounds = [b for b in bounds if b != weakest]
        bands = _bands_from_bounds(bounds, h)
    return bands


# ------------------------------------------------------------
# Шаги 7-8: сложность, минуты, имена, превью
# ------------------------------------------------------------

# Коэффициенты калибровки (подобраны на тестовых изображениях, см. worklog):
#   простой хедер   -> доля ~6-8%  -> 12-14 мин (цель 10-15)
#   насыщенный main -> доля ~25-60% -> 28-70 мин (цель 20-40+ для крупных)
#   футер           -> доля ~6-8%  -> 9-14 мин (цель 8-12)
ENERGY_REF = 14.0       # энергия 14/255 внутри полосы = максимум «текстурности»
COLOR_BINS_REF = 45.0   # 45+ «лишних» квантованных цветов = максимум разнообразия
COLOR_BINS_CAP = 128    # предел перебора сэмплов


def _band_complexity(img, s, e, energy, w):
    """Сложность полосы в диапазоне [0..1.6]:
    нормированная энергия внутри + разнообразие квантованных цветов."""
    # 1) энергия внутри полосы (среднее |a-b| по внутренним строкам)
    inner = [energy[y] for y in range(s + 1, e) if 1 <= y < len(energy)]
    en = sum(inner) / float(len(inner)) if inner else 0.0
    en_norm = min(1.0, en / ENERGY_REF)

    # 2) разнообразие цветов: RGB-сэмпл строк полосы, каналы квантуем до 8 ступеней;
    #    считаем «лишние» сверх первого корзины — однотонная полоса даёт 0
    rgb = img.convert('RGB')
    bins = set()
    band_h = max(1, e - s)
    step_y = max(1, band_h // 24)
    step_x = max(1, w // 48)
    px = rgb.load()
    for y in range(s, e, step_y):
        for x in range(0, w, step_x):
            r, g, b = px[x, y]
            bins.add((r >> 5, g >> 5, b >> 5))
            if len(bins) >= COLOR_BINS_CAP:      # дальше считать незачем
                break
    div = min(1.0, max(0, len(bins) - 1) / float(COLOR_BINS_REF - 1))

    c = 1.6 * (0.55 * en_norm + 0.45 * div)
    return max(0.0, min(1.6, c))


def _minutes_for(share, c):
    return max(8, min(180, int(round(8 + 120 * share * (0.6 + 0.8 * c)))))


def _name_blocks(count, heights):
    """Имена: первый «Хедер», последний «Футер», крупнейший средний «Main»,
    остальные «Секция N» по порядку. Один блок = «Main»."""
    if count == 1:
        return ['Main']
    if count == 2:
        return ['Хедер', 'Футер']
    names = [None] * count
    names[0] = 'Хедер'
    names[-1] = 'Футер'
    middle = list(range(1, count - 1))
    big = max(middle, key=lambda i: heights[i])
    names[big] = 'Main'
    n = 1
    for i in middle:
        if names[i] is None:
            names[i] = 'Секция %d' % n
            n += 1
    return names


def _describe_bands(img, bands, h, energy):
    """Финальные блоки: имя, минуты, доля, превью."""
    w, hh = img.size
    heights = [e - s for s, e in bands]
    names = _name_blocks(len(bands), heights)

    # превью: копия ширины 280, вырезаем те же полосы
    thumb_img = img.copy()
    thumb_img.thumbnail((280, MAX_HEIGHT))
    tw, th = thumb_img.size
    scale_y = th / float(hh)

    blocks = []
    for i, (s, e) in enumerate(bands):
        share = round((e - s) / float(hh), 2)
        c = _band_complexity(img, s, e, energy, w)
        minutes = _minutes_for(share, c)
        y0 = max(0, min(th - 1, int(round(s * scale_y))))
        y1 = max(y0 + 1, min(th, int(round(e * scale_y))))
        part = thumb_img.crop((0, y0, tw, y1))
        buf = io.BytesIO()
        part.save(buf, format='JPEG', quality=70)
        thumb = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
        blocks.append({'name': names[i], 'minutes': minutes,
                       'share': share, 'thumb': thumb})
    return blocks
