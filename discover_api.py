import os
import re
import urllib.request

BASE = "/tmp/apidisco"
os.makedirs(BASE, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ROOT = "https://www.bingoemcasa17.com"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


html = get(ROOT + "/pt-BR/sportsbook").decode("utf-8", "replace")
open(BASE + "/sb.html", "w").write(html)
print("HTML bytes:", len(html))

srcs = re.findall(r'src="([^"]+\.js[^"]*)"', html)
print("JS chunks:", len(srcs))

jsdir = BASE + "/js"
os.makedirs(jsdir, exist_ok=True)

for s in srcs:
    if s.startswith("http"):
        u = s
    else:
        u = ROOT + s
    name = s.split("/")[-1].split("?")[0]
    try:
        data = get(u)
        open(os.path.join(jsdir, name), "wb").write(data)
    except Exception as e:
        print("ERR", name, e)

print("--- downloaded ---")
for f in sorted(os.listdir(jsdir)):
    print(f, os.path.getsize(os.path.join(jsdir, f)))

# agora grep
import subprocess

def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout

print("\n=== API BASE URL ===")
print(sh("grep -rhoE 'https?://[a-zA-Z0-9._-]+\\.[a-zA-Z0-9._-]+(:[0-9]+)?/[a-zA-Z0-9._/-]*' %s | sort -u | head -60" % jsdir))

print("\n=== API PATHS api/v1 ===")
print(sh("grep -rhoE '/[a-zA-Z0-9._/-]*api/v[0-9]+[a-zA-Z0-9._/{}$-]*' %s | sort -u | head -60" % jsdir))

print("\n=== ENDPOINTS ===")
print(sh("grep -rhoE '/[a-zA-Z0-9._/-]{2,70}(login|betplace|balance|betslip|market|odds|coupon|sport|event|selection|placebet|bet)[a-zA-Z0-9._/-]*' %s | sort -u | head -120" % jsdir))

print("\n=== CONTEXT: API_BASE_URL var ===")
print(sh("grep -rhoE '.{80}API_BASE_URL.{160}' %s | head -10" % jsdir))

print("\n=== CONTEXT: playtech ===")
print(sh("grep -rhoiE '.{100}playtech.{100}' %s | head -15" % jsdir))
