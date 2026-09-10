#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if [[ ! -x .venv/bin/python ]]; then
  echo '尚未创建完整虚拟环境，请先运行 ./install.sh' >&2
  exit 1
fi

exec ./.venv/bin/python ./app.py "$@"
