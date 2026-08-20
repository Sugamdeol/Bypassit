"""
Single-file Render website that logs click from USER IP not Render IP
Fixes "Failed to fetch" CORS proxy error by using server-side token fetch (Render IP for pageview only)
then client-side POST from user's browser (User IP for paid click)

Deploy to Render:
- Web Service: Build: pip install flask curl_cffi beautifulsoup4 lxml
            Start: python render_client_ip_bypass.py
- Then your site: https://yourname.onrender.com/?=https://ouo.io/go/GEVWWP auto-bypasses

Flow:
1. User opens https://yourname.onrender.com/?=https://ouo.io/go/GEVWWP
2. JS extracts URL from query
3. JS calls /api/token?url=https://ouo.io/GEVWWP  -> server uses curl_cffi safari18_0 to bypass CF and get _token (this is just pageview, NOT paid click, logged as Render IP)
4. JS receives token, creates hidden form POST to https://ouo.io/xreallcygo/GEVWWP from USER'S BROWSER -> ouo.io logs USER IP as paid click and 302 redirects to final destination
5. User is redirected to final URL
"""
import os, re, datetime
from flask import Flask, request, jsonify, render_template_string
from urllib.parse import urlparse, unquote

try:
    from curl_cffi import requests as cffi_requests
    from bs4 import BeautifulSoup
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

app = Flask(__name__)
LOG_FILE = "/home/user/clicks.log"

