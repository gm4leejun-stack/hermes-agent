#!/bin/bash
# 将 my-skills 软链接到 ~/.hermes/skills/
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.hermes/skills"

install_skill() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "$dst")"
  if [ -L "$dst" ]; then
    echo "  已存在软链接，跳过: $dst"
  elif [ -d "$dst" ]; then
    echo "  已存在目录，备份为 ${dst}.bak: $dst"
    mv "$dst" "${dst}.bak"
    ln -s "$src" "$dst"
  else
    ln -s "$src" "$dst"
    echo "  已链接: $dst -> $src"
  fi
}

echo "安装 my-skills 到 $SKILLS_DIR ..."

install_skill "$SCRIPT_DIR/productivity/smart-reminder"   "$SKILLS_DIR/productivity/smart-reminder"
install_skill "$SCRIPT_DIR/productivity/cronjob-reminder" "$SKILLS_DIR/productivity/cronjob-reminder"
install_skill "$SCRIPT_DIR/apple/apple-reminders"         "$SKILLS_DIR/apple/apple-reminders"

echo "完成。"
