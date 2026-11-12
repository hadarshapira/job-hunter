"""Generate the PNG app icons (magnifier on indigo) with only the Python standard library.

Usage: python scripts/make_icons.py   (writes into public/)
"""

import math
import struct
import zlib
from pathlib import Path

BG = (79, 70, 229)
FG = (255, 255, 255)
OUT = Path(__file__).resolve().parent.parent / "public"


def coverage(x: float, y: float, s: float, rounded: bool) -> tuple[float, float]:
    """Return (background alpha, foreground alpha) for a point in a 0..1 square."""
    bg = 1.0
    if rounded:
        r = 0.22
        cx, cy = min(max(x, r), 1 - r), min(max(y, r), 1 - r)
        bg = 1.0 if math.hypot(x - cx, y - cy) <= r else 0.0
    # Magnifier ring
    d = math.hypot(x - 0.44, y - 0.44)
    ring = abs(d - 0.22) <= 0.04
    # Handle: distance to the segment from (0.60,0.60) to (0.775,0.775)
    t = max(0.0, min(1.0, ((x - 0.60) + (y - 0.60)) / (2 * 0.175)))
    px, py = 0.60 + 0.175 * t, 0.60 + 0.175 * t
    handle = math.hypot(x - px, y - py) <= 0.047
    return bg, 1.0 if (ring or handle) else 0.0


def render(size: int, rounded: bool) -> bytes:
    ss = 3  # supersampling for smooth edges
    rows = []
    for j in range(size):
        row = bytearray([0])
        for i in range(size):
            bga = fga = 0.0
            for sj in range(ss):
                for si in range(ss):
                    b, f = coverage((i + (si + 0.5) / ss) / size, (j + (sj + 0.5) / ss) / size, size, rounded)
                    bga += b
                    fga += f * b
            bga /= ss * ss
            fga /= ss * ss
            mix = fga / bga if bga else 0
            rgb = [round(BG[k] * (1 - mix) + FG[k] * mix) for k in range(3)]
            row += bytes(rgb + [round(bga * 255)])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    (OUT / "icon-192.png").write_bytes(render(192, rounded=False))
    (OUT / "icon-512.png").write_bytes(render(512, rounded=False))  # full-bleed: safe for maskable
    (OUT / "apple-touch-icon.png").write_bytes(render(180, rounded=False))
    print("icons written to", OUT)
