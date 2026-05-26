# Frontend Visual Verifier

Use this skill to take screenshots of the running app and verify pages visually. Works on this machine despite AVG SSL interception.

## Prerequisites

- Playwright Python library: already installed in the `geo` conda env
- Chromium binary: already at `C:/Users/szymo/AppData/Local/ms-playwright/chromium-1208/chrome-win64/chrome.exe`
- **Do NOT run `playwright install`** — the headless-shell download fails due to AVG SSL interception. Use the full Chromium binary via `executable_path` instead.

## Starting the app

Backend (port 8000):
```powershell
cd d:/MOJE/DATA_SCIENCE/INVESTMENT_APP/investor_intelligence
C:/Users/szymo/anaconda3/envs/geo/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Frontend (port 5173):
```powershell
cd frontend
npm run dev
```

If port 8000 is already in use, find the PID and kill it:
```bash
netstat -ano | grep ":8000" | grep LISTENING   # shows PID
taskkill //F //PID <PID>
```

## Taking screenshots

```python
from playwright.sync_api import sync_playwright
import time, os

CHROMIUM = 'C:/Users/szymo/AppData/Local/ms-playwright/chromium-1208/chrome-win64/chrome.exe'
OUT = 'C:/Users/szymo/AppData/Local/Temp/'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
    page = browser.new_page(viewport={'width': 1280, 'height': 900})

    # Collect JS errors
    errors = []
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)

    # Log in via dev mode (bypasses Google OAuth)
    page.goto('http://localhost:5173/login', wait_until='networkidle', timeout=20000)
    page.click('button:has-text("Tryb deweloperski")')   # Polish UI
    page.wait_for_url('**/dashboard', timeout=10000)
    time.sleep(2)

    # Navigate and screenshot
    pages_to_check = [
        ('http://localhost:5173/dashboard',    'dashboard.png'),
        ('http://localhost:5173/decision',     'decision.png'),
        ('http://localhost:5173/ml',           'ml_hub.png'),
        ('http://localhost:5173/ml/hmm',       'ml_hmm.png'),
        ('http://localhost:5173/ml/cape',      'ml_cape.png'),
        ('http://localhost:5173/ml/recession', 'ml_recession.png'),
        ('http://localhost:5173/ml/volatility','ml_vol.png'),
        ('http://localhost:5173/ml/regime-duration', 'ml_km.png'),
        ('http://localhost:5173/ml/fx',        'ml_fx.png'),
        ('http://localhost:5173/ml/pca',       'ml_pca.png'),
    ]

    for url, fname in pages_to_check:
        page.goto(url, wait_until='networkidle', timeout=20000)
        time.sleep(3)   # wait for Recharts data fetch + render
        page.screenshot(path=OUT + fname, full_page=True)
        print('OK:', fname)

    browser.close()
    # Filter out known noise (favicon 404, dev-mode 405s)
    real_errors = [e for e in errors if 'favicon' not in e.lower() and '404' not in e and '405' not in e]
    print('JS errors:', real_errors if real_errors else 'none')

# Delete screenshots after Claude reads them
for _, fname in pages_to_check:
    os.remove(OUT + fname)
```

## Mobile device emulation

Chrome DevTools' "device toolbar" is just viewport + `isMobile` + `hasTouch` + a mobile UA. Playwright exposes the same via `browser.new_context(...)`. Use this to catch layout overflow, tap-target spacing, and mobile-only stylesheet branches.

Presets (match common real devices):

```python
DEVICES = {
    'iphone14':  {'viewport': {'width': 390, 'height': 844},
                  'device_scale_factor': 3, 'is_mobile': True, 'has_touch': True,
                  'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
                                'AppleWebKit/605.1.15 (KHTML, like Gecko) '
                                'Version/17.0 Mobile/15E148 Safari/604.1'},
    'pixel7':    {'viewport': {'width': 412, 'height': 915},
                  'device_scale_factor': 2.625, 'is_mobile': True, 'has_touch': True,
                  'user_agent': 'Mozilla/5.0 (Linux; Android 13; Pixel 7) '
                                'AppleWebKit/537.36 (KHTML, like Gecko) '
                                'Chrome/120.0.0.0 Mobile Safari/537.36'},
}
```

Usage — `new_context()` (not `new_page()`) because mobile flags must be set at context level:

```python
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
    ctx = browser.new_context(**DEVICES['iphone14'])
    page = ctx.new_page()
    # ...login + navigate + screenshot as usual...
    ctx.close()
```

Mobile-specific things to look for in screenshots:
- Horizontal scroll (any page wider than viewport = bug)
- Navbar collapse / hamburger behavior
- Recharts: do legends wrap? Are X-axis labels readable?
- Tap targets: buttons/links should be ≥ 44px tall
- Tables: should either scroll horizontally inside a container or stack vertically
- Modal/dialog widths (Portfolio transaction form, Excel upload preview)

Note: Playwright's Chromium with a mobile UA still uses **Blink**, not WebKit. iOS Safari-specific bugs (100vh, scroll bounce, input zoom on focus) will NOT show up. For those, real devices are needed.

## Reading screenshots in Claude

After the script runs, read each file with the Read tool (Claude can see images):
```
Read: C:/Users/szymo/AppData/Local/Temp/ml_hub.png
```

## Known noise / non-issues

- `405 Method Not Allowed` on some `/auth/...` requests at startup — dev-mode auth flow, benign
- `404 Not Found` for favicon — harmless
- Emoji in `print()` statements will cause `UnicodeEncodeError` on cp1250 terminal — use ASCII in print statements inside Playwright scripts

## Always delete screenshots after reading

Screenshots live in `C:/Users/szymo/AppData/Local/Temp/` — delete after Claude reads them:
```python
import os
os.remove('C:/Users/szymo/AppData/Local/Temp/ml_hub.png')
```
Or in bulk: `del C:\Users\szymo\AppData\Local\Temp\ml_*.png`
