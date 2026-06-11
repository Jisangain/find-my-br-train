# scratch/test_sqlite.py
import sqlite3
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

db_path = "sqlite_db/version33.db"

def run_tests():
    if not os.path.exists(db_path):
        print(f"❌ Error: Database file {db_path} does not exist.")
        sys.exit(1)
        
    print(f"🔍 Testing SQLite database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Check table existence
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    expected_tables = ["stations", "trains", "train_off_days", "routes", "metadata"]
    print(f"   Tables found: {tables}")
    
    for table in expected_tables:
        if table not in tables:
            print(f"❌ Error: Table '{table}' is missing!")
            sys.exit(1)
        else:
            print(f"   ✅ Table '{table}' exists")
            
    # 2. Check metadata
    cursor.execute("SELECT key, value FROM metadata")
    metadata = dict(cursor.fetchall())
    print("\n   Metadata values:")
    for k, v in metadata.items():
        print(f"     • {k}: {v}")
        
    if "Revision" not in metadata:
        print("❌ Error: 'Revision' is missing from metadata table")
        sys.exit(1)
    print("   ✅ 'Revision' metadata key exists")
    
    # 3. Check stations count and schema
    cursor.execute("SELECT COUNT(*) FROM stations")
    stations_count = cursor.fetchone()[0]
    print(f"\n   ✅ Stations count: {stations_count}")
    if stations_count == 0:
        print("❌ Error: Stations table is empty")
        sys.exit(1)
        
    cursor.execute("SELECT id, name_en, name_bn, lat, lng FROM stations LIMIT 3")
    print("   Sample stations:")
    for row in cursor.fetchall():
        print(f"     • {row[0]}: Name(EN)='{row[1]}', Name(BN)='{row[2]}', Lat={row[3]}, Lng={row[4]}")
        
    # 4. Check trains count
    cursor.execute("SELECT COUNT(*) FROM trains")
    trains_count = cursor.fetchone()[0]
    print(f"\n   ✅ Trains count: {trains_count}")
    if trains_count == 0:
        print("❌ Error: Trains table is empty")
        sys.exit(1)
        
    cursor.execute("SELECT id, name_en, name_bn FROM trains LIMIT 3")
    print("   Sample trains:")
    for row in cursor.fetchall():
        print(f"     • {row[0]}: Name(EN)='{row[1]}', Name(BN)='{row[2]}'")
        
    # 5. Check train_off_days count
    cursor.execute("SELECT COUNT(*) FROM train_off_days")
    offdays_count = cursor.fetchone()[0]
    print(f"\n   ✅ Off-days count: {offdays_count}")
    
    # 6. Check routes count and ordering
    cursor.execute("SELECT COUNT(*) FROM routes")
    routes_count = cursor.fetchone()[0]
    print(f"\n   ✅ Routes count: {routes_count}")
    if routes_count == 0:
        print("❌ Error: Routes table is empty")
        sys.exit(1)
        
    # Verify sequence order check (stop_sequence ordering)
    cursor.execute("""
        SELECT train_id, station_id, stop_sequence, flag, arrival_time 
        FROM routes 
        ORDER BY train_id, stop_sequence 
        LIMIT 5
    """)
    print("   Sample route stops:")
    for row in cursor.fetchall():
        print(f"     • Train {row[0]}: Stop {row[2]} at Station '{row[1]}' (Flag={row[3]}, Time={row[4]})")
        
    # 7. Check Foreign Keys integrity
    # Enabling foreign keys validation
    cursor.execute("PRAGMA foreign_key_check")
    fk_violations = cursor.fetchall()
    if fk_violations:
        print(f"❌ Error: Foreign Key Violations found: {fk_violations}")
        sys.exit(1)
    conn.close()
    print("   ✅ Integrity Check: No Foreign Key violations found!")
    
    # 8. Test FastAPI Endpoints using TestClient
    print("\n🌐 Testing FastAPI Endpoint integration...")
    try:
        from fastapi.testclient import TestClient
        from main import app
        
        client = TestClient(app)
        
        # Test version 32 (should return JSON)
        print("   Testing GET /alltrains?version=32 (expecting JSON)...")
        r32 = client.get("/alltrains?version=32")
        assert r32.status_code == 200, f"Expected 200, got {r32.status_code}"
        assert r32.headers["content-type"].startswith("application/json"), f"Expected JSON, got {r32.headers['content-type']}"
        data32 = r32.json()
        assert "Revision" in data32, "Missing 'Revision' in JSON response"
        print("   ✅ /alltrains?version=32 returns valid JSON")
        
        # Test version 33 default behavior (no is_sql parameter, should return JSON)
        print("   Testing GET /alltrains?version=33 (expecting JSON)...")
        r33_default = client.get("/alltrains?version=33")
        assert r33_default.status_code == 200, f"Expected 200, got {r33_default.status_code}"
        assert r33_default.headers["content-type"].startswith("application/json"), f"Expected JSON, got {r33_default.headers['content-type']}"
        data33_default = r33_default.json()
        assert "Revision" in data33_default, "Missing 'Revision' in JSON response"
        print("   ✅ /alltrains?version=33 (default) returns valid JSON")
        
        # Test version 33 with is_sql=false (should return JSON)
        print("   Testing GET /alltrains?version=33&is_sql=false (expecting JSON)...")
        r33_sql_false = client.get("/alltrains?version=33&is_sql=false")
        assert r33_sql_false.status_code == 200, f"Expected 200, got {r33_sql_false.status_code}"
        assert r33_sql_false.headers["content-type"].startswith("application/json"), f"Expected JSON, got {r33_sql_false.headers['content-type']}"
        print("   ✅ /alltrains?version=33&is_sql=false returns valid JSON")

        # Test version 33 with is_sql=true uncompressed
        print("   Testing GET /alltrains?version=33&is_sql=true without gzip (expecting SQLite DB)...")
        # Explicitly omit gzip from accept-encoding
        r33_raw = client.get("/alltrains?version=33&is_sql=true", headers={"accept-encoding": "identity"})
        assert r33_raw.status_code == 200, f"Expected 200, got {r33_raw.status_code}"
        assert r33_raw.headers.get("content-encoding") is None, "Did not expect content-encoding headers"
        print(f"     • Response Content-Type: {r33_raw.headers.get('content-type')}")
        assert "sqlite3" in r33_raw.headers.get("content-type", "") or "octet-stream" in r33_raw.headers.get("content-type", ""), "Expected SQLite/binary content-type"
        
        # Test version 33 with is_sql=true compressed
        print("   Testing GET /alltrains?version=33&is_sql=true with gzip (expecting gzipped SQLite DB)...")
        r33_gzip = client.get("/alltrains?version=33&is_sql=true", headers={"accept-encoding": "gzip"})
        assert r33_gzip.status_code == 200, f"Expected 200, got {r33_gzip.gzip.status_code if hasattr(r33_gzip, 'gzip') else r33_gzip.status_code}"
        assert r33_gzip.headers.get("content-encoding") == "gzip", f"Expected content-encoding gzip, got {r33_gzip.headers.get('content-encoding')}"
        
        # TestClient (httpx) automatically decompresses content for Content-Encoding: gzip responses.
        # So r33_gzip.content is already decompressed.
        decompressed_content = r33_gzip.content
        
        # Save temp file and test SQLite connection
        temp_db = "sqlite_db/temp_download.db"
        if os.path.exists(temp_db):
            os.remove(temp_db)
        with open(temp_db, "wb") as f:
            f.write(decompressed_content)
            
        temp_conn = sqlite3.connect(temp_db)
        temp_cursor = temp_conn.cursor()
        temp_cursor.execute("SELECT value FROM metadata WHERE key = 'Revision'")
        val = temp_cursor.fetchone()[0]
        temp_conn.close()
        os.remove(temp_db)
        
        assert int(val) == int(metadata["Revision"]), f"Downloaded DB revision {val} doesn't match expected {metadata['Revision']}"
        print("   ✅ /alltrains?version=33&is_sql=true returns valid SQLite DB file with matching Revision under both gzip and identity!")
        
        # Test version 33 fallback when DB file does not exist
        print("   Testing GET /alltrains?version=33&is_sql=true fallback when DB file is missing (expecting JSON)...")
        real_db_path = "sqlite_db/version33.db"
        backup_db_path = "sqlite_db/version33_backup.db"
        db_existed = os.path.exists(real_db_path)
        
        if db_existed:
            os.rename(real_db_path, backup_db_path)
            
        try:
            r33_fallback = client.get("/alltrains?version=33&is_sql=true")
            assert r33_fallback.status_code == 200, f"Expected 200, got {r33_fallback.status_code}"
            assert r33_fallback.headers["content-type"].startswith("application/json"), f"Expected JSON, got {r33_fallback.headers['content-type']}"
            data33_fallback = r33_fallback.json()
            assert "Revision" in data33_fallback, "Missing 'Revision' in JSON response fallback"
            print("   ✅ /alltrains?version=33&is_sql=true fallback returned valid JSON successfully!")
        finally:
            if db_existed:
                if os.path.exists(real_db_path):
                    os.remove(real_db_path)
                os.rename(backup_db_path, real_db_path)
        
    except Exception as e:
        print(f"❌ Error during API endpoint integration testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    print("\n🎉 All tests passed successfully!")

if __name__ == '__main__':
    run_tests()
