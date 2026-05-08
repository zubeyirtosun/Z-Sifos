import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "z_sifos.db")

def migrate():
    print(f"Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Update 'agents' table
    print("Checking 'agents' table...")
    cursor.execute("PRAGMA table_info(agents)")
    agent_columns = [col[1] for col in cursor.fetchall()]
    
    if "mcp_enabled" not in agent_columns:
        print("Adding 'mcp_enabled' to 'agents' table...")
        cursor.execute("ALTER TABLE agents ADD COLUMN mcp_enabled BOOLEAN DEFAULT 0")
    else:
        print("'mcp_enabled' already exists in 'agents'.")

    # 2. Update 'metrics' table
    print("Checking 'metrics' table...")
    cursor.execute("PRAGMA table_info(metrics)")
    metrics_columns = [col[1] for col in cursor.fetchall()]
    
    missing_metrics = {
        "rag_reranking_count": "INTEGER DEFAULT 0",
        "rag_reranking_avg_improvement": "FLOAT DEFAULT 0.0",
        "rag_reranking_position_avg": "FLOAT DEFAULT 0.0"
    }
    
    for col_name, col_type in missing_metrics.items():
        if col_name not in metrics_columns:
            print(f"Adding '{col_name}' to 'metrics' table...")
            cursor.execute(f"ALTER TABLE metrics ADD COLUMN {col_name} {col_type}")
        else:
            print(f"'{col_name}' already exists in 'metrics'.")

    conn.commit()
    conn.close()
    print("Migration completed successfully.")

if __name__ == "__main__":
    migrate()
