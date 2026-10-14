"""Pure task rules. Missing or unversioned evidence never means zero."""
from __future__ import annotations

from datetime import datetime, timedelta

from yym.models import Account, CHINA, Snapshot, Status, Task

CATALOG = [
    ('signin', '每日签到', 'daily', '签到'),
    ('activity', '每日活跃与奖励', 'daily', '每日任务'),
    ('gold', '金币妖怪', 'daily', '妖气探索／金币妖怪'),
    ('experience', '经验妖怪', 'daily', '妖气探索／经验妖怪'),
    ('bounties', '悬赏封印', 'daily', '悬赏封印'),
    ('dusk_explore', '逢魔探索礼包', 'daily', '逢魔之时'),
    ('dusk_boss', '逢魔首领', 'daily', '逢魔之时／首领战绩'),
    ('regional', '地域鬼王', 'daily', '地域鬼王'),
    ('guild30', '阴阳寮集体任务', 'daily', '阴阳寮／集体任务'),
    ('prayer', '祈愿', 'daily', '阴阳寮／祈愿'),
    ('barrier', '结界收益', 'daily', '自己的结界主页（保持打开）'),
    ('exp_pool', '经验食盒', 'daily', '结界／经验食盒'),
    ('strength_pool', '体力食盒', 'daily', '结界／体力食盒'),
    ('fostering', '好友寄养', 'daily', '好友寄养信息'),
    ('pet_bonus', '宠物御魂加成', 'daily', '宠物后院'),
    ('pet_battle', '宠物御魂协战', 'daily', '宠物后院'),
    ('pet_other', '其他宠物奖励', 'daily', '宠物后院／奖励详情'),
    ('free_gift', '每日免费礼包', 'daily', '礼包屋／每日免费礼包'),
    ('free_summon', '每日免费召唤', 'daily', '召唤屋'),
    ('guild_supply', '阴阳寮体力补给', 'daily', '阴阳寮'),
    ('yard_noon', '午间庭院体力', 'daily', '庭院／体力补给'),
    ('yard_evening', '晚间庭院体力', 'daily', '庭院／体力补给'),
    ('secret', '秘闻竞速／百战', 'weekly', '秘闻／本周竞速或百战'),
    ('secret_share', '秘闻成绩分享奖励', 'weekly', '秘闻／本周成绩'),
    ('weekly_share', '每周分享奖励', 'weekly', '图鉴／式神绘卷分享'),
    ('pvp', '斗技周奖励', 'weekly', '斗技／周奖励'),
    ('shop', '商店周兑换', 'weekly', '商店／勋章、荣誉、功勋'),
    ('hell', '阴界之门', 'weekly', '阴阳寮／阴界之门'),
    ('guild_boss', '首领退治', 'weekly', '阴阳寮／首领退治'),
]


def timestamp(value) -> datetime | None:
    try:
        if isinstance(value, (int, float)) and value > 1_000_000_000:
            return datetime.fromtimestamp(value, CHINA)
        if isinstance(value, str):
            result = datetime.fromisoformat(value)
            return result.replace(tzinfo=CHINA) if result.tzinfo is None else result.astimezone(CHINA)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def same_day(value, now: datetime) -> bool:
    result = timestamp(value)
    return result is not None and result.date() == now.date()


def week_start(now: datetime, hour: int = 0) -> datetime:
    result = (now - timedelta(days=now.weekday())).replace(hour=hour, minute=0, second=0, microsecond=0)
    return result if now >= result else result - timedelta(days=7)


