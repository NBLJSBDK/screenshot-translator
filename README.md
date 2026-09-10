# Screenshot Translator v0.1.2

面向 **KDE Plasma + Linux + X11** 的无主窗口截图翻译贴片器。

默认体验：

`Ctrl+Alt+D` → 框选区域 → Umi-OCR → 自动识别源语言 → 翻译为 `zh-CN` → 在原截图位置显示翻译贴图。

## V0.1.2 交互

- 默认快捷键：`Ctrl+Alt+D`。
- 框选完成后，选区中心显示转圈指示，OCR/翻译完成或失败后自动消失。
- 贴图默认显示译图，原截图中的非文字区域保留。
- OCR 文字区域使用半透明遮罩并绘制译文。
- 右下角控制组尽量放在截图框外：`[原/译] [原] [译] [×]`。
  - `原/译`：切换原图 / 译图。
  - `原`：复制完整 OCR 原文。
  - `译`：复制完整译文。
  - `×`：关闭。
- `Esc`：关闭贴图（贴图拥有键盘焦点时）。
- 点击贴图和控制组以外的位置：关闭。
- `Alt+Tab` / 单纯失去焦点：不会主动关闭。
- 在贴图图像区域按住左键约 350ms 后拖动：移动整个贴图和控制组。
- 再次触发截图时会关闭旧贴图；一次只保留一个。
- OCR/翻译/贴图失败：系统通知 + 日志，不弹错误对话框。

## 合并内容

V0.1.2 以第二个原型为主干，并合入：

- XDG 配置目录。
- `./run.sh --check` 环境检查。
- 配置热重载，快捷键修改后自动重新注册。
- Umi-OCR 未运行时尝试自动启动并隐藏。
- 全局鼠标监听实现“真正点击贴图外才关闭”，不使用 `Qt.Popup`。
- 日志级别热重载。
- 安装失败时自动清理残缺 `.venv`。
- 清理发布包中的 `__pycache__`。
- `identity` 调试翻译后端，用于只测试截图→OCR→贴图链路。

## 文件放哪里

建议程序固定：

```text
~/tools/screenshot-translator/
```

配置：

```text
~/.config/screenshot-translator/config.toml
```

日志：

```text
~/.local/state/screenshot-translator/app.log
```

缓存目录预留：

```text
~/.cache/screenshot-translator/
```

## 安装

```bash
cd ~/tools/screenshot-translator
./install.sh
```

脚本只在项目目录创建 `.venv` 并向其中安装 `PySide6`、`pynput`，不会向系统 Python 安装这些包。

若 Debian 报 `ensurepip is not available`，先安装：

```bash
sudo apt install python3-venv
```

若仍提示当前版本的 venv 包缺失，再按错误提示安装类似 `python3.13-venv`。

## 检查

```bash
./run.sh --check
```

不会访问外部翻译服务，只检查 X11、Qt 屏幕、输入监听、Umi-OCR HTTP/启动脚本、系统通知等。

## 运行

```bash
./run.sh
```

然后按 `Ctrl+Alt+D`。

前台测试时用终端 `Ctrl+C` 退出常驻程序。

## 配置

程序首次运行或安装时创建：

```text
~/.config/screenshot-translator/config.toml
```

常用项：

```toml
[app]
hotkey = "ctrl+alt+d"

[translation]
backend = "google"
source = "auto"
target = "zh-CN"
```

只英译中：

```toml
source = "en"
```

如果 Google 被 429，可切换其他 backend。V0.1.2 已预留 `libretranslate`；`identity` 不翻译，只把原文画回去，方便独立验证 UI/OCR。

## Umi-OCR

默认：

```text
http://127.0.0.1:1224/api/ocr
```

使用 `data.format = dict`，依赖 OCR 结果中的 `text`、`box`、`end` 来恢复文本与位置。

默认启动脚本：

```text
~/tools/Umi-OCR_Linux_Paddle_2.1.5/umi-ocr.sh
```

## V0.1.2 限制

- 只支持 X11；Wayland 暂不支持。
- 截图后端当前固定为 `qt_x11`；配置字段已预留给后续后端。
- 混合 DPI / 不同分数缩放的多屏尚未专门适配。
- 原文字擦除仍是半透明遮罩，不做 inpainting。
- Google backend 是免 Key 的非官方接口，仍可能出现 HTTP 429。
