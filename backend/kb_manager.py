import os
import hashlib
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

DB_NAME = "mailguard.db"

class KBFileManager:
    def __init__(self, kb_dir: str = "knowledge_base"):
        self.kb_dir = kb_dir
        # Create knowledge_base directory if it doesn't exist
        os.makedirs(kb_dir, exist_ok=True)
        
    def calculate_file_hash(self, filepath: str) -> str:
        """Calculate MD5 hash of file for change detection."""
        hash_md5 = hashlib.md5()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"Error calculating hash for {filepath}: {e}")
            return ""
    
    def scan_directory(self) -> List[Dict]:
        """Scan KB directory and return list of all files with metadata."""
        files = []
        kb_path = Path(self.kb_dir)
        
        if not kb_path.exists():
            return files
            
        for file_path in kb_path.rglob("*"):
            if file_path.is_file():
                try:
                    stat = file_path.stat()
                    file_info = {
                        "filename": file_path.name,
                        "path": str(file_path.relative_to(kb_path)),
                        "full_path": str(file_path),
                        "size": stat.st_size,
                        "hash": self.calculate_file_hash(str(file_path)),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    }
                    files.append(file_info)
                except Exception as e:
                    print(f"Error scanning file {file_path}: {e}")
        
        return files
    
    def get_all_files(self) -> List[Dict]:
        """Get all files from database."""
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("""
            SELECT * FROM kb_files 
            WHERE is_active = 1 
            ORDER BY upload_time DESC
        """)
        
        rows = c.fetchall()
        files = []
        for row in rows:
            # Check if columns exist (handle old schema gracefully if needed, though migration covers it)
            # dict(row) or row.keys() can be used to check existence, 
            # but usually row['column'] works if the query was SELECT * and column exists.
            
            files.append({
                "id": row["id"],
                "filename": row["filename"],
                "file_path": row["file_path"],
                "file_size": row["file_size"],
                "file_hash": row["file_hash"],
                "version": row["version"],
                "upload_time": row["upload_time"],
                "last_modified": row["last_modified"],
                "sync_status": row["sync_status"],
                "sync_time": row["sync_time"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                "category": row["category"] if "category" in row.keys() else None,
                "expiry_date": row["expiry_date"] if "expiry_date" in row.keys() else None
            })
        
        conn.close()
        return files
    
    def detect_changes(self) -> Dict:
        """Detect new, modified, and deleted files."""
        current_files = self.scan_directory()
        db_files = self.get_all_files()
        
        # Create lookup dictionaries
        current_by_path = {f["path"]: f for f in current_files}
        db_by_path = {f["file_path"]: f for f in db_files}
        
        new_files = []
        modified_files = []
        deleted_files = []
        
        # Check for new and modified files
        for path, file_info in current_by_path.items():
            if path not in db_by_path:
                # New file
                new_files.append(file_info)
            else:
                # Check if modified (hash changed)
                db_file = db_by_path[path]
                if file_info["hash"] != db_file["file_hash"]:
                    modified_files.append({
                        **file_info,
                        "db_id": db_file["id"],
                        "old_version": db_file["version"]
                    })
        
        # Check for deleted files
        for path, db_file in db_by_path.items():
            if path not in current_by_path:
                deleted_files.append(db_file)
        
        return {
            "new": new_files,
            "modified": modified_files,
            "deleted": deleted_files,
            "summary": {
                "new_count": len(new_files),
                "modified_count": len(modified_files),
                "deleted_count": len(deleted_files)
            }
        }
    
    def add_file(self, file_info: Dict) -> int:
        """Add new file to database."""
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        c.execute("""
            INSERT INTO kb_files 
            (filename, file_path, file_size, file_hash, version, upload_time, last_modified, sync_status)
            VALUES (?, ?, ?, ?, 1, ?, ?, 'pending')
        """, (
            file_info["filename"],
            file_info["path"],
            file_info["size"],
            file_info["hash"],
            datetime.now().isoformat(),
            file_info["modified"]
        ))
        
        file_id = c.lastrowid
        
        # Add initial version record
        c.execute("""
            INSERT INTO kb_file_versions 
            (file_id, version, file_hash, file_size, created_at)
            VALUES (?, 1, ?, ?, ?)
        """, (file_id, file_info["hash"], file_info["size"], datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        print(f"Added new file: {file_info['filename']} (ID: {file_id})")
        return file_id
    
    def update_file_version(self, db_id: int, file_info: Dict, old_version: int) -> int:
        """Create new version for modified file."""
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        new_version = old_version + 1
        
        # Update main file record
        c.execute("""
            UPDATE kb_files 
            SET file_hash = ?, file_size = ?, version = ?, last_modified = ?, sync_status = 'pending'
            WHERE id = ?
        """, (file_info["hash"], file_info["size"], new_version, file_info["modified"], db_id))
        
        # Add version record
        c.execute("""
            INSERT INTO kb_file_versions 
            (file_id, version, file_hash, file_size, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (db_id, new_version, file_info["hash"], file_info["size"], datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        print(f"Updated file to version {new_version}: {file_info['filename']}")
        return new_version
    
    def mark_file_deleted(self, file_id: int):
        """Mark file as deleted (soft delete)."""
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        c.execute("UPDATE kb_files SET is_active = 0 WHERE id = ?", (file_id,))
        
        conn.commit()
        conn.close()
        
        print(f"Marked file as deleted: ID {file_id}")
    
    def get_file_history(self, file_id: int) -> List[Dict]:
        """Get version history for a file."""
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("""
            SELECT * FROM kb_file_versions 
            WHERE file_id = ? 
            ORDER BY version DESC
        """, (file_id,))
        
        rows = c.fetchall()
        history = []
        for row in rows:
            history.append({
                "id": row["id"],
                "version": row["version"],
                "file_hash": row["file_hash"],
                "file_size": row["file_size"],
                "created_at": row["created_at"],
                "backup_path": row["backup_path"]
            })
        
        conn.close()
        return history
    
    def auto_sync_changes(self) -> Dict:
        """Automatically detect and sync all changes."""
        changes = self.detect_changes()
        
        # Add new files
        for file_info in changes["new"]:
            self.add_file(file_info)
        
        # Update modified files
        for file_info in changes["modified"]:
            self.update_file_version(
                file_info["db_id"],
                file_info,
                file_info["old_version"]
            )
        
        # Mark deleted files
        for file_info in changes["deleted"]:
            self.mark_file_deleted(file_info["id"])
        
        return {
            "status": "success",
            "changes": changes["summary"],
            "message": f"Synced {changes['summary']['new_count']} new, {changes['summary']['modified_count']} modified, {changes['summary']['deleted_count']} deleted files"
        }
