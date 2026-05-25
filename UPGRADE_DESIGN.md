# HLTVAPI 专业级升级设计方案

> 目标：`单 IP 下最大化实时抓取能力与存活能力`，从"基础爬虫"升级为"专业级 HLTV 实时反反爬采集引擎"

---

## 目录

1. [全局架构](#1-全局架构)
2. [Session Manager（最优先）](#2-session-manager最优先)
3. [Fetch Pipeline（最优先）](#3-fetch-pipeline最优先)
4. [Proxy Rotator & 智能限速](#4-proxy-rotator--智能限速)
5. [Live Crawler Engine](#5-live-crawler-engine)
6. [变化驱动抓取（Change Detection）](#6-变化驱动抓取change-detection)
7. [Parser Engine 2.0](#7-parser-engine-20)
8. [Antibot 系统升级](#8-antibot-系统升级)
9. [Browser Context Manager](#9-browser-context-manager)
10. [数据层：Raw HTML Archive & Replay](#10-数据层raw-html-archive--replay)
11. [Task Orchestrator](#11-task-orchestrator)
12. [代码结构](#12-代码结构)
13. [实现路线图](#13-实现路线图)
14. [关键技术决策清单](#14-关键技术决策清单)

---

## 1. 全局架构

### 1.1 当前问题

```
client.py (898行) ← 承担了太多职责
├── 传输层管理 (curl/httpx/PW)
├── 速率限制
├── Cookie管理
├── 路径封禁追踪
├── 内存缓存
├── Block检测
└── 重试逻辑
```

所有逻辑揉在一个类里，违背单一职责。升级后拆分为 Pipeline 架构。

### 1.2 目标架构

```
┌─────────────────────────────────────────────────────────┐
│                    Task Orchestrator                     │
│  (优先级调度、去重、定时触发、事件触发、adaptive polling)  │
└────────────────────┬────────────────────────────────────┘
                     │ tasks
┌────────────────────▼────────────────────────────────────┐
│                    Fetch Pipeline                        │
│  SessionManager → ProxyRotator → Transports → Response   │
│                                          │              │
│                                    ┌─────▼──────┐      │
│                                    │ BlockCheck  │      │
│                                    └─────┬──────┘      │
│                                          │ html/text   │
└────────────────────┬────────────────────────────────────┘
                     │ raw response
┌────────────────────▼────────────────────────────────────┐
│              Raw HTML Archive (append-only)              │
│         + Change Detection (diff-based triggers)         │
└────────────────────┬────────────────────────────────────┘
                     │ raw html (replayable)
┌────────────────────▼────────────────────────────────────┐
│                   Parser Engine 2.0                      │
│  Pipeline: Preprocess → Semantic → Fallback → Validate  │
└────────────────────┬────────────────────────────────────┘
                     │ structured data
┌────────────────────▼────────────────────────────────────┐
│                Data Layer (Warehouse + Cache)            │
└─────────────────────────────────────────────────────────┘
```

### 1.3 核心原则

| 原则 | 说明 |
|------|------|
| **Fail Fast** | 不浪费时间在被封的 session/代理上 |
| **Degrade Gracefully** | 代理不可用 → 延迟增加 → 降速 → 单 IP bare metal |
| **Replayable** | 所有 raw HTML 存档，允许离线重解析 |
| **Stateless Parsing** | Parser 仅依赖 raw HTML，不依赖网络 |
| **Session Isolation** | 每个 transport session 独立，失败不污染其他 |

---

## 2. Session Manager（最优先）

### 2.1 当前问题

- Cookie 全部存在 `self._cookies: dict[str, str]` 一个全局字典
- curl_cffi 的 AsyncSession 和 httpx AsyncClient 各一个单例，没有轮换
- Playwright context 每次请求新建/销毁
- 没有 session 健康度评分
- 被封后没有 session 级别隔离，所有传输层共享同一状态

### 2.2 设计

```python
class SessionIdentity:
    """一个 session 的完整身份指纹"""
    user_agent: str
    accept_language: str
    screen_resolution: tuple[int, int]  # 用于 Playwright
    timezone: str
    platform: Literal["win32", "darwin", "linux"]

class TransportSession:
    """单个传输层 session 的包装"""
    id: str
    transport: Literal["curl", "httpx", "playwright"]
    identity: SessionIdentity
    client: Any  # AsyncSession | AsyncClient | BrowserContext
    cookie_jar: dict[str, str]
    created_at: float
    last_used: float
    request_count: int
    block_count: int
    consecutive_blocks: int
    health_score: float  # 0.0 ~ 1.0
    banned: bool
    ban_time: float | None

class SessionPool:
    """
    维护多个 TransportSession，每个 session 有独立的：
    - User-Agent
    - 指纹参数
    - Cookie jar
    - 健康度评分
    
    策略：
    1. 请求时选择 health_score 最高的 session
    2. 被封后 health_score 降低，减少其使用概率
    3. 连续 block 3 次 → 标记 banned → 5 分钟后重新激活
    4. 定期清理：超过 request_count 阈值的 session 退役，新建替代
    5. curl/httpx session 保留 10-30 个轮流使用
    """
    
    def acquire(self, transport: str) -> TransportSession: ...
    def release(self, session_id: str, success: bool): ...
    def report_block(self, session_id: str): ...
    def rotate_session(self, transport: str) -> TransportSession: ...
    def get_health_stats(self) -> dict: ...
```

### 2.3 关键算法：Session 选择策略

```
score = health_score * (1 + 0.1 * log(1 + request_count))
          - 0.2 * consecutive_blocks
          + random.uniform(0, 0.05)  # 探索噪声

选择 score 最高的 session → Softmax 概率选择 → 避免饥饿
```

- 默认 10 个 curl session + 5 个 httpx session + 2 个 Playwright context
- 每个 session 最多 200 请求后自动退役
- 退役前用其 identity 创建一个替身（避免 fingerprint 频率特征丢失）

### 2.4 指纹多样性要求

每个 TransportSession 的 identity 必须差异化：

| 参数 | 池大小 | 差异化方式 |
|------|--------|-----------|
| User-Agent | 8-12 | Chrome/Edge/Firefox/Safari × Win/Mac/Linux |
| Accept-Language | 5 | en-US, en-GB, 混合语言 |
| Screen Resolution | 4 | 1920×1080, 1440×900, 2560×1440, 1366×768 |
| Timezone | 6 | America/NY, Europe/London, Asia/Shanghai 等 |
| Platform | 3 | Win32, macOS, Linux |

---

## 3. Fetch Pipeline（最优先）

### 3.1 当前问题

- `get()` 方法里塞满 cache → rate limit → semaphore → transport → fallback → playbook
- 传输选择逻辑（`_execute_request`）与业务逻辑混在一起
- 无法灵活配置：比如某些 URL 需要 bypass cache，某些强制 Playwright

### 3.2 设计

```python
@dataclass
class FetchRequest:
    url: str
    cache_ttl: int | None = None
    cache_key: str | None = None
    force_playwright: bool = False
    prefer_curl: bool = False
    bypass_cache: bool = False
    bypass_rate_limit: bool = False
    priority: int = 0          # 0=low, 1=normal, 2=high (live match)
    dedup_key: str | None = None  # 用于实时去重
    metadata: dict = field(default_factory=dict)

@dataclass
class FetchResponse:
    url: str
    html: str
    status: int
    transport_used: str
    session_id: str | None
    from_cache: bool
    fetched_at: float
    ttl: int | None
    response_headers: dict

class FetchPipeline:
    """
    请求生命周期：
    1. Filter (去重、白名单检查)
    2. Cache lookup (L1 → L2 → L3)
    3. Rate limit acquire
    4. Session acquire
    5. Transport attempt
    6. Block check
    7. Cache write
    8. Archive raw HTML
    """
    
    async def execute(self, request: FetchRequest) -> FetchResponse: ...
    async def execute_batch(self, requests: list[FetchRequest]) -> list[FetchResponse]: ...
    def get_pipeline_stats(self) -> dict: ...
```

### 3.3 Transport 选择策略

```
fetch(url) → Pipeline:
  1. 检查当前全局 block 状态（HLTV 是否整体在封）
  2. 检查 path 级别的 ban 状态
  3. 选择 transport:
     a. force_playwright → 直接 Playwright
     b. url path 曾被 block → → Playwright (stealth mode)
     c. SessionPool 选 curl session → 尝试
     d. 失败时降级:
        curl block → httpx → Playwright (stealth mode)
     e. 3 种 transport 全失败 → mark path banned → wait → 重试
```

### 3.4 Retry Strategy 升级

| 错误类型 | 行为 |
|---------|------|
| 429 Too Many Requests | 触发全局减速 + 切换 session |
| 403 / Cloudflare | 释放当前 session + 标记 block + 升级 transport |
| Timeout / ConnectionError | 换 session 重试 |
| 500/502/503/504 | 短等待后重试，不换 session |
| 解析成功但 HTML 异常 | 重抓（可能拿到 partial response） |

---

## 4. Proxy Rotator & 智能限速

### 4.1 当前问题

- 无代理池支持
- `_resolve_proxy()` 只读环境变量，固定到死
- `AdaptiveRateLimiter` 的 backoff 是指数增长，没有"慢恢复"机制
- 没有"时间窗口滑动"：当天/小时用完就彻底截止
- 没有基于请求耗时的动态调速

### 4.2 Proxy Rotator

```python
class Proxy:
    url: str
    type: Literal["http", "socks5", "socks5h"]
    region: str | None
    speed_ms: float       # 滚动平均响应时间
    failed_count: int
    success_count: int
    consecutive_fails: int
    health_score: float   # 0.0 ~ 1.0，基于 success_rate + speed
    banned: bool
    last_checked: float

class ProxyRotator:
    """
    注意：HLTV 对代理 IP 非常敏感。
    策略：本地 IP (无代理) 作为 baseline，代理仅作为 fallback 或轮换。
    
    优先级：无代理(本地) > 高质量住宅代理 > 机房代理
    每成功 N 次（N=5~15 随机）在代理间切换一次。
    """
    
    # 核心能力
    async def get_proxy(self, session: TransportSession) -> Proxy | None: ...
    async def report_result(self, proxy: Proxy, success: bool, latency: float): ...
    def get_stats(self) -> dict: ...
```

### 4.3 Adaptive Rate Limiter 重写

```python
class AdaptiveRateLimiter:
    """
    核心升级点：
    1. 基于滑动时间窗口（非固定整点）的请求计数器
    2. 基于响应时间的动态调速
    3. 基于 block 频率的全局降速
    4. "慢启动"机制：长时间休息后逐步恢复到正常速率
    5. 多维度限速：domain-level + path-level + global
    """
    
    # 速率控制维度
    min_delay: float        # 正常 1.5s
    current_delay: float    # 动态调整，受 block rate 影响
    max_delay: float        # 紧急 10s+
    
    # 滑动窗口（使用 deque）
    request_timestamps: deque[float]  # 最近 1h 的请求时间戳
    block_timestamps: deque[float]    # 最近 1h 的 block 次数
    
    # 智能调速算法
    def _adjust_delay(self):
        """
        如果 1h 内 block_rate > 5%:  delay *= 1.5
        如果 1h 内 block_rate > 15%:  delay *= 3
        如果 10min 内 0 blocks:       delay *= 0.95 (慢恢复)
        如果 min_delay < delay < max_delay, 渐进恢复
        """
```

### 4.4 关键算法：Smart Throttle

```
每个请求后：
  current_rps = len(last_60s_requests) / 60
  block_rps = len(last_60s_blocks) / 60
  
  target_rps = max(1, hourly_limit / 3600)
  
  if block_rps > 0:
    # 有 block → 大幅减速
    throttle_factor = max(3, block_rps * 20)
  elif current_rps > target_rps:
    # 接近上限 → 减速
    throttle_factor = 1 + (current_rps - target_rps) / target_rps
  else:
    # 正常 → 慢速恢复
    throttle_factor = max(1, throttle_factor * 0.99)
  
  current_delay = max(min_delay, min(max_delay, current_delay * throttle_factor))
```

---

## 5. Live Crawler Engine

### 5.1 当前问题

- 没有 live match 的实时抓取机制
- scheduler 只做了每日 ranking snapshot 和 results archive
- 用户在 CLI 手动 `python main.py match <id>` 才能看到比赛状态
- 没有"订阅"某个 match，自动 push 状态变化的机制
- WebSocket 只是监控通道，不是数据推送通道

### 5.2 设计

```python
class LiveMatchTracker:
    """
    对 live match 的"高频低损"追踪。
    
    核心设计：
    1. 从 /matches 页面发现 live match（每 30s 检查一次）
    2. 对每个 live match 建立独立的 polling 协程
    3. Polling 频率：30s → 60s → 120s (指数衰减，比赛结束后停止)
    4. 使用 If-Modified-Since / ETag 减少无效传输
    5. 通过 diff 检测比赛状态变化（map 结束、比分变化、新 demo）
    6. 变化时触发通知 (WebSocket / 回调)
    7. 自动清理：比赛结束 1h 后移除 tracker
    """
    
    tracked_matches: dict[int, MatchTrackerState]
    active_pollers: dict[int, asyncio.Task]
    
    async def start(self): ...
    async def subscribe(self, match_id: int, callback: Callable): ...
    async def unsubscribe(self, match_id: int): ...
    async def _poll_match(self, match_id: int): ...
    async def _detect_changes(self, old: bytes, new: bytes) -> list[Change]: ...
```

### 5.3 Adaptive Polling 算法

```
状态: [upcoming] → [live] → [finished]
                      ↓ polling ↓
            ┌────────────────────────┐
            │  比赛已进行中           │
            │  上一局结束 → 30s 轮询  │
            │  无变化3次 → 60s 轮询   │
            │  Map 切换中 → 15s 轮询   │
            │  Score 变化 → 立即通知   │
            └────────────────────────┘

poll_interval = base_interval * (1 + 0.5 * unchanged_polls)
            * (1 - 0.3 * has_score_change)
            * (1 + 1.0 * is_halftime)  # 半场休息降频
```

### 5.4 流量节省策略

```
1. 使用 HTTP HEAD 或 range request 检查页面修改时间
2. 缓存已知不变的页面片段（event logo, team logo）
3. 对 live match 页面，只提取 map status 和 score 部分
   → 如果可能，用 /matches/{id} 的 stats API 替代全页抓取
4. 使用 Match ID 去重：5s 内相同 ID 不重复抓取
```

---

## 6. 变化驱动抓取（Change Detection）

### 6.1 当前问题

- 所有抓取都是"定时全量"模式：每天固定时间抓一遍
- 不知道页面是否变化，重复消耗请求
- 没有 diff 或 content hash 做变更检测

### 6.2 设计

```python
class ChangeDetector:
    """
    对每个 URL 维护一个 content hash chain。
    
    策略：
    1. 首次抓取：存储 HTML + MD5(content)
    2. 后续抓取前：先算当前 content hash（可通过 ETag/Last-Modified）
    3. 无变更：使用缓存，不触发 parser 和 notify
    4. 有变更：存新版本 + 标记变更类型 + 触发通知
    
    变更类型检测：
    - team ranking: 排名变化、队伍进出 top30
    - upcoming: 新增比赛、比赛延期、format 变化
    - results: 新结果出现
    - live match: 比分变化、局间切换、MVP 更新
    """
    
    _hash_store: dict[str, str]  # url → md5
    
    async def has_changed(self, url: str, new_html: str) -> bool: ...
    async def get_change_type(self, url: str, old_html: str, new_html: str) -> ChangeType: ...
    def mark_stable(self, url: str, ttl: int): ...
    
    # 变更事件
    @dataclass
    class ChangeEvent:
        url: str
        change_type: ChangeType
        old_hash: str
        new_hash: str
        timestamp: float
```

### 6.3 ETag/Last-Modified 集成

```python
class ETagTracker:
    """
    如果 HLTV 返回 ETag 或 Last-Modified header，
    下次请求带上 If-None-Match / If-Modified-Since。
    返回 304 直接跳过，不浪费流量和解析。
    """
    
    _etags: dict[str, str]           # url → etag
    _last_modified: dict[str, str]   # url → last-modified
    
    def record(self, url: str, headers: dict): ...
    def apply(self, url: str, headers: dict) -> dict: ...
```

---

## 7. Parser Engine 2.0

### 7.1 当前问题

- 所有 parser 使用硬编码 CSS selector，HLTV 改版即崩溃
- selector 没有 fallback，没有校验层
- `_parse_match_overview` 等方法在 endpoint 类中，无法独立测试
- 没有"语义层"：selector 失效后没有尝试方案
- 没有 parser pipeline：单次解析失败 = 数据丢失

### 7.2 设计

```python
# ── Semantic Selector ─────────────────────────────────────

@dataclass
class SelectorStrategy:
    """一个字段的多层 selector fallback"""
    field: str
    primary: str
    fallbacks: list[str]                # CSS selector fallback 链
    extractor: Literal["text", "href", "src", "img", "int", "float", "attr"]
    attr: str | None = None             # 如果 extractor 是 attr
    required: bool = False              # True → 此字段缺失时整条记录跳过
    validator: Callable | None = None   # 后置校验
    transform: Callable | None = None   # 后置转换（如 strip, parse date）

class SemanticParser:
    """
    语义层解析器。
    
    与当前硬编码 selector 的区别：
    - 每个字段有 2-3 个 selector 备选
    - 当 primary 返回 None 或空，自动尝试 fallback
    - 记录 selector 命中率，指导后续优化
    - 所有 selector 定义集中在 selectors/ 目录，与解析逻辑分离
    
    使用示例：
    STRATEGIES: dict[str, list[SelectorStrategy]] = {
        "match_overview": [
            SelectorStrategy("team1_name", ".match-teamname", [".team1 .team", ".team-cell:first-child .team"]),
            SelectorStrategy("team1_logo", ".match-team-logo img", [".team1 img[src*='logo']"], extractor="img"),
            SelectorStrategy("match_id", ".match-wrapper", extractor="attr", attr="data-match-id", required=True),
        ]
    }
    """
    strategies: dict[str, list[SelectorStrategy]]
    selector_hitrate: dict[str, dict[str, float]]  # field → {selector → hit%}
    
    def parse(self, soup, context: str) -> dict: ...
    def get_health_report(self) -> dict: ...
```

### 7.3 Parser Pipeline

```python
class ParserPipeline:
    """
    多阶段解析 pipeline。
    
    Stage 1: Preprocess
        - HTML 清洗（修正畸形标签、提取 JSON-LD 数据）
        - 提取 meta 标签中的结构化数据
        - 识别页面类型（upcoming/result/detail/profile）
    
    Stage 2: Semantic Parse
        - 使用 SelectorStrategy 链 + 语义层解析
        - 每个字段最多尝试 3 个 fallback
    
    Stage 3: Validation
        - 检查必填字段是否存在
        - 检查 ID 是否为正整数
        - 检查 URL 格式
        - 检查比分是否在合理范围 (0-50)
        - 检查时间戳是否合理
    
    Stage 4: Enrichment
        - 用已知数据补全（如 team logo 可从上次成功解析拿）
        - 用 URL 推断缺失 ID
        - auto-correct 常见格式问题
    
    Stage 5: 结构化输出
        - 输出 Pydantic model
        - 记录解析统计（成功/失败/字段覆盖率）
    """
    
    stages: list[ParserStage]
    
    async def process(self, html: str, page_type: str) -> ParseResult: ...
    async def reprocess(self, html: str, page_type: str, strategy_override: dict) -> ParseResult: ...
```

### 7.4 抗 DOM 变化机制

```
1. 所有 selector 在 parse 时记录匹配数/空值数
2. 每日报告：每个 selector 的"健康度"
3. 如果某个 selector match_count 从 30 降到 0 → 自动标记为失效
4. 失效 selector 自动降级，启用 fallback
5. 提供 CLI: python main.py validate-selectors 测试所有 selector
6. 支持 HTML snapshot 回放：用历史 fixture 验证新 selector 不影响旧数据
```

---

## 8. Antibot 系统升级

### 8.1 TLS Fingerprint 强化

```python
class TLSFingerprintManager:
    """
    当前：固定 impersonate="chrome124"
    升级：轮换 TLS fingerprint
    
    支持的版本池：
    - chrome124, chrome130, chrome131, chrome132
    - safari17_5, safari18
    - firefox136
    
    每个 session 关联一个 fingerprint 版本。
    session 退役时换一个新的 fingerprint。
    不频繁切换（每 session 只用一个 fingerprint 版本）。
    
    额外：
    - 自定义 JA3 生成（不依赖 curl_cffi 内置）
    - 支持 HTTP/2 fingerprint 定制
    - 随机化 TLS extension order
    """
    
    versions: list[str] = [
        "chrome124", "chrome130", "chrome131",
        "safari17_5", "safari18", "firefox136",
    ]
    
    def assign(self, session: TransportSession) -> str: ...
    def rotate(self, session: TransportSession) -> str: ...
```

### 8.2 HTTP/2 Fingerprint

```python
class H2Fingerprint:
    """
    HTTP/2 connection preface 和 settings 的指纹也会被检测。
    
    需随机化：
    - SETTINGS 帧顺序
    - WINDOW_UPDATE 大小
    - PRIORITY 帧频率
    - PING 帧发送间隔
    - 流并发数
    
    curl_cffi 已经做了一部分，但需要确认使用的是最新版本。
    httpx 的 http2 指纹较弱，只在 fallback 时使用。
    """
```

### 8.3 Header 组合策略

```
每个请求的 header 应该组成"realistic 浏览器 header profile"。
不是每个 header 都随机，而是整个 header set 作为一个 profile：

Profile "Chrome 131 Windows":
  - User-Agent: Chrome 131 / Win10
  - Sec-Ch-Ua: "Chromium";v="131", "Google Chrome";v="131"
  - Sec-Ch-Ua-Platform: "Windows"
  - Sec-Ch-Ua-Mobile: ?0
  - Sec-Fetch-Site: same-origin / cross-site
  - Sec-Fetch-Mode: navigate / no-cors
  - Sec-Fetch-Dest: document / empty
  - Accept: text/html,...
  - Accept-Encoding: gzip, deflate, br, zstd
  - Accept-Language: en-US,en;q=0.9
  - Referer: 来自 _REFERERS 池

Profile "Firefox 136 Windows":
  - User-Agent: Firefox/136.0
  - Accept: text/html,...
  - Accept-Encoding: gzip, deflate, br
  - Accept-Language: en-US,en;q=0.9
  - DNT: 1
  - Sec-GPC: 1
  - Referer: ...

一个 session 固定使用一个 profile，不混用。
混用 header profile 会产生 browser 不存在的 header 组合 → 最容易被检测。
```

### 8.4 Cookie 管理策略

```
1. Session 隔离：每个 TransportSession 有独立的 cookie jar
2. Cookie 持久化：保存到磁盘，重启不丢失
3. 规律性清除：每 N 个请求清除 cookie 重新获取（模拟新访问）
4. 模拟登录流程：/
   → 先访问 / (get home page cookie)
   → 再访问目标页面
5. 避免 cookie 污染：不同 session 不共享 cookie
```

### 8.5 Request Pattern 人性化

```python
class HumanRequestPattern:
    """
    模拟真实用户访问模式。
    核心：不是均匀间隔，而是 on/off burst 模式。
    
    真实用户行为：
    - 浏览期：快速连续访问 3-8 个页面，间隔 2-15s
    - 阅读期：30-120s 停顿（看比赛、读文章）
    - Scroll 行为：请求之间加随机 500-3000ms 模拟阅读
    
    爬虫行为（反面教材）：
    - 均匀间隔 3s 请求 → 稳定可预测 → 容易被检测
    
    本模块实现：
    - 工作时间模式：密集请求（8:00-23:00 请求量占 80%）
    - 休息时间模式：低频率（23:00-8:00 占 20%）
    - Burst 模式：N 个请求连续发出（间隔 1-3s），然后停顿 30-90s
    - 随机略过：每 20-40 个请求随机跳过 1 个 URL（模拟误点）
    - 重访模式：随机回头访问之前看过的页面
    """
    
    burst_size: tuple[int, int] = (3, 8)
    burst_gap: tuple[float, float] = (1.0, 3.0)
    rest_gap: tuple[float, float] = (30.0, 90.0)
    
    async def next_delay(self) -> float: ...
```

### 8.6 全局 Block 检测升级

```python
class BlockDetector:
    """
    多层 block 检测系统：
    
    Level 1: 状态码
      - 429 → rate limit
      - 403 → blocked
    
    Level 2: 关键词
      - 已有: cf-browser-verification, just a moment...
      - 新增: 维护一个模式库，定期从 HLTV block page 更新
    
    Level 3: 响应大小 + 内容分布
      - 正常 HLTV 页面: 150-500KB, HTML 占比 > 60%
      - Block 页面: < 30KB, HTML 占比 > 90%
      - 使用 entropy 检测: 正常页面 content entropy 高于 block page
    
    Level 4: 响应时间模式
      - 突然所有请求都 < 500ms → 可能被 block 到轻量页面
      - 突然所有请求都 > 10s → 可能被质询（challenge）
    
    Level 5: DOM 结构指纹
      - 正常页面包含特定 marker: '.match-wrapper', '.teamsBox'
      - Block 页面缺失这些 marker → 即使 200 也是 block
    """
```

---

## 9. Browser Context Manager

### 9.1 当前问题

- 每个 Playwright 请求：新建 context → new page → goto → close page → close context
- 高频创建 context 开销大（~500ms）
- 没有 browser context 复用
- 没有模拟 human-like browsing behavior

### 9.2 设计

```python
class BrowserContextPool:
    """
    维护 2-3 个持久化的 BrowserContext。
    
    每个 context：
    - 固定一个 viewport / timezone / locale
    - 存储 cookies
    - 每 5-10 分钟 simulate human activity：
      * 访问 / (home page)
      * scroll 一下
      * 等待几秒
    - 每 30 分钟关闭重建（防止 browser leak）
    
    请求策略：
    1. 从 pool 中取一个空闲 context
    2. 在 context 中打开新 page
    3. 先访问 / 获取 cookie（如果无 cookie）
    4. 再 goto 目标 URL
    5. 完成后保留 page（用于后续可能的 navigation）
    6. 返回 context 到池
    
    注意：
    - Playwright 是核选项，只在 stealth mode 使用
    - 在 light mode 下此模块完全跳过
    - 每次使用后检查 browser 内存，超过阈值则重启
    """
    
    _contexts: list[BrowserContext]
    _browser: Browser
    
    async def acquire(self, session: TransportSession) -> BrowserContext: ...
    async def release(self, ctx: BrowserContext): ...
    async def _simulate_human_activity(self, ctx: BrowserContext): ...
    async def _recycle(self, ctx: BrowserContext): ...
```

### 9.3 Stealth Init Script 升级

```javascript
// 当前脚本只覆盖了基本检测
// 升级版本覆盖更多 WebDriver 检测指标：
Object.defineProperties(navigator, {
    webdriver: { get: () => false },
    plugins: { get: () => [1, 2, 3, 4, 5] },
    languages: { get: () => ['en-US', 'en'] },
    hardwareConcurrency: { get: () => 8 },
    deviceMemory: { get: () => 8 },
    maxTouchPoints: { get: () => 0 },  // 非触屏
});

// 覆盖 chrome.runtime
window.chrome = {
    runtime: { connect: () => {}, sendMessage: () => {} },
    loadTimes: () => {},
    csi: () => {},
    app: { isInstalled: false, InstallState: {}, RunningState: {} },
};

// 覆盖 WebGL fingerprint（防止 canvas fingerprinting）
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Open Source Technology Center';  // UNMASKED_VENDOR
    if (parameter === 37446) return 'Mesa DRI Intel(R) HD Graphics (KBL GT2)';  // UNMASKED_RENDERER
    return getParameter(parameter);
};

// 覆盖 navigator.connection
Object.defineProperty(navigator, 'connection', {
    get: () => ({
        effectiveType: '4g',
        downlink: Math.random() * 10 + 5,
        rtt: 50 + Math.floor(Math.random() * 100),
    }),
});

// 覆盖 Permissions
Object.defineProperty(navigator, 'permissions', {
    get: () => ({
        query: async () => ({ state: 'prompt' }),
    }),
});
```

---

## 10. 数据层：Raw HTML Archive & Replay

### 10.1 当前问题

- 解析后原始 HTML 直接丢弃
- 如果 parser 有 bug 或 selector 失效，数据永久丢失
- 无法离线重解析历史数据
- 没有"回放"能力

### 10.2 设计

```python
class HTMLArchive:
    """
    append-only raw HTML 存储。
    
    存储格式：
    archive/
    ├── 2026/
    │   ├── 01/
    │   │   ├── matches_upcoming_2026-01-15T10:30:00.html
    │   │   ├── matches_2367256_2026-01-15T10:31:00.html
    │   │   ├── teams_ranking_2026-01-15T11:00:00.html
    │   │   └── ...
    │   └── 02/...
    └── index.sqlite  # URL + timestamp → filename 映射
    
    索引字段：
    - url
    - fetched_at (timestamp)
    - page_type (upcoming / result / detail / ranking / ...)
    - entity_id (match_id / team_id / player_id)
    - etag
    - content_md5
    - size_bytes
    - filename
    
    查询能力：
    - 按 URL 查历史版本
    - 按 entity_id 查所有相关页面
    - 按时间范围批量
    - 导出为测试 fixture
    """
    
    async def store(self, url: str, html: str, metadata: dict) -> Path: ...
    async def get_latest(self, url: str) -> str | None: ...
    async def get_version(self, url: str, timestamp: float) -> str | None: ...
    async def list_versions(self, url: str) -> list[ArchiveEntry]: ...
```

### 10.3 Replayable Parser

```python
class ReplayParser:
    """
    对 archive 中的 raw HTML 重解析。
    
    使用场景：
    1. Parser 升级后回溯验证兼容性
       python main.py replay --parser v2 --from 2026-01-01 --to 2026-01-15
    2. Selector 失效后重新提取数据
       python main.py replay --selector-match /matches --strategy ./new_strategies.yaml
    3. 批量导出历史数据
       python main.py replay --page-type ranking --format csv --output ./ranking_history.csv
    
    原理：
    1. 从 archive index 查询符合条件的 page
    2. 用当前 parser pipeline 重新解析
    3. 与新版本的 parse result 做 diff
    4. 输出统计报告（兼容性%、字段覆盖率%）
    """
    
    async def replay(
        self,
        page_type: str | None = None,
        url_pattern: str | None = None,
        date_range: tuple[str, str] | None = None,
        parser_version: str = "latest",
    ) -> ReplayReport: ...
```

### 10.4 Cache 层升级

当前三级缓存缺少一个重要功能：**有条件缓存**。

```
升级方向：
1. ETag-aware cache：响应带 ETag 时，缓存附带 ETag
   下次请求带上 If-None-Match，304 直接返回缓存
2. Stale-while-revalidate：
   缓存过期但网络不可用时，返回过期内容
3. 基于变更概率的 TTL：
   - ranking 页面：TTL=1800s（变化低频）
   - upcoming 页面：TTL=60s（变化中频）
   - live match 页面：TTL=15s（变化高频）
4. 预热机制：
   - scheduler 定时刷 ranking/results/upcoming
   - 用户请求时优先命中预热缓存
```

---

## 11. Task Orchestrator

### 11.1 当前问题

- 没有统一的 task 调度框架
- APScheduler 只做两件事：daily ranking snapshot + results archive
- 没有任务优先级
- 没有任务去重
- 没有实时任务触发

### 11.2 设计

```python
@dataclass
class Task:
    id: str
    task_type: TaskType  # POLL_LIVE, FETCH_URL, ARCHIVE, REPARSE, NOTIFY
    url: str | None
    priority: int       # 0-100, live match = 100, ranking = 30
    interval: float     # 轮询间隔
    max_retries: int
    status: TaskStatus
    created_at: float
    last_run: float | None
    metadata: dict

class TaskOrchestrator:
    """
    统一调度引擎，替代 APScheduler 的大部分职责。
    
    Task 类型：
    - FETCH: 单次抓取任务（带缓存优先级）
    - POLL: 定时轮询任务（live match tracking）
    - ARCHIVE: 定时归档任务（ranking snapshot, results archive）
    - REPARSE: 重解析任务（对 archive 数据）
    - NOTIFY: 通知任务（WebSocket push, webhook）
    
    调度策略：
    - 优先级队列：live match > upcoming > results > ranking > news > archive
    - 依赖调度：ranking archive 需要先 fetch ranking 页面
    - 自适应周期：POLL 任务根据变更频率动态调整 interval
    - 全局并发控制：配合 semaphore，不超过 max_concurrency
    
    去重机制：
    - URL-level dedup：5s 内相同 URL 不重复
    - Task-level dedup：相同 id 的 task 排队执行
    - 实时去重：live match 状态更新时取消 pending fetch
    """
    
    _task_queue: asyncio.PriorityQueue
    _running: dict[str, asyncio.Task]
    _dedup_cache: TTLCache[str, float]  # url → timestamp, TTL=5s
    
    def schedule(self, task: Task) -> str: ...
    def cancel(self, task_id: str) -> bool: ...
    async def run_loop(self): ...  # 主循环
    def get_status(self) -> dict: ...
```

### 11.3 Scheduler 整合

```python
class SchedulerService:
    """
    整合 APScheduler（定时任务）+ TaskOrchestrator（实时任务）。
    
    定时任务（cron-based，沿用 APScheduler）：
    - 06:00 ranking snapshot
    - 07:00 results archive
    - 08:00-23:00 每 30min upcoming 页面刷新
    - 每小时 news 刷新
    
    实时任务（event-driven，通过 TaskOrchestrator）：
    - Live match polling（比赛开始自动触发）
    - 用户请求触发的即时抓取（API/CLI）
    - 重解析任务
    
    资源管理：
    - 定时任务使用 "低优先级 burst" 模式
    - 实时任务使用 "高优先级" + "预留 20% concurrency"
    - CPU > 80% 时暂停非必要的定时任务
    """
```

---

## 12. 代码结构

### 12.1 目标目录结构

```
src/
├── core/                          # 新增：核心引擎
│   ├── __init__.py
│   ├── pipeline.py                # FetchPipeline
│   ├── orchestrator.py            # TaskOrchestrator
│   ├── scheduler_service.py       # SchedulerService (整合)
│   └── live_tracker.py            # LiveMatchTracker
│
├── transport/                     # 新增：传输层抽象
│   ├── __init__.py
│   ├── base.py                    # TransportSession, BaseTransport
│   ├── session_pool.py            # SessionPool
│   ├── pool/                      # 具体实现
│   │   ├── curl_pool.py           # CurlSessionPool
│   │   ├── httpx_pool.py          # HttpxSessionPool
│   │   └── playwright_pool.py     # PlaywrightContextPool
│   ├── fingerprint.py             # TLS指纹 + JA3 + H2 管理
│   └── identity.py                # SessionIdentity, HeaderProfile
│
├── proxy/                         # 新增：代理系统
│   ├── __init__.py
│   ├── rotator.py                 # ProxyRotator
│   ├── proxy.py                   # Proxy 模型
│   └── provider/                  # 代理源的适配器
│       ├── static.py              # 静态代理列表
│       └── file_provider.py       # 从文件加载代理
│
├── antibot/                       # 新增：反反爬
│   ├── __init__.py
│   ├── block_detector.py          # BlockDetector (多层检测)
│   ├── human_pattern.py           # HumanRequestPattern
│   ├── rate_limiter.py            # AdaptiveRateLimiter (重写)
│   └── header_profiles.py         # Header 组合策略
│
├── parser/                        # 重构：解析器引擎
│   ├── __init__.py
│   ├── pipeline.py                # ParserPipeline
│   ├── semantic.py                # SemanticParser, SelectorStrategy
│   ├── validator.py               # 校验规则
│   ├── enrichment.py              # 数据补全
│   └── strategies/                # 选中器策略定义（YAML）
│       ├── match_overview.yaml
│       ├── match_detail.yaml
│       ├── ranking.yaml
│       └── ...
│
├── storage/                       # 新增 + 整合：存储层
│   ├── __init__.py
│   ├── archive.py                 # HTMLArchive
│   ├── archive_index.py           # SQLite index
│   ├── cache.py                   # TieredCache (现有的，兼容升级)
│   └── replay.py                  # ReplayParser
│
├── client.py                      # 简化：只保留 HLTVClient facade
├── config.py                      # 扩展新配置项
├── parser.py                      # 保留，兼容旧 parser helper
│
├── endpoints/                     # 重构：简化 endpoint，使用新的 parser engine
├── models/                        # 不变
├── utils/                         # 保持现有，考虑把 retry extract 到 core
├── warehouse/                     # 保持现有
├── scheduler/                     # 简化，委托给 scheduler_service
├── security/                      # 保持不变
├── export/                        # 保持不变
├── monitor/                       # 保持不变
├── tracing/                       # 保持不变
└── plugins/                       # 保持不变
```

### 12.2 核心依赖关系

```
client.py → FetchPipeline → SessionPool
                          → ProxyRotator
                          → BlockDetector
                          → AdaptiveRateLimiter
                          → HTMLArchive
                          
TaskOrchestrator → LiveMatchTracker → FetchPipeline
                                         ↓
                                   ParserPipeline → HTMLArchive
                                                     ↓
                                               Warehouse
```

---

## 13. 实现路线图

### Phase 1: 基础架构重构（1-2 周）★★★★★ 最优先

任务：
1. 实现 `TransportSession` / `SessionPool`
   - 多 session 管理，独立 cookie/fingerprint
   - session 健康度评分和选择策略
   - 现有 client.py 中的 transport 逻辑迁移到 SessionPool
2. 实现 `BlockDetector` 多层检测
   - 封装现有的 block 检测逻辑
   - 增加 Level 3-5 检测
3. 实现 `AdaptiveRateLimiter` 重写
   - 滑动窗口替换固定整点
   - 智能调速算法
4. 实现 `HumanRequestPattern`
   - Burst 模式 + 休息模式

产出：
- 单 IP 下 session 存活时间提升 3-5x
- Block 检测率 > 99%
- 请求模式不再均匀可预测

### Phase 2: Fetch Pipeline & Archive（1 周）★★★★★

任务：
1. 实现 `FetchPipeline`
   - 生命周期管理
   - 统一的 Request/Response 模型
   - 多 transport 自动选择
2. 实现 `HTMLArchive`
   - append-only 存储
   - SQLite index
   - 存量抓取自动归档
3. 实现 `ETagTracker`

产出：
- 全量请求可回放
- 减少 304 响应流量 20-40%

### Phase 3: Parser Engine 2.0（1 周）★★★★

任务：
1. 实现 `SelectorStrategy`
   - YAML 定义 selector 策略
   - fallback 链
   - 命中率统计
2. 实现 `ParserPipeline`
   - Preprocess → Semantic → Validate → Enrich
3. 提取现有 endpoint 的 selector 策略到 YAML
4. 实现 `SelectorHealthReporter`
5. 实现 `ReplayParser`

产出：
- Selector 失效时自动 fallback，不丢数据
- 可离线重解析，验证 parser 兼容性

### Phase 4: Live Crawler Engine（1 周）★★★★

任务：
1. 实现 `LiveMatchTracker`
   - 从 /matches 发现 live match
   - 独立 polling 协程
   - Adaptive polling interval
2. 实现 `ChangeDetector`
   - content hash chain
   - 变更类型检测
3. 实现 `TaskOrchestrator`
   - 优先级队列
   - URL-level dedup
   - Task 生命周期管理

产出：
- Live match 秒级状态更新
- 无变更页面零请求浪费

### Phase 5: 反反爬强化（持续）★★★

任务：
1. `TLSFingerprintManager`
   - 多版本轮换
   - 自定义 JA3
2. `BrowserContextPool`
   - 持久 context
   - 模拟真人 browsing
3. `HeaderProfile` 组合策略
4. `Playwright Stealth Script` 升级
5. `ProxyRotator`（可选，无代理环境可跳过）

### Phase 6: API / CLI 适配（0.5 周）★★

任务：
1. 更新 `api.py` 使用新的 FetchPipeline
2. 更新 `cli.py` 增加新命令：
   - `python main.py archive list/stats/export`
   - `python main.py replay --page-type ranking --from 2026-01-01`
   - `python main.py validate-selectors`
   - `python main.py session stats`
   - `python main.py live watch <match_id>`
3. 增加 WebSocket 数据推送（live match 变更通知）

---

## 14. 关键技术决策清单

| 决策 | 选项 | 推荐 | 理由 |
|------|------|------|------|
| Session 数量 | 5-50 | 10-15 | 太少不够轮换，太多管理成本高且指纹多样性有限 |
| curl_cffi vs httpx 优先级 | curl 优先 / httpx 优先 | curl 优先 | curl_cffi 的 TLS 指纹模仿能力远超 httpx |
| Playwright Context 复用 | 每次新建 / 池化复用 | 池化 + 定时重建 | 新建太慢(500ms)，不重建会 leak |
| ETag 是否存储 | 内存 / 磁盘 | 磁盘(LevelDB) | 重启不丢失，跨 session 共享 |
| Archive 存储格式 | 压缩 / 纯文本 | gzip 压缩 | HLTV 页面平均 200KB，压缩后 ~40KB，大幅节省磁盘 |
| Archive 保留策略 | 永久 / TTL | 永久 + 可选清理 | 磁盘便宜，永久保留便于 replay |
| Selector 策略格式 | Python / YAML | YAML | 非开发者可编辑，CI 可 diff |
| 代理必要性 | 必须 / 可选 | 可选 | 单 IP 环境优先优化 session 管理，代理效果有限 |

### 14.1 为什么不做分布式

```
单 IP 环境下：
- 代理会引入额外延迟和稳定性问题
- HLTV 对代理 IP 的检测可能更严格（已知代理 IP 池）
- 代理的 TLS 连接质量不如直连
- 增加成本但收益不确定

升级重点应该在：
1. Session 管理 → 让单 IP 看起来像多个不同用户
2. Request Pattern → 更像真人行为
3. 智能限速 → 在 block 边缘精确控制
4. Change-driven → 减少无效请求

代理仅作为"紧急降级方案"：
当本地 IP 被 ban 时，用高质量住宅代理过渡
```

### 14.2 性能目标

| 指标 | 当前 | 目标 |
|------|------|------|
| 请求间隔 | 1.5-3s 均匀 | 0.5-2s burst + 30-90s rest，日均请求量不变 |
| Session 存活 | 不稳定，看运气 | 平均 > 72h 不被 ban |
| Block 检测率 | ~80% | > 99% |
| 实时性 | 手动 CLI | Live match < 15s 延迟 |
| 页面体积 | ~200KB 全量 | 平均 ~50KB (gzip) |
| 解析失败(selector 变化) | 数据丢失 | 自动 fallback，99%+ 可用 |
| 重复请求 | ~30% | < 5% (change-driven) |

---

## 总结：最核心的三件事

```
1. SessionPool（最多 session 轮换，独立的 fingerprint/cookie）
   → 解决"单 IP 长期存活"的核心问题

2. HumanRequestPattern（burst + rest 模式）
   → 解决"被检测为爬虫"的核心问题

3. ChangeDetector + LiveMatchTracker（变化驱动）
   → 解决"实时性"和"无效请求"的核心问题
```

这三件事相互独立，可以并行开发，且 Phase 1 全部覆盖。
