import os
import time
import datetime
from flask import Flask, request, jsonify, render_template_string
from urllib.parse import urlparse

try:
    from curl_cffi import requests as cffi_requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError as e:
    HAS_DEPS = False
    print(f"Missing dependencies: {e}")

app = Flask(__name__)
LOG_FILE = "clicks.log"

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ouo.io Render Live Bypass</title>
    <style>
        *{box-sizing:border-box;margin:0;padding:0}
        body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
        .card{background:#1e293b;border:1px solid #334155;border-radius:16px;max-width:720px;width:100%;padding:28px;box-shadow:0 20px 40px rgba(0,0,0,.4)}
        h1{font-size:24px;margin-bottom:6px;color:#f8fafc}
        p.sub{color:#94a3b8;font-size:14px;margin-bottom:20px;line-height:1.5}
        label{font-size:13px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:8px}
        input{width:100%;background:#0f172a;border:1px solid #334155;border-radius:10px;padding:14px 16px;color:#f1f5f9;font-size:15px;outline:none}
        input:focus{border-color:#38bdf8;box-shadow:0 0 0 3px rgba(56,189,248,.2)}
        .controls{display:flex;gap:10px;margin-top:16px}
        button{flex:1;background:#38bdf8;color:#0f172a;border:none;border-radius:10px;padding:14px;font-weight:700;font-size:15px;cursor:pointer;transition:.2s}
        button:hover{background:#7dd3fc}
        button.secondary{background:#334155;color:#f8fafc}
        button.secondary:hover{background:#475569}
        button:disabled{opacity:.6;cursor:not-allowed}
        .result{margin-top:22px;background:#0f172a;border:1px solid #334155;border-radius:12px;padding:16px;display:none}
        .result.show{display:block}
        .row{margin-bottom:12px}
        .row .k{font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.5px}
        .row .v{font-size:14px;margin-top:4px;word-break:break-all;color:#e2e8f0}
        .row .v a{color:#38bdf8}
        .status-success{color:#4ade80}
        .status-fail{color:#f87171}
        .small{font-size:12px;color:#64748b;margin-top:16px;text-align:center}
        details{margin-top:16px}
        summary{cursor:pointer;color:#94a3b8;font-size:13px}
        pre{background:#020617;padding:12px;border-radius:8px;font-size:12px;overflow:auto;max-height:200px;margin-top:8px;color:#cbd5e1}
        .live-indicator{display:inline-block;width:8px;height:8px;background:#4ade80;border-radius:50%;margin-right:6px;box-shadow:0 0 8px #4ade80}
        .class-timer{font-size:12px;color:#38bdf8;float:right}
    </style>
</head>
<body>
    <div class="card">
        <h1><span class="live-indicator"></span>ouo.io Render Live Bypass</h1>
        <p class="sub">Hosted on Render. Use auto-check mode to loop and test status changes continuously.</p>
        <div>
            <label>Shortened URL</label>
            <input id="urlInput" value="https://ouo.io/go/GEVWWP" placeholder="https://ouo.io/XXXXXX">
            <div class="controls">
                <button id="bypassBtn">Bypass Once</button>
                <button id="autoBtn" class="secondary">Start Auto-Check (Every 10s)</button>
            </div>
        </div>
        <div id="result" class="result">
            <div class="row"><div class="k">Original URL</div><div class="v" id="orig"></div></div>
            <div class="row"><div class="k">Working Entry</div><div class="v" id="working"></div></div>
            <div class="row"><div class="k">Resolved / Final URL <span id="timer" class="class-timer"></span></div><div class="v" id="final"></div></div>
            <div class="row"><div class="k">Status</div><div class="v" id="status"></div></div>
            <details><summary>Debug Log</summary><pre id="log"></pre></details>
        </div>
        <p class="small">Powered by curl_cffi & Render Cloud Hosting.</p>
    </div>

    <script>
        let autoInterval = null;
        const btn = document.getElementById('bypassBtn');
        const autoBtn = document.getElementById('autoBtn');
        const input = document.getElementById('urlInput');
        const resultDiv = document.getElementById('result');
        const origEl = document.getElementById('orig');
        const workingEl = document.getElementById('working');
        const finalEl = document.getElementById('final');
        const statusEl = document.getElementById('status');
        const logEl = document.getElementById('log');
        const timerEl = document.getElementById('timer');

        async function performBypass(isAuto = false) {
            const url = input.value.trim();
            if(!url) return;
            if(!isAuto) {
                btn.disabled = true;
                btn.textContent = 'Bypassing...';
            }
            try {
                const res = await fetch('/api/bypass', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({url})
                });
                const data = await res.json();
                origEl.textContent = data.original_url || url;
                workingEl.textContent = data.working_entry || 'N/A';
                
                if(data.final_url){
                    finalEl.innerHTML = `<a href="${data.final_url}" target="_blank">${data.final_url}</a>`;
                } else {
                    finalEl.textContent = 'None - link expired or blocked';
                }
                statusEl.textContent = data.status || '';
                statusEl.className = 'v ' + (data.final_url ? 'status-success' : 'status-fail');
                logEl.textContent = data.debug_log || data.debug || '';
                resultDiv.classList.add('show');
            } catch(e) {
                if(!isAuto) logEl.textContent = 'Error: ' + e.message;
            } finally {
                if(!isAuto) {
                    btn.disabled = false;
                    btn.textContent = 'Bypass Once';
                }
            }
        }

        btn.addEventListener('click', () => performBypass(false));

        autoBtn.addEventListener('click', () => {
            if(autoInterval) {
                clearInterval(autoInterval);
                autoInterval = null;
                autoBtn.textContent = 'Start Auto-Check (Every 10s)';
                autoBtn.style.background = '#334155';
                timerEl.textContent = '';
            } else {
                performBypass(true);
                let countdown = 10;
                autoBtn.textContent = 'Stop Auto-Check';
                autoBtn.style.background = '#ef4444';
                
                autoInterval = setInterval(() => {
                    countdown--;
                    timerEl.textContent = `Next check in ${countdown}s`;
                    if(countdown <= 0) {
                        performBypass(true);
                        countdown = 10;
                    }
                }, 1000);
            }
        });
    </script>
</body>
</html>
"""

def log_click(ip, path, ua):
    ts = datetime.datetime.utcnow().isoformat()
    entry = f"{ts} | IP={ip} | Path={path} | UA={ua[:80]}\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(entry)
    except:
        pass

def bypass_ouo_single(original_url):
    debug = []
    def d(msg):
        debug.append(msg)
    
    try:
        p = urlparse(original_url)
        if "ouo.io" not in p.netloc and "ouo.press" not in p.netloc:
            return {"error": "URL must be ouo.io or ouo.press", "debug_log": "\n".join(debug)}
        
        id_ = original_url.split('/')[-1].split('?')[0]
        if not id_:
            return {"error": "Could not extract ID", "debug_log": "\n".join(debug)}
            
        working_entry = f"https://ouo.io/{id_}"
        if not HAS_DEPS:
            return {"error": "Missing dependencies", "debug_log": "\n".join(debug)}
            
        client = cffi_requests.Session()
        client.headers.update({
            'authority': 'ouo.io',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'accept-language': 'en-US,en;q=0.9',
            'referer': 'http://www.google.com/ig/adde?moduleurl=',
            'upgrade-insecure-requests': '1',
        })
        
        for imp in ["safari18_0", "safari15_5", "chrome133a"]:
            d(f"Trying impersonation {imp}...")
            try:
                r = client.get(working_entry, impersonate=imp, timeout=15)
                is_cf = "Just a moment" in r.text
                if is_cf or r.status_code != 200:
                    continue
                    
                soup = BeautifulSoup(r.text, 'lxml')
                token_el = soup.find('input', {'name':'_token'})
                if not token_el:
                    continue
                
                _token = token_el.get('value')
                x_token_el = soup.find('input', {'name':'x-token'})
                x_token = x_token_el.get('value') if x_token_el else None
                cf_el = soup.find('input', {'name':'cf-turnstile-response'})
                cf_token = cf_el.get('value') if cf_el else None
                
                data = {'_token': _token}
                if x_token: data['x-token'] = x_token
                if cf_token: data['cf-turnstile-response'] = cf_token
                
                go_url = f"https://ouo.io/go/{id_}"
                client.post(go_url, data=data, impersonate=imp, allow_redirects=False, timeout=15, headers={'content-type':'application/x-www-form-urlencoded'})
                
                x_url = f"https://ouo.io/xreallcygo/{id_}"
                r3 = client.post(x_url, data=data, impersonate=imp, allow_redirects=False, timeout=15, headers={'content-type':'application/x-www-form-urlencoded'})
                loc = r3.headers.get('Location')
                
                if loc:
                    return {
                        "original_url": original_url,
                        "working_entry": working_entry,
                        "final_url": loc,
                        "status": f"SUCCESS via {imp} at {datetime.datetime.now().strftime('%H:%M:%S')}",
                        "debug_log": "\n".join(debug)
                    }
            except Exception as e:
                d(f"Error {imp}: {str(e)}")
                
        return {
            "original_url": original_url,
            "working_entry": working_entry,
            "final_url": None,
            "status": f"FAILED (Cloudflare or token challenge block) at {datetime.datetime.now().strftime('%H:%M:%S')}",
            "debug_log": "\n".join(debug)
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "debug_log": traceback.format_exc()}

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/api/bypass', methods=['POST'])
def api_bypass():
    data = request.get_json() or {}
    url = data.get('url','').strip()
    if not url:
        return jsonify({"error":"No URL provided"}), 400
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    ua = request.headers.get('User-Agent','')
    log_click(ip, url, ua)
    result = bypass_ouo_single(url)
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
