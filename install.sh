#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if ! command -v python3 >/dev/null 2>&1; then
  echo '错误：找不到 python3。' >&2
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit('错误：需要 Python >= 3.11。')
print('Python:', sys.version.split()[0])
PY

PY_MM="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

# 上一次失败的 venv 不应影响重试。
rm -rf .venv

if ! python3 -m venv .venv; then
  rm -rf .venv
  echo >&2
  echo '创建 Python 虚拟环境失败。没有安装任何项目 Python 依赖。' >&2
  echo >&2
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}" in
      debian|ubuntu|linuxmint)
        echo 'Debian/Ubuntu 可先安装 venv 支持：' >&2
        echo '  sudo apt install python3-venv' >&2
        echo '若仍提示 ensurepip 不可用，可安装与当前 Python 对应的版本包，例如：' >&2
        echo "  sudo apt install python${PY_MM}-venv" >&2
        ;;
      arch|manjaro|endeavouros)
        echo 'Arch 系通常 Python 已包含 venv；若 Python 安装不完整：' >&2
        echo '  sudo pacman -S python' >&2
        ;;
    esac
  fi
  exit 2
fi

./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/screenshot-translator"
mkdir -p "$CONFIG_DIR"
if [[ ! -e "$CONFIG_DIR/config.toml" ]]; then
  cp config.example.toml "$CONFIG_DIR/config.toml"
  echo "已创建配置：$CONFIG_DIR/config.toml"
else
  echo "保留已有配置：$CONFIG_DIR/config.toml"
fi

echo
echo '安装完成。'
echo '检查：./run.sh --check'
echo '运行：./run.sh'
echo '默认快捷键：Ctrl+Alt+D'
echo "配置：$CONFIG_DIR/config.toml"
