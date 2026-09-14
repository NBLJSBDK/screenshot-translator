# Screenshot Translator 项目协作说明

本文件是项目唯一的 Agent 工作说明。开始开发、排查或测试前先阅读本文件，再检查实际文件、运行环境和 Git 状态。不要依赖已经删除的交接文件，也不要根据旧聊天记录臆测现场。

## 项目目标

Screenshot Translator 是面向 Linux + KDE Plasma 的无主窗口截图翻译贴片工具，支持 X11 和 KDE Plasma Wayland 会话。它提供系统托盘图标（运行状态、截图、打开配置/日志、退出），但不提供普通主窗口、设置界面或完整截图管理器。

默认流程：

```text
Ctrl+Alt+D → 全屏选择层拖选 → Umi-OCR → 翻译 → 在原屏幕位置显示贴片
Super+Ctrl+Shift+O（app.copy_hotkey，可留空禁用）→ 同样框选 → 只 OCR
  → 原文自动复制到剪贴板 + 通知（不翻译、不显示贴图）
```

X11 使用 Qt 直接抓屏和 pynput 全局输入；KDE Wayland 使用 Spectacle 全屏抓取、KGlobalAccel 全局快捷键和全屏透明画布贴图。核心流程已在两边验证；Wayland 的点击外部关闭、键盘焦点、多屏和混合缩放有平台限制，不得夸大为已完成。

## 已验证环境

Wayland 目标环境：

```text
系统：Arch Linux（rolling，内核 7.2.4）
桌面：KDE Plasma / Wayland
会话：XDG_SESSION_TYPE=wayland，WAYLAND_DISPLAY=wayland-0
Python：3.14.7
Spectacle：6.7.5
屏幕：eDP-1 2560x1440 物理，缩放 1.5，逻辑 1707x960，devicePixelRatio 报告为 2.0
全局快捷键：KGlobalAccel（kglobalacceld 6.7.5，KDE D-Bus）
```

X11 参考环境（历史验证）：

```text
系统：Debian GNU/Linux 13 (trixie)
Python：3.13.5
桌面：KDE Plasma / X11
DISPLAY：:0
屏幕：HDMI-0 2560x1440，devicePixelRatio=1
```

Umi-OCR 安装位置：

```text
~/tools/Umi-OCR_Linux_Paddle_2.1.5
```

启动脚本：`~/tools/Umi-OCR_Linux_Paddle_2.1.5/umi-ocr.sh`。

HTTP API：`http://127.0.0.1:1224/api/ocr`。

项目依赖必须在项目 `.venv` 中安装。已验证 PySide6 6.11.2（含 QtDBus）、pynput 1.8.2、evdev 2.0.0、python-xlib 0.33 和 six 可用；Python 3.14 上 evdev 需要可用的 C 工具链编译，Arch 安装 `base-devel` 即可。不要把这些依赖装进系统 Python。

## 文件与路径

```text
app.py                 主程序：选择器、OCR/翻译、贴图、输入监听
config.example.toml    默认配置模板
keys.example.toml      Google Cloud API Key 配置模板，不含真实密钥
assets/app-icon.svg    托盘图标源文件（Font Awesome Free 5.15.4 `globe`，CC BY 4.0；运行时按配色染白）
assets/LICENSE-fontawesome.txt  Font Awesome Free 许可证与署名
requirements.txt       Python 依赖
install.sh             创建 .venv 并安装依赖
run.sh                 使用 .venv 启动 app.py
README.md              用户说明
使用说明.md            新机器安装、Google Cloud 配置和配额防护
AGENTS.md              本文件，唯一的 Agent 说明
```

用户配置、状态和日志位于仓库外：

```text
配置：~/.config/screenshot-translator/config.toml
密钥：~/.config/screenshot-translator/keys.toml（可选，权限应为 600）
日志：~/.local/state/screenshot-translator/app.log
缓存：~/.cache/screenshot-translator/
```

日志默认只写运行元数据和错误，不写截图像素、OCR 正文或翻译正文。

## 程序架构

### 配置和日志

`deep_merge()`、`ensure_runtime_dirs()`、`ensure_config()`、`load_config()`、`configure_logging()`、`reload_log_level()` 和 `notify()` 负责配置合并、XDG 目录、日志级别热加载和通知。

失败必须使用桌面通知加日志，不得弹模态错误对话框。通知优先使用 `notify-send`，否则使用 `kdialog --passivepopup`。

### 截图和全屏选择层

`capture_desktop()` 按 `effective_capture_backend()` 选择后端：

