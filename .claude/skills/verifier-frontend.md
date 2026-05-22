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