HTML = """
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ouo.io Bypass - User IP Logger</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,Segoe UI,Roboto,Arial;background:#0f172a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:14px}
.card{background:#1e293b;border:1px solid #334155;border-radius:16px;max-width:760px;width:100%;padding:24px;box-shadow:0 20px 50px rgba(0,0,0,.5)}
h1{font-size:20px;color:#f8fafc} .sub{color:#94a3b8;font-size:12px;margin:8px 0 16px;line-height:1.5}
label{font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.6px;display:block;margin-bottom:6px}
input{width:100%;background:#020617;border:1px solid #334155;border-radius:10px;padding:12px;color:#f1f5f9;font-size:14px;outline:none}
input:focus{border-color:#38bdf8;box-shadow:0 0 0 3px rgba(56,189,248,.2)}
.btn-row{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
button{flex:1;min-width:140px;background:#38bdf8;color:#0f172a;border:none;border-radius:10px;padding:12px;font-weight:700;font-size:13px;cursor:pointer}
button.secondary{background:#0f172a;color:#e2e8f0;border:1px solid #334155}
button:disabled{opacity:.5}
.result{margin-top:14px;background:#020617;border:1px solid #334155;border-radius:12px;padding:12px;display:none}
.result.show{display:block}
.k{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.5px}
.v{font-size:12px;margin-top:4px;word-break:break-all}
.v a{color:#38bdf8}
.status{margin-top:8px;font-size:12px}
.status.ok{color:#4ade80}.status.err{color:#f87171}.status.wait{color:#fbbf24}
pre{background:#020617;border:1px solid #1e293b;padding:8px;border-radius:8px;font-size:11px;max-height:240px;overflow:auto;margin-top:8px;white-space:pre-wrap}
.badge{display:inline-block;border:1px solid #334155;background:#020617;border-radius:20px;padding:2px 8px;font-size:10px;color:#94a3b8;margin:2px}
code{font-size:11px;background:#020617;padding:1px 5px;border-radius:4px}
.small{font-size:10px;color:#64748b;margin-top:12px;text-align:center;line-height:1.5}
</style>
</head><body>
<div class="card">
<h1>ouo.io Bypass — Logs YOUR IP, not Render's</h1>
<p class="sub">
Fix for <b>"Failed to fetch"</b>: this version gets <code>_token</code> via Render server (pageview from Render IP, not paid), then does final <code>POST https://ouo.io/xreallcygo/ID</code> <b>from YOUR browser</b> → ouo.io logs <b>YOUR IP</b> as paid click.<br>
Auto-bypass: <code>https://yourname.onrender.com/?=https://ouo.io/go/GEVWWP</code><br>
<span class="badge">User IP logged</span><span class="badge">No CORS proxy needed</span><span class="badge">Single file</span>
</p>

<label>Short URL</label>
<input id="urlInput" value="https://ouo.io/go/GEVWWP" placeholder="https://ouo.io/go/XXXX or https://ouo.io/XXXX">

<div class="btn-row">
<button id="bypassBtn">Bypass from MY IP (logs my IP)</button>
<button id="serverBtn" class="secondary">Bypass from Render IP (server-side)</button>
</div>

<div id="result" class="result">
<div><div class="k">Original</div><div class="v" id="orig"></div></div>
<div style="margin-top:8px"><div class="k">Working entry used</div><div class="v" id="working"></div></div>
<div style="margin-top:8px"><div class="k">_token (from server, pageview only)</div><div class="v" id="token"></div></div>
<div style="margin-top:8px"><div class="k">Final destination</div><div class="v" id="final"></div></div>
<div class="status wait" id="status">Waiting...</div>
<pre id="log"></pre>
</div>

<p class="small">
If you see "Failed to fetch" before, that was CORS proxy failing. This fixed version uses <code>/api/token</code> on Render to get token (bypasses Cloudflare via curl_cffi safari18_0), then final POST is from your IP via hidden form.<br>
For <b>GEVWWP</b> final is: <a href="https://www.timesnownews.com/entertainment-news/web-series/squid-game-season-2-creator-reveals-why-front-man-became-player-001-lee-byung-hun-lee-jung-jae-article-116904934/amp" target="_blank">TimesNowNews Squid Game article</a>
</p>
</div>

<script>
function getUrlFromQuery(){
  const search = window.location.search;
  if(!search) return null;
  let raw = search.slice(1);
  if(raw.startsWith('=')) raw = raw.slice(1);
  try{
    const params = new URLSearchParams(search);
    for(let k of ['url','u','link','l','short','q']){
      if(params.has(k)) return decodeURIComponent(params.get(k));
    }
    if(params.has('')){ let v=params.get(''); if(v && v.startsWith('http')) return v; }
  }catch(e){}
  try{
    const decoded = decodeURIComponent(raw);
    const m = decoded.match(/https?:\\/\\/[^\\s&]+/);
    if(m) return m[0];
  }catch(e){}
  if(raw.startsWith('http')) return raw;
  return null;
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
function log(msg){
  const el = document.getElementById('log');
  el.textContent += msg + "\\n";
  el.scrollTop = el.scrollHeight;
  console.log(msg);
}
async function bypassFromUserIP(shortUrl, autoSubmit=true){
  const resultDiv = document.getElementById('result');
  resultDiv.classList.add('show');
  document.getElementById('orig').textContent = shortUrl;
  document.getElementById('log').textContent = '';
  document.getElementById('final').textContent = '...';
  document.getElementById('status').textContent = 'Starting...';
  document.getElementById('status').className = 'status wait';

  try{
    let id = extractId(shortUrl);
    if(!id) throw new Error('Could not extract ID');
    let entryUrl = `https://ouo.io/${id}`;
    document.getElementById('working').textContent = entryUrl;
    log(`[1] ID: ${id}`);
    log(`[2] Working entry: ${entryUrl}`);

    log(`[3] Calling /api/token?url=${entryUrl} -> server uses curl_cffi safari18_0 to bypass CF and get _token (this is pageview from Render IP, NOT paid click)`);
    let tokenRes = await fetch(`/api/token?url=${encodeURIComponent(entryUrl)}`);
    let tokenData = await tokenRes.json();
    log(`[4] /api/token response: ${JSON.stringify(tokenData).slice(0,300)}`);

    if(!tokenData.token){
      throw new Error('No token from server: ' + (tokenData.error || 'unknown') + ' - HTML snippet: ' + (tokenData.html_snippet||'').slice(0,200));
    }

    let token = tokenData.token;
    let xToken = tokenData.x_token;
    let cfToken = tokenData.cf_token;

    document.getElementById('token').textContent = token.slice(0,40)+'...';
    log(`[5] _token: ${token.slice(0,30)}... x-token:${!!xToken} cf:${!!cfToken}`);

    let goUrl = `https://ouo.io/go/${id}`;
    let xUrl = `https://ouo.io/xreallcygo/${id}`;

    log(`[6] Doing first POST to ${goUrl} via fetch no-cors from YOUR IP (optional)`);
    try{
      await fetch(goUrl, {
        method:'POST',
        headers:{'Content-Type':'application/x-www-form-urlencoded'},
        body: `_token=${encodeURIComponent(token)}${xToken?'&x-token='+encodeURIComponent(xToken):''}`,
        mode:'no-cors'
      });
    }catch(e){ log('[6] go POST no-cors ignore: '+e); }

    await new Promise(r=>setTimeout(r,1000));

    if(autoSubmit){
      log(`[7] Creating hidden FORM POST to ${xUrl} from YOUR BROWSER - THIS LOGS YOUR IP on ouo.io`);
      log(`[8] Submitting form in 0.6s - you will be redirected to final URL (your IP logged, not Render's)`);

      let form = document.createElement('form');
      form.method='POST';
      form.action=xUrl;
      form.style.display='none';

      let inp=document.createElement('input'); inp.type='hidden'; inp.name='_token'; inp.value=token; form.appendChild(inp);
      if(xToken){ let i=document.createElement('input'); i.type='hidden'; i.name='x-token'; i.value=xToken; form.appendChild(i); }
      if(cfToken){ let i=document.createElement('input'); i.type='hidden'; i.name='cf-turnstile-response'; i.value=cfToken; form.appendChild(i); }

      document.body.appendChild(form);
      document.getElementById('status').textContent = `Logging click from YOUR IP... Redirecting to final...`;
      document.getElementById('status').className='status ok';
      document.getElementById('final').textContent = 'Will redirect to final after POST from your IP...';

      setTimeout(()=>form.submit(),600);
    }else{
      document.getElementById('status').textContent = 'Token ready, form would submit from your IP in auto mode';
    }

  }catch(err){
    log(`[ERROR] ${err.message}`);
    document.getElementById('status').textContent = 'Failed: '+err.message;
    document.getElementById('status').className='status err';
    document.getElementById('final').innerHTML = 'For GEVWWP, final is <a href="https://www.timesnownews.com/entertainment-news/web-series/squid-game-season-2-creator-reveals-why-front-man-became-player-001-lee-byung-hun-lee-jung-jae-article-116904934/amp" target="_blank">https://www.timesnownews.com/.../amp</a>';
  }
}

async function bypassFromServer(shortUrl){
  const resultDiv = document.getElementById('result');
  resultDiv.classList.add('show');
  document.getElementById('orig').textContent = shortUrl;
  document.getElementById('log').textContent = '';
  document.getElementById('status').textContent = 'Bypassing from Render IP (server-side)...';
  try{
    let res = await fetch('/api/bypass', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({url: shortUrl})
    });
    let data = await res.json();
    document.getElementById('working').textContent = data.working_entry||'';
    document.getElementById('token').textContent = 'Server-side, no client token';
    if(data.final_url){
      document.getElementById('final').innerHTML = `<a href="${data.final_url}" target="_blank">${data.final_url}</a>`;
      document.getElementById('status').textContent = 'SUCCESS via Render IP (ouo.io logs Render IP, not yours)';
      document.getElementById('status').className='status ok';
    }else{
      document.getElementById('final').textContent = 'Failed';
      document.getElementById('status').textContent = 'Failed: '+data.status;
      document.getElementById('status').className='status err';
    }
    document.getElementById('log').textContent = data.debug||'';
  }catch(e){
    document.getElementById('status').textContent = 'Error: '+e.message;
  }
}

document.getElementById('bypassBtn').addEventListener('click', ()=>{
  let url = document.getElementById('urlInput').value.trim();
  if(!url) return alert('Enter URL');
  bypassFromUserIP(url, true);
});
document.getElementById('serverBtn').addEventListener('click', ()=>{
  let url = document.getElementById('urlInput').value.trim();
  if(!url) return alert('Enter URL');
  bypassFromServer(url);
});

window.addEventListener('DOMContentLoaded', ()=>{
  let autoUrl = getUrlFromQuery();
  if(autoUrl){
    document.getElementById('urlInput').value = autoUrl;
    setTimeout(()=>bypassFromUserIP(autoUrl, true), 800);
  }
});
</script>
</body></html>
"""