- `qt_x11`（默认 X11）：`capture_virtual_desktop()` 使用 `QScreen.grabWindow(0)` 抓取各屏幕并合成虚拟桌面。
- `spectacle`（KDE Wayland）：`capture_desktop_spectacle()` 运行 `spectacle -b -n -i -f -o <临时文件>` 抓取整屏，读入 `QImage` 后立即删除临时文件。Wayland 客户端不能读取其他 surface，必须先抓取再显示选择层。`-i` 不能省略：桌面已有 Spectacle GUI 实例时，普通后台调用会被吞掉并返回 0 但不生成文件。

`CaptureResult` 统一返回逻辑虚拟桌面矩形、物理像素截图和 `scale_x`/`scale_y`（物理像素/逻辑像素）。Wayland 下 `QScreen.devicePixelRatio()` 会被 Qt 取整（1.5 报成 2.0），不得用它做坐标换算，必须用截图尺寸与逻辑屏幕尺寸的比值。

`Selector` 是无边框全屏选择层：

- 必须覆盖整个屏幕，包括 KDE 面板和任务栏；选择时任务栏不应重复出现。
- 当前实现使用 `WindowFullScreen`，不要退回只覆盖 available geometry 的普通窗口。
- 背景绘制、选区预览和裁剪都通过“全局逻辑坐标 → 物理像素”映射完成，显示的像素必须和送给 OCR 的截图一致。
- 左键拖动选择；`Esc` 或右键取消；小于最小尺寸的区域无效。
- `selected` 返回全局逻辑 `QRect` 和物理像素裁剪 `QImage`。
- Wayland 下选择层固定显示在 Qt 主屏幕；KWin 可能不给它键盘焦点，此时 `Esc` 无效，右键仍可取消。

不要把窗口局部坐标直接当作虚拟桌面坐标，也不要用拉伸整张图掩盖几何偏移。

### OCR 和翻译

`PipelineWorker` 在后台线程中：

1. 探测 Umi-OCR HTTP 服务。
2. 服务不可用且 `ocr.auto_start=true` 时运行 `umi-ocr.sh --hide` 并等待就绪。
3. 以 base64 PNG 调用 `/api/ocr`，请求 `data.format = dict`；排版方案取 `ocr.parser`（`translate=False` 时可用 `ocr.copy_parser` 覆盖）。
4. 使用返回项的 `text`、`box`、`end` 组织源文本和段落。
5. `translate=True` 时按段落调用可插拔翻译后端；`translate=False` 时只发出 `source_text`（`paragraphs` 为空），供复制模式使用。
6. 发出源文、译文、段落边界框和耗时。

支持的 backend：

```text
google（免 Key 非官方接口，可能 HTTP 429）
google_cloud（官方 Cloud Translation Basic v2，Key 从独立 keys.toml 读取）
libre / libretranslate
identity（原样返回 OCR 文本，仅用于本地链路测试）
```

`google_cloud` 使用 `https://translation.googleapis.com/language/translate/v2`，通过 `X-Goog-Api-Key` 请求头认证；一次请求最多提交 128 个段落，避免逐段等待。Key 不得写入主配置、日志或 Git。

Google 曾出现 HTTP 429。不要让网络翻译成功与否掩盖截图、OCR 或 UI 问题。

### 渲染和贴图

`render_translation()` 复制原图，在 OCR 段落边界框上绘制深色半透明圆角遮罩，再绘制译文。当前版本不做 AI 背景修复或 inpainting，图片和非文字区域保留原图。

截图框选完成后，`LoadingWindow` 在选区中心显示一个不抢焦点的转圈指示；OCR/翻译完成或失败后必须关闭，不得遮挡或改变最终贴图交互。

`OverlayWindow` / `DraggableImage` 显示原位贴图和紧凑控件：

```text
[原/译] [原] [译] [×]
```

- `原/译`：切换原图和译图。
- `原`：复制完整 OCR 原文。
- `译`：复制完整译文。
- `×`：关闭贴图。
- 控件优先放截图下方，空间不足时放上方，再不行放右下角内部。
- 左键按住图片即可拖动整个贴图和控件组（`app.drag_hold_ms = 0` 立即拖动；大于 0 时需长按）。
- 滚轮以鼠标位置为锚点缩放贴图，范围 25%~400%，工具栏按钮尺寸不变。
- 中键点击图片：归位，位置回到最初框选处并将缩放恢复为 100%。
- 右键点击图片：关闭贴图。
- 使用无边框、置顶和 `Tool` 窗口标志；不要使用 `Qt.Popup`。

