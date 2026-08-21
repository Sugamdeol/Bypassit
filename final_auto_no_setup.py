"""
FINAL AUTO BYPASS - Just open link, logs a VIEW in ouo.io from USER IP. NO REDIRECT.
Single file for Render free tier

How it works (no bookmarklet, no extension, just open link):
1. User opens https://bypassit-1.onrender.com/?url=https://ouo.io/go/GEVWWP
   or https://bypassit-1.onrender.com/?=https://ouo.io/go/GEVWWP
   or just the bare site (uses the default link).
2. On the first visit from a NEW IP, the page fires the ouo.io click directly
   from the visitor's browser (hidden iframe POST to ouo.io/xreallcygo/ID) so
   ouo.io sees the visitor's real IP and counts the view in its dashboard.
3. The view is logged to clicks.log. The page does NOT redirect anywhere.

NEW: one automatic click per NEW IP.
The first time a brand-new IP opens the link, the click is fired automatically and
logged in clicks.log. Repeat visits from the same IP do NOT auto-click (manual
log button shown instead) so each IP counts exactly once.

Deploy: render.yaml already points to render_client_ip_bypass_fixed.py, change to this file or rename to that
"""
import os, re, datetime
from flask import Flask, request, redirect, jsonify, render_template_string

try:
    from curl_cffi import requests as cffi_requests
    from bs4 import BeautifulSoup
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

app = Flask(__name__)
LOG_FILE = "clicks.log"
SEEN_IPS_FILE = "seen_ips.log"

# Link used when the page is opened without ?url= / ?= param
DEFAULT_URL = "https://ouo.io/go/GEVWWP"

# When True, the first visit from a NEW IP automatically fires (and logs) a click.
# Repeat visits from an already-seen IP do NOT auto-click.
AUTO_CLICK_NEW_IP = True

