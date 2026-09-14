# Screenshot Translator v0.3.2

面向 **KDE Plasma + Linux** 的无主窗口截图翻译贴片器，支持 X11 与 KDE Plasma Wayland 会话。

新机器从克隆到第一次运行的完整流程见：[使用说明.md](使用说明.md)。

默认体验：

`F14` → 框选区域 → Umi-OCR → 自动识别源语言 → 翻译为 `zh-CN` → 在原截图位置显示翻译贴图。

## 交互

- 默认快捷键：`F14`（截图翻译）；`F15`（`app.copy_hotkey`，可改可留空禁用）——只调用 Umi-OCR 识别，不翻译，识别出的原文自动复制到剪贴板并弹通知。
- 快捷键支持组合键和无修饰键的 `F13`–`F24`；KDE Wayland 下以配置文件为准（启动/改配置时写入 KGlobalAccel）。使用 F13–F24 前需要先启用系统键位选项，见下文“使用 F13–F24 作为快捷键”。
- 框选完成后，选区中心显示转圈指示，OCR/翻译完成或失败后自动消失。
- 贴图默认显示译图，原截图中的非文字区域保留。
- OCR 文字区域使用半透明遮罩并绘制译文。
- 右下角控制组尽量放在截图框外：`[原/译] [原] [译] [×]`。
  - `原/译`：切换原图 / 译图。
  - `原`：复制完整 OCR 原文。
  - `译`：复制完整译文。
  - `×`：关闭。
- `Esc`：关闭贴图（贴图拥有键盘焦点时）。
- 点击贴图和控制组以外的位置：关闭（仅 X11）。
- `Alt+Tab` / 单纯失去焦点：不会主动关闭。
- 在贴图图像区域按住左键即可拖动整个贴图和控制组（`drag_hold_ms = 0` 为立即拖动）。
- 在贴图上滚动滚轮：以鼠标位置为中心缩放贴图（25%~400%）。
- 中键点击贴图：归位，回到最初框选位置并恢复 100% 大小。
- 右键点击贴图：关闭贴图。
- 再次触发截图时会关闭旧贴图；一次只保留一个。
- OCR/翻译/贴图失败：系统通知 + 日志，不弹错误对话框。

### KDE Wayland 会话的差异

Wayland 不允许应用读取其他窗口内容或进行全局输入监听，因此使用以下替换方案：

- 截图：先调用 Spectacle 全屏抓取，再显示本程序的全屏选择层；选择层中的像素与 OCR 输入一致。
- 全局快捷键：注册到 KDE KGlobalAccel（可在“系统设置 → 快捷键”中调整）。
- 贴图：使用全屏透明画布并按原位置绘制，画布只接管贴图和按钮区域，其他位置点击穿透。
- 已知限制：点击贴图外不会关闭（用 `×` 或再次触发快捷键）；全局快捷键触发时选择层不获得键盘焦点，`Esc` 可能无效，可用鼠标右键取消；多屏与混合缩放尚未验证。

## 合并内容

当前版本以第二个原型为主干，并合入：

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

密钥配置（可选）：

```text
~/.config/screenshot-translator/keys.toml
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

不会访问外部翻译服务，只检查当前会话、截图后端、全局快捷键后端、Qt 屏幕、Umi-OCR HTTP/启动脚本、系统通知等。

X11 会话的检查应显示 `会话: OK (x11 ...)`、`截图后端: OK (qt_x11)`、`全局快捷键(pynput): OK`。

KDE Wayland 会话的检查应显示 `会话: OK (wayland KDE)`、`截图后端: OK (spectacle: ...)`、`全局快捷键(KGlobalAccel): OK`；缺少 `spectacle` 或 `gdbus`/`dbus-send` 时会报告 FAIL。

## 运行

```bash
./run.sh
```

然后按 `F14`（翻译）或 `F15`（只识别复制原文）。

前台测试时用终端 `Ctrl+C` 退出常驻程序；从桌面快捷方式启动（没有终端窗口）时用下面的命令停止：

```bash
./run.sh --quit
```

程序是单实例的：已经运行时再次启动只会提示“已在运行”。

系统托盘会显示图标（`app.tray_icon = true`），菜单包含：

- `截图并翻译`：等同按快捷键。
- `打开配置文件` / `打开日志`。
- `退出`：结束常驻程序。

## 配置

程序首次运行或安装时创建：

```text
~/.config/screenshot-translator/config.toml
```

常用项：

```toml
[app]
hotkey = "f14"                      # 截图翻译
copy_hotkey = "f15"                 # 只识别并复制原文；留空禁用
input_backend = "auto"             # auto / pynput / kglobalaccel

[capture]
backend = "auto"                   # auto / qt_x11 / spectacle

[ocr]
parser = "multi_para"              # multi_para / multi_line / single_para / single_line / none
copy_parser = ""                   # 只识别模式单独指定；留空沿用 parser

