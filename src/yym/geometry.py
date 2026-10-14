from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class Placement:
    rect: Rect
    side: str
    collapsed: bool


def dock(target: Rect, work: Rect, width: int = 300, compact: bool = False, gap: int = 6) -> Placement:
    """All arguments are physical pixels, including DPI-scaled sidebar width."""
    narrow = max(38, round(width * 0.16))
    wanted = narrow if compact else width
    left = target.x - work.x
    right = work.right - target.right
    forced = left < wanted + gap and right < wanted + gap
    actual = narrow if forced else wanted
    if left >= actual + gap:
        side, x = "left", target.x - actual - gap
    elif right >= actual + gap:
        side, x = "right", target.right + gap
    else:
        side = "left" if left >= right else "right"
        x = target.x - actual - gap if side == "left" else target.right + gap
    actual = min(actual, work.width)
    height = min(max(target.height, 1), work.height)
    x = max(work.x, min(x, work.right - actual))
    y = max(work.y, min(target.y, work.bottom - height))
    return Placement(Rect(x, y, actual, height), side, compact or forced)
