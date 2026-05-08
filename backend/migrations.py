"""
migrations.py — Simple database migration tracking without Alembic

Provides basic migration versioning for SQLite without external dependencies.
Tracks applied migrations in database metadata table.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from sqlalchemy import Column, Integer, String, DateTime, Text, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

logger_migration = __import__("logging").getLogger("migrations")

Base = declarative_base()


class MigrationRecord(Base):
    """Track applied migrations"""
    __tablename__ = "schema_migrations"
    
    id = Column(Integer, primary_key=True)
    version = Column(String(50), unique=True, nullable=False)  # e.g., "001_initial_schema"
    description = Column(String(255))
    applied_at = Column(DateTime, default=datetime.utcnow)
    schema_hash = Column(String(64))  # SHA256 of schema after migration


class MigrationManager:
    """Manage database migrations"""
    
    def __init__(self, database_url: str, migrations_dir: str = "backend/migrations"):
        self.database_url = database_url
        self.migrations_dir = Path(migrations_dir)
        self.migrations_dir.mkdir(exist_ok=True)
        
        # Create engine and session
        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        
        # Create migrations table
        Base.metadata.create_all(self.engine)
    
    def get_applied_migrations(self) -> List[str]:
        """Get list of applied migration versions"""
        session = self.SessionLocal()
        try:
            records = session.query(MigrationRecord).order_by(MigrationRecord.applied_at).all()
            return [r.version for r in records]
        finally:
            session.close()
    
    def get_pending_migrations(self) -> List[Dict[str, Any]]:
        """Get list of pending migrations"""
        applied = set(self.get_applied_migrations())
        pending = []
        
        for migration_file in sorted(self.migrations_dir.glob("*.py")):
            version = migration_file.stem
            if version.startswith("_") or version in applied:
                continue
            
            # Parse version from filename (e.g., "001_add_users_table")
            if "_" in version:
                ver_num = version.split("_")[0]
                description = "_".join(version.split("_")[1:])
                pending.append({
                    "version": version,
                    "number": int(ver_num),
                    "description": description,
                    "file": migration_file
                })
        
        return sorted(pending, key=lambda x: x["number"])
    
    def record_migration(self, version: str, description: str, schema_hash: str = None):
        """Record a migration as applied"""
        session = self.SessionLocal()
        try:
            record = MigrationRecord(
                version=version,
                description=description,
                schema_hash=schema_hash
            )
            session.add(record)
            session.commit()
            logger_migration.info(f"Recorded migration: {version}")
        finally:
            session.close()
    
    def create_migration(self, description: str):
        """Create a new empty migration file"""
        applied_versions = self.get_applied_migrations()
        next_num = max([int(v.split("_")[0]) for v in applied_versions] + [0]) + 1
        
        version = f"{next_num:03d}_{description.replace(' ', '_').lower()}"
        filepath = self.migrations_dir / f"{version}.py"
        
        template = f'''"""
Migration: {version}

Description: {description}
Created: {datetime.utcnow().isoformat()}
"""

from sqlalchemy import text


def upgrade(connection):
    """Upgrade database schema"""
    # Add your SQL migration here
    # Example: connection.execute(text("ALTER TABLE agents ADD COLUMN new_field TEXT"))
    pass


def downgrade(connection):
    """Downgrade database schema (optional)"""
    # Add your rollback SQL migration here
    # Example: connection.execute(text("ALTER TABLE agents DROP COLUMN new_field"))
    pass
'''
        
        with open(filepath, "w") as f:
            f.write(template)
        
        logger_migration.info(f"Created migration: {version}")
        return version
    
    def run_pending_migrations(self):
        """Execute all pending migrations"""
        pending = self.get_pending_migrations()
        
        if not pending:
            logger_migration.info("No pending migrations")
            return
        
        logger_migration.info(f"Running {len(pending)} pending migrations...")
        
        for migration in pending:
            version = migration["version"]
            filepath = migration["file"]
            
            try:
                # Load and execute migration
                spec = __import__("importlib.util").util.spec_from_file_location("migration", filepath)
                module = __import__("importlib.util").util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Run upgrade function
                if hasattr(module, "upgrade"):
                    with self.engine.connect() as conn:
                        module.upgrade(conn)
                        conn.commit()
                    
                    self.record_migration(version, migration["description"])
                    logger_migration.info(f"✓ Applied: {version}")
                else:
                    logger_migration.warning(f"Migration {version} has no upgrade function")
            
            except Exception as e:
                logger_migration.error(f"✗ Failed to apply {version}: {e}")
                raise


def init_migrations(database_url: str) -> MigrationManager:
    """Initialize migration manager"""
    return MigrationManager(database_url)
