# CLAUDE.md

AI 创意工具箱的开发规范。修改本仓库任何文件前，**必须先读此文件**。

## 仓库结构

```
!好枫/AI工作流/
├── README.md           ← 工具介绍（面向 GitHub 访问者）
├── CLAUDE.md           ← 本文件（开发规范）
├── 方案骨架生成器.html   ← 主工具
├── 创意方案生成器.html   ← 辅助工具
├── index.html           ← 工具索引/分流页
├── deploy.sh            ← NAS 部署脚本
├── deploy/              ← Docker + nginx 配置
├── 版本归档/            ← 历史版本（本地+NAS，不纳入 git）
├── 变更记录/            ← 功能变更笔记
└── v1/                  ← ⚠️ 已废弃，被 gitignore 排除，勿用
```

## 🔄 Git 工作流

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
git checkout dev
# 改代码 → 本地双击 HTML 测试 → 满意后：
git add 方案骨架生成器.html
git commit -m "feat: xxx"
```

### 发布到稳定版

```bash
git checkout main
git merge dev --no-edit
./push.sh              # 推送到 GitHub
./deploy.sh            # 部署到 NAS
# 浏览器打开 tunnel 地址验证
```

> `push.sh` 绕过 ghproxy 直推 GitHub；`deploy.sh` 自动检测 SMB 挂载并拷贝 HTML。

## 📦 版本归档

### 铁律

> 每个大版本独立文件夹，小版本归入大版本文件夹。所有版本永久保留，归档后禁止修改。

### 目录结构

```
版本归档/
├── 方案骨架生成器/
│   └── v1/
│       ├── v1.0/
│       ├── v1.3/
│       └── v1.4/
└── 创意方案生成器/
    ├── v1/v1.0/
    └── v2/v2.3/
```

### 发版流程

**小版本更新**（如 v1.4 → v1.5）：

```
1. cp 方案骨架生成器.html → 版本归档/方案骨架生成器/v1/v1.4/方案骨架生成器.html
2. 修改 方案骨架生成器.html → v1.5（注释 + 页面 badge）
3. 更新 README.md 版本信息
4. git commit -m "chore: archive v1.4, bump to v1.5"
5. git push && ./deploy.sh
```

**大版本更新**（如 v1.x → v2.0）：

```
1. cp 方案骨架生成器.html → 版本归档/方案骨架生成器/v1/v1.x/方案骨架生成器.html
2. mkdir 版本归档/方案骨架生成器/v2/
3. 重写 方案骨架生成器.html → v2.0
4. git commit -m "feat: v2.0, archive v1.x"
```

### 版本号位置

| 位置 | 示例 |
|------|------|
| HTML 顶部注释 | `方案骨架生成器 · v1.5` + 变更说明 + 日期 |
| 页面 badge | `<span class="topbar__version">v1.5</span>` |
| `变更记录/` | 新增或更新对应版本记录 |
| `README.md` | 更新活跃版本和已归档版本表 |

## 📝 .gitignore

```
*                    ← 忽略一切
!*.html              ← 允许所有 .html
!README.md
!CLAUDE.md
!.gitignore
!deploy.sh
!deploy/
!deploy/**           ← Docker + nginx 配置
!变更记录/
!变更记录/*.md
```

> `版本归档/` 被 `*` 屏蔽，不纳入 git。历史版本通过 `git show <commit>` 找回，归档目录仅作本地+NAS 浏览用。

## 🐳 NAS 部署

`deploy.sh` 执行流程：
1. `git push origin main` → GitHub
2. `ssh nas "cd /volume1/web/ai-tools-html && git pull"` → NAS 从 GitHub 拉取

NAS 目录是 `--depth 1` 浅克隆，Docker + nginx 通过 Cloudflare Tunnel 暴露公网。

**NAS 连接信息**：
- 主机：`192.168.1.76`（LAN）
- 用户：`hfmedia`
- 路径：`/volume1/web/ai-tools-html/`
- Git 已安装（2.39.1）
- SSH 密钥已配置（`~/.ssh/id_ed25519`）
- 详见 `deploy/` 目录

> ⚠️ 远程 SSH 暂不可用（路由端口 22 被占）。部署需要局域网。远程可用方案：Tailscale 或路由器转发端口 2222→NAS:22。
