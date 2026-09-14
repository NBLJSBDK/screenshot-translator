# Screenshot Translator Agent Handoff

本文档是面向后续 Agent 的工程现场快照，不是聊天记录，也不是面向最终用户的安装说明。后续 Agent 应先阅读仓库根目录的 `AGENTS.md`，再使用本文档恢复任务现场；当前文件中的状态标签用于区分证据、用户要求和未验证事项。

## 1. Handoff Metadata

- Handoff 创建时间：`2026-09-14T10:12:51+08:00`
- 来源环境：Codex desktop，Linux 工作区
- 当前项目：Screenshot Translator
- Handoff 范围：将当前 X11 版本的完整状态迁移给后续 Agent，继续开发 Arch Linux + KDE Plasma Wayland 兼容性
- 原始完整对话文件：Unknown；当前快照已保留与继续开发有关的需求、决策和证据摘要
- 项目路径：`/home/hao123/tools/screenshot-translator`
- Git repository：`/home/hao123/tools/screenshot-translator/.git`
- 远端：`origin = git@github.com:NBLJSBDK/screenshot-translator.git`
- 分支：`master`
- 快照创建前 HEAD：`861e67a296400c7455d54c4f3fc4fb5b4c3e04de`
- 快照创建前版本标签：`v0.1.0`，指向提交 `861e67a`
- 注意：本文件在快照生成时是新增工作区文件，提交后 HEAD 将变化；后续 Agent 应以实际 `git status`、`git log` 和 `git show` 为准。

## 2. Resume Here

### 当前最终目标

在 Arch Linux + KDE Plasma Wayland 上继续完善 Screenshot Translator，同时保留现有 X11 路径。目标产品仍是无主窗口的快捷键截图翻译贴片器：截图/框选 → 本地 Umi-OCR → 可插拔翻译 → 原位置贴图。

### 当前具体子任务

- 设计并实现 KDE Plasma Wayland 首版兼容性。
- 用户已经选择 KDE Plasma Wayland 优先，首版先保证核心流程可用。
- 用户已经选择“Spectacle 全屏抓取 + 本程序自有框选层”作为首版截图路线的工作方向。

### 当前进度

- X11 截图、全屏框选、OCR、翻译、原位贴图、翻译中转圈、配置和 Google Cloud 配置说明已经存在于代码和文档中。
- 当前代码没有 Wayland 后端；`app.py` 启动时明确拒绝 Wayland。
- 当前代码没有调用 Spectacle；Spectacle 仅作为后续 KDE Wayland 截图后端候选。
- 本次只生成交接文档，未修改程序逻辑。

### 当前阻塞

- Wayland 不允许直接复用 X11 的根窗口抓屏、全局顶层窗口定位和全局鼠标监听假设。
- 当前开发环境是 Debian + KDE Plasma + X11，不是目标 Arch + KDE Plasma Wayland，因此没有目标环境运行证据。
- Wayland 首版仍需决定并验证：Spectacle 调用方式、选区坐标模型、全局快捷键注册方式、贴图窗口定位方式。

### 最近一次操作与结果

- 重新检查了当前 Git 状态、代码入口、配置和依赖。
- 在真实权限下运行 `./run.sh --check`，结果为 `PASS`。
- 静态检查 `python -m py_compile app.py`、`bash -n install.sh run.sh`、`git diff --check` 均通过。
- 当前没有进行新的桌面交互截图验收。

### 下一步立即动作

1. 在目标 Arch + KDE Plasma Wayland 机器上重新采集会话、屏幕、Spectacle、门户和 Qt 平台信息。
2. 先运行当前版本作为基线，记录它按设计拒绝 Wayland 的输出。
3. 以接口方式隔离截图后端，保留 `qt_x11`，新增 KDE Wayland 试验后端。
4. 首先验证单显示器的 Spectacle 全屏截图、程序自有框选和 OCR 链路，再处理多屏、精确贴图和点击外部关闭。

### 重要护栏

- 在 Wayland 实测前不得宣称项目已支持 Wayland。
- 不要把当前 X11 的 `QScreen.grabWindow(0)`、`mapToGlobal()`、`pynput` 全局鼠标监听直接当作 Wayland 方案。
- 不读取、记录或提交真实 API Key、`keys.toml`、私钥、Cookie、Token 或 OCR/翻译正文。
- 不删除 Umi-OCR 安装目录，不使用 `git reset --hard`、`git clean -fd` 覆盖未知修改。
- Git 提交必须遵守 `AGENTS.md`：展示文件、关键 diff 和完整提交消息后取得确认；推送前再次取得确认。当前用户已对本次“整理工作区并提交交接文档”明确提出提交要求，但后续独立任务仍需重新确认。

## 3. Task & Scope

