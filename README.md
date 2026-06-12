# 🛠️ AI 创意工具箱

AI 驱动的综艺策划辅助工具集。输入想法，输出结构化方案。

## 工具

| 工具 | 说明 |
|------|------|
| **[方案骨架生成器](方案骨架生成器.html)** | 快速搭建方案结构框架，含矛盾诊断引擎与因果推导链 |
| **[创意方案生成器](创意方案生成器.html)** | 输入创意想法，一键生成完整方案（含观众旅程、元素拆解、市场适配） |

## 🖥️ 环境

| 环境 | 地址 | 分支 | 说明 |
|------|------|------|------|
| **稳定版** | `https://xxx.trycloudflare.com` | `main` | NAS Docker 部署，Key 服务器注入，无需手动填写 |
| **测试版** | 双击 HTML 文件打开 | `dev` | 本地开发，需手动填 Key（localStorage 记住） |

## 🔄 开发工作流

```
dev 分支（随便改）
    │  本地双击 HTML → file:// 协议 → 填自己的 Key → 测试
    │
    ▼ 确认稳定
main 分支（稳定版）
    │  ./deploy.sh → 推送到 NAS
    │
    ▼
NAS → Cloudflare Tunnel → 公网访问
```

### 日常开发

```bash
# 1. 确保在 dev 分支
git checkout dev

# 2. 改代码，本地双击 HTML 测试
# 打开浏览器 → 填 API Key → 测试功能

# 3. 满意后提交
git add 方案骨架生成器.html
git commit -m "feat: xxx"
```

### 发布到稳定版

```bash
# 1. 合并到 main
git checkout main
git merge dev --no-edit

# 2. 推送到 GitHub
./push.sh

# 3. 部署到 NAS
# 先 Finder → 连接服务器 → smb://NAS-IP → 挂载 ai-tools-html
./deploy.sh "/Volumes/ai-tools-html"

# 4. 浏览器打开 tunnel 地址 → 刷新验证
```

### 版本号规范

改完确认稳定后更新版本号：

| 文件 | 位置 |
|------|------|
| HTML 顶部注释 | `vx.x → vx.x+1` + 日期 + 变更说明 |
| 页面 badge | `<span>vx.x</span>` 或 `class="badge"` |
| `变更记录/` | 追加 `YYYY-MM-DD-vx.x.md` |

## 🐳 NAS 部署

详见 `deploy/` 目录，包含 Dockerfile、docker-compose.yml、nginx 反代配置。

## 历史版本

早期版本归档在 [`v1/`](v1/) 目录。
