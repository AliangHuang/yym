"""Versioned weekly adapters. Only inspect already loaded client objects."""
from __future__ import annotations

from datetime import datetime, timedelta
import time

from yym.memory import GameSession
from yym.models import Account, CHINA, Status
from yym.rules import timestamp, week_start
from yym.storage import load_settings


def config_time(value) -> datetime | None:
    if isinstance(value, (list, tuple)) and len(value) >= 6:
        try:
            return datetime(*(int(v) for v in value[:6]), tzinfo=CHINA)
        except (ValueError, TypeError, OverflowError):
            return None
    return timestamp(value)


def unknown(detail: str, source: str = '') -> dict:
    return {'verified': False, 'detail': detail, 'source': source}


def period(now: datetime, status: Status, detail: str, source: str, hour=0, **extra) -> dict:
    begin = week_start(now, hour)
    return {'verified': True, 'period_start': begin.isoformat(),
            'period_end': (begin + timedelta(days=7)).isoformat(),
            'status': status.value, 'detail': detail, 'source': source, **extra}


def secret_evidence(rows: list[dict], now: datetime) -> dict:
    """Regular secret floors are lifetime records and cannot prove this week's race."""
    active = [r for r in rows if (begin := config_time(r.get('begin_time')))
              and (end := config_time(r.get('rank_end_time') or r.get('end_time')))
              and begin <= now < end]
    if not active:
        ends = [d for r in rows if (d := config_time(r.get('rank_end_time') or r.get('end_time')))]
        detail = (f'已加载赛程只覆盖到 {max(ends):%m-%d %H:%M}；本周赛程未确认' if ends
                  else '本周赛程对象未加载，请保持竞速／百战详情页打开')
        return unknown(detail, 'dungeon_challenge_race.begin_time / rank_end_time')
    row = max(active, key=lambda r: config_time(r['begin_time']))
    return unknown(f"赛程 {row.get('id', '—')} 已加载；本周各层通关和奖励记录尚未核实",
                   'dungeon_challenge_race / advanced_floor')


def shop_evidence(offers: list[dict], records, selected, now: datetime, fresh: bool) -> tuple[dict, list]:
    choices = [{'id': str(r['CellID']), 'label': f"{r.get('ShopName', '商店')} · {r.get('ProductName', r['CellID'])}",
                'capacity': r['limit'][1]} for r in offers]
    if not choices:
        return unknown('周限购商品配置尚未加载，请打开勋章／荣誉／功勋商店'), []
    if not fresh or not isinstance(records, dict) or not isinstance(records.get('once_week'), list):
        return unknown('商品配置已加载；当前服务器周的购买记录未确认', 'SHOP_BUY_LIMIT_SOME_TIME'), choices
    chosen = [r for r in choices if selected is None or r['id'] in selected]
    if not chosen:
        return unknown('尚未选择关注商品，可在设置中选择'), choices
    counts = {}
    for entry in records['once_week']:
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and isinstance(entry[1], (int, float)):
            counts[str(entry[0])] = max(0, entry[1])
    done = sum(counts.get(r['id'], 0) >= r['capacity'] for r in chosen)
    detail = '\n'.join(f"{r['label']} {counts.get(r['id'], 0)}/{r['capacity']}" for r in chosen)
    return period(now, Status.COMPLETE if done == len(chosen) else Status.INCOMPLETE,
                  detail, 'ShopManager.getThisWeekBuyNum / sblst.once_week / shop.limit',
                  progress=done, target=len(chosen)), choices


def pvp_evidence(score, honor, wins, rewards, history, now: datetime) -> dict:
    summary = f'当前积分 {score if isinstance(score, (int, float)) else "未加载"}；本周荣誉 {honor if isinstance(honor, (int, float)) else "未加载"}'
    if isinstance(wins, int):
        summary += f'；本周胜场 {wins}'
    checkpoint = week_start(now, 6)
    current = any(isinstance(r, dict) and timestamp(r.get('ts')) == checkpoint for r in history or [])
    if not current:
        return unknown(summary + '\n当前周重置、参与资格和结算尚未确认', 'pvp_score / honor_score_this_week / pvp_score_week_history')
    claimed = len(rewards) if isinstance(rewards, (list, dict)) else None
    detail = summary + (f'；胜场奖励已领 {claimed} 档' if claimed is not None else '；胜场领奖记录未加载')
    return unknown(detail + '\n段位奖励资格与结算尚未确认', 'pvp_score / pvpww / pvpwwr / pvp_score_week_history')