X11 下 `OverlayWindow` 通过全局矩形定位贴图。Wayland 不允许客户端定位顶层窗口，因此 `OverlayWindow` 进入 `canvas_mode`：窗口是全屏透明画布，贴图按逻辑坐标画在画布内，`setMask()` 把输入区域限制为贴图和按钮，其余位置的点击穿透给下层窗口；拖动只移动画布内的子控件，不移动窗口。`LoadingWindow` 同样用全屏透明画布绘制选区中心的转圈，并用 mask 把自己限制在转圈区域。

贴图在 X11 下可以通过 `Esc`、点击贴图和控件组外部、右键点击图片或 `×` 关闭；Wayland 没有全局鼠标监听，只能通过右键点击图片、`×`、再次截图或 `Esc`（若窗口有键盘焦点）关闭。单纯失去焦点或 Alt+Tab 不得关闭。再次截图时先关闭旧贴图，一次只保留一个。

### 全局输入和控制器

`create_input_service()` 按会话选择输入后端，并同时注册两个动作（`KGA_ACTIONS`）：`capture`（翻译，`app.hotkey`）和 `copy`（只识别，`app.copy_hotkey`，留空禁用）。

- `pynput`（X11）：`InputService` 监听两个全局快捷键和鼠标按下事件，`close_on_outside_click` 依赖它。
- `kglobalaccel`（KDE Wayland）：`WaylandInputService` 通过 KGlobalAccel D-Bus 注册两个动作并订阅 `globalShortcutPressed`，按 `shortcut` 名分派到 `hotkey_pressed` / `copy_hotkey_pressed`。PySide6 无法序列化 `setShortcut` 的 `u` flags，因此设置快捷键通过 `gdbus`（优先）或 `dbus-send` 子进程完成；doRegister、setInactive 和信号订阅仍走 QtDBus。Wayland 没有全局鼠标监听，`mouse_pressed` 不会触发。

快捷键支持组合键和无修饰键的 F13-F24（例如 `f13`）。配置文件为准：每次启动和配置变更都会写入 KGlobalAccel；在 System Settings 中的临时修改会在下次启动时被配置覆盖。留空表示把该动作标记为 inactive。X11/pynput 只支持到 F20。

`Controller` 负责配置热加载、快捷键重注册、选择层、后台流水线、贴图生命周期、系统托盘图标（`app.tray_icon` 热切换）和点击外部关闭逻辑。托盘用 `QSystemTrayIcon`（KDE 下为 StatusNotifierItem），菜单为截图、截图并复制原文、打开配置、打开日志、退出；左键单击等同触发截图。`_start_selection(mode)` 以 `pending_mode`（`translate` / `copy`）区分两条流水线；`copy` 模式完成后写入剪贴板并通知，不创建 `OverlayWindow`。

## 安装、检查和运行

```bash
cd ~/tools/screenshot-translator
./install.sh
./run.sh --check
./run.sh
```

程序是单实例的：`acquire_single_instance()` 用 `~/.local/state/screenshot-translator/app.lock` 的 `flock` 阻止重复启动；没有终端窗口的实例用 `./run.sh --quit` 停止（读取锁文件 PID 后发送 SIGTERM）。锁文件不能以 `"w"` 模式打开，否则会清掉正在运行实例的 PID。

`install.sh` 只在项目中创建 `.venv` 并安装 `requirements.txt`，不应使用 `sudo`，不应污染系统 Qt 路径。`--check` 不访问外部翻译服务；Umi-OCR 未运行但脚本存在时可以报告运行时自动启动警告。

KDE Wayland 还需要系统已有 `spectacle`，以及 `gdbus`（glib2）或 `dbus-send`（dbus）之一；`install.sh` 不安装这些系统包。

首次运行保持终端可见，先将配置设为：

```toml
[translation]
backend = "identity"
source = "auto"
target = "zh-CN"
```

只有本地截图 → OCR → 渲染 → 贴图交互稳定后，才测试真实翻译后端。

## 验证顺序

每次修改后依次执行：

