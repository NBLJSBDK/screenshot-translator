# Screenshot Translator 项目协作说明

本文件是项目唯一的 Agent 工作说明。开始开发、排查或测试前先阅读本文件，再检查实际文件、运行环境和 Git 状态。不要依赖已经删除的交接文件，也不要根据旧聊天记录臆测现场。

## 项目目标

Screenshot Translator 是面向 Linux + KDE Plasma + X11 的无主窗口截图翻译贴片工具。它不提供普通主窗口、托盘设置界面或完整截图管理器。

默认流程：

```text
Ctrl+Alt+D → 全屏选择层拖选 → Umi-OCR → 翻译 → 在原屏幕位置显示贴片
```

当前 v0.1.x 只支持 X11，程序明确拒绝 Wayland。不要宣称 Wayland 支持。

## 已验证环境

```text
主机：Linux desktop (example environment)
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

项目依赖必须在项目 `.venv` 中安装。已验证 PySide6 6.11.2、pynput 1.8.2、evdev 2.0.0、python-xlib 0.33 和 six 可用；Debian 的 `python3.13-dev` 提供 evdev 编译所需的 `Python.h`。不要把这些依赖装进系统 Python。

## 文件与路径

```text
app.py                 主程序：选择器、OCR/翻译、贴图、输入监听
config.example.toml    默认配置模板
requirements.txt       Python 依赖
install.sh             创建 .venv 并安装依赖
run.sh                 使用 .venv 启动 app.py
README.md              用户说明
AGENTS.md              本文件，唯一的 Agent 说明
```

用户配置、状态和日志位于仓库外：

```text
配置：~/.config/screenshot-translator/config.toml
日志：~/.local/state/screenshot-translator/app.log
缓存：~/.cache/screenshot-translator/
```

日志默认只写运行元数据和错误，不写截图像素、OCR 正文或翻译正文。

## 程序架构

### 配置和日志

`deep_merge()`、`ensure_runtime_dirs()`、`ensure_config()`、`load_config()`、`configure_logging()`、`reload_log_level()` 和 `notify()` 负责配置合并、XDG 目录、日志级别热加载和通知。

失败必须使用桌面通知加日志，不得弹模态错误对话框。通知优先使用 `notify-send`，否则使用 `kdialog --passivepopup`。

### 截图和全屏选择层

`capture_virtual_desktop()` 使用 Qt/X11 的 `QScreen.grabWindow(0)` 抓取各屏幕并合成虚拟桌面，返回全局虚拟桌面矩形和 `QImage`。

`Selector` 是无边框全屏选择层：

- 必须覆盖整个屏幕，包括 KDE 面板和任务栏；选择时任务栏不应重复出现。
- 当前实现使用 `WindowFullScreen`，不要退回只覆盖 available geometry 的普通窗口。
- 背景绘制、选区预览和裁剪都要通过窗口全局原点映射到虚拟桌面坐标。
- 左键拖动选择；`Esc` 或右键取消；小于最小尺寸的区域无效。
- `selected` 同时返回全局 `QRect` 和裁剪后的 `QImage`。

不要把窗口局部坐标直接当作虚拟桌面坐标，也不要用拉伸整张图掩盖几何偏移。显示的像素必须和送给 OCR 的截图一致。

### OCR 和翻译

`PipelineWorker` 在后台线程中：

1. 探测 Umi-OCR HTTP 服务。
2. 服务不可用且 `ocr.auto_start=true` 时运行 `umi-ocr.sh --hide` 并等待就绪。
3. 以 base64 PNG 调用 `/api/ocr`，请求 `data.format = dict`。
4. 使用返回项的 `text`、`box`、`end` 组织源文本和段落。
5. 按段落调用可插拔翻译后端。
6. 发出源文、译文、段落边界框和耗时。

支持的 backend：

```text
google（免 Key 非官方接口，可能 HTTP 429）
libre / libretranslate
identity（原样返回 OCR 文本，仅用于本地链路测试）
```

Google 曾出现 HTTP 429。不要让网络翻译成功与否掩盖截图、OCR 或 UI 问题。

### 渲染和贴图

`render_translation()` 复制原图，在 OCR 段落边界框上绘制深色半透明圆角遮罩，再绘制译文。当前版本不做 AI 背景修复或 inpainting，图片和非文字区域保留原图。

`OverlayWindow` / `DraggableImage` 显示原位贴图和紧凑控件：

```text
[原/译] [原] [译] [×]
```

- `原/译`：切换原图和译图。
- `原`：复制完整 OCR 原文。
- `译`：复制完整译文。
- `×`：关闭贴图。
- 控件优先放截图下方，空间不足时放上方，再不行放右下角内部。
- 左键长按默认约 350ms 后可以拖动整个贴图和控件组。
- 使用无边框、置顶和 `Tool` 窗口标志；不要使用 `Qt.Popup`。

贴图只允许通过 `Esc`、点击贴图和控件组外部、点击 `×` 关闭。单纯失去焦点或 Alt+Tab 不得关闭。再次截图时先关闭旧贴图，一次只保留一个。

### 全局输入和控制器

`InputService` 使用 `pynput` 监听全局快捷键和鼠标按下事件。默认快捷键 `ctrl+alt+d` 必须可配置。

`Controller` 负责配置热加载、快捷键重注册、选择层、后台流水线、贴图生命周期和点击外部关闭逻辑。

## 安装、检查和运行

```bash
cd ~/tools/screenshot-translator
./install.sh
./run.sh --check
./run.sh
```

`install.sh` 只在项目中创建 `.venv` 并安装 `requirements.txt`，不应使用 `sudo`，不应污染系统 Qt 路径。`--check` 不访问外部翻译服务；Umi-OCR 未运行但脚本存在时可以报告运行时自动启动警告。

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
3. 前台程序启动无异常。
4. `Ctrl+Alt+D` 显示覆盖整个屏幕的选择层，任务栏只出现一次。
5. 拖选区域的显示像素、全局边界和 OCR 输入一致。
6. 使用 `identity` 验证原位贴图。
7. 验证原/译切换、复制原文、复制译文、`×`、`Esc`、点击外部、Alt+Tab、长按拖动和再次截图替换。
8. 验证 OCR/翻译失败只通知和写日志。
9. 最后单独测试 Google 或 LibreTranslate。

在完整实测前不要声称全部功能可用。混合 DPI、多屏和 Wayland 仍未完成专门验证。

## 保护边界

- 不删除 `~/tools/Umi-OCR_Linux_Paddle_2.1.5`。
- 不重新安装 Manggo 或覆盖 `/usr/bin/qt.conf`、`/usr/plugins` 等系统 Qt 路径。
- 不假设系统有 Tesseract；它不是项目依赖。
- 不增加主窗口、托盘图标、设置 GUI 或模态错误窗口，除非用户明确改变需求。
- 不把 `.venv`、缓存、日志或个人配置提交到仓库。
- 不使用 `git reset --hard`、`git clean -fd` 等会销毁未知修改的命令。

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

环境安装和本地诊断已经完成。当前历史中已有：

```text
7b72614 chore: 初始化截图翻译工具项目
5fd821d fix(capture): 修复全屏选区与坐标偏移
```

选择层全屏和坐标修复已经通过静态检查、Qt 几何测试、运行日志和 `./run.sh --check` 验证。配置暂时使用 `identity` backend，Umi-OCR 可自动启动。接下来优先完成真实桌面交互验收，再单独验证真实翻译后端。
