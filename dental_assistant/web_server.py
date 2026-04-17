"""
Flask web server for the Book Catalog.
Run:  python web/server.py
Then open http://localhost:5000
"""
import sys
from pathlib import Path

# project root on path so database / models / config are importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import json
import queue
import threading
import requests as http
from flask import Flask, jsonify, request, abort, render_template, Response, stream_with_context, send_file
from werkzeug.utils import secure_filename
from database import BookRepository
from find_files import find_online_sources
from models import Book

app = Flask(__name__, template_folder="templates", static_folder="static")
repo = BookRepository()

FILES_DIR = ROOT / "files"
FILES_DIR.mkdir(exist_ok=True)
ALLOWED_EXT = {".pdf", ".epub", ".djvu", ".fb2", ".doc", ".docx"}


def book_to_dict(b: Book) -> dict:
    return {
        "id": b.id,
        "title": b.title,
        "author": b.author,
        "genre": b.genre,
        "year": b.year,
        "publisher": b.publisher,
        "language": b.language,
        "isbn": b.isbn,
        "pages": b.pages,
        "notes": b.notes,
        "file_path": b.file_path,
        "has_file": bool(b.file_path),
        "processed": bool(b.processed),
        "date_added": b.date_added,
    }


def dict_to_book(data: dict, book_id: int | None = None, current: Book | None = None) -> Book:
    def intval(key):
        v = data.get(key)
        try:
            return int(v) if v not in (None, "", "null") else None
        except (ValueError, TypeError):
            return None

    return Book(
        id=book_id,
        title=data.get("title", "").strip(),
        author=data.get("author", "").strip(),
        genre=data.get("genre", "").strip(),
        year=intval("year"),
        publisher=data.get("publisher", "").strip(),
        language=data.get("language", "").strip(),
        isbn=data.get("isbn", "").strip(),
        pages=intval("pages"),
        notes=data.get("notes", "").strip(),
        processed=bool(data["processed"]) if "processed" in data else bool(current.processed if current else False),
        date_added=data.get("date_added", ""),
    )


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── API ────────────────────────────────────────────────────────────────────────

@app.route("/api/books", methods=["GET"])
def list_books():
    query = request.args.get("q", "").strip()
    field = request.args.get("field", "all")
    if query:
        books = repo.search(query, field)
    else:
        books = repo.get_all()
    return jsonify([book_to_dict(b) for b in books])


@app.route("/api/books/<int:book_id>", methods=["GET"])
def get_book(book_id):
    book = repo.get_by_id(book_id)
    if not book:
        abort(404)
    return jsonify(book_to_dict(book))


@app.route("/api/books", methods=["POST"])
def create_book():
    data = request.get_json(force=True)
    if not data.get("title") or not data.get("author"):
        abort(400, "title and author are required")
    book = dict_to_book(data)
    new_id = repo.add_book(book)
    book.id = new_id
    return jsonify(book_to_dict(book)), 201


@app.route("/api/books/<int:book_id>", methods=["PUT"])
def update_book(book_id):
    current = repo.get_by_id(book_id)
    if not current:
        abort(404)
    data = request.get_json(force=True)
    if not data.get("title") or not data.get("author"):
        abort(400, "title and author are required")
    book = dict_to_book(data, book_id=book_id, current=current)
    repo.update_book(book)
    return jsonify(book_to_dict(repo.get_by_id(book_id)))


@app.route("/api/books/<int:book_id>", methods=["DELETE"])
def delete_book(book_id):
    if not repo.get_by_id(book_id):
        abort(404)
    repo.delete_book(book_id)
    return "", 204


@app.route("/api/books/<int:book_id>/sources", methods=["GET"])
def get_book_sources(book_id):
    book = repo.get_by_id(book_id)
    if not book:
        abort(404)
    return jsonify(find_online_sources(book))


@app.route("/api/books/<int:book_id>/processed", methods=["POST"])
def set_book_processed(book_id):
    book = repo.get_by_id(book_id)
    if not book:
        abort(404)
    data = request.get_json(force=True)
    processed = bool(data.get("processed", True))
    repo.set_processed(book_id, processed)
    return jsonify(book_to_dict(repo.get_by_id(book_id)))


