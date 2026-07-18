import os
import sqlite3
import gzip
import json
from fastapi.testclient import TestClient
from main import app

def test_alltrains_sql():
    # Ensure sqlite_db directory exists
    os.makedirs("sqlite_db", exist_ok=True)
    
    # 1. Clean up potential old test databases to ensure generation is tested
    for v in [0, 32, 34]:
        path = f"sqlite_db/version{v}.db"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    client = TestClient(app)

    # Helper to check if file is a valid SQLite DB and contains correct metadata version
    def verify_sqlite_db(content: bytes, expected_version: int):
        # Write to temporary file to open with sqlite3
        temp_path = f"sqlite_db/temp_test_v{expected_version}.db"
        with open(temp_path, "wb") as f:
            f.write(content)
        
        try:
            conn = sqlite3.connect(temp_path)
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM metadata WHERE key = 'version'")
            version_val = cursor.fetchone()[0]
            assert int(version_val) == expected_version, f"Expected version {expected_version}, got {version_val}"
            
            cursor.execute("SELECT value FROM metadata WHERE key = 'Revision'")
            revision_val = cursor.fetchone()[0]
            print(f"✓ Valid SQLite DB for version {expected_version} verified. Revision: {revision_val}")
            conn.close()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    # Test 1: Query version 34 (should trigger database generation and serve it)
    print("👉 Testing /alltrains?version=34&is_sql=true")
    res = client.get("/alltrains?version=34&is_sql=true")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.sqlite3"
    assert "alltrains_v34.db" in res.headers["content-disposition"]
    verify_sqlite_db(res.content, 34)
    assert os.path.exists("sqlite_db/version34.db"), "version34.db was not generated/saved"

    # Test 2: Query version 32 (should trigger generation for version 32)
    print("👉 Testing /alltrains?version=32&is_sql=true")
    res = client.get("/alltrains?version=32&is_sql=true")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.sqlite3"
    assert "alltrains_v32.db" in res.headers["content-disposition"]
    verify_sqlite_db(res.content, 32)
    assert os.path.exists("sqlite_db/version32.db"), "version32.db was not generated/saved"

    # Test 3: Query version 0 (should fall back to version 0)
    print("👉 Testing /alltrains?version=0&is_sql=true")
    res = client.get("/alltrains?version=0&is_sql=true")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.sqlite3"
    assert "alltrains_v0.db" in res.headers["content-disposition"]
    verify_sqlite_db(res.content, 0)
    assert os.path.exists("sqlite_db/version0.db"), "version0.db was not generated/saved"

    # Test 4: Query version 34 with gzip encoding
    print("👉 Testing /alltrains?version=34&is_sql=true (Gzip)")
    res = client.get("/alltrains?version=34&is_sql=true", headers={"Accept-Encoding": "gzip"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.sqlite3"
    
    # httpx/TestClient automatically decodes gzip content, so res.content is already decompressed
    verify_sqlite_db(res.content, 34)

    # Test 5: Verify that querying again uses the cached DB (should be extremely fast/instant)
    print("👉 Testing /alltrains?version=34&is_sql=true (Cached)")
    res = client.get("/alltrains?version=34&is_sql=true")
    assert res.status_code == 200
    verify_sqlite_db(res.content, 34)

    print("🎉 All /alltrains is_sql tests passed successfully!")

if __name__ == "__main__":
    test_alltrains_sql()