### 当前目标

[USER] 用户希望把项目带到 Arch Linux + KDE Plasma Wayland 上继续完善。首个目标环境是 KDE Plasma Wayland，不要求本阶段立即覆盖所有 Wayland compositor。

[USER] 首版优先保证核心链路：快捷键触发、截图、框选、Umi-OCR、翻译、贴图显示。完整复刻 X11 的多屏精确定位、点击贴图外关闭和所有窗口行为可以在核心链路稳定后继续补齐，但不能在未验证时宣称已完成。

[USER] 截图路线优先采用 Spectacle 全屏抓取，再使用本程序现有框选层；这保留程序对 OCR 输入图像和框选区域的控制。

### 已完成

- X11 直接抓屏并合成虚拟桌面。
- 全屏 Qt 选区层覆盖 KDE 面板和任务栏。
- 选区坐标从窗口局部坐标转换为全局虚拟桌面坐标，并从同一张截图裁剪。
- Umi-OCR HTTP API 调用、段落组织和可插拔翻译后端。
- Google Cloud Translation Basic v2 的独立 Key 配置模板和使用说明。
- 翻译过程的非抢焦点转圈指示。
- 原图/译图切换、复制原文/译文、关闭、长按拖动和再次截图替换等 X11 交互。
- Git 已清理旧的 `v0.1.2`、`v0.1.3` 标签，并在 `861e67a` 创建、推送 `v0.1.0`。

### 尚未完成

- Wayland 截图后端。
- Wayland 全局快捷键后端。
- Wayland 下选区坐标和多输出模型。
- Wayland 下可靠的原位贴图定位和全局点击外部关闭。
- Arch Linux + KDE Plasma Wayland 的真实运行和交互验收。

### 当前任务边界

- 继续维护独立 Screenshot Translator 程序；Umi-OCR 继续作为本地 OCR 服务使用。
- Umi-OCR 插件化曾被讨论，但当前不是本阶段实施目标。
- 不新增普通主窗口、托盘设置 GUI 或模态错误窗口，除非用户后续明确改变需求。

## 4. Environment

### 当前可验证环境

- OS：Debian GNU/Linux 13 (trixie)
- 桌面：KDE Plasma
- 会话：X11
- `DISPLAY`：`:0`
- 屏幕：`HDMI-0 2560x1440`，`devicePixelRatio=1`
- Python：`3.13.5`
- Shell：`zsh`
- 项目虚拟环境：`.venv`
- 已验证 Python 包：PySide6 `6.11.2`、pynput `1.8.2`
- `requirements.txt` 当前只声明 `PySide6>=6.8,<7` 和 `pynput>=1.8,<2`
- Umi-OCR 启动脚本：`~/tools/Umi-OCR_Linux_Paddle_2.1.5/umi-ocr.sh`
- Umi-OCR HTTP：`http://127.0.0.1:1224`
- 系统通知：`kdialog` 可用；检查结果使用了 `/usr/bin/kdialog` fallback

### 当前主机中与 Wayland 方向有关的组件

- `/usr/bin/spectacle` 存在。
- `xdg-desktop-portal-kde` 后端存在。
- PySide6 包含 `libqwayland.so` 和 `libqxcb.so`。
- 当前项目 `.venv` 没有 `dbus-next`、PyGObject 或 pydbus；若直接实现 D-Bus 门户，需要新增依赖或采用其他调用方式。
- 当前会话不是目标 Wayland 会话；上述组件存在不等于 Wayland 功能已经验证。

### 目标环境

- 发行版：Arch Linux（[USER]）
- 桌面：KDE Plasma（[USER]）
- 会话：Wayland（[USER]）
- 具体 Plasma、KWin、Qt、Spectacle、xdg-desktop-portal-kde、PipeWire 版本：Unknown，必须在目标机重新采集。
- 目标机屏幕数量、排列、缩放和面板位置：Unknown。

### 用户运行目录

这些目录不属于 Git 仓库，后续 Agent 不应将其中的秘密复制到交接文档：

- 配置：`~/.config/screenshot-translator/config.toml`
- Key：`~/.config/screenshot-translator/keys.toml`（可选，建议权限 `600`）
- 日志：`~/.local/state/screenshot-translator/app.log`
- 缓存：`~/.cache/screenshot-translator/`

## 5. Repository & Working Tree State

### 快照创建前状态

[VERIFIED][GIT] 仓库路径为 `/home/hao123/tools/screenshot-translator`。

[VERIFIED][GIT] 分支为 `master`，工作区、暂存区和未跟踪文件在本次新增交接文档前均为空；`master` 与 `origin/master` 均位于 `861e67a`。

