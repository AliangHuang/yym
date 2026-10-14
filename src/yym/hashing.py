"""CPython SipHash-1-3 for dictionary lookup, evaluated only in the host process."""
import struct

MASK = (1 << 64) - 1


def _rotate(value, bits):
    return ((value << bits) | (value >> (64 - bits))) & MASK


def _round(v):
    a, b, c, d = v
    a = (a + b) & MASK; b = _rotate(b, 13) ^ a; a = _rotate(a, 32)
    c = (c + d) & MASK; d = _rotate(d, 16) ^ c
    a = (a + d) & MASK; d = _rotate(d, 21) ^ a
    c = (c + b) & MASK; b = _rotate(b, 17) ^ c; c = _rotate(c, 32)
    return a, b, c, d


def unicode_hash(text: str, secret: bytes) -> int:
    if not text:
        return 0
    largest = max(map(ord, text))
    raw = text.encode('latin1' if largest <= 255 else 'utf-16-le' if largest <= 65535 else 'utf-32-le')
    k0, k1 = struct.unpack('<QQ', secret[:16])
    v = (k0 ^ 0x736f6d6570736575, k1 ^ 0x646f72616e646f6d,
         k0 ^ 0x6c7967656e657261, k1 ^ 0x7465646279746573)
    full = len(raw) // 8 * 8
    for (word,) in struct.iter_unpack('<Q', raw[:full]):
        v = _round((v[0], v[1], v[2], v[3] ^ word))
        v = (v[0] ^ word, v[1], v[2], v[3])
    last = ((len(raw) & 255) << 56) | int.from_bytes(raw[full:], 'little')
    v = _round((v[0], v[1], v[2], v[3] ^ last))
    v = (v[0] ^ last, v[1], v[2] ^ 0xff, v[3])
    for _ in range(3):
        v = _round(v)
    result = (v[0] ^ v[1] ^ v[2] ^ v[3]) & MASK
    result = result - (1 << 64) if result >= (1 << 63) else result
    return -2 if result == -1 else result
