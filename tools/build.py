"""Build the portable Windows distribution; run with the project Python 3.12 venv."""
from importlib import metadata
from pathlib import Path
import os
import shutil
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    # Host utilities may supply an unrelated ICU DLL through PATH. Qt on Windows
    # uses the system ICU API; a Poppler/Conda ICU with the same filename is incompatible.
    system_root = Path(os.environ['SystemRoot'])
    os.environ['PATH'] = os.pathsep.join([str(Path(sys.executable).parent),
                                         str(system_root / 'System32'), str(system_root)])
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from yym.ui import app_icon
    app = QApplication.instance() or QApplication([])
    assets = root / 'build' / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    icon = assets / 'yym.ico'
    if not app_icon().pixmap(128, 128).save(str(icon), 'ICO'):
        raise RuntimeError('Could not write application icon')
    import PyInstaller.__main__
    PyInstaller.__main__.run([
        '--noconfirm', '--clean', '--windowed', '--onedir', '--name', 'yym',
        '--icon', str(icon), '--paths', str(root / 'src'),
        '--add-data', f'{root / "src" / "yym" / "profiles"}{os.pathsep}yym/profiles',
        '--exclude-module', 'PySide6.QtWebEngineCore',
        '--exclude-module', 'PySide6.QtWebEngineWidgets',
        '--exclude-module', 'PySide6.QtQml',
        '--exclude-module', 'PySide6.QtQuick',
        '--exclude-module', 'pytest',
        str(root / 'tools' / 'launcher.py'),
    ])
    output = root / 'dist' / 'yym'
    for name in ['README.md', 'LICENSE', 'THIRD_PARTY.md']:
        shutil.copy2(root / name, output / name)
    shutil.copytree(root / 'docs', output / 'docs', dirs_exist_ok=True)
    notices = output / 'licenses'
    notices.mkdir(exist_ok=True)
    shutil.copytree(root / 'licenses', notices, dirs_exist_ok=True)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, notices / 'PYTHON-LICENSE.txt')
    for name in ['PySide6-Essentials', 'shiboken6', 'PyInstaller']:
        package = metadata.distribution(name)
        for file in package.files or []:
            if '.dist-info/licenses/' in str(file).replace('\\', '/'):
                source = Path(package.locate_file(file))
                if source.is_file():
                    target = notices / name.lower().replace('-', '_') / Path(*file.parts[file.parts.index('licenses') + 1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    print(f'Built {output / "yym.exe"}')


if __name__ == '__main__':
    main()