[VERIFIED][GIT] 快照创建前本地标签只有 `v0.1.0`；旧的 `v0.1.2`、`v0.1.3` 已被删除。远端在推送前没有旧标签，推送后 `origin` 有 `v0.1.0`。

### 快照创建后的预期状态

- 当前 Agent 新增：`AGENT_HANDOFF.md`。
- 没有已知的用户原有未提交修改。
- 没有来源不明的代码修改。
- 交接文档提交前，`git status --short` 应显示 `?? AGENT_HANDOFF.md`；提交后应恢复干净。

### 最近提交

```text
861e67a feat(setup): 增加 Google Cloud 配置与新机说明
a45f0f8 feat(ui): 增加翻译中转圈提示
180e7cd chore: 忽略本地运行状态
3ae6d64 docs: 集中项目协作与运行说明
1f59385 fix(capture): 修复全屏选区与坐标偏移
be64230 chore: 初始化截图翻译工具项目
```

### 版本命名注意事项

[VERIFIED][CODE][GIT] `app.py` 和 `README.md` 的程序版本文字仍为 `0.1.2`，而当前 Git 发布标签是用户要求创建的 `v0.1.0`。该命名差异没有在本次任务中修改；后续发布工作应先确认版本策略，再决定是否统一。

## 6. Project Map

| 对象 | 作用 | Wayland 任务关系 |
| --- | --- | --- |
| `app.py` | 主程序，包含配置、截图、选区、OCR、翻译、渲染、贴图和输入监听 | 主要实现文件；需要隔离 X11/Wayland 能力 |
| `capture_virtual_desktop()` | 使用 `QScreen.grabWindow(0)` 抓取并合成虚拟桌面 | 当前 X11 专用，需要新增后端或适配器 |
| `Selector` | 全屏 Qt 选区层，绘制截图、遮罩、矩形和裁剪结果 | 当前依赖虚拟桌面和全局坐标；首版需在单屏 Wayland 验证 |
| `InputService` | 使用 pynput 注册全局快捷键和全局鼠标监听 | Wayland 下全局快捷键和鼠标监听需要替代路径 |
| `PipelineWorker` | 启动/检查 Umi-OCR，调用 HTTP OCR，组织段落并调用翻译 | 与显示系统基本无关，可保持 |
| `render_translation()` | 在 OCR 边界框绘制译文遮罩和文字 | 与显示系统基本无关，可保持 |
| `OverlayWindow` / `DraggableImage` | 原位显示贴图、按钮和拖动行为 | `setGeometry(global QRect)` 和全局鼠标关闭在 Wayland 下需重新验证 |
| `Controller` | 串联快捷键、选择层、后台流水线和贴图生命周期 | 负责根据会话选择后端 |
| `config.example.toml` | 主配置模板，当前 `capture.backend = "qt_x11"` | 应扩展为可选择的 Wayland 后端，但先保持 X11 默认值 |
| `keys.example.toml` | 空的 Google Cloud Key 模板 | 只允许保留占位符，不得写入真实 Key |
| `install.sh` / `run.sh` | 创建虚拟环境、安装依赖和启动程序 | Wayland 依赖安装策略需在实现后更新 |
| `README.md` / `使用说明.md` | 快速说明和新机器安装、Google API、配额和隐私说明 | Wayland 验证后再更新当前“仅 X11”表述 |
| `AGENTS.md` | 项目协作、保护边界、验证和 Git 规则 | 所有后续 Agent 必须遵守 |
| `AGENT_HANDOFF.md` | 本次结构化状态快照 | 用于跨 Agent 恢复，不替代实际文件和 Git 检查 |

## 7. Changes Made

### 本次交接文档

- File：`AGENT_HANDOFF.md`
- Change：按用户提供的 Handoff Engineer 提示词建立结构化现场快照。
- Reason：后续 Agent 需要在无聊天历史的情况下继续 Arch Linux + KDE Plasma Wayland 开发。
- Before：仓库没有 `AGENT_HANDOFF.md`。
- After：新增包含 Resume Here、环境、Git、代码地图、验证事实、假设、失败尝试、决策、护栏、下一步和验收标准的交接文件。
- Verification：已重新检查代码、配置、Git、静态检查和 `./run.sh --check`；本文件本身仍需在提交后通过 `git diff --check` 和实际 Git 状态复核。

### 既有 X11 实现（本次未修改）