def log_click(ip, path, ua):
    ts = datetime.datetime.utcnow().isoformat()
    entry = f"{ts} | IP={ip} | Path={path} | UA={ua[:100]}\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(entry)
    except:
        pass

def get_token_for_url(entry_url):
    """Server-side token fetch (Render IP for pageview only) using curl_cffi safari18_0 to bypass CF"""
    if not HAS_CFFI:
        return {"error": "curl_cffi not installed", "token": None}

    from urllib.parse import urlparse
    p = urlparse(entry_url)
    id_ = entry_url.split('/')[-1].split('?')[0]

    client = cffi_requests.Session()
    client.headers.update({
        'authority': 'ouo.io',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9',
        'referer': 'http://www.google.com/ig/adde?moduleurl=',
        'upgrade-insecure-requests': '1',
    })

    for imp in ["safari18_0", "safari15_5", "chrome133a"]:
        try:
            r = client.get(entry_url, impersonate=imp, timeout=15)
            if "Just a moment" in r.text:
                continue
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'lxml')
            token_el = soup.find('input', {'name':'_token'})
            if not token_el:
                continue
            _token = token_el.get('value')
            x_el = soup.find('input', {'name':'x-token'})
            x_token = x_el.get('value') if x_el else None
            cf_el = soup.find('input', {'name':'cf-turnstile-response'})
            cf_token = cf_el.get('value') if cf_el else None

            return {
                "token": _token,
                "x_token": x_token,
                "cf_token": cf_token,
                "id": id_,
                "impersonation": imp,
                "html_snippet": r.text[:500]
            }
        except Exception as e:
            continue

    return {"error": "Could not fetch token - all impersonations failed, maybe link expired or CF blocked", "token": None}

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/token')
def api_token():
    url = request.args.get('url','')
    if not url:
        # Also try getting from ?= query
        raw = request.query_string.decode(errors='ignore')
        # raw might be =https://... or https://...
        if raw.startswith('='):
            raw = raw[1:]
        url = raw
        # Try decode url param
        if not url.startswith('http'):
            url = request.args.get('url') or request.args.get('u') or request.args.get('link') or ''
    if not url:
        return jsonify({"error":"No url param"}), 400

    # If url is like https://ouo.io/go/GEVWWP, convert to https://ouo.io/GEVWWP for working entry
    # Extract ID and rebuild
    try:
        id_ = url.split('/')[-1].split('?')[0]
        if id_ == 'go' or not id_:
            # Try second last
            parts = [p for p in url.split('/') if p]
            id_ = parts[-1] if parts else ''
        entry = f"https://ouo.io/{id_}"
    except:
        entry = url

    result = get_token_for_url(entry)
    result["entry_url"] = entry
    result["original_url"] = url
    return jsonify(result)

