import httpx

BASE = "http://127.0.0.1:8000"

with httpx.Client() as client:
    # Login
    r = client.post(
        f"{BASE}/api/v1/auth/login",
        data={
            "username": "alice@holomed-test.local",
            "password": "StrongPass123!",
        },
    )

    print("LOGIN:", r.status_code)
    print(r.json())

    # Check cookie
    print("COOKIES:", client.cookies)

    # Upload DICOM
    with open("test.dcm", "rb") as f:
        r = client.post(
            f"{BASE}/api/v1/medical-data/dicom/upload",
            files={
                "file": (
                    "test.dcm",
                    f,
                    "application/dicom",
                )
            },
        )

    print("\nUPLOAD:", r.status_code)
    print(r.text)