@app.route("/api/bot/find-files")
def bot_find_files():
    """SSE: scan books without files, find open-access downloads, stream progress."""
    def sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def generate():
        from find_files import find_file_for_book
        msg_q: queue.Queue = queue.Queue()

        only_recommended = request.args.get("only_recommended", "0") == "1"

        def worker():
            all_books = [b for b in repo.get_all() if not b.file_path]
            if only_recommended:
                all_books = [b for b in all_books if b.genre != "Знайдена література"]
            books = all_books
            msg_q.put({"type": "start", "total": len(books)})
            found = []
            for i, book in enumerate(books):
                msg_q.put({"type": "checking", "index": i + 1, "total": len(books),
                            "title": book.title})
                result = find_file_for_book(book)
                if result:
                    found.append({"book_id": book.id, "title": book.title,
                                  "author": book.author, **result})
                    msg_q.put({"type": "found", "book_id": book.id,
                               "title": book.title, "source": result["source"],
                               "format": result["format"], "url": result["url"],
                               "size_mb": result.get("size_mb")})
            msg_q.put({"type": "done", "found": found})
            msg_q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            msg = msg_q.get()
            if msg is None:
                yield sse({"type": "end"})
                break
            yield sse(msg)

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/bot/download", methods=["POST"])
def bot_download():
    """Download approved files and attach to books."""
    items = request.get_json(force=True)  # [{book_id, url, format}, ...]
    results = []
    for item in items:
        book_id = item["book_id"]
        url     = item["url"]
        fmt     = item.get("format", "pdf")
        book    = repo.get_by_id(book_id)
        if not book:
            results.append({"book_id": book_id, "ok": False, "error": "not found"})
            continue
        try:
            r = http.get(url, timeout=60, stream=True)
            r.raise_for_status()
            from werkzeug.utils import secure_filename as sf
            safe = f"{book_id}_{sf(book.title[:40])}.{fmt}"
            dest = FILES_DIR / safe
            with open(str(dest), "wb") as fh:
                for chunk in r.iter_content(65536):
                    fh.write(chunk)
            repo.set_file_path(book_id, safe)
            results.append({"book_id": book_id, "ok": True, "file": safe})
        except Exception as e:
            results.append({"book_id": book_id, "ok": False, "error": str(e)})
    return jsonify(results)


@app.route("/api/books/<int:book_id>/upload", methods=["POST"])
def upload_file(book_id):
    book = repo.get_by_id(book_id)
    if not book:
        abort(404)
    if "file" not in request.files:
        abort(400, "no file")
    f = request.files["file"]
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        abort(400, f"Unsupported format: {ext}")

    # delete old file if exists
    if book.file_path:
        old = FILES_DIR / book.file_path
        if old.exists():
            old.unlink()

    safe_name = f"{book_id}_{secure_filename(f.filename)}"
    dest = FILES_DIR / safe_name
    f.save(str(dest))
    repo.set_file_path(book_id, safe_name)
    return jsonify({"file": safe_name}), 200


@app.route("/api/books/<int:book_id>/file", methods=["DELETE"])
def delete_file(book_id):
    book = repo.get_by_id(book_id)
    if not book:
        abort(404)
    if book.file_path:
        p = FILES_DIR / book.file_path
        if p.exists():
            p.unlink()
        repo.set_file_path(book_id, "")
    return "", 204


@app.route("/files/<int:book_id>")
def open_file(book_id):
    book = repo.get_by_id(book_id)
    if not book or not book.file_path:
        abort(404)
    path = FILES_DIR / book.file_path
    if not path.exists():
        abort(404)
    return send_file(str(path), as_attachment=False)


@app.route("/api/stats")
def stats():
    books = repo.get_all()
    genres: dict[str, int] = {}
    for b in books:
        genres[b.genre or "Інше"] = genres.get(b.genre or "Інше", 0) + 1
    return jsonify({"total": repo.count(), "by_genre": genres})


# ── Search page ────────────────────────────────────────────────────────────────

@app.route("/search")
def search_page():
    return render_template("search.html")


@app.route("/files-manager")
def files_manager():
    return render_template("files.html")


@app.route("/link-files")
def link_files():
    return render_template("link.html")