- `capture_virtual_desktop()` 枚举 Qt 屏幕，调用 `screen.grabWindow(0)`，按屏幕几何偏移绘制到合成的虚拟桌面 `QImage`。
- `Selector.show_selector()` 设置虚拟桌面几何并调用 `showFullScreen()`，保证选择层覆盖 KDE 面板和任务栏。
- `Selector.mouseReleaseEvent()` 将窗口局部矩形转换成全局矩形，再从同一张桌面图像裁剪，发出全局 `QRect` 和 `QImage`。
- `Controller.selection_done()` 显示 `LoadingWindow`，编码 PNG，并启动 `PipelineWorker`。
- `PipelineWorker` 通过 `http://127.0.0.1:1224/api/ocr` 发送 Base64 PNG，请求 `data.format=dict`，再调用配置的翻译后端。
- `Controller.pipeline_done()` 调用 `render_translation()`，创建 `OverlayWindow`，在选区位置显示原图和译图。

## 8. Verified Facts

- [VERIFIED][CODE] 当前默认快捷键是 `ctrl+alt+d`，由 `InputService` 使用 pynput 监听。
- [VERIFIED][CODE] 当前截图后端默认值和唯一接受值是 `qt_x11`；`Selector` 对其他后端抛出暂不支持错误。
- [VERIFIED][CODE] `capture_virtual_desktop()` 的实现使用 `QScreen.grabWindow(0)`，函数文档明确写明 X11-backed。
- [VERIFIED][CODE] `main()` 在 `XDG_SESSION_TYPE=wayland` 时返回错误并打印“目前只支持 X11”；没有 `DISPLAY` 时也拒绝启动。
- [VERIFIED][CODE] 当前源码中没有 `spectacle` 调用。
- [VERIFIED][CODE] `config.example.toml` 的 `[capture]` 配置为 `backend = "qt_x11"`，并注明后续可插拔截图后端。
- [VERIFIED][CODE] Umi-OCR 是本地 HTTP 服务；OCR、翻译和贴图流水线不依赖 X11 截图实现的具体代码。
- [VERIFIED][CODE] 日志只记录运行元数据和错误，不应记录截图像素、OCR 正文或翻译正文。
- [VERIFIED][GIT] 当前 `master` 和 `origin/master` 在 `861e67a`。
- [VERIFIED][GIT] `v0.1.0` 是 annotated tag，其解引用提交为 `861e67a`。
- [VERIFIED][LOG] 在真实权限和桌面状态目录下执行 `./run.sh --check`，输出 `X11: OK`、`全局输入监听(pynput): OK`、`Qt 屏幕: OK (HDMI-0=2560x1440@1x)`、`Umi-OCR HTTP: OK`、`检查结果: PASS`。
- [VERIFIED][LOG] 当前检查报告翻译配置为 `backend=google_cloud source=auto target=zh-CN`；检查本身不调用外部翻译服务。
- [VERIFIED][LOG] PySide6 的 Qt 平台插件中存在 Wayland 和 XCB 插件，但插件存在不代表应用已经 Wayland 兼容。
- [VERIFIED][LOG] 当前主机有 `/usr/bin/spectacle` 和 KDE xdg-desktop-portal 后端。

## 9. Assumptions / Unverified

### [UNVERIFIED][RUNTIME] Arch + KDE Plasma Wayland 的实际行为

- 尚未在目标 Arch 机器运行项目。
- 尚未验证 Spectacle 的具体版本、参数、输出文件时序、全屏截图是否包含所有输出及其缩放行为。
- 尚未验证 Qt Wayland 全屏选择层是否能覆盖 KDE 面板并稳定接收拖选输入。
- 尚未验证多屏排列、负坐标、混合 DPI 和 Wayland compositor 坐标与像素坐标之间的换算。

### [ASSUMPTION] 首版 Spectacle 工作方式

工作假设是：先让 Spectacle 在选区层显示前抓取整屏到临时 PNG，再由本程序显示这张静态图并继续自有框选。这样可以保留现有 OCR 输入和选区裁剪流程，避免直接依赖 Spectacle 的区域坐标返回。必须先在目标机验证 Spectacle CLI 的可用参数和截图时序。

### [UNVERIFIED] Wayland 贴图定位

Qt 文档指出典型 Wayland XDG Shell 不支持客户端任意设置顶层窗口位置；当前 `OverlayWindow` 依赖全局 `setGeometry()`。需要在 KDE Plasma Wayland 实测后决定使用 layer-shell/KWin 专用能力、按输出窗口显示，或首版接受贴图定位/点击外部关闭的差异。

### [UNVERIFIED] Wayland 全局快捷键

当前 `pynput` 不能作为通用 Wayland 全局快捷键方案。候选方案是 XDG Global Shortcuts Portal 或 KDE 全局快捷键接口；具体接口可用性、用户授权 UI 和 Python D-Bus 依赖需在目标机确认。

## 10. Failed Attempts

### F-001：在受限沙箱中直接运行 `./run.sh --check`