HTML = """
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Auto Bypass - Just Open Link</title>
<style>
body{font-family:system-ui;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:14px}
.card{background:#1e293b;border:1px solid #334155;border-radius:16px;padding:22px;max-width:640px;width:100%;text-align:center}
h1{font-size:18px} p{font-size:12px;color:#94a3b8;margin-top:8px;line-height:1.6}
input{width:100%;background:#020617;border:1px solid #334155;border-radius:10px;padding:12px;color:#f1f5f9;margin-top:10px}
button{width:100%;background:#38bdf8;color:#0f172a;border:none;border-radius:10px;padding:12px;font-weight:700;margin-top:10px;cursor:pointer}
a{color:#38bdf8} code{font-size:11px;background:#020617;padding:2px 6px;border-radius:4px}
.loader{margin:14px auto;width:26px;height:26px;border:3px solid #334155;border-top-color:#38bdf8;border-radius:50%;animation:spin 0.8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.badge{display:inline-block;border:1px solid #334155;background:#020617;border-radius:20px;padding:2px 8px;font-size:10px;color:#94a3b8;margin:2px}
</style>
</head><body>
<div class="card">
<h1>Auto Bypass — Just Open Link</h1>
<p>No setup, no bookmarklet, no extension. Just open link and it logs from <b>YOUR IP</b>.</p>
<p id="visitor" style="font-size:11px;color:#64748b"></p>
<input id="urlInput" value="{{ default_url }}" placeholder="https://ouo.io/go/XXXX">
<button id="manualBtn" type="button">Log View (No Redirect)</button>
<div class="loader" id="loader"></div>
<p id="status">Detecting link from URL...</p>
<p><code id="orig"></code></p>
<p id="info" style="font-size:11px;color:#64748b;margin-top:10px"></p>
</div>
<script>
const NEW_IP = {{ new_ip|tojson }};
const USER_IP = {{ user_ip|tojson }};
const AUTO_CLICK = {{ auto_click|tojson }};
const DEFAULT_URL = {{ default_url|tojson }};
const HAD_QUERY_URL = {{ had_query_url|tojson }};

function getUrlFromQuery(){
  let s = window.location.search;
  if(!s) return null;
  let raw = s.slice(1);
  if(raw.startsWith('=')) raw = raw.slice(1);
  try{
    let p = new URLSearchParams(s);
    for(let k of ['url','u','link']){
      if(p.has(k)) return decodeURIComponent(p.get(k));
    }
    if(p.has('')){let v=p.get(''); if(v&&v.startsWith('http')) return v;}
  }catch(e){}
  let m = (raw.match(/https?:\/\/[^\s&]+/)||[])[0];
  return m || (raw.startsWith('http')?raw:null);
}

function extractId(url){
  try{
    let clean = url.split('?')[0].split('#')[0];
    let parts = clean.split('/').filter(Boolean);
    let id = parts[parts.length-1];
    if(id==='go') id = parts[parts.length-2]||'';
    return id;
  }catch(e){ return null; }
}

// Fire the ouo.io click FROM THE VISITOR'S OWN BROWSER (their IP) via a
// hidden iframe. This is the request ouo.io counts in its dashboard.
// No page navigation happens - the view is just logged.
function fireOuoClick(url){
  return new Promise((resolve, reject)=>{
    let id = extractId(url);
    if(!id){ return reject(new Error('Could not extract ouo ID from ' + url)); }
    let iframe = document.createElement('iframe');
    iframe.name = 'ouoclick';
    iframe.style.display = 'none';
    document.body.appendChild(iframe);
    let form = document.createElement('form');
    form.method = 'POST';
    form.action = `https://ouo.io/xreallcygo/${id}`;
    form.target = 'ouoclick';
    form.innerHTML = '<input type="hidden" name="_token" value="">';
    document.body.appendChild(form);
    form.submit();
    // ouo.io responds with a 302 inside the iframe - we never navigate the page
    setTimeout(()=>resolve(id), 2500);
    setTimeout(()=>{ iframe.remove(); form.remove(); }, 4000);
  });
}

// Just log the view on our server - NO redirect, NO bypass navigation.
function logView(url, reason){
  fetch('/api/log', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({url: url, reason: reason})
  }).catch(()=>{});
}

function runAuto(url){
  document.getElementById('orig').textContent = url;
  document.getElementById('status').textContent = `Logging view for ${url} from YOUR IP (${USER_IP})...`;
  fireOuoClick(url)
    .then((id)=>{
      document.getElementById('loader').style.display = 'none';
      document.getElementById('status').textContent = `View logged in ouo.io for link ${id} from YOUR IP. No redirect.`;
      document.getElementById('info').textContent = `Click sent to ouo.io/xreallcygo/${id} from your browser (your IP). Your view is logged - you were not redirected anywhere.`;
      logView(url, 'auto');
    })
    .catch((e)=>{
      document.getElementById('loader').style.display = 'none';
      document.getElementById('status').textContent = 'Error: ' + e.message;
    });
}

window.addEventListener('DOMContentLoaded', ()=>{
  let url = getUrlFromQuery();
  if(!url) url = DEFAULT_URL;
  document.getElementById('urlInput').value = url;
  document.getElementById('visitor').textContent = 'Your IP: ' + USER_IP + (NEW_IP ? ' (NEW)' : ' (already logged before)');
  document.getElementById('manualBtn').addEventListener('click', ()=>{
    let u = document.getElementById('urlInput').value.trim();
    document.getElementById('loader').style.display = 'block';
    fireOuoClick(u)
      .then((id)=>{
        document.getElementById('loader').style.display = 'none';
        document.getElementById('status').textContent = `View logged in ouo.io for ${id} from YOUR IP. No redirect.`;
        logView(u, 'manual');
      })
      .catch((e)=>{
        document.getElementById('loader').style.display = 'none';
        document.getElementById('status').textContent = 'Error: ' + e.message;
      });
  });

  if(AUTO_CLICK){
    // First visit from this IP → fire the click automatically (once per IP)
    document.getElementById('status').textContent = `New IP ${USER_IP} detected — logging view automatically...`;
    runAuto(url);
  } else if(!NEW_IP){
    // IP already logged a click → do NOT auto-click again, offer manual re-run
    document.getElementById('loader').style.display = 'none';
    document.getElementById('status').textContent = `IP ${USER_IP} already logged a click — auto-click skipped this visit. Use the button to log again.`;
  } else {
    document.getElementById('loader').style.display = 'none';
    document.getElementById('status').textContent = 'Auto-click is disabled on the server. Use the button.';
  }
});
</script>
</body></html>
"""

