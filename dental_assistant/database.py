import sqlite3
from pathlib import Path
from models import Book
from config import DB_PATH


class BookRepository:
    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                author      TEXT NOT NULL,
                genre       TEXT DEFAULT '',
                year        INTEGER,
                publisher   TEXT DEFAULT '',
                language    TEXT DEFAULT '',
                isbn        TEXT DEFAULT '',
                pages       INTEGER,
                notes       TEXT DEFAULT '',
                file_path   TEXT DEFAULT '',
                processed   INTEGER DEFAULT 0,
                date_added  TEXT DEFAULT ''
            )
        """)
        # migrate: add file_path if it doesn't exist yet
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(books)").fetchall()]
        if "file_path" not in cols:
            self._conn.execute("ALTER TABLE books ADD COLUMN file_path TEXT DEFAULT ''")
        if "processed" not in cols:
            self._conn.execute("ALTER TABLE books ADD COLUMN processed INTEGER DEFAULT 0")
        self._conn.commit()

    def _row_to_book(self, row: sqlite3.Row) -> Book:
        return Book(
            id=row["id"],
            title=row["title"],
            author=row["author"],
            genre=row["genre"] or "",
            year=row["year"],
            publisher=row["publisher"] or "",
            language=row["language"] or "",
            isbn=row["isbn"] or "",
            pages=row["pages"],
            notes=row["notes"] or "",
            file_path=row["file_path"] or "",
            processed=bool(row["processed"]) if "processed" in row.keys() else False,
            date_added=row["date_added"] or "",
        )

    def add_book(self, book: Book) -> int:
        cur = self._conn.execute(
            """INSERT INTO books (title, author, genre, year, publisher, language,
                                  isbn, pages, notes, file_path, processed, date_added)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (book.title, book.author, book.genre, book.year, book.publisher,
             book.language, book.isbn, book.pages, book.notes,
             book.file_path, int(book.processed), book.date_added)
        )
        self._conn.commit()
        return cur.lastrowid

    def update_book(self, book: Book):
        self._conn.execute(
            """UPDATE books SET title=?, author=?, genre=?, year=?, publisher=?,
                               language=?, isbn=?, pages=?, notes=?, processed=?
               WHERE id=?""",
            (book.title, book.author, book.genre, book.year, book.publisher,
             book.language, book.isbn, book.pages, book.notes, int(book.processed), book.id)
        )
        self._conn.commit()

    def set_file_path(self, book_id: int, file_path: str):
        self._conn.execute(
            "UPDATE books SET file_path=? WHERE id=?", (file_path, book_id)
        )
        self._conn.commit()

    def set_processed(self, book_id: int, processed: bool):
        self._conn.execute(
            "UPDATE books SET processed=? WHERE id=?",
            (1 if processed else 0, book_id),
        )
        self._conn.commit()

    def delete_book(self, book_id: int):
        self._conn.execute("DELETE FROM books WHERE id=?", (book_id,))
        self._conn.commit()

    def get_by_id(self, book_id: int) -> Book | None:
        row = self._conn.execute(
            "SELECT * FROM books WHERE id=?", (book_id,)
        ).fetchone()
        return self._row_to_book(row) if row else None

    def get_all(self) -> list[Book]:
        rows = self._conn.execute(
            "SELECT * FROM books ORDER BY genre, author, title"
        ).fetchall()
        return [self._row_to_book(r) for r in rows]

    def search(self, query: str, field: str = "all") -> list[Book]:
        q = f"%{query}%"
        if field == "all":
            rows = self._conn.execute(
                """SELECT * FROM books
                   WHERE title LIKE ? OR author LIKE ? OR genre LIKE ?
                      OR publisher LIKE ? OR notes LIKE ?
                   ORDER BY genre, author, title""",
                (q, q, q, q, q)
            ).fetchall()
        elif field == "year":
            rows = self._conn.execute(
                "SELECT * FROM books WHERE CAST(year AS TEXT) LIKE ? ORDER BY year",
                (q,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT * FROM books WHERE {field} LIKE ? ORDER BY genre, author, title",
                (q,)
            ).fetchall()
        return [self._row_to_book(r) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]

    def close(self):
        self._conn.close()

"""
Online source finder for books from legitimate internet catalogs and open-access
libraries.

Two main entry points:
  - find_file_for_book(book): best open file download when available
  - find_online_sources(book): ranked list of legal online sources / previews
"""