@app.route('/api/bypass', methods=['POST'])
def api_bypass():
    data = request.get_json() or {}
    url = data.get('url','').strip()
    if not url:
        return jsonify({"error":"No URL"}), 400

    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    ua = request.headers.get('User-Agent','')
    log_click(ip, url, ua)

    # Reuse logic from earlier bypass_website.py
    try:
        id_ = url.split('/')[-1].split('?')[0]
        if id_ == 'go':
            parts = [p for p in url.split('/') if p]
            id_ = parts[-1]
        entry = f"https://ouo.io/{id_}"

        if not HAS_CFFI:
            return jsonify({"error":"Missing deps"})

        client = cffi_requests.Session()
        client.headers.update({
            'authority': 'ouo.io',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'accept-language': 'en-US,en;q=0.9',
            'referer': 'http://www.google.com/ig/adde?moduleurl=',
            'upgrade-insecure-requests': '1',
        })

        for imp in ["safari18_0","safari15_5","chrome133a"]:
            try:
                r = client.get(entry, impersonate=imp, timeout=15)
                if "Just a moment" in r.text or r.status_code != 200:
                    continue
                soup = BeautifulSoup(r.text,'lxml')
                token_el = soup.find('input', {'name':'_token'})
                if not token_el:
                    continue
                _token = token_el.get('value')
                x_el = soup.find('input', {'name':'x-token'})
                x_token = x_el.get('value') if x_el else None

                data_post = {'_token': _token}
                if x_token:
                    data_post['x-token'] = x_token

                r2 = client.post(f"https://ouo.io/go/{id_}", data=data_post, impersonate=imp, allow_redirects=False, timeout=15, headers={'content-type':'application/x-www-form-urlencoded'})
                r3 = client.post(f"https://ouo.io/xreallcygo/{id_}", data=data_post, impersonate=imp, allow_redirects=False, timeout=15, headers={'content-type':'application/x-www-form-urlencoded'})
                loc = r3.headers.get('Location')
                if loc:
                    return jsonify({
                        "original_url": url,
                        "working_entry": entry,
                        "final_url": loc,
                        "status": f"SUCCESS via {imp} (Render IP - ouo.io logs Render IP)",
                        "debug": f"GET {entry} {r.status_code} -> POST go {r2.status_code} -> POST xreallcygo {r3.status_code} Location {loc}"
                    })
            except Exception as e:
                continue

        return jsonify({
            "original_url": url,
            "working_entry": entry,
            "final_url": None,
            "status": "FAILED - expired or CF blocked",
            "debug": "All impersonations failed"
        })

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "debug": traceback.format_exc()})

@app.route('/logs')
def logs():
    if not os.path.exists(LOG_FILE):
        return "No logs yet", 200, {'Content-type':'text/plain'}
    with open(LOG_FILE, "r") as f:
        return f.read()[-20000:], 200, {'Content-type':'text/plain; charset=utf-8'}

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting bypass website (User IP logger) on 0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
