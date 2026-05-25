"""
append-only raw HTML 存储 + SQLite index。

存储格式:
    archive/{YYYY}/{MM}/{page_type}_{entity_id}_{YYYY-MM-DDTHH:mm:ss}.html.gz

索引: archive/index.sqlite
    - url, fetched_at, page_type, entity_id, etag, content_md5, size_bytes, filename
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import sqlite3
import time as tmod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("hltv.storage.archive")


@dataclass
class ArchiveEntry:
    url: str
    fetched_at: float
    page_type: str = ""
    entity_id: str = ""
    content_md5: str = ""
    size_bytes: int = 0
    filename: str = ""
    status_code: int = 200
    transport: str = ""
    response_time: float = 0.0


class HTMLArchive:
    """
    append-only raw HTML 存储 + 查询。

    设计原则：
    - 只追加，不修改
    - 文件格式通用（gzip HTML），可直接用浏览器打开
    - SQLite 索引可独立查询
    - 支持按 URL / entity_id / 时间范围查询

    用法：
        archive = HTMLArchive(base_dir="./archive")
        await archive.store("https://...", "<html>...", {})
        latest = await archive.get_latest("https://...")
    """

    def __init__(self, base_dir: str = "./archive") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._base_dir / "index.sqlite"
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(str(self._index_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS archive_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                fetched_at REAL NOT NULL,
                page_type TEXT DEFAULT '',
                entity_id TEXT DEFAULT '',
                content_md5 TEXT DEFAULT '',
                size_bytes INTEGER DEFAULT 0,
                filename TEXT NOT NULL,
                status_code INTEGER DEFAULT 200,
                transport TEXT DEFAULT '',
                response_time REAL DEFAULT 0.0
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_url ON archive_index(url)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_fetched_at ON archive_index(fetched_at)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity ON archive_index(page_type, entity_id)
        """)
        self._conn.commit()

    async def store(
        self,
        url: str,
        html: str,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """
        存储 raw HTML 到 archive。

        Args:
            url: 源 URL
            html: 原始 HTML 内容
            metadata: 额外元信息 (status_code, transport, response_time, page_type, entity_id)

        Returns:
            存储的文件路径
        """
        meta = metadata or {}
        now = datetime.now()
        ts = now.strftime("%Y-%m-%dT%H-%M-%S")
        year = now.strftime("%Y")
        month = now.strftime("%m")

        page_type = meta.get("page_type", "unknown")
        entity_id = str(meta.get("entity_id", ""))
        content_md5 = hashlib.md5(html.encode()).hexdigest()

        # 构建文件名: {page_type}_{entity_id}_{timestamp}.html.gz
        if entity_id and entity_id != "None":
            filename = f"{page_type}_{entity_id}_{ts}.html.gz"
        else:
            # 从 URL 提取 slug
            slug = url.rstrip("/").split("/")[-1].split("?")[0] or "index"
            filename = f"{slug}_{ts}.html.gz"

        file_dir = self._base_dir / year / month
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / filename

        # 写入 gzip 压缩的 HTML
        compressed = gzip.compress(html.encode("utf-8"), compresslevel=6)
        file_path.write_bytes(compressed)

        # 写入索引
        entry = ArchiveEntry(
            url=url,
            fetched_at=tmod.time(),
            page_type=page_type,
            entity_id=entity_id,
            content_md5=content_md5,
            size_bytes=len(compressed),
            filename=str(file_path.relative_to(self._base_dir)),
            status_code=meta.get("status_code", 200),
            transport=meta.get("transport", ""),
            response_time=meta.get("response_time", 0.0),
        )
        self._insert_entry(entry)

        logger.debug("Archived: %s → %s (%d bytes)", url, file_path, len(compressed))
        return file_path

    async def get_latest(self, url: str) -> str | None:
        """获取指定 URL 最新版本的 raw HTML。"""
        if self._conn is None:
            return None
        cursor = self._conn.execute(
            "SELECT filename FROM archive_index WHERE url = ? ORDER BY fetched_at DESC LIMIT 1",
            (url,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._read_file(self._base_dir / row[0])

    async def get_versions(self, url: str, limit: int = 10) -> list[ArchiveEntry]:
        """获取指定 URL 的所有历史版本。"""
        if self._conn is None:
            return []
        cursor = self._conn.execute(
            "SELECT * FROM archive_index WHERE url = ? ORDER BY fetched_at DESC LIMIT ?",
            (url, limit),
        )
        return [self._row_to_entry(row) for row in cursor.fetchall()]

    async def get_by_entity(
        self,
        page_type: str,
        entity_id: str | int,
        limit: int = 50,
    ) -> list[ArchiveEntry]:
        """按 entity 查询所有相关页面。"""
        if self._conn is None:
            return []
        cursor = self._conn.execute(
            """SELECT * FROM archive_index
               WHERE page_type = ? AND entity_id = ?
               ORDER BY fetched_at DESC LIMIT ?""",
            (page_type, str(entity_id), limit),
        )
        return [self._row_to_entry(row) for row in cursor.fetchall()]

    async def get_by_date_range(
        self,
        start: float,
        end: float,
        page_type: str | None = None,
        limit: int = 100,
    ) -> list[ArchiveEntry]:
        """按时间范围查询。"""
        if self._conn is None:
            return []
        if page_type:
            cursor = self._conn.execute(
                """SELECT * FROM archive_index
                   WHERE fetched_at >= ? AND fetched_at <= ? AND page_type = ?
                   ORDER BY fetched_at DESC LIMIT ?""",
                (start, end, page_type, limit),
            )
        else:
            cursor = self._conn.execute(
                """SELECT * FROM archive_index
                   WHERE fetched_at >= ? AND fetched_at <= ?
                   ORDER BY fetched_at DESC LIMIT ?""",
                (start, end, limit),
            )
        return [self._row_to_entry(row) for row in cursor.fetchall()]

    async def read_content(self, entry: ArchiveEntry) -> str | None:
        """读取存档 entry 的真实 HTML 内容。"""
        return self._read_file(self._base_dir / entry.filename)

    def _insert_entry(self, entry: ArchiveEntry) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            """INSERT INTO archive_index
               (url, fetched_at, page_type, entity_id, content_md5, size_bytes, filename, status_code, transport, response_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.url, entry.fetched_at, entry.page_type, entry.entity_id,
                entry.content_md5, entry.size_bytes, entry.filename,
                entry.status_code, entry.transport, entry.response_time,
            ),
        )
        self._conn.commit()

    def _read_file(self, path: Path) -> str | None:
        if not path.exists():
            return None
        try:
            compressed = path.read_bytes()
            return gzip.decompress(compressed).decode("utf-8")
        except Exception as e:
            logger.error("Error reading archive file %s: %s", path, e)
            return None

    def _row_to_entry(self, row: sqlite3.Row) -> ArchiveEntry:
        return ArchiveEntry(
            url=row[1], fetched_at=row[2], page_type=row[3],
            entity_id=row[4], content_md5=row[5], size_bytes=row[6],
            filename=row[7], status_code=row[8], transport=row[9],
            response_time=row[10],
        )

    def get_stats(self) -> dict[str, Any]:
        if self._conn is None:
            return {"total": 0}
        cursor = self._conn.execute("SELECT COUNT(*) FROM archive_index")
        total = cursor.fetchone()[0]
        cursor = self._conn.execute(
            "SELECT page_type, COUNT(*) FROM archive_index GROUP BY page_type",
        )
        type_stats = {row[0]: row[1] for row in cursor.fetchall()}
        return {
            "total_entries": total,
            "by_type": type_stats,
            "db_path": str(self._index_path),
            "archive_dir": str(self._base_dir),
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
