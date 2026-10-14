# Window following performance

2026-10-14，yym 0.1.1 修复 MuMu 拖动时侧栏和模拟器一起卡顿的问题。

旧实现使用 `GWLP_HWNDPARENT` 将侧栏设为另一个进程窗口的附属窗口。微软说明，这种 owner/owned 关系会[自动连接输入队列](https://devblogs.microsoft.com/oldnewthing/20130607-00/?p=4143)，使两个程序的界面处理发生等待。旧代码还在 WinEvent 回调中直接跟随，监听全桌面的位置事件，并在纯移动时重复传入尺寸和切换控件显示状态。

修复后的侧栏保持独立窗口，不设置跨进程 owner。仅在 MuMu 或痒痒猫获得焦点时将侧栏置于前方，切换其他应用时降回普通层级，全程不激活或修改 MuMu 窗口。最小化和恢复由只读窗口状态控制。

位置、显示和最小化事件限定到目标进程，过滤非窗口对象、子对象及[自身进程事件](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwineventhook)。回调仅记录待更新窗口，16 毫秒单次定时器合并事件后读取最新坐标，不排队保存历史位置。尺寸未变时使用 [SWP_NOSIZE](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos)，坐标不变则不调用定位；展开状态不变时不切换布局。

## Verification

* 48 项自动测试通过，包括 2,000 条突发事件合并、退出取消待更新、目标进程过滤、纯移动不缩放及不抢焦点。
* 两个显示器的 150%／100% DPI 左吸附、右回退、双侧不足折叠和最小化恢复通过原生坐标及 Qt 控件检查。
* `tools/verify_follow.py` 创建独立进程的测试窗口：5 秒内 624 次移动，合并为 206 次侧栏跟随，单次更新第 95 百分位约 2.11 毫秒。
* 刻意阻塞侧栏 GUI 200 毫秒时，目标测试窗口在扣除两端各 30 毫秒的区间内仍移动 17 次，窗口间没有跨进程 owner 绑定。

以上是原生测试窗口及程序自动测试，不代表对用户鼠标拖动手感的测量。游戏验证仍只使用文件、内存和窗口属性，不使用截图、OCR、战斗或领奖。
