# 痒痒猫 · yym

Windows 上吸附在 MuMu 窗口旁的阴阳师日常、周常侧栏。每个模拟器实例独立连接、采样和保存账号记录。

0.1.1 修复拖动卡顿：侧栏使用独立窗口，高频位置事件按帧合并，纯移动不重复调整尺寸；吸附方向和折叠规则保持一致。验证过程见 [docs/performance.md](docs/performance.md)。

0.1.2 修复两个侧栏重叠时点击对象变化：只提升当前实例对应的侧栏及其设置窗口，点击前方侧栏时不再同时提升后方侧栏。验证过程见 [docs/overlap.md](docs/overlap.md)。

0.1.3 完成多开窗口交互回归：设置只阻止所属侧栏的输入，随模拟器最小化隐藏并在恢复时保留未保存选择和原有焦点；修复置顶模拟器导致侧栏反复调整层级。验证过程见 [docs/interaction.md](docs/interaction.md)。

## 启动

解压便携包后运行 `dist/yym/yym.exe`（包内也可直接运行 `yym.exe`），无需另装 Python。请保留整个 `yym` 目录及 `_internal`，不要只复制 EXE。

1. 启动 MuMu 并登录游戏，再启动痒痒猫。
2. 自动发现失败时，从托盘菜单选择 MuMu 安装目录，选择包含 `nx_main` 的目录或 `nx_main` 本身。也可设置 `MUMU_HOME`。
3. 默认在模拟器左侧显示，左侧不足时移至右侧；两侧都不足时折叠成窄条。跟随移动、缩放、跨屏和最小化恢复。
4. 在“日常／周常”页签查看状态。设置中可选择关注项目及周兑换商品，也可筛选待办、隐藏已完成项、立即刷新或暂停。
5. 页面数据未加载时，按卡片提示在游戏中打开对应页面。部分临时对象只在页面停留期间存在。痒痒猫不会打开游戏页面、领取奖励或进行战斗。
6. 从系统托盘选择“退出痒痒猫”。退出会停止读取进程，并恢复由工具临时启用的 ADB root；原本已启用的 root 保持原样。

## 数据与状态

只读取进程映射、客户端对象和服务器已下发的数据。不截图、不 OCR、不修改游戏内存、不注入代码、不调用游戏 RPC，也不提供手动标记完成。

默认每 5 秒开始一轮采样，每个实例一个后台进程。读取超时不叠加请求；断线、进程重启和角色变化时重新连接。暂停或超过 30 秒未更新时，旧状态显示为“未确认／上次记录”。

| 状态 | 含义 |
| --- | --- |
| 未完成／进行中 | 当前周期有可靠计数或进行中的寄养等记录 |
| 待领取 | 完成条件满足，但仍有奖励或收益可领取 |
| 已完成 | 当前周期完成条件和适用的领取条件均已核实 |
| 未确认 | 未加载、未适配、证据过期，或缺少当前周期／领奖证据 |
| 未开放／已错过 | 有可靠开放配置或明确时段，当前不可进行 |

日常和周常没有统一的“清零”推断：悬赏使用批次有效期，竞速使用赛程起止时间，商店使用客户端每周购买字段，斗技单独核实周结算。无法确认重置规则的活动不会凭系统日期判定已完成。

自动祈愿的累计收片不表示今天收到碎片；结界今天收过一次也不表示当前追加收益已清空。食盒和寄养展示当前收益／到期状态。斗技不设额外积分目标。

## 当前适配范围

任务目录包含 22 项日常和 7 项周常。**目录覆盖不等于每项都已有可靠完成判定。** 各字段的证据和限制见 [docs/coverage.md](docs/coverage.md)。

目前能判定的主要项目包括签到、基础活跃与领取记录、已加载的金币／经验次数、地域鬼王、寮集体任务、祈愿安排、食盒、寄养、宠物御魂加成及协战、免费召唤、免费礼包和庭院体力等。是否显示结果取决于当前账号是否下发相应字段。

周兑换支持勋章、荣誉、功勋商店中已核实的周限购商品和账号周购买记录；默认关注荣誉符咒、勋章符咒／达摩、功勋符咒／碎片礼包，可自行选择。竞速当前赛程、分享领奖、斗技资格／结算和限时寮活动仍可能显示未确认，不能将历史最高层数或上周段位作为本周完成结果。

当前只适配已实测的 Windows x64、MuMu 6.8.4 和国服 x86_64 客户端库：

```text
c1dd25d02c5761b3e49454aa7ae081e7f75001e5c2d556bd8736f9647659e131
```

主机使用 Python 3.12，游戏内的已校验对象布局为 CPython 3.11。客户端库摘要不匹配时停止读取并提示未适配，不尝试套用旧地址。其他客户端、渠道和架构需要独立核实。

## 本地记录

配置、轮转日志和每个账号的最近一次快照保存在 `%LOCALAPPDATA%/yym`：

```text
settings.json
yym.log
yym-worker-0.log
accounts/<server-account-hash>/latest.json
```

快照包含账号标识、任务、所属周期、进度、来源和读取时间，仅保存在本机。历史文件不直接用作今天或本周的完成结果；不上传遥测。项目测试夹具使用合成账号，不包含真实账号数据。

## 开发与构建

在 Windows x64、Python 3.12 环境执行：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
.venv/Scripts/python.exe -m pip install -e . --no-deps --no-build-isolation
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m yym
.venv/Scripts/python.exe tools/build.py
```

构建产物位于 `dist/yym/yym.exe`。构建脚本同时复制 MIT 许可证、说明和第三方许可证。Qt 以独立 DLL 提供。

使用 `python tools/package.py` 生成便携包、源码包及 `dist/checksums.sha256`。本次实测结果及尚未完成的实机场景见 [docs/validation.md](docs/validation.md)。

数据读取诊断（输出含账号资料，请勿直接公开）：

```powershell
.venv/Scripts/python.exe -m yym --list-instances
.venv/Scripts/python.exe -m yym --once --instance 0 --output local/snapshot.json
```

新增客户端适配可用 `tools/profile_client.py <library> --output <candidate.json>` 提取公开符号。候选文件默认标为 `REVIEW_REQUIRED`，必须核实 ABI、字段、周期和奖励规则后才可加入发行版。

源码按 MIT 许可发布，保留原仓库 [LICENSE](LICENSE)。
