#!/bin/bash
# 部署到 NAS 稳定版
# 用法: ./deploy.sh
# 优先触发 NAS git pull，SSH 不通时回退到管道直传
set -e

NAS_HOST="${NAS_HOST:-192.168.1.76}"
NAS_USER="${NAS_USER:-hfmedia}"
NAS_PATH="${NAS_PATH:-/volume1/web/ai-tools-html}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=5"

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

# ── 先推 GitHub ──
echo "📤 git push → GitHub"
git push origin main
echo ""

# ── 方法: NAS git pull ──
deploy_via_git_pull() {
  echo "🔄 NAS git pull → ${NAS_USER}@${NAS_HOST}:${NAS_PATH}"
  ssh $SSH_OPTS "${NAS_USER}@${NAS_HOST}" "cd ${NAS_PATH} && git pull origin main" && \
    echo "✅ NAS 已同步" || echo "❌ git pull 失败"
}

# ── 方法: SSH 管道直传（回退） ──
FILES=(
  "index.html"
  "方案骨架生成器.html"
  "创意方案生成器.html"
)

deploy_via_ssh_pipe() {
  echo "🚀 SSH 管道直传 → ${NAS_USER}@${NAS_HOST}:${NAS_PATH}"
  echo ""
  for f in "${FILES[@]}"; do
    if [ -f "$f" ]; then
      cat "$f" | ssh $SSH_OPTS "${NAS_USER}@${NAS_HOST}" "cat > ${NAS_PATH}/${f}" && \
        echo "  ✅ $f" || echo "  ❌ $f 失败"
    else
      echo "  ⚠️  $f 不存在，跳过"
    fi
  done
}

# ── 执行 ──
if ssh $SSH_OPTS "${NAS_USER}@${NAS_HOST}" "echo ok" &>/dev/null; then
  deploy_via_git_pull
else
  echo "⚠️  SSH 不通，无法部署。（需要局域网 SSH 或配好端口转发/Tailscale）"
  exit 1
fi

echo ""
echo "📋 完成。"