- Why：确认当前运行状态。
- Action：在默认沙箱权限下执行 `./run.sh --check`。
- Result：程序初始化日志时无法创建 `/home/hao123/.local/state/screenshot-translator/app.log`，报 `OSError: [Errno 30] Read-only file system`。
- Conclusion：该失败证明的是沙箱无法写用户状态目录，不是项目 X11 检查失败。
- Retry：在真实用户桌面权限下重试。
- Retry result：[VERIFIED][RUNTIME] 重试通过，完整检查结果为 `PASS`。

### F-002：默认 SSH 配置读取远端标签

- Why：确认远端旧标签是否存在。
- Action：执行 `git ls-remote --tags origin`。
- Result：系统 SSH 配置文件权限问题导致连接失败。
- Retry：使用项目用户的 `~/.ssh/config`，通过 `git -c core.sshCommand='ssh -F /home/hao123/.ssh/config'` 重试。
- Conclusion：[VERIFIED][GIT] 重试成功并确认远端原本没有 tag。

### F-003：在默认沙箱中删除本地 tag

- Why：按用户授权清理旧 `v0.1.2`、`v0.1.3`。
- Action：执行本地 tag 删除和新 tag 创建。
- Result：`.git/refs` 锁文件无法创建，报只读文件系统。
- Retry：使用提升权限执行同一逻辑。
- Conclusion：[VERIFIED][GIT] 本地旧 tag 删除、新 `v0.1.0` 创建成功；该操作未修改项目文件。

### F-004：使用 `ssh -F /dev/null` 访问 GitHub

- Why：绕过系统 SSH 配置权限问题。
- Action：不加载项目 SSH 配置直接执行 `git ls-remote`。
- Result：因为没有加载项目中指定的 IdentityFile，返回 `Permission denied (publickey)`。
- Conclusion：`/dev/null` 配置不是有效的项目远端访问方案；后续应使用项目用户 SSH 配置，禁止将密钥内容写入文档。

## 11. Decisions

### D-001：保持独立程序，Umi-OCR 作为外部 OCR 引擎

- Decision：[USER] Screenshot Translator 继续作为主程序，负责快捷键、截图、框选、翻译和贴图；Umi-OCR 通过本地 HTTP 提供 OCR。
- Reason：当前链路已经按此边界工作，Umi-OCR 插件机制主要面向 OCR 引擎，不直接提供本程序所需的翻译和原位贴图生命周期。
- Alternatives considered：改造成 Umi-OCR 插件；暂不采用。
- Trade-off：需要自行处理 Wayland 截图和窗口交互，但能保留现有产品行为和可插拔翻译后端。
- Revisit when：用户明确要求插件分发或 Umi-OCR 成为主界面。

### D-002：保留 `qt_x11`，新增独立 Wayland 后端

- Decision：[USER/ASSUMPTION] X11 现有路径保持可用，Wayland 不通过删除检查或伪装成 X11 来实现。
- Reason：X11 和 Wayland 对抓屏、全局输入、顶层窗口定位的权限模型不同。
- Alternatives considered：把 `QScreen.grabWindow(0)` 直接扩展到 Wayland；已排除为不可靠路径。
- Trade-off：需要维护两套后端和运行时选择逻辑。
- Revisit when：Wayland 路径稳定并且确认是否需要统一抽象。

### D-003：首个 Wayland 目标是 KDE Plasma

- Decision：[USER] 优先支持 Arch Linux + KDE Plasma Wayland。
- Reason：用户的目标机器和当前 KDE 生态明确，KDE 可提供 Spectacle、KWin 和 KDE portal 集成。
- Alternatives considered：首版同时覆盖 GNOME、wlroots 等所有 Wayland compositor；暂不采用。
- Trade-off：首版范围较小，但可能需要后续抽象为更通用的 portal/layer-shell 方案。
- Revisit when：KDE 首版核心流程通过真实验收后。

### D-004：首版优先核心流程，不立即承诺完全 X11 交互对齐

- Decision：[USER] 先保证截图→框选→OCR→翻译→贴图核心流程；多屏、点击外部关闭和所有精确定位行为分阶段处理。
- Reason：Wayland 对全局位置和全局输入有结构性限制，先验证最小可用链路能降低调试范围。
- Trade-off：Wayland 首版可能暂时不具备 X11 的全部关闭和多屏行为。
- Revisit when：单屏核心流程稳定后。

### D-005：首版截图工作方向为 Spectacle 全屏抓取 + 自有框选

- Decision：[USER] 优先采用 Spectacle 在选区层前抓取整屏，再使用本程序自有选择层。
- Reason：当前程序需要保留 OCR 输入图像、选区裁剪和后续贴图数据；Spectacle 的区域截图结果不天然提供本程序需要的全局矩形。
- Alternatives considered：直接使用 Screenshot Portal 区域选择；ScreenCast + PipeWire；均暂不作为首版路线。
- Trade-off：引入临时文件和 Spectacle 版本差异，需要验证截图时序；换取较小的第一步改动和可复用的自有选择逻辑。
- Revisit when：Spectacle CLI 无法在目标 KDE/Wayland 稳定提供整屏图，或需要更可靠的输出元数据时。

