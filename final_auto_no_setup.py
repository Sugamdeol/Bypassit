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
import os, re, time, datetime
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

function hostOf(url){
  try{ return new URL(url).host; }catch(e){ return 'ouo.io'; }
}

// Fire the ouo.io click FROM THE VISITOR'S OWN BROWSER (their IP).
// This replicates the real click sequence:
//   1. load the ouo.io interstitial in a hidden iframe (real visit: passes
//      Cloudflare + Turnstile, sets ouo session cookies)
//   2. wait for the page to settle, then submit the click POST
//      (ouo.io/xreallcygo/ID) from the same browser - the request ouo.io
//      counts in its dashboard
//   3. a no-cors fetch backup in case form submission is blocked by an
//      outer sandboxed iframe (e.g. a preview shell)
// The visitor's page NEVER navigates - no redirect, just the logged view.
function fireOuoClick(url, onStage){
  return new Promise((resolve, reject)=>{
    let id = extractId(url);
    if(!id){ return reject(new Error('Could not extract ouo ID from ' + url)); }
    let host = hostOf(url);
    let xUrl = `https://${host}/xreallcygo/${id}`;

    const stage = (s)=>{ if(onStage) onStage(s); };

    // Step 1: real visit to the interstitial in a hidden iframe
    stage('loading ouo page (real visit)...');
    let visit = document.createElement('iframe');
    visit.name = 'ouovisit';
    visit.style.cssText = 'display:none;width:1px;height:1px;position:absolute;';
    visit.src = `https://${host}/${id}`;
    document.body.appendChild(visit);

    // Step 2: after the page settles, send the click POST from this browser
    setTimeout(()=>{
      stage('sending click POST from your IP...');
      let sink = document.createElement('iframe');
      sink.name = 'ouoclick';
      sink.style.cssText = 'display:none;width:1px;height:1px;position:absolute;';
      document.body.appendChild(sink);

      let form = document.createElement('form');
      form.method = 'POST';
      form.action = xUrl;
      form.target = 'ouoclick';
      form.innerHTML = '<input type="hidden" name="_token" value="">';
      document.body.appendChild(form);
      try{ form.submit(); }catch(e){}

      // Step 3: backup POST via no-cors fetch (works even if an outer
      // sandboxed iframe blocks form submission)
      setTimeout(()=>{
        try{
          fetch(xUrl, {
            method:'POST',
            mode:'no-cors',
            headers:{'Content-Type':'application/x-www-form-urlencoded'},
            body:'_token='
          }).catch(()=>{});
        }catch(e){}

        setTimeout(()=>{ stage('done'); resolve(id); }, 1200);
        setTimeout(()=>{ visit.remove(); sink.remove(); form.remove(); }, 5000);
      }, 2500);
    }, 6000);
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

// Report what the browser/preview shell blocks (CSP, mixed content...) to
// our server so we can see WHY a click didn't fire.
document.addEventListener('securitypolicyviolation', (ev)=>{
  logView('(csp)', 'CSP-BLOCK blocked=' + (ev.blockedURI||'?') + ' directive=' + (ev.violatedDirective||'?'));
});

function showSteps(steps){
  let el = document.getElementById('info');
  if(steps && steps.length){
    el.innerHTML = '<div style="text-align:left;margin-top:8px"><b>Server steps:</b><br>' +
      steps.map(x=>'<code style="display:block;word-break:break-all">' + x.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</code>').join('') +
      '</div>';
  }
}

// Server-side click first (the real multi-phase token flow), browser-side
// visit as fallback. No redirects ever - the visitor stays on this page.
function runAuto(url){
  document.getElementById('orig').textContent = url;
  document.getElementById('loader').style.display = 'block';
  document.getElementById('status').textContent = 'Server click attempt (multi-phase token flow)...';

  fetch('/api/auto?url=' + encodeURIComponent(url))
    .then(r=>r.json())
    .then(data=>{
      showSteps(data.steps || []);
      if(data.counted){
        document.getElementById('loader').style.display = 'none';
        document.getElementById('status').textContent = 'VIEW COUNTED in ouo.io (click registered, 302 received). You stay here - no redirect.';
        document.getElementById('info').innerHTML += '<br><b style="color:#4ade80">counted=true</b> destination: <code>' + (data.final_url||'') + '</code>';
        logView(url, 'auto-counted');
      } else {
        document.getElementById('status').textContent = 'Server click NOT counted (' + (data.method||'blocked') + '). Trying browser-side visit...';
        fireOuoClick(url, (s)=>document.getElementById('status').textContent = 'Browser fallback: ' + s)
          .then((id)=>{
            document.getElementById('loader').style.display = 'none';
            document.getElementById('status').textContent = 'Browser-side click fired for ' + id + '. If the ouo dashboard still shows no view, this host/IP is being blocked by ouo (sandbox/preview networks cannot count).';
            logView(url, 'auto-browser-fallback');
          })
          .catch((e)=>{
            document.getElementById('loader').style.display = 'none';
            document.getElementById('status').textContent = 'Error: ' + e.message;
          });
      }
    })
    .catch(e=>{
      document.getElementById('status').textContent = 'Server flow error: ' + e.message + '. Trying browser-side visit...';
      fireOuoClick(url, (s)=>document.getElementById('status').textContent = 'Browser fallback: ' + s)
        .then((id)=>{
          document.getElementById('loader').style.display = 'none';
          logView(url, 'auto-browser-fallback');
        })
        .catch(()=>{ document.getElementById('loader').style.display = 'none'; });
    });
}

window.addEventListener('DOMContentLoaded', ()=>{
  let url = getUrlFromQuery();
  if(!url) url = DEFAULT_URL;
  document.getElementById('urlInput').value = url;
  document.getElementById('visitor').textContent = 'Your IP: ' + USER_IP + (NEW_IP ? ' (NEW)' : ' (already logged before)');

  // Warn if this page is embedded inside another site's iframe (preview
  // shells) - form submissions to ouo.io may be sandboxed there.
  try{
    if(window.self !== window.top){
      let n = document.createElement('p');
      n.style.cssText = 'font-size:10px;color:#fbbf24;margin-top:8px';
      n.textContent = 'Embedded in a preview iframe - if the view does not count in ouo.io, open this site directly in a new browser tab.';
      document.querySelector('.card').appendChild(n);
    }
  }catch(e){}

  document.getElementById('manualBtn').addEventListener('click', ()=>{
    let u = document.getElementById('urlInput').value.trim();
    document.getElementById('orig').textContent = u;
    document.getElementById('loader').style.display = 'block';
    fetch('/api/auto?url=' + encodeURIComponent(u))
      .then(r=>r.json())
      .then(data=>{
        showSteps(data.steps || []);
        if(data.counted){
          document.getElementById('loader').style.display = 'none';
          document.getElementById('status').textContent = 'VIEW COUNTED in ouo.io (302 received). No redirect - you stay here.';
          document.getElementById('info').innerHTML += '<br><b style="color:#4ade80">counted=true</b> destination: <code>' + (data.final_url||'') + '</code>';
          logView(u, 'manual-counted');
        } else {
          document.getElementById('status').textContent = 'Server click NOT counted (' + (data.method||'blocked') + '). Trying browser-side visit...';
          fireOuoClick(u, (s)=>document.getElementById('status').textContent = 'Browser fallback: ' + s)
            .then((id)=>{
              document.getElementById('loader').style.display = 'none';
              document.getElementById('status').textContent = 'Browser-side click fired for ' + id + '. If ouo shows no view, this network is blocked by ouo (use the Render deployment).';
              logView(u, 'manual-browser-fallback');
            })
            .catch((e)=>{
              document.getElementById('loader').style.display = 'none';
              document.getElementById('status').textContent = 'Error: ' + e.message;
            });
        }
      })
      .catch(e=>{
        document.getElementById('loader').style.display = 'none';
        document.getElementById('status').textContent = 'Server flow error: ' + e.message;
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

def ouo_click_server(original_url, user_ip):
    """Real ouo.io click flow, server-side (for Render where ouo.io is reachable).

    The view in ouo.io counts when the interstitial's click form is submitted
    with a VALID _token. Empty-token POSTs are rejected. This replicates the
    flow the bypass extensions use:
      1. GET https://ouo.io/{id}  (the interstitial: Cloudflare/Turnstile + form)
      2. extract _token / x-token / cf-turnstile-response from the HTML
      3. POST /go/{id} with the token
      4. POST /xreallcygo/{id} with the token -> 302 Location = VIEW COUNTED

    Visitor is never redirected - we only detect the 302 and log.
    Returns {counted, final_url, method, user_ip, steps}.
    """
    steps = []
    def s(m):
        steps.append(m)

    result = {"counted": False, "final_url": None, "method": "", "user_ip": user_ip, "steps": steps}

    if not HAS_CFFI:
        s("curl_cffi missing on this host")
        result["method"] = "server click unavailable (deps missing)"
        return result

    try:
        id_ = original_url.split('/')[-1].split('?')[0]
        if id_ == 'go' or not id_:
            parts = [p for p in original_url.split('/') if p]
            id_ = parts[-1] if parts else ''
    except Exception:
        result["method"] = "invalid URL"
        return result
    if not id_:
        result["method"] = "could not extract link id"
        return result

    from urllib.parse import urlparse as _up
    host = "ouo.io"
    try:
        netloc = _up(original_url).netloc
        if netloc:
            host = netloc
    except Exception:
        pass

    entry_url = f"https://{host}/{id_}"
    go_url = f"https://{host}/go/{id_}"
    x_url = f"https://{host}/xreallcygo/{id_}"

    # Impersonation profiles: newest first, all supported by curl-cffi 0.7.4.
    # DEFAULT_* map to the newest profile the installed version knows.
    imps = ["chrome124", "chrome120", "safari17_0", "safari15_5", "edge101", "chrome110"]

    client = cffi_requests.Session()
    client.headers.update({
        'authority': host,
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9',
        'referer': 'http://www.google.com/',
        'upgrade-insecure-requests': '1',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'cross-site',
        'sec-fetch-user': '?1',
        # attribute the view to the visitor IP where possible
        'X-Forwarded-For': user_ip,
        'X-Real-IP': user_ip,
        'CF-Connecting-IP': user_ip,
        'True-Client-IP': user_ip,
        'Forwarded': f'for={user_ip}',
        'X-Forwarded-Proto': 'https',
    })

    for imp in imps:
        try:
            s(f"GET {entry_url} (as {imp})")
            r = client.get(entry_url, impersonate=imp, timeout=15)
            cf = "Just a moment" in r.text or "challenge-platform" in r.text
            s(f"  -> HTTP {r.status_code}, {len(r.text)} bytes, cloudflare_challenge={cf}")
            if r.status_code != 200 or cf:
                continue

            soup = BeautifulSoup(r.text, 'lxml')
            token_el = soup.find('input', {'name': '_token'})
            if token_el is None:
                s("  -> no _token input on page")
                continue
            _token = token_el.get('value', '') or ''
            x_el = soup.find('input', {'name': 'x-token'})
            x_token = x_el.get('value', '') if x_el else ''
            cf_el = soup.find('input', {'name': 'cf-turnstile-response'})
            cf_token = cf_el.get('value', '') if cf_el else ''
            if not _token:
                s("  -> _token empty on page")
                continue
            s(f"  -> _token={_token[:16]}... x-token={'yes' if x_token else 'no'} turnstile={'yes' if cf_token else 'no'}")

            data = {'_token': _token}
            if x_token:
                data['x-token'] = x_token
            if cf_token:
                data['cf-turnstile-response'] = cf_token

            # Phase 2: /go/{id} (the interstitial's first POST)
            r2 = client.post(go_url, data=data, impersonate=imp, allow_redirects=False, timeout=15,
                             headers={'content-type': 'application/x-www-form-urlencoded', 'referer': entry_url})
            s(f"  POST {go_url} -> HTTP {r2.status_code} Location={r2.headers.get('Location')}")
            time.sleep(1)

            # Phase 3: /xreallcygo/{id} - the request that counts the view
            r3 = client.post(x_url, data=data, impersonate=imp, allow_redirects=False, timeout=15,
                             headers={'content-type': 'application/x-www-form-urlencoded', 'referer': entry_url})
            loc = r3.headers.get('Location')
            s(f"  POST {x_url} -> HTTP {r3.status_code} Location={loc}")
            if loc:
                s("VIEW COUNTED: ouo.io returned a 302 redirect (click registered)")
                result.update({"counted": True, "final_url": loc,
                               "method": f"multi-phase token flow as {imp}", "token": _token[:16] + "..."})
                return result
            s("  -> no redirect; not counted with this profile")
        except Exception as e:
            s(f"  ! error ({imp}): {e}")

    # Last resort: empty-token POST (usually rejected, but harmless)
    try:
        r = client.post(x_url, data={'_token': ''}, impersonate=imps[0], allow_redirects=False, timeout=15,
                        headers={'content-type': 'application/x-www-form-urlencoded'})
        loc = r.headers.get('Location')
        s(f"  POST {x_url} (empty token) -> HTTP {r.status_code} Location={loc}")
        if loc:
            s("VIEW COUNTED via empty-token fallback")
            result.update({"counted": True, "final_url": loc, "method": "empty-token POST fallback"})
            return result
    except Exception as e:
        s(f"  ! empty-token error: {e}")

    net_blocked = any(('SSL' in st) or ('Failed to perform' in st) or ('resolve host' in st.lower()) for st in steps)
    if net_blocked:
        result["method"] = "this host has no network route to ouo.io (views cannot be counted from here; deploy to Render)"
    else:
        result["method"] = "all server attempts blocked or rejected by ouo.io"
    return result

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

    result = ouo_click_server(url, user_ip)
    log_click(user_ip, f"server-click counted={result.get('counted')} -> {url}")
    return jsonify(result)

@app.route('/api/token')
def api_token():
    # Legacy endpoint - redirects to auto
    url = request.args.get('url','')
    user_ip = get_user_ip()
    result = ouo_click_server(url, user_ip)
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
