import urllib.request
import urllib.parse
import json
import uuid

def check_url(url, method="GET", data=None, headers=None):
    if headers is None:
        headers = {}
    try:
        if data:
            data = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read(), resp.getheaders()
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.items()
    except Exception as e:
        return 0, str(e), []

print("1. Checking frontend (port 5173)...")
status, content, _ = check_url("http://localhost:5173")
print(f"Frontend Root Status: {status}")

print("\n2. Checking backend (port 8001)...")
# API Authentication
email = f"http_test_{uuid.uuid4().hex[:8]}@example.com"
password = "TestPassword123!"

# Register
status, content, _ = check_url(f"http://127.0.0.1:8001/api/v1/auth/register?email={urllib.parse.quote(email)}&password={password}", method="POST")
print(f"Auth Register Status: {status}")

# Login
status, content, headers = check_url("http://127.0.0.1:8001/api/v1/auth/login", method="POST", data={"username": email, "password": password})
print(f"Auth Login Status: {status}")

cookies = [v for k, v in headers if k.lower() == 'set-cookie']
session_cookie = cookies[0].split(";")[0] if cookies else ""
print(f"Session Cookie Obtained: {bool(session_cookie)}")

auth_headers = {"Cookie": session_cookie} if session_cookie else {}

# Reports upload (using multipart/form-data manually)
boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
body = (
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="title"\r\n\r\n'
    f'HTTP Upload Test\r\n'
    f'--{boundary}\r\n'
    f'Content-Disposition: form-data; name="file"; filename="test_report.txt"\r\n'
    f'Content-Type: text/plain\r\n\r\n'
    f'Hello World PDF Content\r\n'
    f'--{boundary}--\r\n'
).encode("utf-8")

req = urllib.request.Request("http://127.0.0.1:8001/api/v1/reports", data=body, method="POST", headers={**auth_headers, "Content-Type": f"multipart/form-data; boundary={boundary}"})
try:
    with urllib.request.urlopen(req) as resp:
        print(f"Report Upload Status: {resp.status}")
        report_data = json.loads(resp.read().decode())
        report_id = report_data.get("id")
        print(f"Uploaded Report ID: {report_id}")
except urllib.error.HTTPError as e:
    print(f"Report Upload Failed: {e.code} - {e.read()}")
    report_id = None

# Reports list
if report_id:
    req = urllib.request.Request("http://127.0.0.1:8001/api/v1/reports", headers=auth_headers)
    with urllib.request.urlopen(req) as resp:
        print(f"Report List Status: {resp.status}")
        reports_list = json.loads(resp.read().decode())
        found = any(r.get("id") == report_id for r in reports_list)
        print(f"New Report present in list: {found}")
    
    req = urllib.request.Request(f"http://127.0.0.1:8001/api/v1/reports/{report_id}", headers=auth_headers)
    with urllib.request.urlopen(req) as resp:
        print(f"Single Report Status: {resp.status}")
        print(f"Single Report Content Valid: {json.loads(resp.read().decode()).get('title') == 'HTTP Upload Test'}")
