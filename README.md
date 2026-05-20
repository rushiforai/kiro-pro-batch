# Kiro Pro Batch Tool

Kiro Pro/Pro+ 批量订阅自动化工具，支持 GitHub / Google / AWS Builder ID 三种登录方式。
## 个人的碎碎念
- 本来是想赚点钱的，奈何kiro天天杀卡，昨晚卡头从我拿卡到使用不超过4小时直接没了？？？？这我玩个蛋啊，硬是亏1100
- 别问我这东西怎么用，为啥这么多bug，本来就是主线程里拆出来的
- 如果你们有好的合并可以给我提交，完善一下
- 我是真干不动了，你们如果有自己发现百分百开通成功的卡的话可以研究一下子喔
- bug很多，逻辑不全，你们自己补一补，我懒得补了
## 功能

- 多登录方式：GitHub 纯协议登录、Google 浏览器自动化、Builder ID 注册
- 多开卡渠道：支持 3 种虚拟卡 API 接入
- Stripe 自动支付：BitBrowser 指纹浏览器 + YesCaptcha 打码
- Web 控制面板：Flask 实时状态监控
- 并发控制：线程池 + 窗口槽位管理
- 智能重试：拒卡换 IP、连续失败熔断

## 项目结构

```
├── config.py              # 全局配置（需自行填写）
├── main.py                # 主入口，批量编排
├── auth_github.py         # GitHub OAuth 纯协议登录
├── auth_google.py         # Google OAuth 浏览器自动化
├── auth_builderid.py      # AWS Builder ID 注册/登录
├── browser.py             # BitBrowser 指纹浏览器管理
├── card_api.py            # 虚拟卡开卡 API（多渠道）
├── kiro.py                # Kiro 订阅管理（CBOR/Smithy 协议）
├── proxy.py               # SOCKS5 代理管理 + 美国 IP 验活
├── storage.py             # 成功/失败账号持久化
├── stripe_pay.py          # Stripe Checkout 自动填卡支付
├── web_ui.py              # Flask Web 控制面板
├── templates/index.html   # Web UI 前端
└── extensions/yescaptcha/ # YesCaptcha 浏览器插件（需自行放置）
```

## 依赖

```
pip install requests cbor2 pyotp DrissionPage flask urllib3
```

## 外部依赖

- [BitBrowser](https://www.bitbrowser.net/) - 指纹浏览器（需本地运行）
- SOCKS5 代理服务（需支持美国 IP）
- 虚拟卡 API（需自行对接）
- YesCaptcha 浏览器插件（用于 hCaptcha 打码）

## 使用

1. 复制 `config.py`，填入你的代理、开卡 API 等配置
2. 准备账号文件，格式：
   - GitHub: `用户名----密码----TOTP密钥`
   - Google: `邮箱----密码----TOTP密钥`
   - Builder ID: `邮箱----接码链接`
3. 启动 Web UI: `python web_ui.py`
4. 或直接命令行: `python main.py`

## 配置说明

编辑 `config.py`：

| 配置项 | 说明 |
|--------|------|
| SUBSCRIPTION_PLAN | 订阅套餐 "pro" 或 "pro+" |
| CARD_CHANNEL | 开卡渠道 "10r" / "3r" / "huakai" |
| MAX_WORKERS | 并发线程数 |
| ACCOUNTS_PER_CARD | 每张卡分配几个号 |
| PROXY_* | 代理配置 |
| CARD_API_* | 开卡 API 配置 |

## 免责声明

本项目仅供学习研究使用，请遵守相关服务条款。
