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
SEEN_IPS_FILE = "seen_ips.log"

# When True, the very first time the site is opened from a new IP address,
# a click on the link is triggered automatically (and logged) without any
# button press. Repeat visits from an already-seen IP do NOT auto-click.
AUTO_CLICK_NEW_IP = True

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ouo.io Live Auto-Clicker & Bypass</title>
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
        <h1><span class="live-indicator"></span>ouo.io Auto-Clicker & Bypass</h1>
        <p class="sub">Forces an active server click request on every check / opening sequence. On the first visit from a NEW IP, a click is fired &amp; logged automatically.</p>
        <div class="row">
            <div class="k">Visitor</div>
            <div class="v" id="visitor">Detecting IP...</div>
        </div>
        <div>
            <label>Shortened URL</label>
            <input id="urlInput" value="https://ouo.io/go/GEVWWP" placeholder="https://ouo.io/XXXXXX">
            <div class="controls">
                <button id="bypassBtn">Trigger Click & Bypass</button>
                <button id="autoBtn" class="secondary">Start Auto-Click Loop (Every 10s)</button>
            </div>
        </div>
        <div id="result" class="result">
            <div class="row"><div class="k">Original URL</div><div class="v" id="orig"></div></div>
            <div class="row"><div class="k">Working Entry Triggered</div><div class="v" id="working"></div></div>
            <div class="row"><div class="k">Resolved / Final URL <span id="timer" class="class-timer"></span></div><div class="v" id="final"></div></div>
            <div class="row"><div class="k">Status & Click Log</div><div class="v" id="status"></div></div>
            <details><summary>Debug Log</summary><pre id="log"></pre></details>
        </div>
        <p class="small">Powered by curl_cffi universal browser impersonation.</p>
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
        const visitorEl = document.getElementById('visitor');

        // Set server-side: whether this visit comes from a brand new IP
        const NEW_IP = {{ new_ip|tojson }};
        const USER_IP = {{ user_ip|tojson }};
        const AUTO_CLICK = {{ auto_click|tojson }};

        function getUrlFromQuery(){
            let s = window.location.search;
            if(!s) return null;
            let raw = s.slice(1);
            if(raw.startsWith('=')) raw = raw.slice(1);
            try{
                let p = new URLSearchParams(s);
                for(let k of ['url','u','link']){
                    if(p.has(k)){ let v = p.get(k); if(v) return v; }
                }
                if(p.has('')){ let v = p.get(''); if(v && v.startsWith('http')) return v; }
            }catch(e){}
            let m = (raw.match(/https?:\/\/[^\s&]+/)||[])[0];
            return m || (raw.startsWith('http') ? raw : null);
        }

        async function performBypass(isAuto = false) {
            const url = input.value.trim();
            if(!url) return;
            if(!isAuto) {
                btn.disabled = true;
                btn.textContent = 'Sending Click & Bypassing...';
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
                    btn.textContent = 'Trigger Click & Bypass';
                }
            }
        }

        btn.addEventListener('click', () => performBypass(false));

        autoBtn.addEventListener('click', () => {
            if(autoInterval) {
                clearInterval(autoInterval);
                autoInterval = null;
                autoBtn.textContent = 'Start Auto-Click Loop (Every 10s)';
                autoBtn.style.background = '#334155';
                timerEl.textContent = '';
            } else {
                performBypass(true);
                let countdown = 10;
                autoBtn.textContent = 'Stop Auto-Click Loop';
                autoBtn.style.background = '#ef4444';

                autoInterval = setInterval(() => {
                    countdown--;
                    timerEl.textContent = `Next click in ${countdown}s`;
                    if(countdown <= 0) {
                        performBypass(true);
                        countdown = 10;
                    }
                }, 1000);
            }
        });

        // ---- Automatic click on the very first visit from a NEW IP ----
        window.addEventListener('DOMContentLoaded', () => {
            const q = getUrlFromQuery();
            if(q) input.value = q;

            if(AUTO_CLICK) {
                visitorEl.textContent = USER_IP + ' - new IP detected, auto-click fired on open.';
                visitorEl.className = 'v status-success';
                statusEl.textContent = 'Auto-click: sending click for new IP ' + USER_IP + '...';
                resultDiv.classList.add('show');
                // wait briefly so the page paints, then send the click automatically
                setTimeout(() => performBypass(true), 600);
            } else if(NEW_IP) {
                visitorEl.textContent = USER_IP + ' - new IP detected (auto-click disabled on server).';
            } else {
                visitorEl.textContent = USER_IP + ' - already logged a click before, auto-click skipped for this visit.';
            }
        });
    </script>