# ── OneDrive browser ───────────────────────────────────────────────────────────

BOOK_EXTENSIONS = {".pdf", ".epub", ".djvu", ".fb2", ".doc", ".docx"}


@app.route("/api/onedrive/browse")
def onedrive_browse():
    """Return folder tree: {subfolders: [{name, files: [{name, path, ext}]}]}"""
    import re
    folder_str = request.args.get("folder", "").strip()
    if not folder_str:
        return jsonify({"error": "folder param required"}), 400
    root = Path(folder_str)
    if not root.is_dir():
        return jsonify({"error": f"Not a directory: {folder_str}"}), 400

    subfolders = []
    # Collect files directly in root
    root_files = [p for p in sorted(root.iterdir())
                  if p.is_file() and p.suffix.lower() in BOOK_EXTENSIONS]
    if root_files:
        subfolders.append({
            "name": "(корінь)",
            "files": [{"name": p.name, "path": str(p), "ext": p.suffix.lstrip(".")} for p in root_files],
        })

    # Subdirectories
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        files = [p for p in sorted(sub.rglob("*"))
                 if p.is_file() and p.suffix.lower() in BOOK_EXTENSIONS]
        if files:
            subfolders.append({
                "name": sub.name,
                "files": [{"name": p.name, "path": str(p), "ext": p.suffix.lstrip(".")} for p in files],
            })

    return jsonify({"subfolders": subfolders})


@app.route("/api/books/<int:book_id>/link-onedrive", methods=["POST"])
def link_onedrive_file(book_id):
    """Copy a file from OneDrive path and attach it to the book."""
    import re
    book = repo.get_by_id(book_id)
    if not book:
        abort(404)
    data = request.get_json(force=True)
    src_path = Path(data.get("path", ""))
    if not src_path.is_file():
        return jsonify({"error": f"File not found: {src_path}"}), 400
    if src_path.suffix.lower() not in BOOK_EXTENSIONS:
        return jsonify({"error": "Unsupported file type"}), 400

    # Delete old file if exists
    if book.file_path:
        old = FILES_DIR / book.file_path
        if old.exists():
            old.unlink()

    safe_name = f"{book_id}_{re.sub(r'[^a-zA-Z0-9._-]', '_', src_path.name)}"
    dest = FILES_DIR / safe_name
    import shutil
    if not dest.exists():
        shutil.copy2(str(src_path), str(dest))
    repo.set_file_path(book_id, safe_name)
    return jsonify({"ok": True, "file": safe_name})


