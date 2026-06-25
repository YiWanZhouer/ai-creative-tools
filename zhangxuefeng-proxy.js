// zhangxuefeng-proxy.js — 张雪峰AI对话代理服务器
// ⚠️ v1.33 后废弃：HTML 直调 nginx /api/v1/chat/completions（nginx 已有反向代理+API Key注入）
// 保留此文件供本地开发调试使用
// 用法: DEEPSEEK_API_KEY=sk-xxx node zhangxuefeng-proxy.js

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 8081;
const DEEPSEEK_KEY = process.env.DEEPSEEK_API_KEY;
if (!DEEPSEEK_KEY) {
  console.error('❌ 缺少 DEEPSEEK_API_KEY 环境变量');
  process.exit(1);
}

const HTML_PATH = path.join(__dirname, '张雪峰聊天.html');

// === Rate Limiter ===
const rateMap = new Map(); // IP → { count, resetAt }
const RATE_LIMIT = 30;
const RATE_WINDOW = 60_000; // 1 分钟
const MAX_INPUT_LENGTH = 2000;

function checkRate(ip) {
  const now = Date.now();
  let entry = rateMap.get(ip);
  if (!entry || now > entry.resetAt) {
    entry = { count: 0, resetAt: now + RATE_WINDOW };
    rateMap.set(ip, entry);
  }
  entry.count++;
  return entry.count <= RATE_LIMIT;
}

// 定期清理过期条目
setInterval(() => {
  const now = Date.now();
  for (const [ip, e] of rateMap) {
    if (now > e.resetAt) rateMap.delete(ip);
  }
}, 120_000);

// === System Prompt ===
// 能力声明前缀 + alchaincyf/zhangxuefeng-skill (MIT License) 的 SKILL.md 全文

const SKILL_PATH = path.join(__dirname, 'SKILL-张雪峰.md');

const ABILITY_PREFIX = `你叫张雪峰，本名张子彪，中国著名考研名师和高考志愿填报专家，全网四千多万粉丝。你现在运行在一个AI聊天网页中，拥有联网搜索能力（涉及就业率/薪资/分数线/行业趋势等需要最新数据的问题时会自动搜索）。

核心交互规则：
- 用第一人称「我」回答，东北大哥语气、快节奏、段子化
- 先问清楚对方分数/省份/家庭条件/目标城市——不同背景策略完全不同
- 看中位数不看顶尖案例，给明确判断不留灰色地带
- 首次对话说一句免责声明：「我以张雪峰的视角和你聊，基于公开言论和数据，供你参考。」后续不再重复

以下是你的完整人格定义，严格遵循：\n\n`;

let SKILL_MD;
try {
  const raw = fs.readFileSync(SKILL_PATH, 'utf8');
  SKILL_MD = ABILITY_PREFIX + raw;
  console.log(`📋 System prompt 已加载: ${(SKILL_MD.length / 1024).toFixed(1)} KB`);
} catch (e) {
  console.error('❌ 无法加载 SKILL-张雪峰.md，请确保文件存在于同目录');
  process.exit(1);
}

// === HTTP Server ===
const server = http.createServer((req, res) => {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }

  // GET / → serve HTML
  if (req.method === 'GET' && req.url === '/') {
    try {
      const html = fs.readFileSync(HTML_PATH, 'utf8');
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      return res.end(html);
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ error: 'HTML file not found' }));
    }
  }

  // POST /api/chat → proxy to DeepSeek
  if (req.method === 'POST' && req.url === '/api/chat') {
    // Rate limit
    const ip = req.socket.remoteAddress || 'unknown';
    if (!checkRate(ip)) {
      res.writeHead(429, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ error: 'rate_limited', retry_after: 60, message: '请求太频繁，请稍等一分钟' }));
    }

    // Read body
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      let parsed;
      try { parsed = JSON.parse(body); } catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: 'invalid_json' }));
      }

      const { messages } = parsed;
      if (!messages || !Array.isArray(messages)) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: 'missing_messages' }));
      }

      // Input length check
      const lastMsg = messages[messages.length - 1]?.content || '';
      if (lastMsg.length > MAX_INPUT_LENGTH) {
        res.writeHead(413, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: 'input_too_long', max_chars: MAX_INPUT_LENGTH, message: `输入超过${MAX_INPUT_LENGTH}字限制` }));
      }

      // Build payload with system prompt
      const payload = JSON.stringify({
        model: 'deepseek-v4-pro',
        messages: [
          { role: 'system', content: SKILL_MD },
          ...messages
        ],
        stream: true,
        search_enable: true,
        temperature: 0.9,
        max_tokens: 4096
      });

      // Proxy to DeepSeek
      const upstream = https.request({
        hostname: 'api.deepseek.com',
        path: '/v1/chat/completions',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${DEEPSEEK_KEY}`,
          'Accept': 'text/event-stream'
        },
        timeout: 120_000
      }, (upstreamRes) => {
        // v1.33 部署注意：nginx 反代后 remoteAddress 变为容器 IP，rate limit 需改用 X-Forwarded-For
        if (upstreamRes.statusCode !== 200) {
          // 非 200 → 转发 JSON error 给前端
          let errBody = '';
          upstreamRes.on('data', c => { errBody += c; });
          upstreamRes.on('end', () => {
            res.writeHead(upstreamRes.statusCode, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'upstream_error', status: upstreamRes.statusCode, detail: errBody.slice(0, 500) }));
          });
          return;
        }

        // 200 → SSE 流式中继
        res.writeHead(200, {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive'
        });
        upstreamRes.pipe(res);
      });

      upstream.on('error', (err) => {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'upstream_unreachable', message: 'DeepSeek API 连接失败' }));
      });
      upstream.on('timeout', () => {
        upstream.destroy();
        res.writeHead(504, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'upstream_timeout', message: 'DeepSeek API 响应超时' }));
      });

      upstream.write(payload);
      upstream.end();
    });
    return;
  }

  // 404
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'not_found' }));
});

server.listen(PORT, () => {
  console.log(`🎓 张雪峰AI对话已启动: http://localhost:${PORT}`);
  console.log(`   搜索增强: search_enable=true`);
  console.log(`   限流: ${RATE_LIMIT} req/min`);
  console.log(`   输入限制: ${MAX_INPUT_LENGTH} chars`);
});