### D-006：创建独立交接文件

- Decision：[USER] 使用用户提供的 Handoff Engineer 提示词生成 `AGENT_HANDOFF.md`，供下一 Agent 接续 Wayland 开发。
- Reason：需要把当前现场、证据状态、失败路径、决策和下一步从聊天中迁移到仓库。
- Trade-off：交接文件必须随项目维护，且不能替代当前实际文件、Git 状态和运行验证。

## 12. Guardrails / Do Not Do

- 不把 `AGENTS.md`、`AGENT_HANDOFF.md` 中的工作规则误当成用户本次新增功能请求；本次用户请求是整理工作区、创建交接文档并提交。
- 不将真实 API Key、`keys.toml`、私钥、Cookie、Token、个人配置、截图像素、OCR 正文或翻译正文写入 Git 或交接文档。
- 不读取真实 `keys.toml` 内容；只记录其存在、用途和路径。
- 不删除 `~/tools/Umi-OCR_Linux_Paddle_2.1.5`。
- 不污染系统 Python、系统 Qt 路径或 `/usr/bin/qt.conf`；依赖安装到项目 `.venv`。
- 不假设系统安装了 Tesseract；它不是当前项目依赖。
- 不使用 `git reset --hard`、`git clean -fd` 或其他覆盖未知工作区修改的命令。
- Git 提交按 `AGENTS.md` 的消息格式执行，禁止 `add`、`update`、`modify`、`big` 作为 type。
- 每次提交前必须检查工作树、暂存区和 diff，并向用户展示拟提交文件、关键 diff 和完整消息取得确认。
- 推送远端前必须再次取得用户明确确认；本次已授权的 tag 整理/推送权限不自动延伸到后续任务。
- 在 Arch + KDE Plasma Wayland 的实际验证完成前，不更新文档为“Wayland 已支持”，也不删除 X11 后端。
- 不把 Wayland 的失败简单归因于 OCR、翻译或 Google API；先区分截图、输入、窗口定位和网络链路。

## 13. User Requirements & Acceptance Criteria

### 用户要求

- [USER] 新 Agent 不应依赖旧聊天历史，必须通过 `AGENT_HANDOFF.md` 和项目现场恢复工作。
- [USER] 目标环境是 Arch Linux + KDE Plasma Wayland。
- [USER] 保留当前独立程序的产品方向和核心体验。
- [USER] 截图路线首选 Spectacle 与本程序自有框选层组合。
- [USER] 不涉及隐私，不提交真实凭据；项目历史和工作区不得泄露密钥。
- [USER] 提交和推送遵守既有 Git 规则；本次 tag 清理和推送已完成，后续新提交仍需按规则确认。

### Wayland 首版验收标准

在目标 Arch + KDE Plasma Wayland 上，至少需要逐项验证并记录证据：

1. 程序可以在 Wayland 会话启动，不再错误地走 `qt_x11`。
2. 配置可明确选择 Wayland 后端；X11 配置和路径继续可用。
3. 快捷键可以在其他窗口获得焦点时触发，且不会依赖 X11 `pynput` 全局监听。
4. 单显示器上可以获取当前桌面图像，框选层显示的像素与 OCR 输入一致。
5. 拖选、取消、最小尺寸校验和转圈提示正常。
6. Umi-OCR 收到截图并返回结构化文字，`identity` 后端可以先完成本地链路验证。
7. 真实翻译后，译图能够显示且原图/译图、复制和关闭控件可用。
8. 失败只产生通知和日志，不弹模态错误对话框。
9. 文档中的 Wayland 支持范围、依赖和限制与实际测试一致。
10. 多屏、混合 DPI、精确原位贴图和点击外部关闭若未完成，必须明确标记为未验证或后续范围。

## 14. Current Runtime / Problem Scene

### 当前运行现场

- 当前主机仍是 KDE Plasma + X11，`DISPLAY=:0`。
- 当前配置的翻译 backend 是 `google_cloud`，源语言 `auto`，目标语言 `zh-CN`。
- `./run.sh --check` 在真实权限下通过；Umi-OCR HTTP 当前可用。
- 本次没有启动前台主程序进行新的截图交互，未产生新的运行截图或 OCR 正文。
- 当前项目没有运行中的 Wayland 实例可供验证。

### 当前代码行为

