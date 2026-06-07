# Kiro Pro Batch Tool

Kiro Pro/Pro+ batch subscription automation tool supporting three login methods: GitHub / Google / AWS Builder ID.

## Features

- Multiple login methods: GitHub pure protocol login, Google browser automation, Builder ID registration
- Multiple card channels: Support 3 virtual card API integrations
- Stripe auto payment: BitBrowser fingerprint browser + YesCaptcha captcha solving
- Web control panel: Flask real-time status monitoring
- Concurrent control: Thread pool + window slot management
- Smart retry: Reject card with IP switching, consecutive failure circuit breaker

## Project Structure

```
├── config.py              # Global configuration (fill in yourself)
├── main.py                # Main entry, batch orchestration
├── auth_github.py         # GitHub OAuth pure protocol login
├── auth_google.py         # Google OAuth browser automation
├── auth_builderid.py      # AWS Builder ID registration/login
├── browser.py             # BitBrowser fingerprint browser management
├── card_api.py            # Virtual card opening API (multi-channel)
├── kiro.py                # Kiro subscription management (CBOR/Smithy protocol)
├── proxy.py               # SOCKS5 proxy management + US IP verification
├── storage.py             # Success/failure account persistence
├── stripe_pay.py          # Stripe Checkout auto card payment
├── web_ui.py              # Flask Web control panel
├── templates/index.html   # Web UI frontend
└── extensions/yescaptcha/ # YesCaptcha browser plugin (place yourself)
```

## Dependencies

```
pip install requests cbor2 pyotp DrissionPage flask urllib3
```

## External Dependencies

- [BitBrowser](https://www.bitbrowser.net/) - Fingerprint browser (needs local execution)
- SOCKS5 proxy service (needs to support US IPs)
- Virtual card API (needs custom integration)
- YesCaptcha browser plugin (for hCaptcha solving)

## Usage

1. Copy `config.py` and fill in your proxy, card API and other configurations
2. Prepare account file with format:
   - GitHub: `username----password----TOTP_key`
   - Google: `email----password----TOTP_key`
   - Builder ID: `email----code_link`
3. Start Web UI: `python web_ui.py`
4. Or command line: `python main.py`

## Configuration

Edit `config.py`:

| Config Item | Description |
|--------|------|
| SUBSCRIPTION_PLAN | Subscription plan "pro" or "pro+" |
| CARD_CHANNEL | Card channel "10r" / "3r" / "huakai" |
| MAX_WORKERS | Concurrent thread count |
| ACCOUNTS_PER_CARD | Accounts per card |
| PROXY_* | Proxy configuration |
| CARD_API_* | Card API configuration |

## Disclaimer

This project is for learning and research purposes only. Please comply with relevant service terms.
