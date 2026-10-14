import json
from yym.models import Account, Snapshot
from yym.storage import data_dir, save_snapshot, load_settings, save_settings


def test_account_snapshots_do_not_overwrite_other_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    a, b = Snapshot('0', Account('a', 'test-a', 'server')), Snapshot('1', Account('b', 'test-b', 'server'))
    save_snapshot(a)
    save_snapshot(b)
    files = list((data_dir() / 'accounts').glob('*/latest.json'))
    assert len(files) == 2
    assert {json.loads(p.read_text(encoding='utf-8'))['account']['uid'] for p in files} == {'a', 'b'}


def test_preferences_round_trip_and_corruption_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    settings = {'accounts': {'a': {'shop_selected': ['28'], 'hidden_tasks': ['pvp']}}}
    save_settings(settings)
    assert load_settings() == settings
    (data_dir() / 'settings.json').write_text('{bad')
    assert load_settings() == {}