- `main()` 遇到 `XDG_SESSION_TYPE=wayland` 直接返回 2。
- `Selector` 只接受 `qt_x11`，并在初始化时抓取所有 Qt 屏幕。
- `OverlayWindow` 通过全局矩形定位贴图；`Controller.global_mouse_press()` 依赖全局鼠标坐标判断贴图外点击。
- `InputService` 同时监听全局键盘和鼠标；这在 X11 检查中通过，在 Wayland 未验证。

### 当前阻塞的工程问题

1. 抓屏：Wayland 没有可直接读取整个桌面的 X11 根窗口语义；需要 Spectacle、Screenshot Portal 或 ScreenCast/PipeWire。
2. 坐标：当前合成虚拟桌面和全局 `QRect` 依赖 X11/Qt 几何行为；Wayland 输出坐标、逻辑尺寸和像素尺寸需要重新建模。
3. 输入：全局快捷键和全局鼠标监听需要 Wayland 允许的接口。
4. 贴图：典型 Wayland 顶层窗口由 compositor 控制位置，当前 `setGeometry(global QRect)` 不能直接视为可靠。

## 15. Next Steps

### P0 — 目标机基线与接口设计

#### P0-1：采集 Arch + KDE Plasma Wayland 现场

- Action：在目标机项目目录执行：

  ```bash
  cat /etc/os-release
  uname -a
  echo "$XDG_SESSION_TYPE"
  echo "$XDG_CURRENT_DESKTOP"
  echo "$WAYLAND_DISPLAY"
  echo "$DISPLAY"
  command -v spectacle
  spectacle --version
  command -v xdg-desktop-portal
  command -v pw-cli
  ./run.sh --check
  ```

- Expected：明确 Arch、Plasma、Wayland、Spectacle、portal、PipeWire 和当前程序基线状态；当前版本预期会报告 Wayland 不支持。
- If successful：记录版本和屏幕/缩放信息，进入 P0-2。
- If failed：先区分缺少命令、会话变量错误、Umi-OCR 路径错误和程序本身的 X11 拒绝，不修改无关配置。

#### P0-2：建立截图后端接口

- Action：在 `app.py` 中将当前 `capture_virtual_desktop()` 的结果抽象为包含图像、输出/虚拟几何、逻辑尺寸和缩放元数据的 capture result；保留现有 `qt_x11` 实现。
- Expected：X11 行为不变，后端选择不再由 `Selector` 内部硬编码拒绝所有非 `qt_x11`。
- If successful：静态检查并在当前 X11 上运行 `./run.sh --check`，确认没有回归。
- If failed：恢复到后端接口之前的可运行状态，检查坐标和 QImage 生命周期，不修改 OCR/翻译代码。

#### P0-3：验证 Spectacle 全屏抓取

- Action：根据目标机 `spectacle --help` 确认全屏、后台、输出文件参数；在显示选择层前调用 Spectacle 写入临时 PNG，读取为 `QImage`，再显示现有选择层。
- Expected：Spectacle 在 Wayland 下能在无额外区域选择 UI 的情况下产生整屏 PNG；程序能够确认文件存在、尺寸、格式和完成时机。
- If successful：先用单显示器和 `identity` backend 验证截图→OCR→贴图。
- If failed：记录 Spectacle 版本和 stderr，评估 KDE Screenshot Portal；不要直接把失败归因于 Qt 或 Umi-OCR。

#### P0-4：替换 Wayland 全局快捷键

- Action：确认 KDE Plasma Wayland 是否提供 Global Shortcuts Portal 或 KDE KGlobalAccel 可用接口；将 `InputService` 拆成 X11 和 Wayland 实现。
- Expected：快捷键在应用未获得焦点时可触发；X11 仍使用现有配置。
- If failed：记录 portal 缺少、权限请求或 D-Bus 依赖问题，暂时允许以前台按钮/测试命令触发核心截图链路，不伪造全局快捷键已可用。

#### P0-5：先完成单屏选择层与贴图实验

- Action：在单显示器 Wayland 上验证 Qt `showFullScreen()`、鼠标局部坐标、选区裁剪和贴图窗口的实际定位。
- Expected：至少可选择区域、得到一致图像并显示译图；记录任务栏覆盖、窗口层级和贴图位置结果。
- If failed：评估按输出创建窗口、KDE/layer-shell 能力或阶段性降低外部点击关闭要求；不得用 X11 全局坐标假设掩盖失败。

### P1 — 核心流程稳定后

- 支持多显示器、输出坐标、负坐标和混合 DPI。
- 完善原位贴图定位、拖动和点击贴图外关闭。
- 增加 Wayland 配置说明、系统依赖和故障排查。
- 重新运行 `identity`、真实 Google Cloud 和 LibreTranslate 链路。

### P2 — 后续扩展

- 评估 Screenshot Portal 或 ScreenCast/PipeWire 作为更通用的后端。
- 评估 GNOME/wlroots 等其他 Wayland compositor。
- 评估是否需要 Umi-OCR 插件分发；当前不作为 Wayland 首版阻塞项。

