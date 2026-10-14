from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from yym.models import Instance

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(args: list[str], timeout: float = 15, binary: bool = False) -> str | bytes:
    # Android shell commands must not consume the worker's parent-control pipe.
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip()[:400] or "Command failed")
    return result.stdout if binary else result.stdout.decode("utf-8", "replace").strip()


def discover_install(configured: str = "") -> Path | None:
    candidates = [configured, os.environ.get("MUMU_HOME", ""), "G:/MuMuPlayer"]
    for drive in ["C:", "D:", "E:", "F:"]:
        candidates += [f"{drive}/Program Files/Netease/MuMuPlayer", f"{drive}/MuMuPlayer"]
    if os.name == "nt":
        import winreg
        for root in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            for branch in [r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"]:
                try:
                    with winreg.OpenKey(root, branch) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                                    name = winreg.QueryValueEx(sub, "DisplayName")[0]
                                    if "mumu" in name.lower():
                                        candidates.append(winreg.QueryValueEx(sub, "InstallLocation")[0])
                            except OSError:
                                continue
                except OSError:
                    pass
    for value in candidates:
        if not value:
            continue
        path = Path(value)
        if path.is_file():
            path = path.parent
        for root in [path, path / "nx_main"]:
            if (root / "mumu-cli.exe").is_file() and (root / "adb.exe").is_file():
                return root
    return None


def discover_instances(install: Path) -> list[Instance]:
    values = json.loads(run([str(install / "mumu-cli.exe"), "info", "--vmindex", "all"]))
    result = []
    for index, item in values.items():
        if item.get("is_process_started") and item.get("main_wnd") and item.get("adb_port"):
            result.append(Instance(str(index), item.get("name", f"MuMu {index}"),
                                   int(str(item["main_wnd"]), 16), int(item["pid"]),
                                   f"{item.get('adb_host_ip', '127.0.0.1')}:{item['adb_port']}"))
    return result


class Adb:
    def __init__(self, executable: str, serial: str):
        self.executable, self.serial = executable, serial

    def call(self, *args: str, timeout: float = 15, binary: bool = False):
        return run([self.executable, "-s", self.serial, *args], timeout=timeout, binary=binary)

    def shell(self, command: str, timeout: float = 15) -> str:
        return self.call("shell", command, timeout=timeout)

    def connect(self) -> None:
        run([self.executable, "connect", self.serial], timeout=8)


class RootLease:
    """Restore only root enabled by this worker; never change MuMu configuration."""
    def __init__(self, adb: Adb, on_change=None):
        self.adb, self.owned, self.on_change = adb, False, on_change

    def acquire(self) -> None:
        self.adb.connect()
        if self.adb.shell("id -u") == "0":
            return
        self.owned = True
        if self.on_change:
            self.on_change(True)
        message = self.adb.call("root")
        if "cannot" in message.lower() or "not allowed" in message.lower():
            raise PermissionError("无法取得只读数据所需权限")
        for _ in range(15):
            try:
                if self.adb.shell("id -u", timeout=2) == "0":
                    return
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            time.sleep(0.2)
        raise PermissionError("读取权限未就绪")

    def close(self) -> None:
        if self.owned:
            self.adb.call("unroot", timeout=5)
            self.owned = False
            if self.on_change:
                self.on_change(False)
