"""
Simple filesystem storage client that replaces boto3 S3 client.
No S3 API emulation - direct filesystem operations.
"""

import os
import shutil
from pathlib import Path


class LocalStorage:
    """
    Drop-in replacement for boto3 S3 client using local filesystem.
    Simpler than MinIO - no S3 protocol overhead.
    """
    
    def __init__(self, base_path=None):
        """
        Initialize local storage.
        
        Args:
            base_path: Base directory for file storage.
                      If None, reads from STORAGE_PATH environment variable.
                      Default: ~/verdad_debates_storage
        """
        if base_path is None:
            base_path = os.getenv(
                'STORAGE_PATH',
                '~/verdad_debates_storage'
            )
        
        # Expand ~ and ensure absolute path
        self.base_path = os.path.abspath(os.path.expanduser(base_path))
        Path(self.base_path).mkdir(parents=True, exist_ok=True)
        
        print(f"LocalStorage initialized at: {self.base_path}")
    
    def upload_file(self, local_path, bucket_name, remote_path):
        """
        Upload file to local storage.
        
        Args:
            local_path: Path to local file
            bucket_name: Ignored (kept for compatibility with boto3)
            remote_path: Destination path relative to base_path
        
        Returns:
            Absolute path to stored file
        """
        # Create full destination path
        dest_path = os.path.join(self.base_path, remote_path)
        
        # Create parent directories
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        # Copy file
        shutil.copy2(local_path, dest_path)
        
        print(f"✓ Uploaded: {local_path} → {dest_path}")
        return dest_path
    
    def download_file(self, bucket_name, remote_path, local_path):
        """
        Download file from local storage.
        
        Args:
            bucket_name: Ignored (kept for compatibility with boto3)
            remote_path: Source path relative to base_path
            local_path: Destination path
        
        Returns:
            Absolute path to downloaded file
        """
        # Create full source path
        source_path = os.path.join(self.base_path, remote_path)
        
        # Check if file exists
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"File not found: {source_path}")
        
        # Create parent directories for destination
        os.makedirs(os.path.dirname(os.path.abspath(local_path)), exist_ok=True)
        
        # Copy file
        shutil.copy2(source_path, local_path)
        
        print(f"✓ Downloaded: {source_path} → {local_path}")
        return os.path.abspath(local_path)
    
    def delete_object(self, Bucket, Key):
        """
        Delete file from local storage.
        
        Args:
            Bucket: Ignored (kept for compatibility with boto3)
            Key: File path relative to base_path
        """
        file_path = os.path.join(self.base_path, Key)
        
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"✓ Deleted: {file_path}")
        else:
            print(f"⚠ File not found (already deleted?): {file_path}")
    
    def get_file_path(self, remote_path):
        """
        Get absolute path to a file in storage.
        Useful for direct file access without copying.
        
        Args:
            remote_path: File path relative to base_path
        
        Returns:
            Absolute path to file
        """
        return os.path.join(self.base_path, remote_path)
    
    def list_files(self, prefix=""):
        """
        List all files under a prefix.
        
        Args:
            prefix: Directory prefix to list
        
        Returns:
            List of file paths relative to base_path
        """
        search_path = os.path.join(self.base_path, prefix)
        
        if not os.path.exists(search_path):
            return []
        
        files = []
        for root, dirs, filenames in os.walk(search_path):
            for filename in filenames:
                full_path = os.path.join(root, filename)
                relative_path = os.path.relpath(full_path, self.base_path)
                files.append(relative_path)
        
        return files
