"""
Global Configuration - All modifiable parameters are centralized here
"""

# ── Kiro Configuration ──
KIRO_BASE = "https://app.kiro.dev"

# Subscription plan: "pro" or "pro+"
SUBSCRIPTION_PLAN = "pro+"

# ── Card Channel Selection ──
# "10r" = 10 yuan per card (batch card opening API)
# "3r"  = 3 yuan per card (key_id from database/3r_cards.txt)
# "huakai" = HuaKai cards (credentials from database/huakai_cards.txt)
CARD_CHANNEL = "10r"

# ── HuaKai Card API ──
CARD_HUAKAI_API = "https://your-card-api.example.com/api/redeem"

# ── Card Opening API (10r channel) ──
CARD_API_URL = "https://your-card-api.example.com/api/user/open_card.php"
CARD_API_LOGIN_URL = "https://your-card-api.example.com/api/auth.php"
CARD_API_USERNAME = "your_username"
CARD_API_PASSWORD = "your_password"
CARD_API_TOKEN = ""
CARD_API_COOKIE = "server_name_session=your_session_cookie"

# ── Card Opening API (3r channel) ──
CARD_3R_API = "http://your-3r-api.example.com:7890/api/keys/query"

# ── BitBrowser ──
BITBROWSER_API = "http://127.0.0.1:54345"

# ── Proxy ──
PROXY_HOST = "your-proxy.example.com"
PROXY_PORT = 2312
PROXY_USER = "your_proxy_user"
PROXY_PASS = "your_proxy_pass"

# ── Concurrency Control ──
MAX_WORKERS = 8
THREAD_START_DELAY = 3  # seconds (proxy rate limit: 10 concurrent per second)
ACCOUNTS_PER_CARD = 2   # number of accounts per card (1=one-to-one, 2=one-to-two)

# ── Debug Card (used when less than 10 accounts) ──
DEBUG_CARD = {"number": "4111111111111111", "expiry": "1226", "cvv": "123"}
