#!/usr/bin/env python3
"""
fetch_hot_signals.py — 每日热点快报管线
每日 09:00 由 DSM Task Scheduler 触发，或手动执行。
抓取 6 源热搜 → 去重 → DeepSeek 分析 → 原子写入 signal_feed.json
"""

import os, sys, re, json, time, tempfile, logging, atexit, shutil
from datetime import datetime, timedelta

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    raise RuntimeError('requests library is required. Install: pip install requests')

# ── Paths ────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, '.env')
LOG_DIR = os.path.join(SCRIPT_DIR, 'logs')
OUTPUT_FILE = os.path.join(SCRIPT_DIR, 'signal_feed.json')
LOCK_DIR = '/tmp/daily-hotspot.lock'
CALENDAR_PATH = os.path.join(SCRIPT_DIR, 'seasonal_events.json')
CALENDAR_WINDOW_DAYS = 45

DRY_RUN = '--dry-run' in sys.argv


def _parse_iso(ts_str: str) -> datetime:
    """Parse ISO timestamp, always returns naive datetime for safe comparison."""
    if not ts_str:
        return datetime(2000, 1, 1)
    try:
        dt = datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        # Python 3.8-3.10 polyfill: strip timezone colon (+08:00 → +0800)
        clean = re.sub(r'([+-]\d{2}):(\d{2})$', r'\1\2', str(ts_str))
        dt = datetime.fromisoformat(clean)
    # Strip tzinfo so comparison with naive datetime.now() never raises TypeError
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt

# ── Logging ──────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'hotspot.log'), encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 0. ENV LOADING
# ═══════════════════════════════════════════════════════════
def _load_env():
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

_load_env()
DEEPSEEK_KEY = os.environ.get('DEEPSEEK_KEY', '')
DEEPSEEK_API = 'https://api.deepseek.com/v1/chat/completions'
DEEPSEEK_MODEL = 'deepseek-v4-pro'


# ═══════════════════════════════════════════════════════════
# 1. HTTP HELPERS
# ═══════════════════════════════════════════════════════════
def _http_get(url, headers=None, timeout=15):
    """Unified HTTP GET with fallback to urllib."""
    if HAS_REQUESTS:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        r.raise_for_status()
        return r.text
    else:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8')


# ═══════════════════════════════════════════════════════════
# 2. SOURCE FETCHERS
# ═══════════════════════════════════════════════════════════
DAILYHOT_API = 'http://127.0.0.1:6688'

def fetch_dailyhotapi(source: str, top_n=100):
    """通用 DailyHotApi 抓取函数。source: weibo|zhihu|bilibili|..."""
    try:
        text = _http_get(f'{DAILYHOT_API}/{source}', timeout=10)
        data = json.loads(text)
        if data.get('code') != 200:
            log.warning(f'[dailyhotapi/{source}] API 返回: {data.get("message","")}')
            return []
        items = data.get('data', [])
        return [{'title': item.get('title', ''),
                 'source': source,
                 'hot': str(item.get('hot', item.get('desc', '')) or '')}
                for item in items[:top_n] if item.get('title')]
    except Exception as e:
        log.warning(f'[dailyhotapi/{source}] 失败: {e}')
        return []


def fetch_weibo_hot():
    return fetch_dailyhotapi('weibo')


def fetch_zhihu_hot():
    return fetch_dailyhotapi('zhihu')


def fetch_douyin_hot():
    return fetch_dailyhotapi('douyin')


def fetch_baidu_hot():
    return fetch_dailyhotapi('baidu')


def fetch_douban_group_hot():
    return fetch_dailyhotapi('douban-group')


def fetch_bilibili_hot():
    """B站热门 TOP10"""
    try:
        text = _http_get('https://api.bilibili.com/x/web-interface/popular',
                         headers={
                             'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                             'Referer': 'https://www.bilibili.com'
                         })
        data = json.loads(text)
        items = data.get('data', {}).get('list', [])
        return [{'title': item.get('title', ''),
                 'source': 'bilibili',
                 'hot': str(item.get('stat', {}).get('view', ''))}
                for item in items[:10] if item.get('title')]
    except Exception as e:
        log.warning(f'[bilibili] 抓取失败: {e}')
        return []