1. `python -m py_compile app.py`、`bash -n install.sh run.sh`、`git diff --check`。
2. `./run.sh --check`。
3. 前台程序启动无异常，系统托盘出现图标；`./run.sh --quit` 能结束实例。
4. `Ctrl+Alt+D` 显示覆盖整个屏幕的选择层（X11 下任务栏只出现一次；Wayland 下整屏变暗）。
5. 拖选区域的显示像素、全局边界和 OCR 输入一致（Wayland 注意逻辑坐标×缩放 = 物理像素）。
6. 使用 `identity` 验证原位贴图（Wayland 贴图应出现在选区原位置）。
7. 验证原/译切换、复制原文、复制译文、`×`、右键关闭、中键归位、滚轮缩放、左键拖动、再次截图替换；Wayland 的 `Esc`/点击外部限制见上。
8. 按 `Super+Ctrl+Shift+O`（`app.copy_hotkey`）框选：应只 OCR、不翻译，原文进入剪贴板并弹通知；`app.copy_hotkey` 留空时该动作不注册。
9. 验证 OCR/翻译失败只通知和写日志。
10. 最后单独测试 Google 或 LibreTranslate。

在完整实测前不要声称全部功能可用。混合 DPI、多屏和 GNOME/wlroots 等非 KDE Wayland 尚未专门验证。

## 保护边界

- 不删除 `~/tools/Umi-OCR_Linux_Paddle_2.1.5`。
- 不重新安装 Manggo 或覆盖 `/usr/bin/qt.conf`、`/usr/plugins` 等系统 Qt 路径。
- 不假设系统有 Tesseract；它不是项目依赖。
- 不把真实 API Key、`keys.toml` 或其他凭据提交到仓库。
- 托盘图标已按用户要求实现（`app.tray_icon`）；不增加主窗口、设置 GUI 或模态错误窗口，除非用户再次明确改变需求。
- 不把 `.venv`、缓存、日志或个人配置提交到仓库。
- 不使用 `git reset --hard`、`git clean -fd` 等会销毁未知修改的命令。
- 不把 Wayland 的平台限制（点击外部关闭、Esc 焦点、多屏定位）描述成已修复；也不要在未在目标会话实测前宣称 Wayland 支持范围。

## Git 协作规范

提交消息格式：

```text
<type>(<scope>): <简短说明>
```

允许的 `type`：

| type | 用途 | 示例 |
| --- | --- | --- |
| `feat` | 新功能 | `feat(auth): 增加微信登录功能` |
| `fix` | 修补 Bug | `fix(capture): 修复全屏选区偏移` |
| `refactor` | 重构 | `refactor: 简化逻辑判断函数` |
| `perf` | 性能优化 | `perf: 提高渲染效率` |
| `docs` | 文档变动 | `docs: 更新项目说明` |
| `test` | 测试变动 | `test: 添加选择层几何测试` |
| `chore` | 构建或辅助工具 | `chore: 升级依赖库` |
| `wip` | 工作进行中 | `wip: 正在处理选择层` |

禁止使用：`add`、`update`、`modify`、`big`。

提交规则：

- 按逻辑分组、分步提交，不把无关修改混成一个提交。
- 提交前检查工作树、暂存区和 diff。
- 每次提交前先向用户展示拟提交文件、关键 diff 和完整提交消息，并取得明确确认。
- 用户对一次任务的提交授权只使用一次；完成该任务后不得自动延伸到后续任务。
- 未确认时可以编辑、测试、查看 diff 和暂存，但不得执行 `git commit`。
- `git push` 前必须再次取得用户明确确认；初始化或更换远程地址也要先说明目标。
- 保留用户已有修改，不使用破坏性 Git 操作覆盖未知内容。

## 当前工作起点

X11 与 KDE Plasma Wayland 的适配已经完成并验证到以下程度：

- `./run.sh --check` 在 Arch + KDE Plasma Wayland 上 PASS（会话、spectacle、KGlobalAccel、Qt 屏幕、Umi-OCR、通知）。
- KGlobalAccel 触发 → Spectacle 全屏抓取 → 全屏选择层（外部截图确认 85% 像素被暗化）已验证。
- 合成鼠标事件端到端：框选逻辑坐标 (400,300,1001,521) → 物理裁剪 1501x782 → Umi-OCR 8 段 → `identity` 渲染 → Wayland 画布贴图位置与选区一致，画布外区域像素不变。
- 尚未在真实鼠标/拖动/按钮操作下完成人工交互验收；`Esc` 焦点、点击外部关闭、多屏、混合缩放的 Wayland 行为仍未验证。

后续优先事项：

1. 在 Wayland 会话用真实鼠标完成一次完整交互验收（拖选、右键取消、太长/太短选区、贴图按钮、拖动、再次截图）。
2. 用真实翻译后端（`google` 或 `google_cloud`）验证译图显示。
3. 评估多屏与混合缩放；当前选择层固定在 Qt 主屏幕。
4. 每次提交前按 Git 规范展示文件、diff 和提交消息并取得用户确认。
