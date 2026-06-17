#!/bin/bash
# 部署到 NAS 稳定版
# 用法: ./deploy.sh
# 优先通过 SSH 直传，SSH 不通时回退到 SMB 挂载
set -e

NAS_HOST="${NAS_HOST:-192.168.1.76}"
NAS_USER="${NAS_USER:-hfmedia}"
NAS_PATH="${NAS_PATH:-/volume1/web/ai-tools-html}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=5"

FILES=(
  "index.html"
  "方案骨架生成器.html"
  "创意方案生成器.html"
)

# ── 分支检查 ──
BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "main" ]; then
  echo "⚠️  当前分支: $BRANCH（非 main）"
  echo ""
  read -p "是否先合并 dev 到 main？[Y/n] " yn
  if [ "$yn" != "n" ] && [ "$yn" != "N" ]; then
    git checkout main
    git merge dev --no-edit
    echo "✅ dev → main 合并完成"
  else
    echo "❌ 取消部署。请切换到 main 分支后重试。"
    exit 1
  fi
fi

# ── 方法: SSH 管道 ──
deploy_via_ssh() {
  echo "🚀 SSH 直传 → ${NAS_USER}@${NAS_HOST}:${NAS_PATH}"
  echo ""
  for f in "${FILES[@]}"; do
    if [ -f "$f" ]; then
      cat "$f" | ssh $SSH_OPTS "${NAS_USER}@${NAS_HOST}" "cat > ${NAS_PATH}/${f}" && \
        echo "  ✅ $f" || echo "  ❌ $f 失败"
    else
      echo "  ⚠️  $f 不存在，跳过"
    fi
  done
  return 0
}

# ── 方法: SMB 挂载（回退） ──
find_mount() {
  for vol in /Volumes/*; do
    [ "$vol" = "/Volumes/Macintosh HD" ] && continue
    [ "$vol" = "/Volumes/Recovery" ] && continue
    if [ -d "$vol/ai-tools-html" ]; then
      echo "$vol/ai-tools-html"
      return 0
    fi
  done
  return 1
}

deploy_via_smb() {
  local smb_path=$(find_mount)
  if [ -z "$smb_path" ]; then
    echo "🔌 NAS SMB 未挂载，正在打开 Finder 连接…"
    open "smb://hfmedia@192.168.1.76/web"
    echo "请在 Finder 中登录后重新运行 deploy.sh"
    exit 1
  fi
  echo "📁 SMB 拷贝 → $smb_path"
  echo ""
  for f in "${FILES[@]}"; do
    if [ -f "$f" ]; then
      cp "$f" "$smb_path/" && echo "  ✅ $f" || echo "  ❌ $f 失败"
    else
      echo "  ⚠️  $f 不存在，跳过"
    fi
  done
}

# ── 执行 ──
if ssh $SSH_OPTS "${NAS_USER}@${NAS_HOST}" "echo ok" &>/dev/null; then
  deploy_via_ssh
else
  echo "⚠️  SSH 不通，回退到 SMB…"
  deploy_via_smb
fi

echo ""
echo "📋 完成。"