[translation]
backend = "google"
source = "auto"
target = "zh-CN"
```

`auto` 会按当前会话自动选择：X11 使用 `qt_x11` + `pynput`，KDE Wayland 使用 `spectacle` + `kglobalaccel`。在 Wayland 下 `close_on_outside_click` 不生效。

### 使用 F13–F24 作为快捷键

系统默认的 xkb `inet` 映射会把 FK13–FK18 等映射成 `XF86Tools`、`XF86Launch5` 等多媒体键，KGlobalAccel/KDE 里配的 F13–F24 永远匹配不到。需要先让这些键发送真正的 F13–F24。

**KDE Plasma Wayland：**

```bash
sudo localectl set-x11-keymap us pc105 "" fkeys:basic_13-24
kwriteconfig6 --file kxkbrc --group Layout --key Options "fkeys:basic_13-24"
kwriteconfig6 --file kxkbrc --group Layout --key ResetOldOptions true
# 注销重新登录后生效（KWin 只在启动时重建键位表）
```

注意：KWin 读取 kxkbrc 的 `Options` 时要求 `ResetOldOptions=true`，否则选项会被忽略。

**KDE Plasma X11 / Debian：**

```bash
# 当前会话立即生效
setxkbmap -option fkeys:basic_13-24

# 开机默认
sudo sed -i 's/^XKBOPTIONS=.*/XKBOPTIONS="fkeys:basic_13-24"/' /etc/default/keyboard
sudo dpkg-reconfigure keyboard-configuration   # 或重启
```

KDE X11 也可以在「系统设置 → 输入设备 → 键盘 → 布局 → 高级」勾选 “Use F13-F24 as usual function keys”。

**自定义某个 FK 键的行为（用户级 xkb，不动系统包文件）：**

例如把 FK16 改成右 Ctrl、其余保持 F 键：

```bash
mkdir -p ~/.config/xkb/symbols ~/.config/xkb/rules
cat > ~/.config/xkb/symbols/screenshot <<'EOF'
partial alphanumeric_keys modifier_keys
xkb_symbols "fkeys" {
    key <FK13> { [ F13 ] };
    key <FK14> { [ F14 ] };
    key <FK15> { [ F15 ] };
    key <FK16> { [ Control_R ] };
    key <FK17> { [ F17 ] };
    key <FK18> { [ F18 ] };
    key <FK19> { [ F19 ] };
    key <FK20> { [ F20 ] };
    key <FK21> { [ F21 ] };
    key <FK22> { [ F22 ] };
    key <FK23> { [ F23 ] };
    key <FK24> { [ F24 ] };
};
EOF
cp /usr/share/X11/xkb/rules/evdev ~/.config/xkb/rules/evdev
# 在规则文件的 "! option = symbols" 段追加：
#   screenshot:fkeys = +screenshot(fkeys)
# 然后系统选项使用自定义名字：
sudo localectl set-x11-keymap us pc105 "" screenshot:fkeys
```

验证键位映射：

```bash
xkbcli compile-keymap --rules evdev --model pc105 --layout us --options screenshot:fkeys | grep "FK1[3-6]"
xev        # X11：按 F14 应显示 keysym 0xffcb (F14)
```

之后把配置写成例如 `hotkey = "f13"`、`copy_hotkey = "f14"` 即可。xkb 的 layout/options 改动在 KDE Wayland 下需要注销重登才生效。

只英译中：

```toml
source = "en"
```

如果 Google 被 429，可切换其他 backend。已预留 `libretranslate`；`identity` 不翻译，只把原文画回去，方便独立验证 UI/OCR。

### Google Cloud API Key

正式 Google Cloud Translation Basic v2 后端使用独立的密钥文件，不把 Key 写入主配置或仓库：

```bash
cp keys.example.toml ~/.config/screenshot-translator/keys.toml
chmod 600 ~/.config/screenshot-translator/keys.toml
```

编辑 `keys.toml`：

```toml
[google_cloud]
api_key = "你的 Google Cloud API Key"
```

再把主配置切换为：

```toml
[translation]
backend = "google_cloud"
```

程序每次截图时读取密钥文件；Key 缺失或配置格式错误会以通知和日志提示，不会把 Key 写入日志。

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

## 当前限制

- X11 与 KDE Plasma Wayland 核心流程已验证；GNOME、wlroots 等其他 Wayland compositor 未验证。
- Wayland 下无法实现全局鼠标监听：点击贴图外关闭不可用，用 `×` 或再次触发快捷键代替。
- Wayland 全局快捷键触发时选择层通常不获得键盘焦点，`Esc` 可能无效，可用鼠标右键取消。
- 混合 DPI / 不同分数缩放的多屏尚未专门适配；Wayland 选择层当前固定显示在 Qt 主屏幕。
- 原文字擦除仍是半透明遮罩，不做 inpainting。
- `google` backend 是免 Key 的非官方接口，仍可能出现 HTTP 429。
- `google_cloud` backend 使用官方 Basic v2 API，支持一次请求多个段落；需要用户自行配置 API Key。
