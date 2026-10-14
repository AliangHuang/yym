import json
from pathlib import Path

import pytest

from yym.models import Account, Snapshot, Status
from yym.rules import evaluate


@pytest.fixture
def evidence():
    return json.loads((Path(__file__).parent / 'fixtures' / 'current.json').read_text())


def tasks(evidence):
    return {task.id: task for task in evaluate(evidence).tasks}


def test_claimed_and_pending_are_separate(evidence):
    values = tasks(evidence)
    assert values['activity'].status == Status.COMPLETE
    assert values['bounties'].status == Status.PENDING
    assert values['gold'].status == Status.INCOMPLETE
    assert values['experience'].status == Status.COMPLETE


def test_cumulative_prayer_does_not_mean_today_finished(evidence):
    value = tasks(evidence)['prayer']
    assert value.status == Status.IN_PROGRESS
    assert '累计 1/99' in value.detail
    assert '今日收片未确认' in value.detail


def test_missing_counters_are_unknown_not_zero():
    values = tasks({'daily_current': True})
    for name in ['gold', 'experience', 'pet_battle', 'activity', 'guild30']:
        assert values[name].status == Status.UNKNOWN


def test_cross_day_flags_do_not_remain_completed(evidence):
    evidence['observed_at'] = '2026-10-15T00:01:00+08:00'
    evidence['daily_current'] = False
    values = tasks(evidence)
    for name in ['signin', 'activity', 'pet_bonus', 'free_summon']:
        assert values[name].status == Status.UNKNOWN


def test_old_guild_reset_prevents_claiming_today_count(evidence):
    evidence['guild_current'] = False
    assert tasks(evidence)['guild30'].status == Status.UNKNOWN


def test_continuous_income_is_distinct_from_daily_claim(evidence):
    values = tasks(evidence)
    assert values['exp_pool'].status == Status.COMPLETE
    assert values['strength_pool'].status == Status.PENDING
    assert '3 点体力' in values['strength_pool'].detail


def test_old_week_record_is_rejected(evidence):
    evidence['weekly'] = {'pvp': {'verified': True, 'period_start': '2026-10-05T00:00:00+08:00',
                                 'period_end': '2026-10-12T00:00:00+08:00', 'status': 'complete',
                                 'detail': 'old', 'source': 'fixture'}}
    assert tasks(evidence)['pvp'].status == Status.UNKNOWN


def test_current_week_record_is_accepted_only_when_verified(evidence):
    row = {'verified': True, 'period_start': '2026-10-12T08:00:00+08:00',
           'period_end': '2026-10-19T08:00:00+08:00', 'status': 'in_progress',
           'detail': '资格已达成，等待结算', 'source': 'fixture', 'progress': 4, 'target': 10}
    evidence['weekly'] = {'secret': row}
    assert tasks(evidence)['secret'].status == Status.IN_PROGRESS
    row['verified'] = False
    assert tasks(evidence)['secret'].status == Status.UNKNOWN


def test_epoch_zero_is_not_a_current_timestamp():
    evidence = {'observed_at': '2026-10-14T20:00:00+08:00', 'daily_current': True,
                'barrier': {'collected_at': 0}, 'free_gift_at': 0}
    assert tasks(evidence)['barrier'].status == Status.UNKNOWN


def test_round_trip_and_account_isolation(evidence):
    value = evaluate(evidence, '0')
    restored = Snapshot.from_dict(json.loads(json.dumps(value.to_dict())))
    assert restored == value
    assert Account('a', server='one').key != Account('b', server='one').key
    assert Account('a', server='one').key != Account('a', server='two').key


def test_activity_unclaimed_highest_reward_is_pending(evidence):
    evidence['activity_rewards'] = [1, 2, 3, 4]
    assert tasks(evidence)['activity'].status == Status.PENDING


def test_fostering_end_is_pending_not_completed(evidence):
    evidence['fostering'] = {'started_at': '2026-10-14T10:00:00+08:00', 'ends_at': '2026-10-14T16:00:00+08:00'}
    assert tasks(evidence)['fostering'].status == Status.PENDING


def test_barrier_claim_today_does_not_prove_current_income_empty(evidence):
    evidence['barrier'] = {'collected_at': evidence['observed_at'], 'current_known': False}
    task = tasks(evidence)['barrier']
    assert task.status == Status.UNKNOWN
    assert '今日有收取记录' in task.detail


def test_old_or_undated_bounty_is_unknown_even_if_all_claimed(evidence):
    evidence['bounties'][0].update(claimed=True, period_start=0, period_end=0)
    assert tasks(evidence)['bounties'].status == Status.UNKNOWN
