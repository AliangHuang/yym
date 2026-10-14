"""Extract a candidate ABI profile for developer review, never enable it automatically."""
import argparse
import hashlib
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('library', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    with args.library.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        handle.seek(0)
        elf = ELFFile(handle)
        if elf.elfclass != 64 or elf['e_machine'] != 'EM_X86_64':
            raise SystemExit('Only the reviewed x86_64 layout is supported')
        names = {'PyInterpreterState_Head', '_Py_HashSecret'} | {f'Py{n}_Type' for n in ['Unicode', 'Dict', 'Module', 'Long', 'List', 'Tuple', 'Bool', 'Float', 'Bytes', 'Type']}
        symbols = {}
        for section in elf.iter_sections():
            if section['sh_type'] in ['SHT_DYNSYM', 'SHT_SYMTAB']:
                for symbol in section.iter_symbols():
                    if symbol.name in names:
                        symbols[symbol.name] = symbol['st_value']
        if set(symbols) != names:
            raise SystemExit('Required CPython symbols are missing')
    candidate = {'sha256': digest, 'architecture': 'x86_64', 'python_abi': 'REVIEW_REQUIRED', 'symbols': symbols}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(candidate, indent=2), encoding='utf-8')
    print('Candidate written. Validate ABI offsets, getters and period rules before including in a release.')


if __name__ == '__main__':
    main()
