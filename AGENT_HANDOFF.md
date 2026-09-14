# Screenshot Translator Agent Handoff

本文档是面向后续 Agent 的工程现场快照，不是聊天记录，也不是面向最终用户的安装说明。后续 Agent 应先阅读仓库根目录的 `AGENTS.md`，再使用本文档恢复任务现场；状态标签用于区分证据、用户要求和未验证事项。

## 1. Handoff Metadata

- Handoff 更新时间：`2026-09-14T15:20:00+08:00`
- 当前项目：Screenshot Translator
- Handoff 范围：KDE Plasma Wayland 适配完成后的现场，以及仍然未验证的交互范围
- 项目路径：`$HOME/tools/screenshot-translator`
- 远端：`origin`（GitHub，私钥配置在用户 `~/.ssh/config` 中，不要复制密钥）
- 分支：`master`
- 上一份交接文档对应 X11 阶段；X11 行为在本次适配中保留。

## 2. Resume Here

### 当前状态

KDE Plasma Wayland 的核心链路已实现并在真实 Arch + KDE Plasma Wayland 会话中验证：

```text
KGlobalAccel 快捷键 → Spectacle 全屏抓取 → 全屏选择层 → Umi-OCR
→ 可插拔翻译 → 全屏透明画布原位贴图
```

X11 路径保留原有 `qt_x11` + `pynput` 实现。

### 本次实现摘要

- `capture.backend = auto`：X11 解析为 `qt_x11`，Wayland 解析为 `spectacle`；显式配置的 `qt_x11` 在 Wayland 下会记录警告并改用 `spectacle`。
- `capture_desktop_spectacle()`：`spectacle -b -n -f -o <临时文件>`，读入 `QImage` 后立即删除临时文件；返回逻辑虚拟桌面矩形、物理截图和 `scale_x`/`scale_y`。
- `Selector`：统一按“全局逻辑坐标 → 物理像素”映射绘制和裁剪，Wayland 下全屏窗口固定主屏幕。
- `app.input_backend = auto`：X11 用 `pynput`，Wayland 用 `KGlobalAccel`（`WaylandInputService`）。
- `OverlayWindow`/`LoadingWindow` 在 Wayland 进入全屏透明画布模式，`setMask()` 限制输入区域，其余点击穿透。
- 贴图交互：左键按住立即拖动、滚轮以鼠标位置为锚点缩放（25%~400%）、中键归位（位置+100%）、右键点击图片关闭；合成事件单测已通过。
- 第二个全局快捷键（默认 `Super+Ctrl+Shift+O`，`app.copy_hotkey`）：只调用 Umi-OCR 并把原文复制到剪贴板（`ocr.copy_parser` 可单独指定解析方案）；KGlobalAccel 双动作注册与 `translate=False` 流水线已单测。
- 单实例保护（`app.lock` + flock）和 `--quit` 停止常驻实例；系统托盘（StatusNotifierItem）提供截图、截图并复制原文、打开配置/日志、退出；已实测 SNI 注册成功。
- `--check` 按会话输出 `截图后端` 和 `全局快捷键` 检查结果。

### 重要实现事实

- Wayland 下 `QScreen.devicePixelRatio()` 会被 Qt 取整（1.5 报成 2.0），坐标换算必须使用 `截图物理尺寸 / 逻辑屏幕尺寸`；窗口实际按 1.5 渲染（`QWidget.devicePixelRatioF()`=1.5）。
- Spectacle 后台抓屏必须加 `-i`：已有 Spectacle GUI 实例时会吞掉请求并 exit 0 但不写文件。
- PySide6 `QDBusMessage` 无法序列化 KGlobalAccel `setShortcut` 的 `u` flags（会发成 `i`），设置快捷键必须走 `gdbus`（优先）或 `dbus-send` 子进程；`doRegister`、`setInactive`、`shortcut` 读取和信号订阅可用 QtDBus。
- QtDBus 信号订阅的 slot 必须写成 `"1on_pressed(QString,QString,qlonglong)"` 这种 SLOT 宏格式字符串。
- KGlobalAccel 仅 `doRegister` 不会抓取按键；必须调用 `setShortcut` 且 flags = `SetPresent(2) | NoAutoloading(4)` = 6。
- 已存在的 KGlobalAccel 绑定优先保留，便于用户在 System Settings 中自定义。

## 3. Verified Facts