def evaluate(e: dict, instance: str = '') -> Snapshot:
    now = timestamp(e.get('observed_at')) or datetime.now(CHINA)
    day, week = now.date().isoformat(), week_start(now).date().isoformat()
    tasks = {key: Task(key, name, cadence, observed_at=now.isoformat(),
                       period=day if cadence == 'daily' else week,
                       detail='数据未加载或当前周期尚未确认', needs_page=page)
             for key, name, cadence, page in CATALOG}
    def set_task(key, status, detail, source, progress=None, target=None):
        task = tasks[key]
        task.status, task.detail, task.source = status, detail, source
        task.progress, task.target = progress, target
        if status != Status.UNKNOWN:
            task.needs_page = ''

    fresh = bool(e.get('daily_current'))
    signed = e.get('signin', {})
    if any(same_day(v, now) for v in signed.get('signed_time', [])) and signed.get('signed'):
        set_task('signin', Status.COMPLETE, '今日已签到', 'recordparam.ONCE_DAY_SIGN')
    elif fresh and signed:
        set_task('signin', Status.INCOMPLETE, '今日尚未签到', 'recordparam.ONCE_DAY_SIGN')

    if fresh:
        score = e.get('activity_score')
        rewards = e.get('activity_rewards')
        if isinstance(score, (int, float)) and isinstance(rewards, list):
            state = Status.COMPLETE if set(range(1, 6)).issubset(rewards) else Status.PENDING if score >= 100 else Status.INCOMPLETE
            set_task('activity', state, f'基础活跃 {score}/100；有 {len(rewards)} 档领取记录', 'currency.900505 / daily_task_reward', score, 100)
        for key in ['gold', 'experience']:
            dungeon = e.get(key)
            if isinstance(dungeon, dict) and isinstance(dungeon.get('remaining'), int):
                left, capacity = dungeon['remaining'], dungeon.get('capacity')
                set_task(key, Status.COMPLETE if left == 0 else Status.INCOMPLETE,
                         f'剩余 {left}' + (f'/{capacity}' if capacity else '') + ' 次',
                         'lazy_cds.v / ResourceFightNewPanel', None if capacity is None else capacity - left, capacity)
        bounty = e.get('bounties')
        bounty_current = (isinstance(bounty, list) and bool(bounty)
                          and all((a := timestamp(t.get('period_start'))) and (b := timestamp(t.get('period_end')))
                                  and a <= now < b for t in bounty))
        if bounty_current:
            claimed = sum(bool(t.get('claimed')) for t in bounty)
            finished = sum(t.get('progress', 0) >= t.get('target', 1) for t in bounty)
            state = Status.COMPLETE if claimed == len(bounty) else Status.PENDING if finished > claimed else Status.INCOMPLETE
            detail = '\n'.join(f"{t['name']} {t['progress']}/{t['target']}" + (' 已领' if t.get('claimed') else '') for t in bounty)
            set_task('bounties', state, detail, 'MonsterHuntMgr._huntData._taskList', claimed, len(bounty))
        elif isinstance(bounty, list) and bounty:
            tasks['bounties'].detail = '悬赏记录已加载；有效期字段不足，当前批次未确认'
            tasks['bounties'].source = 'MonsterHuntMgr._taskList._startTime / _endTime'
        if 'dusk_supply' in e:
            set_task('dusk_explore', Status.COMPLETE if e['dusk_supply'] else Status.INCOMPLETE,
                     '探索礼包已领' if e['dusk_supply'] else '探索礼包未领取', 'recordparam.EVENING_SUPPLY_REWARD')
        if 'regional_count' in e:
            count = e['regional_count']
            # A challenge is participation, not proof of exhausting today's available bosses.
            target = e.get('regional_capacity')
            state = Status.COMPLETE if target and count >= target else Status.IN_PROGRESS if count else Status.INCOMPLETE
            set_task('regional', state, f'今日挑战 {count}' + (f'/{target}' if target else '；每日上限待加载'), 'recordparam.DAILY_BOSS_ATTACK', count, target)
        if e.get('guild_current') and isinstance(e.get('guild_count'), int):
            count = e['guild_count']
            set_task('guild30', Status.COMPLETE if count >= 30 else Status.INCOMPLETE,
                     f'{count}/30 次', 'FINISHED_GUILD_TASK_TIMES / guild_task_info', count, 30)
        prayer = e.get('prayer')
        if isinstance(prayer, dict):
            if prayer.get('auto_active'):
                set_task('prayer', Status.IN_PROGRESS,
                         f"自动祈愿已开启；累计 {prayer.get('received', 0)}/{prayer.get('target', 0)} 片\n今日收片未确认",
                         'GUILD_HERO_AUTO_BEG_INFO (cumulative)')
            elif prayer.get('today_count', 0) > 0:
                set_task('prayer', Status.COMPLETE, '今日已祈愿；收片情况单独确认', 'guild_beg_times')
            else:
                set_task('prayer', Status.INCOMPLETE, '未发现今日祈愿记录', 'guild_beg_times')
        if isinstance(e.get('exp_pool'), (int, float)):
            amount = max(0, int(e['exp_pool']))
            set_task('exp_pool', Status.PENDING if amount else Status.COMPLETE,
                     f'当前经验 {amount}' + ('，已清空' if not amount else ' 可领取'), 'recordparam.JJ_EXP_POOL.exp')
        if isinstance(e.get('strength_pool'), (int, float)):
            amount = max(0, int(e['strength_pool']))
            set_task('strength_pool', Status.PENDING if amount else Status.COMPLETE,
                     f'当前可收 {amount} 点体力；持续积累', 'recordparam.STRENGTH_COLLECTION')
        if 'pet_bonus' in e:
            set_task('pet_bonus', Status.COMPLETE if e['pet_bonus'] else Status.INCOMPLETE,
                     '今日已领取' if e['pet_bonus'] else '今日未领取', 'recordparam.PET_YUHUN_BUFF')
        if 'pet_fighted' in e:
            done = e['pet_fighted'] > 0
            set_task('pet_battle', Status.COMPLETE if done else Status.INCOMPLETE,
                     '已有今日协战记录' if done else '今日协战记录为 0', 'pet_dict.is_fighted', int(done), 1)
        if 'free_summon_used' in e:
            used = e['free_summon_used']
            set_task('free_summon', Status.COMPLETE if used else Status.INCOMPLETE,
                     f'今日已用 {used} 次免费召唤', 'recordparam.GAMBLE_DAY_FREE_NUM')

    harvest = e.get('barrier', {})
    if same_day(harvest.get('collected_at'), now):
        set_task('barrier', Status.UNKNOWN, '今日有收取记录；当前追加收益未确认', 'one_click_approval.cooldown_key_13')
        tasks['barrier'].needs_page = '自己的结界主页（保持打开）'
    if harvest.get('current_known') and isinstance(harvest.get('amount'), (int, float)):
        pending = harvest['amount'] > 0
        set_task('barrier', Status.PENDING if pending else Status.COMPLETE,
                 harvest.get('description', '当前有收益可领取' if pending else '当前暂无收益'), 'GuildLogic.lbs_info / barrier card data')
    foster = e.get('fostering')
    if isinstance(foster, dict) and foster.get('started_at'):
        start = timestamp(foster['started_at'])
        end = timestamp(foster.get('ends_at'))
        if end:
            pending = now >= end
            set_task('fostering', Status.PENDING if pending else Status.IN_PROGRESS,
                     f"寄养{'已结束，待领取' if pending else '进行中'}；{end:%m-%d %H:%M} 到期", 'set_other.t / Constant.643')
        else:
            set_task('fostering', Status.IN_PROGRESS, f'寄养已安排（{start:%m-%d %H:%M}）；到期时间待确认', 'set_other.t')
    elif fresh and foster == {}:
        set_task('fostering', Status.INCOMPLETE, '当前未安排寄养', 'set_other')
    for key, stamp, source in [('free_gift', e.get('free_gift_at'), 'growth_gift_last_free_reward.t'),
                               ('guild_supply', e.get('guild_supply_at'), 'LBS_BOSS_CDTIME.reward_t')]:
        if same_day(stamp, now):
            when = timestamp(stamp)
            set_task(key, Status.COMPLETE, f'今日 {when:%H:%M} 已领取', source)
        elif fresh and key == 'free_gift' and e.get('free_gift_loaded'):
            set_task(key, Status.INCOMPLETE, '未发现今日领取记录', source)
    for key, window_id in [('yard_noon', 104), ('yard_evening', 105)]:
        windows = e.get('yard_windows', {}).get(str(window_id), [])
        if not windows or not fresh:
            continue
        begin, end = timestamp(windows[0][0]), timestamp(windows[0][1])
        if not begin or not end or begin.date() != now.date():
            continue
        if window_id in e.get('yard_claimed', []):
            state, detail = Status.COMPLETE, '本时段已领取'
        elif now < begin:
            state, detail = Status.UNAVAILABLE, f'{begin:%H:%M} 开放'
        elif now >= end:
            state, detail = Status.MISSED, '未领取，时段已结束'
        else:
            state, detail = Status.PENDING, f'可领取，截至 {end:%H:%M}'
        set_task(key, state, detail, 'strength_rewards / active_time_list')

    # Weekly adapters supply explicit, verified period boundaries. Never infer a reset from the host weekday.
    for key, data in e.get('weekly', {}).items():
        if key not in tasks or tasks[key].cadence != 'weekly':
            continue
        begin, end = timestamp(data.get('period_start')), timestamp(data.get('period_end'))
        if not data.get('verified') or not begin or not end or not begin <= now < end:
            if data.get('detail'):
                tasks[key].detail = data['detail']
                tasks[key].source = data.get('source', '')
            continue
        set_task(key, Status(data['status']), data['detail'], data['source'], data.get('progress'), data.get('target'))
        tasks[key].period = begin.isoformat()

    return Snapshot(instance, Account(**e.get('account', {})), list(tasks.values()),
                    checked_at=now.isoformat(), server_time=e.get('server_time', ''),
                    connection='connected', message='只读数据已更新', choices=e.get('choices', {}))
