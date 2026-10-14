import pytest
from yym.geometry import Rect, dock


def test_default_left():
    result = dock(Rect(500, 100, 800, 800), Rect(0, 0, 1920, 1040))
    assert result.side == 'left'
    assert result.rect.x == 194
    assert result.rect.width == 300
    assert not result.collapsed


def test_fallback_right():
    result = dock(Rect(100, 100, 800, 800), Rect(0, 0, 1920, 1040))
    assert result.side == 'right'
    assert result.rect.x == 906


@pytest.mark.parametrize('scale', [1, 1.25, 1.5])
def test_scaled_and_negative_monitor_coordinates(scale):
    work = Rect(-2560, 0, 2560, 1400)
    result = dock(Rect(-1900, 120, 900, 1000), work, round(300 * scale), gap=round(6 * scale))
    assert result.side == 'left'
    assert result.rect.width == round(300 * scale)
    assert work.x <= result.rect.x < result.rect.right <= work.right


def test_both_sides_insufficient_compacts_inside_work_area():
    work = Rect(0, 0, 1920, 1040)
    result = dock(Rect(0, -20, 1920, 1200), work)
    assert result.collapsed
    assert result.rect.width == 48
    assert 0 <= result.rect.x <= result.rect.right <= 1920
    assert result.rect.y == 0
    assert result.rect.bottom == 1040