@app.route("/api/onedrive/auto-link", methods=["POST"])
def onedrive_auto_link():
    """
    Auto-match OneDrive folder files to catalog books by folder→genre mapping.
    Body: { folder, apply: bool }
    Returns: { pairs: [{book_id, book_title, file_path, file_name, folder}], unmatched_books, unmatched_files }
    """
    import re, shutil
    from collections import defaultdict

    data = request.get_json(force=True)
    folder_str = data.get("folder", "").strip()
    apply = bool(data.get("apply", False))

    root = Path(folder_str)
    if not root.is_dir():
        return jsonify({"error": f"Not a directory: {folder_str}"}), 400

    # Folder name → genre mapping (Ukrainian folder names → Czech genre names in catalog)
    FOLDER_TO_GENRE = {
        "дитинство":               "Dětské zubní lékařství",
        "ортодонтія":              "Ortodoncie",
        "ортопедія":               "Protetika",
        "парадонтологіє":          "Parodontologie",
        "парадонтологія":          "Parodontologie",
        "терапевтична":            "Konzervační zubní lékařství",
        "хірургія":                "Orální chirurgie",
        "фармакологія":            "Farmakologie",
        "соціальна медицина асорті": None,   # skip
        "скошушки конспекти":      None,     # skip
    }

    def pick_representative(files):
        """From a group of Підшивка parts, pick the best single file."""
        # Prefer file without "Частина"
        main = [f for f in files if not re.search(r'частина', f.name, re.I)]
        if main:
            return sorted(main)[0]
        # Prefer _Частина1 (not _Частина10, _Частина11 etc.)
        part1 = [f for f in files if re.search(r'Частина1(?!\d)', f.name, re.I)]
        if part1:
            return part1[0]
        return sorted(files)[0]

    def group_files_by_number(files):
        """Group files by Підшивка number → {1: best_file, 2: best_file, ...}"""
        groups = defaultdict(list)
        for f in files:
            m = re.search(r'[Пп]ідшивка(\d+)', f.name)
            if m:
                groups[int(m.group(1))].append(f)
        return {num: pick_representative(group) for num, group in sorted(groups.items())}

    books_by_genre = defaultdict(list)
    for b in repo.get_all():
        if not b.file_path:
            books_by_genre[b.genre or ""].append(b)

    pairs = []
    unmatched_books = []
    unmatched_files = []

    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        genre = FOLDER_TO_GENRE.get(sub.name.lower())
        if genre is None:
            continue  # explicitly skipped folder

        files_in_folder = [p for p in sorted(sub.rglob("*"))
                           if p.is_file() and p.suffix.lower() in BOOK_EXTENSIONS]
        file_groups = group_files_by_number(files_in_folder)

        genre_books = sorted(books_by_genre.get(genre, []), key=lambda b: b.title)

        used_nums = set()
        for idx, book in enumerate(genre_books):
            # Try file group by 1-based index
            num = idx + 1
            if num in file_groups:
                pairs.append({
                    "book_id":    book.id,
                    "book_title": book.title,
                    "file_path":  str(file_groups[num]),
                    "file_name":  file_groups[num].name,
                    "folder":     sub.name,
                    "genre":      genre,
                })
                used_nums.add(num)
            else:
                unmatched_books.append({"id": book.id, "title": book.title, "genre": genre})

        for num, f in file_groups.items():
            if num not in used_nums:
                unmatched_files.append({"name": f.name, "folder": sub.name})

    if apply:
        for pair in pairs:
            src = Path(pair["file_path"])
            book = repo.get_by_id(pair["book_id"])
            if not book or not src.is_file():
                continue
            safe_name = f"{book.id}_{re.sub(r'[^a-zA-Z0-9._-]', '_', src.name)}"
            dest = FILES_DIR / safe_name
            if not dest.exists():
                shutil.copy2(str(src), str(dest))
            repo.set_file_path(book.id, safe_name)
            pair["saved_as"] = safe_name

    return jsonify({
        "pairs":           pairs,
        "unmatched_books": unmatched_books,
        "unmatched_files": unmatched_files,
        "applied":         apply,
    })