- [VERIFIED][RUNTIME] `./run.sh --check` 在 Arch + KDE Plasma Wayland 上 PASS：`会话: OK (wayland KDE)`、`截图后端: OK (spectacle)`、`全局快捷键(KGlobalAccel): OK`、`Umi-OCR HTTP: OK`。
- [VERIFIED][RUNTIME] KGlobalAccel `invokeShortcut` 触发后应用完成 Spectacle 抓取（2560x1440 / 逻辑 1707x960 / scale 1.4997x1.5）并显示全屏选择层；外部 Spectacle 抓屏对比显示 85.3% 采样像素被选择层暗化。
- [VERIFIED][RUNTIME] 合成鼠标事件端到端：框选逻辑 (400,300,1001,521) → 物理裁剪 1501x782 → Umi-OCR 8 段 → `identity` → 画布贴图位置与选区一致，画布左侧区域像素完全不变。
- [VERIFIED][RUNTIME] `LoadingWindow` 画布模式：全屏几何、mask 仅为选区中心 34x34 转圈、`WA_TransparentForMouseEvents`。
- [VERIFIED][CODE] X11 路径未删除：`qt_x11`、`pynput`、定位式 `OverlayWindow` 和点击外部关闭逻辑仍在。
- [VERIFIED][LOG] KGlobalAccel 快捷键注册后为 `Ctrl+Alt+D`（key `0xc000044`），出现在 `~/.config/kglobalshortcutsrc` 的 `[screenshot-translator]` 段。

## 4. Not Verified / Limitations

- [UNVERIFIED] 真实鼠标交互：拖选、右键取消、过长/过短选区、贴图按钮、拖动、滚轮缩放、中键归位、右键关闭、再次截图替换尚未人工验收。
- [UNVERIFIED] 真实翻译后端（`google` / `google_cloud`）的最新一次验证；集成测试使用 `identity`。
- [UNVERIFIED] 多屏、负坐标、混合 DPI；Wayland 选择层当前固定在 Qt 主屏幕。
- [LIMITATION] Wayland 全局快捷键触发选择层时 KWin 不给键盘焦点（日志 `active=False`），`Esc` 可能无效；右键仍可取消。
- [LIMITATION] Wayland 无全局鼠标监听：点击贴图外部不关闭，用 `×`、再次触发快捷键或（有焦点时）`Esc`。
- [LIMITATION] GNOME、wlroots 等非 KDE Wayland 未验证。

## 5. Environment

```text
系统：Arch Linux（rolling）
桌面：KDE Plasma / Wayland
会话：XDG_SESSION_TYPE=wayland，WAYLAND_DISPLAY=wayland-0
Python：3.14.7（项目 .venv）
PySide6：6.11.2（含 QtDBus）
Spectacle：6.7.5
屏幕：eDP-1 2560x1440 物理，缩放 1.5，逻辑 1707x960
全局快捷键：kglobalacceld 6.7.5（KDE D-Bus）
Umi-OCR：~/tools/Umi-OCR_Linux_Paddle_2.1.5，HTTP 127.0.0.1:1224
```

用户运行目录（不在仓库内）：

```text
配置：~/.config/screenshot-translator/config.toml
密钥：~/.config/screenshot-translator/keys.toml（可选，600）
日志：~/.local/state/screenshot-translator/app.log
缓存：~/.cache/screenshot-translator/（Spectacle 临时截图会自动清理）
```

## 6. Next Steps

1. 在 Wayland 会话用真实鼠标完成一次完整交互验收，记录每一步结果。
2. 用真实翻译后端验证译图显示；必要时先切 `identity` 排除网络因素。
3. 评估多屏/混合缩放方案；首版不承诺。
4. 若需要，评估 XDG GlobalShortcuts Portal 或 XWayland 定位方案作为 Gnome/wlroots 的通用后备。

## 7. Guardrails

- 不提交真实 API Key、`keys.toml`、日志正文、OCR/翻译正文或截图像素。
- 不读取 `keys.toml` 内容，只使用其路径和存在性。
- 不删除 `~/tools/Umi-OCR_Linux_Paddle_2.1.5`。
- 不使用 `git reset --hard`、`git clean -fd` 覆盖未知修改。
- Git 提交按 `AGENTS.md` 规范：展示文件、关键 diff 和完整消息并取得用户确认；推送前再次确认。