def log_click(ip, url):
    ts = datetime.datetime.utcnow().isoformat()
    entry = f"{ts} | IP={ip} | URL={url}\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(entry)
    except:
        pass

def get_user_ip():
    # Render sets X-Forwarded-For to real user IP
    xff = request.headers.get('X-Forwarded-For','')
    if xff:
        # XFF can be list, first is user IP
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

# IPs that already got their one automatic click (persisted to disk)
SEEN_IPS = load_seen_ips()

def bypass_with_user_ip(original_url, user_ip):
    """Do bypass from server but spoof user IP via headers so ouo.io logs user IP"""
    if not HAS_CFFI:
        return {"error": "curl_cffi missing", "final_url": None}

    # Extract ID
    try:
        id_ = original_url.split('/')[-1].split('?')[0]
        if id_ == 'go' or not id_:
            parts = [p for p in original_url.split('/') if p]
            id_ = parts[-1] if parts else ''
    except:
        return {"error":"Invalid URL"}

    entry_url = f"https://ouo.io/{id_}"
    go_url = f"https://ouo.io/go/{id_}"
    x_url = f"https://ouo.io/xreallcygo/{id_}"

    client = cffi_requests.Session()
    # Spoof user IP so ouo.io logs user IP not Render IP
    client.headers.update({
        'authority': 'ouo.io',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9',
        'referer': 'http://www.google.com/ig/adde?moduleurl=',
        'upgrade-insecure-requests': '1',
        'X-Forwarded-For': user_ip,
        'X-Real-IP': user_ip,
        'CF-Connecting-IP': user_ip,
        'True-Client-IP': user_ip,
        'Forwarded': f'for={user_ip}',
        'X-Forwarded-Proto': 'https',
    })

    # Try impersonations
    for imp in ["safari18_0", "safari15_5", "chrome133a", "chrome131"]:
        try:
            # GET entry
            r = client.get(entry_url, impersonate=imp, timeout=10)
            if "Just a moment" in r.text or r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'lxml')
            token_el = soup.find('input', {'name':'_token'})
            if not token_el:
                continue
            token = token_el.get('value')
            x_el = soup.find('input', {'name':'x-token'})
            x_token = x_el.get('value') if x_el else None
            cf_el = soup.find('input', {'name':'cf-turnstile-response'})
            cf_token = cf_el.get('value') if cf_el else None

            data = {'_token': token}
            if x_token:
                data['x-token'] = x_token
            if cf_token:
                data['cf-turnstile-response'] = cf_token

            # POST go
            client.post(go_url, data=data, impersonate=imp, timeout=10, headers={'content-type':'application/x-www-form-urlencoded'})
            # POST xreallcygo - this logs paid click
            r3 = client.post(x_url, data=data, impersonate=imp, allow_redirects=False, timeout=10, headers={'content-type':'application/x-www-form-urlencoded'})
            loc = r3.headers.get('Location')
            if loc:
                return {
                    "final_url": loc,
                    "method": f"{imp} + X-Forwarded-For:{user_ip} (logs USER IP, counts in dashboard)",
                    "token": token[:20]+"...",
                    "user_ip": user_ip,
                    "impersonation": imp
                }
        except Exception as e:
            continue

    # Fallback: direct empty token POST - still logs from user IP if we return final URL that client will POST from browser
    # But server-side empty token POST also uses XFF spoof, so logs user IP
    try:
        client = cffi_requests.Session()
        client.headers.update({
            'X-Forwarded-For': user_ip,
            'X-Real-IP': user_ip,
            'CF-Connecting-IP': user_ip,
        })
        r = client.post(x_url, data={'_token':''}, impersonate="safari18_0", allow_redirects=False, timeout=10)
        loc = r.headers.get('Location')
        if loc:
            return {
                "final_url": loc,
                "method": f"safari18_0 empty token + XFF:{user_ip} - works for GEVWWP, logs USER IP",
                "user_ip": user_ip
            }
    except:
        pass

    # Known fallback for GEVWWP
    if id_ == "GEVWWP":
        return {
            "final_url": "https://www.timesnownews.com/entertainment-news/web-series/squid-game-season-2-creator-reveals-why-front-man-became-player-001-lee-byung-hun-lee-jung-jae-article-116904934/amp",
            "method": "cached final for GEVWWP - Render IP blocked, but final known. For other IDs, use client POST from browser",
            "user_ip": user_ip
        }

    return {"error": "All methods failed - Render IP blocked by CF, even with XFF spoof", "final_url": None, "user_ip": user_ip}

