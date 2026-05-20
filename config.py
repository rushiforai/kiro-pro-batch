"""
全局配置 - 所有可修改的参数集中在这里
"""

# ── Kiro 配置 ──
KIRO_BASE = "https://app.kiro.dev"

# 订阅套餐: "pro" 或 "pro+"
SUBSCRIPTION_PLAN = "pro+"

# ── 开卡渠道选择 ──
# "10r" = 10块一张（批量开卡API）
# "3r"  = 3块一张（key_id 从 shujuku/3r卡.txt 取）
# "huakai" = 华开卡（卡密从 shujuku/华开卡.txt 取）
CARD_CHANNEL = "10r"

# ── 华开卡 API ──
CARD_HUAKAI_API = "https://your-card-api.example.com/api/redeem"

# ── 开卡 API (10r渠道) ──
CARD_API_URL = "https://your-card-api.example.com/api/user/open_card.php"
CARD_API_LOGIN_URL = "https://your-card-api.example.com/api/auth.php"
CARD_API_USERNAME = "your_username"
CARD_API_PASSWORD = "your_password"
CARD_API_TOKEN = ""
CARD_API_COOKIE = "server_name_session=your_session_cookie"

# ── 开卡 API (3r渠道) ──
CARD_3R_API = "http://your-3r-api.example.com:7890/api/keys/query"

# ── BitBrowser ──
BITBROWSER_API = "http://127.0.0.1:54345"

# ── 代理 ──
PROXY_HOST = "your-proxy.example.com"
PROXY_PORT = 2312
PROXY_USER = "your_proxy_user"
PROXY_PASS = "your_proxy_pass"

# ── 并发控制 ──
MAX_WORKERS = 8
THREAD_START_DELAY = 3  # 秒（代理每秒10并发限制）
ACCOUNTS_PER_CARD = 2   # 每张卡分配几个号（1=一卡一号，2=一卡两号）

# ── 调试卡（少于10个号时使用） ──
DEBUG_CARD = {"number": "4111111111111111", "expiry": "1226", "cvv": "123"}