@app.route("/api/search/online")
def search_online():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    results = []

    # ── OpenLibrary ──────────────────────────────────────────────────────────
    try:
        ol = http.get(
            "https://openlibrary.org/search.json",
            params={"q": q, "limit": 20, "fields": "key,title,author_name,first_publish_year,publisher,isbn,language,number_of_pages_median"},
            timeout=8,
        ).json()
        for doc in ol.get("docs", []):
            authors = doc.get("author_name") or []
            isbn_list = doc.get("isbn") or []
            langs = doc.get("language") or []
            results.append({
                "source": "OpenLibrary",
                "title": doc.get("title", ""),
                "author": ", ".join(authors[:3]),
                "year": doc.get("first_publish_year"),
                "publisher": (doc.get("publisher") or [""])[0],
                "isbn": isbn_list[0] if isbn_list else "",
                "language": langs[0].upper() if langs else "",
                "pages": doc.get("number_of_pages_median"),
                "notes": f"OpenLibrary key: {doc.get('key','')}",
            })
    except Exception as e:
        print(f"OpenLibrary error: {e}")

    # ── Google Books (fallback / supplement) ─────────────────────────────────
    if len(results) < 5:
        try:
            gb = http.get(
                "https://www.googleapis.com/books/v1/volumes",
                params={"q": q, "maxResults": 15, "printType": "books"},
                timeout=8,
            ).json()
            for item in gb.get("items", []):
                info = item.get("volumeInfo", {})
                isbns = {i["type"]: i["identifier"] for i in info.get("industryIdentifiers", [])}
                results.append({
                    "source": "Google Books",
                    "title": info.get("title", ""),
                    "author": ", ".join(info.get("authors", [])[:3]),
                    "year": int(info.get("publishedDate", "0")[:4]) if info.get("publishedDate") else None,
                    "publisher": info.get("publisher", ""),
                    "isbn": isbns.get("ISBN_13") or isbns.get("ISBN_10", ""),
                    "language": info.get("language", "").upper(),
                    "pages": info.get("pageCount"),
                    "notes": info.get("description", "")[:300] if info.get("description") else "",
                })
        except Exception as e:
            print(f"Google Books error: {e}")

    # deduplicate by title+author
    seen, unique = set(), []
    for r in results:
        key = (r["title"].lower(), r["author"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return jsonify(unique[:30])


@app.route("/api/bot/run")
def bot_run():
    """Server-Sent Events stream: runs the bot and pushes live progress."""
    q_str = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 20)), 60)
    if not q_str:
        return jsonify({"error": "query required"}), 400

    def sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def generate():
        msg_queue: queue.Queue = queue.Queue()

        def bot_thread():
            from bot import search_openlibrary, search_googlebooks, search_crossref, deduplicate, save_to_db

            def push(msg_type, **kwargs):
                msg_queue.put({"type": msg_type, **kwargs})

            push("status", text=f"Запускаю пошук для «{q_str}»…")
            all_results = []

            for src_name, fn in [
                ("OpenLibrary", lambda: search_openlibrary(q_str, limit)),
                ("Google Books", lambda: search_googlebooks(q_str, limit)),
                ("CrossRef",     lambda: search_crossref(q_str, limit)),
            ]:
                push("source_start", source=src_name)
                found = fn()
                push("source_done", source=src_name, count=len(found))
                all_results += found
                import time; time.sleep(0.2)

            unique = deduplicate(all_results)
            push("status", text=f"Дедублікація: {len(all_results)} → {len(unique)} унікальних")

            push("status", text="Зберігаю в базу даних…")
            added, skipped = save_to_db(unique)
            push("done", added=added, skipped=skipped, total=repo.count())
            msg_queue.put(None)  # sentinel

        threading.Thread(target=bot_thread, daemon=True).start()

        while True:
            msg = msg_queue.get()
            if msg is None:
                yield sse({"type": "end"})
                break
            yield sse(msg)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/search/save", methods=["POST"])
def save_found_book():
    data = request.get_json(force=True)
    if not data.get("title"):
        abort(400, "title is required")

    def intval(k):
        v = data.get(k)
        try:
            return int(v) if v not in (None, "", "null") else None
        except (ValueError, TypeError):
            return None

    book = Book(
        title=data["title"].strip(),
        author=data.get("author", "").strip(),
        genre="Знайдена література",
        year=intval("year"),
        publisher=data.get("publisher", "").strip(),
        language=data.get("language", "").strip(),
        isbn=data.get("isbn", "").strip(),
        pages=intval("pages"),
        notes=data.get("notes", "").strip(),
    )
    new_id = repo.add_book(book)
    book.id = new_id
    return jsonify(book_to_dict(book)), 201


if __name__ == "__main__":
    print("Book Catalog web server starting on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

from pathlib import Path

# Ensure the project root is on sys.path so imports work regardless of CWD
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tkinter import messagebox
from ui.app_window import BookCatalogApp


def main():
    try:
        app = BookCatalogApp()
        app.mainloop()
    except Exception as exc:
        messagebox.showerror("Помилка запуску", str(exc))
        raise


if __name__ == "__main__":
    main()

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Book:
    title: str
    author: str
    genre: str = ""
    year: int | None = None
    publisher: str = ""
    language: str = ""
    isbn: str = ""
    pages: int | None = None
    notes: str = ""
    file_path: str = ""
    processed: bool = False
    date_added: str = field(default_factory=lambda: date.today().isoformat())
    id: int | None = None

"""
OneDrive ↔ Catalog sync script
Scans OneDrive for book files, fuzzy-matches them to DB records,
and links matches (copies file reference into the catalog).

Usage:
    python sync_onedrive.py              # scan & report
    python sync_onedrive.py --apply      # scan, report, and link matches
    python sync_onedrive.py --threshold 60   # lower match threshold (default 70)
    python sync_onedrive.py --folder "C:/Users/vlad_/OneDrive/SomeFolder"
"""