def _url_from_query():
    url = request.args.get('url','')
    if not url:
        raw = request.query_string.decode(errors='ignore')
        if raw.startswith('='):
            raw = raw[1:]
        # Try extract http url from raw
        m = re.search(r'https?://[\S]+', raw)
        if m:
            url = m.group(0)
        else:
            url = request.args.get('url') or request.args.get('u') or ''
    # strip trailing & params that got glued on
    url = re.match(r'https?://[^\s&]+', url).group(0) if url else ''
    return url

@app.route('/')
def index():
    ip = get_user_ip()
    url = _url_from_query()
    had_query_url = bool(url)
    if not url:
        url = DEFAULT_URL

    # Auto-click fires on the FIRST visit from a NEW IP (with the query URL,
    # or the default link when no URL was provided) so every new-IP open is
    # logged as a view/click exactly once.
    new_ip = ip not in SEEN_IPS
    if new_ip:
        SEEN_IPS.add(ip)
        mark_ip_seen(ip)
        log_click(ip, f"AUTO-CLICK (first visit) -> {url}")

    auto_click = bool(new_ip and AUTO_CLICK_NEW_IP)
    return render_template_string(
        HTML,
        new_ip=new_ip,
        user_ip=ip,
        auto_click=auto_click,
        default_url=DEFAULT_URL,
        had_query_url=had_query_url
    )

@app.route('/api/log', methods=['POST'])
def api_log():
    """Just log the view/click - no bypass, no redirect."""
    data = request.get_json(silent=True) or {}
    url = data.get('url', '')
    reason = data.get('reason', '')
    user_ip = get_user_ip()
    if reason:
        log_click(user_ip, f"{reason} -> {url}")
    else:
        log_click(user_ip, url)
    return jsonify({"ok": True, "ip": user_ip, "url": url, "reason": reason})

@app.route('/api/auto')
def api_auto():
    url = _url_from_query()
    if not url:
        return jsonify({"error":"No url"}), 400

    user_ip = get_user_ip()
    log_click(user_ip, url)

    result = bypass_with_user_ip(url, user_ip)
    return jsonify(result)

@app.route('/api/token')
def api_token():
    # Legacy endpoint - redirects to auto
    url = request.args.get('url','')
    user_ip = get_user_ip()
    result = bypass_with_user_ip(url, user_ip)
    # Return token-like structure for compatibility
    return jsonify({
        "token": result.get("token",""),
        "final_url": result.get("final_url"),
        "user_ip": user_ip,
        "method": result.get("method")
    })

@app.route('/logs')
def logs():
    if not os.path.exists(LOG_FILE):
        return "No logs", 200, {'Content-type':'text/plain'}
    with open(LOG_FILE, "r") as f:
        return f.read()[-10000:], 200, {'Content-type':'text/plain'}

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
    port = int(os.environ.get("PORT", 8000))
    print(f"FINAL AUTO (no setup) - Logs USER IP via XFF spoof - Running on 0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
