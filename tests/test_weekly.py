from datetime import datetime

from yym.models import CHINA, Status
from yym.rules import evaluate, week_start
from yym.weekly import config_time, pvp_evidence, scheduled_evidence, secret_evidence, shop_evidence

NOW = datetime(2026, 10, 14, 12, tzinfo=CHINA)


def offer(cell='22', limit=2):
    return {'CellID': int(cell), 'ProductName': 'test', 'ShopName': 'store', 'limit': [5, limit]}


def test_shop_uses_weekly_counts_and_selected_items():
    data, choices = shop_evidence([offer(), offer('40', 1)], {'once_week': [[22, 2]]}, ['22'], NOW, True)
    assert data['status'] == Status.COMPLETE
    assert len(choices) == 2
    data, _ = shop_evidence([offer(), offer('40', 1)], {'once_week': [[22, 2]]}, None, NOW, True)
    assert data['status'] == Status.INCOMPLETE
    assert data['progress'] == 1 and data['target'] == 2


def test_empty_week_list_is_authoritative_but_absent_list_is_unknown():
    assert shop_evidence([offer()], {'once_week': []}, None, NOW, True)[0]['status'] == Status.INCOMPLETE
    assert not shop_evidence([offer()], {}, None, NOW, True)[0]['verified']
    assert not shop_evidence([offer()], {'once_week': [[22, 2]]}, None, NOW, False)[0]['verified']


def test_no_selected_items_does_not_become_complete():
    assert not shop_evidence([offer()], {'once_week': []}, [], NOW, True)[0]['verified']


def test_old_secret_schedule_never_means_current_week_done():
    row = {'id': 1, 'begin_time': [2026, 10, 5, 9, 0, 0], 'end_time': [2026, 10, 12, 0, 0, 0]}
    result = secret_evidence([row], NOW)
    assert not result['verified']
    assert '10-12' in result['detail']


def test_even_current_schedule_needs_current_results_and_rewards():
    row = {'id': 2, 'begin_time': [2026, 10, 12, 9, 0, 0], 'end_time': [2026, 10, 19, 0, 0, 0]}
    result = secret_evidence([row], NOW)
    assert not result['verified'] and '通关和奖励' in result['detail']


def test_pvp_rank_and_wins_do_not_imply_settlement():
    data = pvp_evidence(1400, 200, 3, [1], [{'ts': week_start(NOW, 6).timestamp()}], NOW)
    assert not data['verified']
    assert '本周胜场 3' in data['detail']
    assert '结算尚未确认' in data['detail']


def test_pvp_reset_is_monday_six_not_midnight():
    monday = datetime(2026, 10, 12, 5, 59, tzinfo=CHINA)
    assert week_start(monday, 6).day == 5
    assert week_start(monday.replace(hour=6), 6).day == 12


def test_invalid_config_dates_are_unconfirmed():
    assert config_time([2026, 2, 31, 0, 0, 0]) is None
    assert config_time([2026, 10, 12, 9, 0, 0, 0, 0, -1]).hour == 9


def test_weekly_choices_survive_snapshot():
    value = evaluate({'choices': {'shop': [{'id': '22', 'label': 'test'}]}})
    assert value.choices['shop'][0]['id'] == '22'


def test_configured_activity_closed_and_open_are_distinct_from_completion():
    config = {'open_week_day': [5], 'open_time': [[[10, 0], [23, 0]]]}
    closed = scheduled_evidence(config, NOW, True, 'test')
    assert closed['status'] == Status.UNAVAILABLE
    assert '10-17 10:00' in closed['detail']
    assert not scheduled_evidence(config, NOW.replace(day=17), True, 'test')['verified']
    assert not scheduled_evidence(config, NOW, False, 'test')['verified']
