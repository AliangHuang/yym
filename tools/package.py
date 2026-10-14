"""Create portable and source archives, excluding local account data and build caches."""
import hashlib
from pathlib import Path
import subprocess
import zipfile

from yym import __version__


def main():
    root = Path(__file__).resolve().parents[1]
    dist = root / 'dist'
    program = dist / 'yym'
    if not (program / 'yym.exe').is_file():
        raise SystemExit('Build yym first')
    archives = [dist / f'yym-{__version__}-win-x64.zip', dist / f'yym-{__version__}-source.zip']
    with zipfile.ZipFile(archives[0], 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(program.rglob('*')):
            if path.is_file():
                output.write(path, path.relative_to(dist))
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard', '-z']).split(b'\0')
    with zipfile.ZipFile(archives[1], 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for name in sorted({n.decode('utf-8') for n in names if n}):
            path = root / name
            if path.is_file():
                output.write(path, Path('yym') / name)
    checksum = '\n'.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}' for path in archives) + '\n'
    (dist / 'checksums.sha256').write_text(checksum, encoding='ascii')
    for path in archives:
        print(f'{path.name}: {path.stat().st_size / 1024 / 1024:.1f} MiB')


if __name__ == '__main__':
    main()