# ═══════════════════════════════════════════════════════════
# 3. DEDUP
# ═══════════════════════════════════════════════════════════
def title_similarity(a: str, b: str) -> float:
    """Simple character-level Jaccard similarity for Chinese titles."""
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def merge_dedup(all_topics: list, threshold=0.7) -> list:
    """Merge topics across sources by title similarity."""
    merged = []
    for topic in all_topics:
        found = False
        for m in merged:
            if title_similarity(topic['title'], m['title']) > threshold:
                # Merge: add source & platforms
                if topic['source'] not in m['platforms']:
                    m['platforms'].append(topic['source'])
                m['sources_raw'].append(topic)
                found = True
                break
        if not found:
            merged.append({
                'title': topic['title'],
                'platforms': [topic['source']],
                'sources_raw': [topic],
            })
    return merged


# ═══════════════════════════════════════════════════════════
# 4. DEEPSEEK API
# ═══════════════════════════════════════════════════════════
DEEPSEEK_PROMPT = """你是一个综艺节目策划顾问。以下是当前中国互联网的全网热搜数据，
包含微博热搜、知乎热榜、B站热门、抖音热点、百度热搜、豆瓣小组六个来源的 TOP 条目。

请对每条热搜进行分析，输出一个 JSON 对象。格式：

{
  "generated_at": "ISO时间戳",
  "ttl_hours": 24,
  "sources": ["weibo", "zhihu", "bilibili", "douyin", "baidu", "douban-group"],
  "total_raw": 原始条目数,
  "signals": [
    {
      "id": "L1",
      "channel": "热议|高赞|剧集|日韩|热门",
      "topic": "提炼后的主题标签（≤10字）",
      "source": "平台名",
      "angle": "从综艺策划角度分析，这条热点可以启发什么类型的综艺？（≤60字）",
      "genres": ["talent_show|dating|observation|survival|communal|travel"],
      "dominant": ["E4"],
      "auxiliary": ["E6"],
      "score": 1-10的热度/策划价值评分,
      "platforms": ["跨平台出现的来源列表"]
    }
  ]
}

叙事引擎 ID 对照：
E1=素人造星, E2=竞争/淘汰, E3=悬念/推理, E4=关系/情感,
E5=情境实验, E6=成长/蜕变, E7=日常/治愈, E8=幽默/游戏, E9=规则/系统

类型片对照：
talent_show=选秀/竞技, dating=恋综/情感, observation=观察类,
survival=生存/挑战, communal=群居实验, travel=旅行/公路

数据源特征指南：
- 微博：文娱话题、公共讨论、社会事件（综艺策划最强信号源）
- 知乎：社会议题、深度讨论、代际冲突（适合观察类/群居实验选题）
- B站：年轻用户兴趣、ACG/生活方式/高赞内容
- 抖音：短视频趋势、流行文化、挑战赛/素人改造等品类发源地
- 百度：搜索行为趋势、含电影/电视剧子类，直接对标娱乐产业
- 豆瓣小组：生活方式讨论、情绪趋势、代际态度。从豆瓣话题中识别生活方式趋势和代际价值观信号，筛选有大众共鸣潜力的

规则：
- channel 必须严格从这 5 个值中选择：热议、高赞、剧集、日韩、热门。禁止自创频道名（如观察/旅行/游戏等）
- dominant 和 auxiliary 必须是数组格式，例如 ["E4"]，即使只有一个引擎也要用方括号包裹。auxiliary 为空时写 "auxiliary": []
- 只输出 JSON，不要任何其他文字
- 从所有数据中筛选有综艺策划价值的信号，不设数量上限。不适合综艺策划的热搜直接跳过
- 同一事件在多个源中出现（多源共振）→ 合并为一条，platforms 列出所有来源，score 额外 +1
- 同主题跨平台出现 → 合并为一条，platforms 列出所有来源
- angle 必须具体可操作，不要泛泛而谈
- dominant 必须恰好选 1 个最核心引擎 ID（E1-E9），auxiliary 选 0-2 个辅助引擎
- **关键：只输出纯 JSON 对象，不要用 Markdown 代码块包裹（不要 ```json ... ```）**
- **如果某条热搜不适合综艺策划 → 跳过，不要强行生成**
- **韩综标记**：若热搜涉及韩国综艺/韩综（关键词：罗英锡/罗PD/新西游记/姜虎东/刘在石/Mnet/BoysPlanet/Produce/theqoo/더쿠/시청률/예능/韩综/定档），追加 "tags": ["k-variety"] 字段"""

FIX_PROMPT = """
Your previous response was not valid JSON.
Output ONLY the JSON object — no markdown wrapping, no extra text.
Ensure: no trailing commas, all strings use double quotes,
newlines in strings are escaped as \\n."""


