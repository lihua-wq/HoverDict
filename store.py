"""Wordbook storage: SQLite, one row per word.

Rows remember when a word was first added (added_at), when it was last seen
(last_seen) and when it was exported (exported_at) so the daily export never
hands the same word to the vocabulary app twice.
"""
import os
import sqlite3
import sys
import threading
from datetime import datetime, date


def _app_dir():
    """Where config.json / wordbook.db / hover.log live.

    A frozen (PyInstaller) build keeps them next to the exe so they survive;
    the source tree keeps them in ``data/``.
    """
    override = os.environ.get("HOVERDICT_HOME")
    if override:
        return override
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "data")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


APP_DIR = _app_dir()
DB_PATH = os.path.join(APP_DIR, "wordbook.db")

SCHEMA = """CREATE TABLE IF NOT EXISTS words(
               word TEXT PRIMARY KEY,
               added_at TEXT NOT NULL,
               count INTEGER NOT NULL DEFAULT 1,
               source TEXT DEFAULT '',
               brief TEXT DEFAULT '',
               last_seen TEXT DEFAULT '',
               exported_at TEXT DEFAULT '',
               exported_day TEXT DEFAULT ''
           )"""


class Wordbook:
    def __init__(self, path=DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(SCHEMA)
        self._migrate()
        self._conn.commit()

    # ---------- schema ----------
    def _migrate(self):
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(words)")}
        for name, ddl in (
            ("last_seen", "TEXT DEFAULT ''"),
            ("exported_at", "TEXT DEFAULT ''"),
            ("exported_day", "TEXT DEFAULT ''"),
        ):
            if name not in cols:
                self._conn.execute(f"ALTER TABLE words ADD COLUMN {name} {ddl}")

    # ---------- write ----------
    def add(self, word, source="", brief=""):
        """Insert or bump. Returns True if the word is new.

        added_at stays at the first sighting so a word keeps the day it was
        first collected (that is what the daily export groups by).
        """
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            row = self._conn.execute("SELECT count FROM words WHERE word=?", (word,)).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE words SET count=count+1, last_seen=? WHERE word=?", (now, word)
                )
                self._conn.commit()
                return False
            self._conn.execute(
                "INSERT INTO words(word, added_at, count, source, brief, last_seen)"
                " VALUES(?,?,1,?,?,?)",
                (word, now, source, brief[:300], now),
            )
            self._conn.commit()
            return True

    def mark_exported(self, words, day):
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._conn.executemany(
                "UPDATE words SET exported_at=?, exported_day=? WHERE word=?",
                [(now, day, w) for w in words],
            )
            self._conn.commit()

    def remove(self, word):
        with self._lock:
            self._conn.execute("DELETE FROM words WHERE word=?", (word,))
            self._conn.commit()

    def clear(self):
        with self._lock:
            self._conn.execute("DELETE FROM words")
            self._conn.commit()

    # ---------- read ----------
    def has(self, word):
        with self._lock:
            return self._conn.execute("SELECT 1 FROM words WHERE word=?", (word,)).fetchone() is not None

    def words(self, search=""):
        with self._lock:
            if search:
                rows = self._conn.execute(
                    "SELECT word, added_at, count, brief, exported_at FROM words WHERE word LIKE ?"
                    " ORDER BY added_at DESC",
                    (f"%{search}%",),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT word, added_at, count, brief, exported_at FROM words"
                    " ORDER BY added_at DESC"
                ).fetchall()
        return rows

    def count(self):
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]

    def pending_by_day(self, include_today=True):
        """{day: [word, ...]} for words never exported, oldest day first."""
        today = date.today().isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT word, substr(added_at,1,10) FROM words"
                " WHERE exported_at IS NULL OR exported_at='' ORDER BY added_at"
            ).fetchall()
        out = {}
        for word, day in rows:
            if not include_today and day == today:
                continue
            out.setdefault(day, []).append(word)
        return dict(sorted(out.items()))

    def exported_days(self):
        with self._lock:
            return self._conn.execute(
                "SELECT exported_day, exported_at, COUNT(*) FROM words WHERE exported_day<>''"
                " GROUP BY exported_day ORDER BY exported_day DESC"
            ).fetchall()

    # ---------- export ----------
    @staticmethod
    def _write_words(path, words, append=False):
        mode = "a" if append else "w"
        with open(path, mode, encoding="utf-8", newline="\n") as f:
            if append:
                f.write("\n")
            f.write("\n".join(words))
            f.write("\n")

    def export_txt(self, path, words=None):
        """One word per line, UTF-8 without BOM - the format bbdc.cn accepts."""
        lines = [r[0] for r in self.words()] if words is None else list(words)
        self._write_words(path, lines, append=False)
        return len(lines)

    def export_days(self, out_dir, include_today=True, prefix="hoverdict"):
        """One TXT per day for words not exported yet.

        A day that already has a file gets the new words appended, so you end up
        with exactly one file per day and no word is ever written twice.
        Returns [(path, number_of_new_words), ...].
        """
        os.makedirs(out_dir, exist_ok=True)
        written = []
        for day, words in self.pending_by_day(include_today=include_today).items():
            unique = list(dict.fromkeys(words))
            path = os.path.join(out_dir, f"{prefix}-{day}.txt")
            self._write_words(path, unique, append=os.path.exists(path))
            self.mark_exported(unique, day)
            written.append((path, len(unique)))
        return written

    def export_pending_all(self, path):
        """Single file with every word not exported yet (for a >=20 word upload)."""
        words = [w for ws in self.pending_by_day(include_today=True).values() for w in ws]
        words = list(dict.fromkeys(words))
        if not words:
            return 0
        self._write_words(path, words, append=False)
        self.mark_exported(words, date.today().isoformat())
        return len(words)
