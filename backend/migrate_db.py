import sqlite3
import os

db_path = "./antigravity_ai.db"

if not os.path.exists(db_path):
    print("Veritabanı bulunamadı, yeni veritabanı ilk başlatmada otomatik oluşacaktır.")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # --- agents tablosu güncellemeleri ---
    cursor.execute("PRAGMA table_info(agents)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "status" not in columns:
        print("Sütun ekleniyor: agents.status")
        cursor.execute("ALTER TABLE agents ADD COLUMN status TEXT DEFAULT 'ready'")
    
    if "model_metadata" not in columns:
        print("Sütun ekleniyor: agents.model_metadata")
        cursor.execute("ALTER TABLE agents ADD COLUMN model_metadata TEXT")

    if "owner_id" not in columns:
        print("Sütun ekleniyor: agents.owner_id")
        cursor.execute("ALTER TABLE agents ADD COLUMN owner_id INTEGER")

    # --- users tablosu ---
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cursor.fetchone():
        print("Tablo oluşturuluyor: users")
        cursor.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                hashed_password TEXT,
                role TEXT DEFAULT 'user',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # --- documents tablosu güncellemeleri ---
    cursor.execute("PRAGMA table_info(documents)")
    doc_columns = [col[1] for col in cursor.fetchall()]
    
    if "status" not in columns: # Wait, I should check doc_columns
        pass

    if "status" not in doc_columns:
        print("Sütun ekleniyor: documents.status")
        cursor.execute("ALTER TABLE documents ADD COLUMN status TEXT DEFAULT 'pending'")
    
    if "error_message" not in doc_columns:
        print("Sütun ekleniyor: documents.error_message")
        cursor.execute("ALTER TABLE documents ADD COLUMN error_message TEXT")

    conn.commit()
    conn.close()
    print("Veritabanı başarıyla güncellendi.")
