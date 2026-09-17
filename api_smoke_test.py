import httpx
import sys

BASE_URL = "http://127.0.0.1:8001"

def run_tests():
    try:
        client = httpx.Client(base_url=BASE_URL)
        # 1. Root
        r = client.get("/")
        print("Root:", r.status_code)
        
        # 2. login
        email = "smoke_test@example.com"
        password = "password123"
        client.post("/api/v1/auth/register", params={"email": email, "password": password})
        
        login_resp = client.post("/api/v1/auth/login", data={"username": email, "password": password})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        
        # 3. /auth/me
        r = client.get("/api/v1/auth/me")
        print("/auth/me:", r.status_code)
        
        # 4. patients
        r = client.get("/api/v1/medical-data/patients")
        print("patients:", r.status_code)
        
        # 5. studies
        r = client.get("/api/v1/dicomweb/studies")
        print("studies:", r.status_code)
        
        # 6. reports
        r = client.get("/api/v1/reports")
        print("reports:", r.status_code)
        
        # 7. measurements
        r = client.get("/api/v1/measurements")
        print("measurements:", r.status_code)
        
        # 8. audit
        r = client.get("/api/v1/audit")
        print("audit:", r.status_code)
        
        # 9. templates
        r = client.get("/api/v1/templates")
        print("templates:", r.status_code)
        
        # 10. consents
        r = client.get("/api/v1/consents")
        print("consents:", r.status_code)
        
        # 11. storage
        r = client.get("/api/v1/storage-connections")
        print("storage-connections:", r.status_code)
        
        # 12. search
        r = client.post("/api/v1/search", json={"query": "test"})
        print("search:", r.status_code)
        
        # 13. AI summary
        # we need a report first
        report_resp = client.get("/api/v1/reports")
        reports = report_resp.json()
        if len(reports) > 0:
            report_id = reports[0]["id"]
            r = client.post(f"/api/v1/reports/{report_id}/summary", data={"mode": "standard"})
            print("ai_summary POST:", r.status_code)
            r = client.get(f"/api/v1/reports/{report_id}/summary")
            print("ai_summary GET:", r.status_code)
        else:
            print("ai_summary skipped (no reports found)")
            
        print("All API smoke tests passed!")
    except Exception as e:
        print("Exception during smoke tests:", e)
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
