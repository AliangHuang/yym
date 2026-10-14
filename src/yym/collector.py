from __future__ import annotations

from datetime import datetime, timedelta
import logging

from yym.memory import GameSession
from yym.models import Account, CHINA, Snapshot
from yym.rules import evaluate, same_day, timestamp

log = logging.getLogger(__name__)


def collect(session: GameSession, instance: str) -> Snapshot:
    s = session
    s.prepare()
    now = datetime.now(CHINA)
    server = s.value('serverTime')
    server_id = s.value('server_id', '')
    short_id = s.value('short_id', 0)
    account = Account(str(s.value('id') or f'{server_id}:{short_id}'), s.value('_name', '等待登录'), str(server_id), short_id)
    e = {'observed_at': now.isoformat(), 'account': account.__dict__,
         'server_time': timestamp(server).isoformat() if timestamp(server) else '',
         'daily_current': same_day(server, now), 'weekly': {}}

    def section(label, read):
        try:
            read()
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            log.debug('Section unavailable: %s %s', label, type(exc).__name__)

    def core():
        e['signin'] = s.param('ods', {})
        currency = s.py.lazy_mapping(s.player['currency'])
        e['activity_score'] = s.py.atom(currency[900505]) if 900505 in currency else None
        e['activity_rewards'] = s.value('daily_task_reward')
        cds = s.value('lazy_cds', {})
        for name, mode in [('gold', 2), ('experience', 1)]:
            state = cds.get(str(mode))
            if not isinstance(state, dict):
                continue
            config = s.config('com.data.cdata.universal_lazy_cd', mode)
            if 'v' in state:
                e[name] = {'remaining': state['v'], 'capacity': config.get('max') if config else None}
        if 'esr' in s.params:
            e['dusk_supply'] = s.param('esr')
        if s.module('com.param_def'):
            # DAILY_BOSS_ATTACK's default [] is established by AreaKingLogic.
            boss_list = s.param('dba', [])
            e['regional_count'] = len(boss_list) if isinstance(boss_list, (dict, list)) else 0
        fame = s.py.atom(currency[900055]) if 900055 in currency else None
        thresholds = [s.config('com.data.cdata.Constant', key) for key in [711, 712]]
        limits = [constant_number(row) for row in thresholds]
        if isinstance(fame, (int, float)) and all(value is not None for value in limits):
            e['regional_capacity'] = 1 + sum(fame >= value for value in limits)

    def bounties():
        module = s.module('ui.monsterhunt.MonsterHuntMgr')
        if 'm_instance' not in module:
            return
        manager = s.py.attrs(module['m_instance'])
        hunt = s.py.attrs(manager['_huntData'])
        result = []
        for pointer in s.py.sequence(hunt['_taskList']):
            attrs = s.py.attrs(pointer)
            val = lambda key, default=0: s.py.decode(attrs[key]) if key in attrs else default
            result.append({'name': val('_taskName', '悬赏'),
                           'progress': val('_cur_kill_num_1') + val('_cur_kill_num_2'),
                           'target': val('_target_kill_num_1') + val('_target_kill_num_2'),
                           'claimed': val('_got_reward', False),
                           'period_start': val('_startTime', None), 'period_end': val('_endTime', None)})
        e['bounties'] = result

    def guild():
        info = s.module_value('module.guild.GuildLogic', 'guild_task_info', {})
        reset = info.get('last_refresh_task_time') if isinstance(info, dict) else None
        e['guild_count'] = s.param('fgtt')
        e['guild_current'] = same_day(reset or s.param('lrgts'), now)
        auto, guild_info = s.param('ghabi', {}), s.value('guild_info', {})
        e['prayer'] = {'auto_active': bool(auto and auto.get('guild_id') == guild_info.get('entityid')),
                       'received': auto.get('donated_num', 0), 'target': auto.get('beg_num', 0),
                       'today_count': s.value('guild_beg_times', 0)}
        config = s.py.lazy_mapping(s.globals['userconfig']) if 'userconfig' in s.globals else {}
        approval = s.py.decode(config['one_click_approval']) if 'one_click_approval' in config else {}
        e['barrier'] = {'collected_at': approval.get('cooldown_key_13'), 'current_known': False}
        pool = s.param('jep')
        if isinstance(pool, dict) and 'exp' in pool:
            e['exp_pool'] = pool['exp']
        if 'sc' in s.params:
            e['strength_pool'] = s.param('sc')
        foster = s.value('set_other')
        if isinstance(foster, dict):
            e['fostering'] = {'started_at': foster.get('t')} if foster else {}
            hours = s.config('com.data.cdata.Constant', 643)
            duration = constant_number(hours)
            if foster.get('t') and duration is not None and 0 < duration <= 48:
                e['fostering']['ends_at'] = foster['t'] + duration * 3600

    def pets():
        if 'pet_yuhun' in s.params:
            e['pet_bonus'] = s.param('pet_yuhun')
        if 'pet_dict' in s.player:
            data = s.py.mapping(s.player['pet_dict'])
            flags = []
            for pointer in data.values():
                pet = s.py.lazy_mapping(pointer)
                if 'is_fighted' in pet:
                    flags.append(bool(s.py.atom(pet['is_fighted'])))
            if flags:
                e['pet_fighted'] = sum(flags)

    def welfare():
        config = s.py.lazy_mapping(s.player['config_data']) if 'config_data' in s.player else {}
        gift = s.py.decode(config['growth_gift_last_free_reward']) if 'growth_gift_last_free_reward' in config else {}
        e['free_gift_loaded'] = bool(gift)
        e['free_gift_at'] = gift.get('t')
        if 'gdfn' in s.params:
            e['free_summon_used'] = s.param('gdfn')
        e['guild_supply_at'] = s.param('lbc', {}).get('reward_t')
        active = s.py.mapping(s.player['active_time_list'])
        e['yard_windows'] = {str(i): s.py.decode(active[f'strength_rewards_{i}'])
                             for i in [104, 105] if f'strength_rewards_{i}' in active}
        e['yard_claimed'] = s.value('strength_rewards', [])

    for label, read in [('core', core), ('bounties', bounties), ('guild', guild), ('pets', pets), ('welfare', welfare)]:
        section(label, read)
    from yym.weekly import collect_weekly
    section('weekly', lambda: collect_weekly(s, e, now))
    # Detect a role swap instead of combining data from two accounts in one sample.
    old_pointer = s.globals['player1']
    s.reader.cache.clear()
    current = s.module('Globals').get('player1')
    if current != old_pointer:
        raise ValueError('角色切换中，等待下一次读取')
    attrs = s.py.lazy_attrs(current)
    if 'short_id' in attrs and s.py.atom(attrs['short_id']) != short_id:
        raise ValueError('角色切换中，等待下一次读取')
    return evaluate(e, instance)


def constant_number(row: dict | None) -> float | None:
    value = row.get('value') if row else None
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
