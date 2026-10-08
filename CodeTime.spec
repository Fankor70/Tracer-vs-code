# -*- mode: python ; coding: utf-8 -*-
"""Сборка CodeTime в один exe.

Список статики берётся из самого codetime.py (белый список STATIC_FILES),
а не дублируется здесь руками. Причина: интерфейс полностью рисуется
JavaScript, и если в сборку не попал хотя бы один из JS/CSS файлов,
приложение стартует с ЧЁРНЫМ ПУСТЫМ ОКНОМ — без единой ошибки в логах.
Раньше здесь стоял только 'dashboard.html', из-за чего всё так и случилось.
"""
import ast
import os

from PyInstaller.utils.hooks import collect_all

SPEC_DIR = SPECPATH

# --- какие файлы интерфейса обязаны попасть внутрь --------------------------
FALLBACK_STATIC = ['app.css', 'tui_widgets.js', 'tui.js',
                   'screens_a.js', 'screens_b.js']


def static_files():
    """Читаем STATIC_FILES из исходника, не выполняя его."""
    src = os.path.join(SPEC_DIR, 'codetime.py')
    try:
        with open(src, 'rb') as f:
            tree = ast.parse(f.read().decode('utf-8'), filename=src)
    except (OSError, SyntaxError) as e:
        print('  ! не удалось разобрать codetime.py (%r) — беру запасной список' % (e,))
        return list(FALLBACK_STATIC)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == 'STATIC_FILES':
                try:
                    return list(ast.literal_eval(node.value).keys())
                except (ValueError, TypeError):
                    break
    print('  ! STATIC_FILES не найден в codetime.py — беру запасной список')
    return list(FALLBACK_STATIC)


# --- проверка: файлы должны существовать ДО сборки -------------------------
datas = [('dashboard.html', '.')]
for name in static_files():
    full = os.path.join(SPEC_DIR, name)
    if not os.path.isfile(full):
        raise SystemExit(
            'СБОРКА ОТМЕНЕНА: в белом списке статики есть «%s», а файла нет.\n'
            'Интерфейс не запустится — он состоит ровно из этих файлов.' % name)
    datas.append((name, '.'))

print('  статика в сборке: %s' % ', '.join(n for n, _ in datas))

binaries = []
hiddenimports = ['pynput.keyboard', 'pynput.keyboard._win32', 'pynput.mouse', 'pynput.mouse._win32', 'pystray._win32', 'webview.platforms.edgechromium', 'webview.platforms.winforms']
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('clr_loader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['codetime.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CodeTime',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
