# Overlapping sidebar input

2026-10-14，yym 0.1.2 修复两个侧栏重叠时点击落到后方窗口的问题。

原生窗口检查显示，两扇侧栏均没有 `WS_EX_TRANSPARENT`。旧代码将“前台窗口属于 yym 进程”作为所有侧栏的提升条件。因此点击侧栏 A 后，周期跟随会把同进程的侧栏 B 也提升到前方，使鼠标下的命中窗口改变。

新规则逐实例匹配前台窗口及其现有 owner 链：仅本实例的 MuMu、侧栏、设置对话框或所属弹出窗口使该侧栏保持前方。其他侧栏不因共享进程而被提升。只读取既有 owner 关系，不恢复此前已取消的跨进程窗口绑定。

## Verification

* 51 项自动测试通过；新增同进程侧栏隔离、设置对话框归属及 owner 链循环保护测试。
* `tools/verify_overlap.py` 用临时窗口和受控的前台窗口标识复现旧逻辑：激活 A 后，真实 Windows 命中 HWND 变成 B。
* 替换为新逻辑后，交替将两个临时侧栏置前，共 4 次原生命中和按钮事件验证。每次前方按钮收到 1 次点击，后方收到 0 次，按下至松开期间命中窗口稳定。
* 测试注入前台标识以避免抢占用户焦点，窗口层级、命中和按钮消息仍由 Windows／Qt 实际处理；未向游戏发送任何输入，未使用截图或 OCR。
* 双屏 100%／150% DPI 的吸附、回退、折叠和最小化恢复再次通过。

窗口层级与祖先关系分别参见微软的 [SetWindowPos](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos) 和 [GetAncestor](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getancestor) 文档。