</body>
</html>
"""

def get_user_ip():
    """Real visitor IP (first X-Forwarded-For hop when behind Render/proxy)."""
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'

def load_seen_ips():
    ips = set()
    try:
        with open(SEEN_IPS_FILE, "r") as f:
            for line in f:
                ip = line.strip()
                if ip:
                    ips.add(ip)
    except FileNotFoundError:
        pass
    return ips

def mark_ip_seen(ip):
    try:
        with open(SEEN_IPS_FILE, "a") as f:
            f.write(ip + "\n")
    except Exception:
        pass

# In-memory set of IPs that already got their automatic click,
# loaded from disk at startup and appended to the file as new IPs arrive.
SEEN_IPS = load_seen_ips()

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

        # Real browser impersonation profiles supported by curl-cffi 0.7.4
        for imp in ["chrome124", "chrome120", "safari17_0", "safari15_5", "edge101", "chrome110"]:
            d(f"Sending fresh click request via impersonation '{imp}'...")
            try:
                r = client.get(working_entry, impersonate=imp, timeout=15)
                is_cf = "Just a moment" in r.text
                if is_cf or r.status_code != 200:
                    d(f"    -> Blocked or status {r.status_code}, trying next profile")
                    continue

                soup = BeautifulSoup(r.text, 'lxml')
                token_el = soup.find('input', {'name':'_token'})
                if not token_el:
                    d("    -> Token not found, trying next profile")
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
                    d(f"SUCCESS: Click verified and processed via '{imp}'")
                    return {
                        "original_url": original_url,
                        "working_entry": working_entry,
                        "final_url": loc,
                        "status": f"CLICK SENT & RESOLVED via '{imp}' at {datetime.datetime.now().strftime('%H:%M:%S')}",
                        "debug_log": "\n".join(debug)
                    }
            except Exception as e:
                d(f"Error {imp}: {str(e)}")

        return {
            "original_url": original_url,
            "working_entry": working_entry,
            "final_url": None,
            "status": f"CLICK SENT, BUT FAILED REDIRECT (Cloudflare Block) at {datetime.datetime.now().strftime('%H:%M:%S')}",
            "debug_log": "\n".join(debug)
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "debug_log": traceback.format_exc()}

@app.route('/')
def index():
    ip = get_user_ip()
    ua = request.headers.get('User-Agent', '')
    new_ip = ip not in SEEN_IPS
    if new_ip:
        # First time this IP opens the site: remember it and log the
        # automatic click so it only happens once per IP.
        SEEN_IPS.add(ip)
        mark_ip_seen(ip)
        log_click(ip, 'AUTO-CLICK (first visit from new IP)', ua)
    auto_click = bool(new_ip and AUTO_CLICK_NEW_IP)
    return render_template_string(
        HTML_PAGE,
        new_ip=new_ip,
        user_ip=ip,
        auto_click=auto_click
    )

@app.route('/api/bypass', methods=['POST'])
def api_bypass():
    data = request.get_json() or {}
    url = data.get('url','').strip()
    if not url:
        return jsonify({"error":"No URL provided"}), 400
    ip = get_user_ip()
    ua = request.headers.get('User-Agent','')
    log_click(ip, url, ua)
    result = bypass_ouo_single(url)
    return jsonify(result)

@app.route('/logs')
def logs():
    if not os.path.exists(LOG_FILE):
        return "No clicks logged yet.", 200, {'Content-Type': 'text/plain'}
    with open(LOG_FILE, "r") as f:
        return f.read()[-20000:], 200, {'Content-Type': 'text/plain'}

@app.route('/ips')
def ips():
    return jsonify({
        "auto_click_new_ip": AUTO_CLICK_NEW_IP,
        "count": len(SEEN_IPS),
        "seen_ips": sorted(SEEN_IPS)
    })

@app.route('/debug-headers')
def debug_headers():
    """Dump what the proxy sends us - useful to check if the real visitor IP is forwarded."""
    return jsonify({
        "remote_addr": request.remote_addr,
        "headers": {k: v for k, v in request.headers.items()}
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