def scheduled_evidence(row, now: datetime, fresh: bool, name: str) -> dict:
    source = f'active_time.{name}.open_week_day / open_time'
    if not fresh or not isinstance(row, dict):
        return unknown('开放时间尚未加载；请在活动开放时进入页面核实本期进度', source)
    days, windows = row.get('open_week_day'), row.get('open_time')
    if not isinstance(days, list) or not days or not isinstance(windows, list) or not windows:
        return unknown('活动开放配置不完整，本期挑战与领奖未确认', source)
    try:
        intervals = []
        start = week_start(now)
        for day in days:
            if not isinstance(day, int) or not 0 <= day <= 6:
                raise ValueError('Invalid weekday')
            for begin, end in windows:
                opening = start + timedelta(days=day, hours=begin[0], minutes=begin[1])
                closing = start + timedelta(days=day, hours=end[0], minutes=end[1])
                if closing <= opening:
                    closing += timedelta(days=1)
                intervals.append((opening, closing))
        if any(a <= now < b for a, b in intervals):
            return unknown('当前时段已开放；本期挑战与领奖记录未确认，请打开活动页面', source)
        upcoming = min(a for a, _ in intervals if a > now) if any(a > now for a, _ in intervals) else min(a for a, _ in intervals) + timedelta(days=7)
        return period(now, Status.UNAVAILABLE, f'当前未开放；下次 {upcoming:%m-%d %H:%M}\n本周参与和领奖尚未确认', source)
    except (TypeError, ValueError, IndexError):
        return unknown('开放配置暂不支持，本期挑战与领奖未确认', source)


def collect_weekly(session: GameSession, evidence: dict, now: datetime) -> None:
    s, result = session, evidence.setdefault('weekly', {})
    result.update(
        secret_share=unknown('本周成绩分享的领取标记尚未核实；普通通关记录不能代替领奖记录'),
        weekly_share=unknown('未核实每周分享领取字段；累计分享和旧活动分享不作为完成依据'),
        hell=unknown('需在阴界之门开放时加载，当前参与层数与本期领奖记录未确认'),
        guild_boss=unknown('需在首领退治开放时加载，本期挑战与领奖记录未确认'),
    )
    try:
        cached = getattr(s, '_race_rows', (0, []))
        if time.monotonic() - cached[0] > 60:
            cached = (time.monotonic(), s.cached_configs('com.data.cdata.dungeon_challenge_race', 500))
            s._race_rows = cached
        result['secret'] = secret_evidence(cached[1], now)
    except (KeyError, ValueError, TypeError):
        result['secret'] = unknown('赛程读取未完成，请保持竞速／百战详情页打开')
    try:
        result['pvp'] = pvp_evidence(s.value('pvp_score'), s.value('honor_score_this_week'),
                                   s.param('pvpww'), s.param('pvpwwr'),
                                   s.initial('pvp_score_week_history', []), now)
    except (KeyError, ValueError, TypeError):
        result['pvp'] = unknown('斗技周记录尚未加载')
    try:
        records = s.param('sblst')
        # Verified base-store cells plus cells present in the account's weekly record.
        ids = {21, 22, 24, 25, 26, 40, 42, 44, 701, 702, 703, 704, 705, 706}
        if isinstance(records, dict):
            ids.update(int(r[0]) for r in records.get('once_week', []) if isinstance(r, list) and len(r) == 2)
        offers = []
        for cell in sorted(ids):
            row = s.config('com.data.cdata.shop', cell)
            limit = row.get('limit', []) if row else []
            if (row and len(limit) >= 2 and limit[0] == 5 and isinstance(limit[1], (int, float))
                    and limit[1] > 0 and (not row.get('begin_time') or (config_time(row['begin_time']) or now) <= now)
                    and (not row.get('end_time') or now < (config_time(row['end_time']) or now))):
                offers.append(row)
        account = Account(**evidence['account'])
        selected = load_settings().get('accounts', {}).get(account.key, {}).get('shop_selected', ['22', '40', '42', '704', '705'])
        result['shop'], choices = shop_evidence(offers, records, selected, now, evidence.get('daily_current', False))
        evidence['choices'] = {'shop': choices}
    except (KeyError, ValueError, TypeError):
        result['shop'] = unknown('周兑换记录读取未完成，请打开商店页面')
    for key, name in [('guild_boss', 'guild_boss'), ('hell', 'guild_fight_rip')]:
        try:
            result[key] = scheduled_evidence(s.config('com.data.cdata.active_time', name), now,
                                             evidence.get('daily_current', False), name)
        except (KeyError, ValueError, TypeError):
            pass