### Completion Criteria

只有满足以下条件，才能把 Wayland 版本标记为完成：

- 目标 Arch + KDE Plasma Wayland 有实际运行记录，而不是仅有静态检查。
- 截图、框选、OCR、翻译、贴图和错误通知核心链路全部有可重复验证结果。
- X11 现有路径仍通过检查和至少一次交互回归。
- Wayland 的快捷键、窗口层级、坐标、缩放和限制在文档中如实说明。
- 未完成的多屏、混合 DPI 或关闭行为明确列为未验证，不得使用模糊的“基本完成”。
- Git 工作区、提交和标签状态经过实际命令复核，且没有秘密或运行缓存进入历史。

## 16. Reusable Commands

以下命令已在当前项目或当前主机确认用途；目标 Arch 机器上的输出需要重新记录。

```bash
# 查看当前 Git 状态和历史
git status --short --branch
git log --oneline --decorate -10

# 静态检查
python -m py_compile app.py
bash -n install.sh run.sh
git diff --check

# 本地环境检查（需真实用户状态目录可写）
./run.sh --check

# 启动程序
./run.sh

# 查看配置、密钥和日志路径；不会打印密钥内容
./run.sh --config-path
./run.sh --keys-path
./run.sh --log-path

# 检查 Spectacle CLI 参数；目标机需在图形会话中重跑
spectacle --help
spectacle --version
```

### Git 提交前命令

```bash
git status --short --branch
git diff -- AGENT_HANDOFF.md
git diff --check
```

提交消息候选：

```text
docs(handoff): 创建 Wayland 开发交接快照
```

该消息遵守 `AGENTS.md` 的 `<type>(<scope>): <简短说明>` 格式。提交前必须把拟提交文件、关键 diff 和完整消息展示给用户并取得确认。

## 17. Additional Context

- 当前仓库的 `README.md` 标题仍为 `Screenshot Translator v0.1.2`，`app.py` 的 `VERSION` 也为 `0.1.2`；这与用户要求创建的 Git tag `v0.1.0` 是命名层面的不一致，后续发布时需要明确处理。
- `使用说明.md` 当前明确要求 KDE Plasma + X11，并说明项目不需要 Spectacle；这是当前版本事实，不应在 Wayland 实现未验证前直接改写成跨平台说明。
- 用户此前遇到的截图任务栏/错位问题，当前代码通过 `showFullScreen()`、虚拟桌面几何和全局坐标裁剪处理；这些修复应在 X11 路径中保留，Wayland 不应直接复制其坐标假设。
- 用户此前要求翻译过程中显示转圈图标；`LoadingWindow` 已实现，Wayland 改动不应遮挡或改变该交互。
- 用户此前要求密钥单独配置且不进 Git；`keys.example.toml` 只有空占位符，`.gitignore` 忽略 `keys.toml`，该边界必须继续保持。
- 当前默认配置的 `translation.backend` 在模板中是 `google`，实际用户配置检查结果是 `google_cloud`；不要读取真实配置中的 Key 来解释这个差异。

## 18. Conversation / Evidence Index

### 本次直接证据

- `AGENTS.md`：项目协作规则、当前 X11 限制、架构、验证顺序、保护边界和 Git 规则。
- `app.py`：截图、选区、OCR、翻译、贴图、输入监听和 Wayland 拒绝逻辑。
- `config.example.toml`：当前 `qt_x11` 截图后端、Umi-OCR 和翻译配置模板。
- `README.md`：快速使用、X11 限制和版本交互说明。
- `使用说明.md`：新机器安装、Google API、配额和隐私/Git 边界。
- `requirements.txt`、`install.sh`、`run.sh`：依赖、安装和启动入口。
- `git status`、`git log`、`git show-ref`：当前分支、提交、标签和工作区证据。
- `./run.sh --check`：真实 X11 桌面、屏幕、pynput、Umi-OCR HTTP 和通知能力的最新检查证据。

### Wayland 设计参考

- Wayland 协议模型：客户端不能直接读取其他客户端 surface，也不能假设 X11 根窗口语义。
- XDG Desktop Portal Screenshot：支持屏幕、窗口和区域目标，但应用需要处理异步请求和返回 URI。
- XDG Desktop Portal Global Shortcuts：提供不依赖当前焦点的全局快捷键会话，但具体 backend 和用户授权需目标机验证。
- KDE Spectacle：支持整屏和矩形区域截图；CLI 参数、文件输出和 D-Bus 行为必须以目标机安装版本为准。

这些参考用于说明设计约束，不替代目标 Arch + KDE Plasma Wayland 的实际运行证据。
