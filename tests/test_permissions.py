from yym.mumu import RootLease
import subprocess


class FakeAdb:
    def __init__(self, rooted=False):
        self.rooted, self.calls = rooted, []

    def connect(self):
        pass

    def shell(self, command, **kwargs):
        return '0' if self.rooted else '2000'

    def call(self, command, **kwargs):
        self.calls.append(command)
        self.rooted = command == 'root'
        return ''


def test_preexisting_root_is_preserved():
    adb = FakeAdb(True)
    lease = RootLease(adb)
    lease.acquire()
    lease.close()
    assert adb.rooted
    assert adb.calls == []


def test_temporary_root_is_restored_and_reported():
    adb, changes = FakeAdb(), []
    lease = RootLease(adb, changes.append)
    lease.acquire()
    assert adb.rooted
    lease.close()
    assert not adb.rooted
    assert adb.calls == ['root', 'unroot']
    assert changes == [True, False]


def test_adb_subprocess_never_consumes_parent_control_pipe(monkeypatch):
    from yym.mumu import run
    calls = []
    def fake_run(args, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(args, 0, b'ok', b'')
    monkeypatch.setattr(subprocess, 'run', fake_run)
    assert run(['adb', 'shell', 'id']) == 'ok'
    assert calls[0]['stdin'] == subprocess.DEVNULL