def load_calendar(json_path: str = CALENDAR_PATH) -> list:
    """读取日历JSON，返回±45天窗口内的事件列表（只读，无副作用）。"""
    if not os.path.exists(json_path):
        log.warning(f'日历文件不存在: {json_path}，跳过日历注入')
        return []
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        log.warning(f'日历文件解析失败: {e}，跳过日历注入')
        return []

    events = data.get('events', [])
    if not events:
        return []

    now = datetime.now()
    window_start = now - timedelta(days=CALENDAR_WINDOW_DAYS)
    window_end = now + timedelta(days=CALENDAR_WINDOW_DAYS)

    matched = []
    for evt in events:
        try:
            dr = evt.get('date_range', '')
            start_str, end_str = dr.split('~')
            start_m, start_d = int(start_str[:2]), int(start_str[3:])
            end_m, end_d = int(end_str[:2]), int(end_str[3:])

            # Year assignment: if start_month > end_month → cross-year
            if start_m > end_m:
                evt_start = datetime(now.year, start_m, start_d)
                evt_end = datetime(now.year + 1, end_m, end_d)
            else:
                evt_start = datetime(now.year, start_m, start_d)
                evt_end = datetime(now.year, end_m, end_d)

            # Check overlap with ±45 day window
            if evt_start <= window_end and evt_end >= window_start:
                matched.append(evt)
        except (ValueError, IndexError):
            log.warning(f'日历事件 date_range 格式无效: {evt.get("id","?")} {dr}')
            continue

    return matched


def cleanup_calendar(json_path: str = CALENDAR_PATH):
    """删除结束日+365天<今天的事件，走write_atomic写回。"""
    if not os.path.exists(json_path):
        return
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError):
        log.warning('cleanup_calendar: JSON解析失败，跳过清理')
        return

    events = data.get('events', [])
    if not events:
        return

    today = datetime.now()
    cutoff = today - timedelta(days=365)
    kept = []
    removed = 0
    for evt in events:
        try:
            dr = evt.get('date_range', '')
            end_str = dr.split('~')[1]
            end_dt = datetime(today.year, int(end_str[:2]), int(end_str[3:]))
            if end_dt > today:
                end_dt = datetime(today.year - 1, int(end_str[:2]), int(end_str[3:]))
            if end_dt >= cutoff:
                kept.append(evt)
            else:
                removed += 1
        except (ValueError, IndexError):
            kept.append(evt)  # keep malformed entries

    if removed == 0:
        return

    data['events'] = kept
    data['last_updated'] = today.strftime('%Y-%m-%d')
    try:
        write_atomic(data, target=json_path)
        log.info(f'cleanup_calendar: 删除 {removed} 条过期事件')
    except Exception as e:
        log.error(f'cleanup_calendar: 写入失败: {e}')


def build_calendar_section(events: list) -> str:
    """生成日历段落文本，注入prompt。零事件返回占位文本。"""
    if not events:
        return "📅 当前季节无日历热点事件。"

    today_str = datetime.now().strftime('%Y-%m-%d')
    lines = [f"📅 当前季节热点日历（{today_str}，±{CALENDAR_WINDOW_DAYS}天窗口，共 {len(events)} 条事件）："]
    for evt in events:
        name = evt.get('name', '?')
        cat = evt.get('category', '')
        dr = evt.get('date_range', '')
        angle = evt.get('variety_angle', '')
        engines = evt.get('engines', [])
        keywords = evt.get('keywords', [])
        kw_str = ','.join(keywords) if keywords else ''
        eng_str = ','.join(engines) if engines else ''
        parts = [dr, name]
        if cat:
            parts.append(f'[{cat}]')
        if kw_str:
            parts.append(f'🏷{kw_str}')
        if angle:
            parts.append(f'→ {angle}')
        if eng_str:
            parts.append(f'【{eng_str}】')
        lines.append('- ' + ' '.join(parts))
    return '\n'.join(lines)


def build_prompt(merged_topics: list, extra_system: str = "", calendar_events: list = None) -> str:
    topics_text = []
    for i, t in enumerate(merged_topics):
        platforms = ', '.join(t['platforms'])
        topics_text.append(f"{i+1}. [{platforms}] {t['title']}")

    calendar_section = build_calendar_section(calendar_events or [])

    return (DEEPSEEK_PROMPT + "\n\n---\n"
            + calendar_section + "\n\n---\n当前热搜数据：\n"
            + '\n'.join(topics_text))


