from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib

CHINA = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(CHINA).isoformat(timespec="seconds")


class Status(StrEnum):
    INCOMPLETE = "incomplete"
    IN_PROGRESS = "in_progress"
    PENDING = "pending_reward"
    COMPLETE = "complete"
    UNKNOWN = "unconfirmed"
    UNAVAILABLE = "unavailable"
    MISSED = "missed"


LABELS = {
    Status.INCOMPLETE: "未完成", Status.IN_PROGRESS: "进行中",
    Status.PENDING: "待领取", Status.COMPLETE: "已完成",
    Status.UNKNOWN: "未确认", Status.UNAVAILABLE: "未开放", Status.MISSED: "已错过",
}


@dataclass(frozen=True)
class Instance:
    index: str
    name: str
    hwnd: int
    pid: int
    serial: str


@dataclass
class Account:
    uid: str = ""
    name: str = "等待登录"
    server: str = ""
    short_id: int = 0

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.server}|{self.uid or self.short_id}".encode()).hexdigest()[:24]


@dataclass
class Task:
    id: str
    title: str
    cadence: str = "daily"
    status: Status = Status.UNKNOWN
    detail: str = "等待读取"
    progress: float | int | None = None
    target: float | int | None = None
    source: str = ""
    observed_at: str = ""
    period: str = ""
    needs_page: str = ""


@dataclass
class Snapshot:
    instance: str
    account: Account = field(default_factory=Account)
    tasks: list[Task] = field(default_factory=list)
    checked_at: str = field(default_factory=now_iso)
    server_time: str = ""
    connection: str = "connecting"
    message: str = "正在连接"
    duration_ms: int = 0
    choices: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> Snapshot:
        value = dict(value)
        value["account"] = Account(**value.get("account", {}))
        value["tasks"] = [Task(**{**t, "status": Status(t["status"])}) for t in value.get("tasks", [])]
        return cls(**value)