def call_deepseek(user_prompt: str, temperature: float = 0.7, extra_system: str = "") -> str:
    """Call DeepSeek API, return raw text response."""
    if not DEEPSEEK_KEY:
        raise RuntimeError('DEEPSEEK_KEY 未配置，请检查 .env 文件')

    messages = [{"role": "system", "content": "You are a helpful assistant." + extra_system}]
    messages.append({"role": "user", "content": user_prompt})

    body = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 65536,
    }

    resp = requests.post(
        DEEPSEEK_API,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()
    content = result['choices'][0]['message']['content']
    return content


# ═══════════════════════════════════════════════════════════
# 5. 4-LAYER JSON DEFENSE
# ═══════════════════════════════════════════════════════════
# L1: Clean
def clean_llm_output(text: str) -> str:
    """R1-R7 cleaning rules for LLM JSON output."""
    text = text.strip()                        # R3
    text = text.lstrip('﻿')               # R2: BOM

    # R1: Markdown code block
    if text.startswith('```'):
        lines = text.split('\n')
        lines = lines[1:]                      # drop ```json
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        text = '\n'.join(lines).strip()

    # R4: trailing commas
    text = re.sub(r',(\s*[}\]])', r'\1', text)

    # R6: NaN / Infinity
    text = text.replace('NaN', 'null').replace('Infinity', 'null')

    # R7: single-quote keys → double-quote
    text = re.sub(r"'(\w+)'(\s*:)", r'"\1"\2', text)

    # R8: JSON truncation repair — find last valid key-value and close
    if not text.endswith('}'):
        # Find last complete "key": value, or "key": "value" pair
        last_comma = text.rfind(',')
        if last_comma > 0:
            # Drop incomplete last element, close JSON
            text = text[:last_comma] + '\n    }\n  ]\n}'
            log.warning('R8: JSON 截断修复 — 丢弃最后一个不完整元素')

    return text


# L3: Schema validation
VALID_CHANNELS = {'热议', '高赞', '剧集', '日韩', '热门'}
VALID_GENRES = {'talent_show', 'dating', 'observation', 'survival', 'communal', 'travel'}
VALID_ENGINES = {f'E{i}' for i in range(1, 10)}
REQUIRED_SIGNAL_FIELDS = ['id', 'channel', 'topic', 'source', 'angle', 'genres', 'dominant', 'score']

# ── L2.5: Signal normalization (fix common LLM output mistakes) ──

CHANNEL_FALLBACK_MAP = {
    '观察': '高赞',   # LLM confused genre name with channel
    '旅行': '热门',
    '游戏': '热议',
}


def normalize_signal(s: dict, idx: int) -> dict:
    """Fix common LLM output quirks before schema validation."""
    # P1: auxiliary may be omitted when empty (prompt says "0-2 个")
    if 'auxiliary' not in s or s['auxiliary'] is None:
        s['auxiliary'] = []

    # P2: dominant/auxiliary as bare string instead of array
    if isinstance(s.get('dominant'), str):
        if s['dominant'].strip():
            log.warning(f'signals[{idx}].dominant 是字符串，自动转为数组: {s["dominant"]}')
            s['dominant'] = [s['dominant']]
        else:
            s['dominant'] = []
    if s.get('dominant') is None or (isinstance(s.get('dominant'), list) and len(s['dominant']) == 0):
        s['dominant'] = ['E1']  # E1=素人造星(通用引擎), always in VALID_ENGINES

    if isinstance(s.get('auxiliary'), str):
        if s['auxiliary'].strip():
            log.warning(f'signals[{idx}].auxiliary 是字符串，自动转为数组: {s["auxiliary"]}')
            s['auxiliary'] = [s['auxiliary']]
        else:
            s['auxiliary'] = []

    # P0: channel normalization — map unknown or missing channels
    ch = s.get('channel', '')
    if not ch or ch not in VALID_CHANNELS:
        new_ch = CHANNEL_FALLBACK_MAP.get(ch, '热议')
        log.warning(f'signals[{idx}].channel 自动修正: "{ch}" → "{new_ch}"')
        s['channel'] = new_ch

    # platforms default
    if 'platforms' not in s or s['platforms'] is None:
        s['platforms'] = []

    return s


def normalize_signals(data: dict) -> dict:
    """Apply normalize_signal to every signal in parsed JSON."""
    if 'signals' in data and isinstance(data['signals'], list):
        data['signals'] = [normalize_signal(s, i) for i, s in enumerate(data['signals'])]
    return data


def validate_signal_schema(data: dict) -> list:
    """Return list of errors. Empty list = pass."""
    errors = []
    if 'generated_at' not in data:
        errors.append('缺失 generated_at')
    if 'signals' not in data or not isinstance(data['signals'], list):
        errors.append('缺失或无效的 signals 数组')
        return errors

    for i, s in enumerate(data['signals']):
        for field in REQUIRED_SIGNAL_FIELDS:
            if field not in s:
                errors.append(f'signals[{i}].{field} 缺失')
        if s.get('channel') not in VALID_CHANNELS:
            errors.append(f'signals[{i}].channel 无效: {s.get("channel")}')
        for g in s.get('genres', []):
            if g not in VALID_GENRES:
                errors.append(f'signals[{i}].genres 包含无效值: {g}')
        for e in s.get('dominant', []) + s.get('auxiliary', []):
            if e not in VALID_ENGINES:
                errors.append(f'signals[{i}].引擎ID 无效: {e}')
        if 'platforms' not in s:
            errors.append(f'signals[{i}].platforms 缺失')
    return errors


# L4: Atomic write
def write_atomic(data: dict, target=OUTPUT_FILE):
    """Atomic write: tmp file + os.rename()."""
    dirname = os.path.dirname(target) or '.'
    fd, tmp_path = tempfile.mkstemp(dir=dirname, prefix='.signal_feed_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(tmp_path, 0o644)
        os.rename(tmp_path, target)
        log.info(f'✅ signal_feed.json 写入成功 ({len(data.get("signals",[]))} 条信号, {os.path.getsize(target)} bytes)')
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ═══════════════════════════════════════════════════════════
# 6. MAIN PIPELINE
# ═══════════════════════════════════════════════════════════
MAX_RETRIES = 2
RETRY_DELAY = 3
STALENESS_DAYS = 3


def generate_signal_feed(raw_topics: list, sources_ok: list) -> bool:
    """
    AI analysis → 4-layer defense → atomic write.
    Returns True if fresh JSON was written, False if fallback.
    """
    merged = merge_dedup(raw_topics)
    log.info(f'去重后 {len(merged)} 条, 原始 {len(raw_topics)} 条')

    calendar_events = load_calendar()
    cleanup_calendar()
    if calendar_events:
        log.info(f'日历注入: {len(calendar_events)} 条事件在 ±{CALENDAR_WINDOW_DAYS} 天窗口内')

    base_temp = 0.7

    for attempt in range(MAX_RETRIES + 1):
        try:
            temp = base_temp + (0.2 if attempt == 1 else 0)
            extra_system = FIX_PROMPT if attempt == 2 else ""

            raw_output = call_deepseek(build_prompt(merged, extra_system, calendar_events), temp)
            log.info(f'DeepSeek 返回 {len(raw_output)} chars')

            cleaned = clean_llm_output(raw_output)            # L1
            data = json.loads(cleaned)                        # L2
            data = normalize_signals(data)                    # L2.5 (fix LLM quirks)
            errors = validate_signal_schema(data)             # L3
            if errors:
                raise ValueError(f"Schema 校验失败: {', '.join(errors[:5])}")

            # Fill metadata (always use real time, don't trust AI timestamp)
            data['generated_at'] = datetime.now().astimezone().isoformat()
            data['ttl_hours'] = 24
            data['sources'] = sources_ok
            data['total_raw'] = len(raw_topics)

            write_atomic(data)                                 # L4
            return True

        except Exception as e:
            log.error(f'第 {attempt+1}/{MAX_RETRIES+1} 次尝试失败: {e}')
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    # All retries failed → try yesterday's JSON
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                old = json.load(f)
            ts = _parse_iso(old.get('generated_at', '2000-01-01'))
            if datetime.now() - ts < timedelta(days=STALENESS_DAYS):
                log.warning(f'全部重试失败，复用 {STALENESS_DAYS} 天内的 signal_feed.json')
                return False
        except Exception as e:
            log.error(f'复用旧 JSON 失败: {e}')

    log.error(f'signal_feed.json 不存在或超过 {STALENESS_DAYS} 天，回退硬编码')
    return False


# ═══════════════════════════════════════════════════════════
# 7. CONCURRENCY LOCK
# ═══════════════════════════════════════════════════════════
def _write_pid():
    """Write current PID inside the lock directory."""
    with open(os.path.join(LOCK_DIR, 'pid'), 'w') as f:
        f.write(str(os.getpid()))


def _pid_alive(pid: int) -> bool:
    """Check if a process with given PID exists. POSIX only (os.kill with signal 0)."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def acquire_lock() -> bool:
    """Acquire mkdir-based lock with PID file for stale detection."""
    try:
        os.mkdir(LOCK_DIR)
        os.chmod(LOCK_DIR, 0o755)
        _write_pid()
        atexit.register(release_lock)
        return True
    except FileExistsError:
        # Lock exists — check if holder is alive
        try:
            with open(os.path.join(LOCK_DIR, 'pid')) as f:
                pid = int(f.read().strip())
            if _pid_alive(pid):
                return False  # Lock valid
        except (FileNotFoundError, ValueError):
            pass  # PID file missing/corrupt → stale lock
        # Stale lock — steal atomically
        try:
            shutil.rmtree(LOCK_DIR)
        except FileNotFoundError:
            pass
        try:
            os.mkdir(LOCK_DIR)
            os.chmod(LOCK_DIR, 0o755)
            _write_pid()
            atexit.register(release_lock)
            return True
        except FileExistsError:
            return False  # Another process grabbed it first


def release_lock():
    """Release lock directory. Safe to call multiple times."""
    try:
        shutil.rmtree(LOCK_DIR)
    except FileNotFoundError:
        pass


# ═══════════════════════════════════════════════════════════
# 8. ENTRY POINT
# ═══════════════════════════════════════════════════════════
def main():
    log.info('=' * 50)
    log.info(f'fetch_hot_signals.py 启动 {"(DRY RUN)" if DRY_RUN else ""}')

    # Check API key
    if not DRY_RUN and not DEEPSEEK_KEY:
        log.error('DEEPSEEK_KEY 未配置。请在 .env 文件中设置 DEEPSEEK_KEY=sk-...')
        sys.exit(1)

    # Fetch all 6 sources
    log.info('抓取数据源...')
    results = {}
    for name, fn in [('weibo', fetch_weibo_hot), ('zhihu', fetch_zhihu_hot),
                      ('bilibili', fetch_bilibili_hot), ('douyin', fetch_douyin_hot),
                      ('baidu', fetch_baidu_hot), ('douban-group', fetch_douban_group_hot)]:
        items = fn()
        results[name] = items
        log.info(f'  [{name}] {len(items)} 条')

    sources_ok = [k for k, v in results.items() if v]
    all_topics = [t for v in results.values() for t in v]
    log.info(f'总计 {len(all_topics)} 条原始数据, 成功源: {sources_ok}')

    if DRY_RUN:
        # Show merged preview without API call
        merged = merge_dedup(all_topics)
        log.info(f'[DRY RUN] 去重后 {len(merged)} 条')
        for i, m in enumerate(merged[:10]):
            log.info(f'  {i+1}. [{", ".join(m["platforms"])}] {m["title"]}')
        log.info(f'[DRY RUN] prompt 预览 (前500字):')
        log.info(build_prompt(merged)[:500])
        log.info('[DRY RUN] 完成 — 未调 DeepSeek, 未写文件')
        return

    if not all_topics:
        log.warning('所有源抓取失败')

    # Degradation check
    if len(sources_ok) >= 4:
        log.info('L1: 全量 AI 分析')
        ok = generate_signal_feed(all_topics, sources_ok)
    elif len(sources_ok) >= 1:
        log.warning(f'L2: 仅 {len(sources_ok)} 源可用, 标注数据不完整')
        ok = generate_signal_feed(all_topics, sources_ok)
    else:
        log.error('L3/L4: 无可用源, 检查昨日 JSON...')
        if os.path.exists(OUTPUT_FILE):
            try:
                with open(OUTPUT_FILE) as f:
                    old = json.load(f)
                ts = _parse_iso(old.get('generated_at', '2000-01-01'))
                if datetime.now() - ts < timedelta(days=STALENESS_DAYS):
                    log.warning(f'保留 {STALENESS_DAYS} 天内的旧 JSON')
                    ok = False
                else:
                    log.error(f'JSON 超过 {STALENESS_DAYS} 天, 无新数据')
                    ok = False
            except Exception:
                log.error('昨日 JSON 无效, 无新数据')
                ok = False
        else:
            log.error('无 signal_feed.json, 首次部署后首次运行失败')
            ok = False

    log.info(f'管线结束, 结果: {"✅ 已更新" if ok else "⚠️ 降级"}')
    log.info('=' * 50)


if __name__ == '__main__':
    if not acquire_lock():
        log.warning('上一轮尚未完成，跳过本次执行')
        sys.exit(0)
    try:
        main()
    finally:
        release_lock()
