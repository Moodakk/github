import csv
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOOKS_DB = ROOT / "books.db"
DOCS_DB = ROOT / "dental_bot" / "data" / "library.db"
REPORTS_DIR = ROOT / "reports"

STOPWORDS = {
    "a",
    "and",
    "book",
    "books",
    "clinical",
    "dil",
    "do",
    "edition",
    "et",
    "al",
    "i",
    "ii",
    "iii",
    "iv",
    "kol",
    "na",
    "of",
    "oral",
    "or",
    "pro",
    "s",
    "the",
    "u",
    "v",
    "vydani",
    "vydani",
    "z",
}
GENERIC_TITLES = {
    "",
    "3",
    "7",
    "aa",
    "cebny plan",
    "doporucena literatura",
    "doporu ena literatura",
    "info",
    "lll",
    "o",
}


def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = REPORTS_DIR / f"local_holdings_{timestamp}.csv"
    html_path = REPORTS_DIR / f"local_holdings_{timestamp}.html"

    books_conn = sqlite3.connect(str(BOOKS_DB))
    books_conn.row_factory = sqlite3.Row
    docs_conn = sqlite3.connect(str(DOCS_DB))
    docs_conn.row_factory = sqlite3.Row

    try:
        books = books_conn.execute(
            "SELECT id, genre, title, author, year, publisher, file_path FROM books ORDER BY genre, author, title"
        ).fetchall()
        docs = docs_conn.execute(
            "SELECT id, title, path, chunk_count, language, extra_json FROM documents ORDER BY path"
        ).fetchall()
        first_chunks = {
            row["document_id"]: row["text"]
            for row in docs_conn.execute(
                "SELECT document_id, text FROM chunks WHERE chunk_index=0"
            )
        }
    finally:
        docs_conn.close()

    matches: list[dict] = []
    medium_matches: list[dict] = []
    matched_doc_paths: set[str] = set()

    for book in books:
        match = _find_best_match(book, docs, first_chunks)
        if not match:
            continue
        if match["confidence"] == "high":
            matches.append(match)
            matched_doc_paths.add(match["doc_path"])
        elif match["confidence"] == "medium":
            medium_matches.append(match)

    updated = 0
    try:
        for item in matches:
            if item["current_file_path"] != item["doc_path"]:
                books_conn.execute(
                    "UPDATE books SET file_path=? WHERE id=?",
                    (item["doc_path"], item["book_id"]),
                )
                updated += 1
        books_conn.commit()
    finally:
        books_conn.close()

    unmatched_docs = []
    for doc in docs:
        if doc["path"] in matched_doc_paths:
            continue
        unmatched_docs.append(
            {
                "section": _section_from_path(doc["path"]),
                "title": doc["title"],
                "clean_title": _clean_title(doc["title"], doc["path"]),
                "path": doc["path"],
                "chunk_count": doc["chunk_count"],
                "language": doc["language"],
                "generic": _normalize(doc["title"]) in GENERIC_TITLES,
            }
        )

    _write_csv(csv_path, matches, medium_matches, unmatched_docs)
    _write_html(html_path, matches, medium_matches, unmatched_docs, updated)

    print(f"High-confidence holdings: {len(matches)}")
    print(f"Medium-confidence holdings: {len(medium_matches)}")
    print(f"Unmatched local docs: {len(unmatched_docs)}")
    print(f"Updated books.db file_path rows: {updated}")
    print(f"CSV report: {csv_path}")
    print(f"HTML report: {html_path}")


def _find_best_match(book: sqlite3.Row, docs: list[sqlite3.Row], first_chunks: dict[int, str]) -> dict | None:
    book_title_norm = _normalize(book["title"])
    book_title_tokens = _tokens(book["title"])
    author_tokens = _tokens(book["author"])[:2]
    if not book_title_tokens:
        return None

    best: dict | None = None
    for doc in docs:
        doc_title_norm = _normalize(doc["title"])
        path_norm = _normalize(doc["path"])
        chunk_norm = _normalize(first_chunks.get(doc["id"], "")[:1800])

        title_area = path_norm if doc_title_norm in GENERIC_TITLES else f"{doc_title_norm} {path_norm}"
        title_hits = sum(1 for token in book_title_tokens if token in title_area)
        author_hits = sum(1 for token in author_tokens if token in title_area or token in chunk_norm)
        phrase_hit = book_title_norm in title_area if book_title_norm else False
        chunk_phrase_hit = book_title_norm in chunk_norm if book_title_norm else False

        score = (title_hits / len(book_title_tokens)) * 0.8
        if author_tokens:
            score += (author_hits / len(author_tokens)) * 0.2
        if phrase_hit:
            score += 0.5
        if chunk_phrase_hit and doc_title_norm not in GENERIC_TITLES:
            score += 0.15
        if "podshivka" in path_norm or "castina" in path_norm or "cast" in path_norm:
            score += 0.05
        if doc_title_norm in GENERIC_TITLES and not phrase_hit:
            score -= 0.35

        candidate = {
            "book_id": book["id"],
            "section": book["genre"],
            "book_title": book["title"],
            "book_author": book["author"],
            "book_year": book["year"] or "",
            "publisher": book["publisher"] or "",
            "current_file_path": book["file_path"] or "",
            "doc_title": doc["title"],
            "clean_doc_title": _clean_title(doc["title"], doc["path"]),
            "doc_path": doc["path"],
            "doc_section": _section_from_path(doc["path"]),
            "chunk_count": doc["chunk_count"],
            "language": doc["language"],
            "score": round(score, 3),
            "phrase_hit": phrase_hit,
            "generic_doc_title": doc_title_norm in GENERIC_TITLES,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    if not best:
        return None
    if best["score"] >= 0.8:
        best["confidence"] = "high"
        return best
    if best["score"] >= 0.6:
        best["confidence"] = "medium"
        return best
    return None


def _write_csv(path: Path, matches: list[dict], medium_matches: list[dict], unmatched_docs: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["High-confidence holdings"])
        writer.writerow(
            [
                "Section",
                "Book title",
                "Author",
                "Score",
                "Detected title",
                "Path",
                "Folder",
                "Chunks",
                "Language",
            ]
        )
        for row in matches:
            writer.writerow(
                [
                    row["section"],
                    row["book_title"],
                    row["book_author"],
                    row["score"],
                    row["clean_doc_title"],
                    row["doc_path"],
                    row["doc_section"],
                    row["chunk_count"],
                    row["language"],
                ]
            )

        writer.writerow([])
        writer.writerow(["Medium-confidence holdings"])
        writer.writerow(
            [
                "Section",
                "Book title",
                "Author",
                "Score",
                "Detected title",
                "Path",
                "Folder",
                "Chunks",
                "Language",
            ]
        )
        for row in medium_matches:
            writer.writerow(
                [
                    row["section"],
                    row["book_title"],
                    row["book_author"],
                    row["score"],
                    row["clean_doc_title"],
                    row["doc_path"],
                    row["doc_section"],
                    row["chunk_count"],
                    row["language"],
                ]
            )

        writer.writerow([])
        writer.writerow(["Unmatched local docs"])
        writer.writerow(
            [
                "Folder",
                "Detected title",
                "Original OCR title",
                "Path",
                "Chunks",
                "Language",
                "Generic OCR title",
            ]
        )
        for row in unmatched_docs:
            writer.writerow(
                [
                    row["section"],
                    row["clean_title"],
                    row["title"],
                    row["path"],
                    row["chunk_count"],
                    row["language"],
                    "yes" if row["generic"] else "no",
                ]
            )


def _write_html(
    path: Path,
    matches: list[dict],
    medium_matches: list[dict],
    unmatched_docs: list[dict],
    updated: int,
) -> None:
    counts = Counter(item["section"] for item in matches)
    unmatched_by_folder = Counter(item["section"] for item in unmatched_docs)

    def rows_for(items: list[dict], *, unmatched: bool = False) -> str:
        html_rows = []
        for item in items:
            if unmatched:
                html_rows.append(
                    "<tr>"
                    f"<td>{escape(item['section'])}</td>"
                    f"<td>{escape(item['clean_title'])}</td>"
                    f"<td>{escape(item['title'])}</td>"
                    f"<td>{item['chunk_count']}</td>"
                    f"<td>{escape(item['language'])}</td>"
                    f"<td>{'yes' if item['generic'] else 'no'}</td>"
                    f"<td>{escape(item['path'])}</td>"
                    "</tr>"
                )
            else:
                html_rows.append(
                    "<tr>"
                    f"<td>{escape(item['section'])}</td>"
                    f"<td>{escape(item['book_title'])}</td>"
                    f"<td>{escape(item['book_author'])}</td>"
                    f"<td>{item['score']}</td>"
                    f"<td>{escape(item['clean_doc_title'])}</td>"
                    f"<td>{escape(item['doc_section'])}</td>"
                    f"<td>{item['chunk_count']}</td>"
                    f"<td>{escape(item['language'])}</td>"
                    f"<td>{escape(item['doc_path'])}</td>"
                    "</tr>"
                )
        return "".join(html_rows)

    by_section = "".join(
        f"<li>{escape(section)}: {count}</li>"
        for section, count in sorted(counts.items())
    )
    unmatched_section = "".join(
        f"<li>{escape(section)}: {count}</li>"
        for section, count in sorted(unmatched_by_folder.items())
    )

    document = f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <title>Local holdings report</title>
  <style>
    body {{
      font-family: "Segoe UI", Tahoma, sans-serif;
      margin: 24px;
      color: #1f2937;
      background: #f8fafc;
    }}
    h1, h2 {{
      margin-bottom: 8px;
    }}
    .summary {{
      margin-bottom: 20px;
      padding: 14px 16px;
      background: #e0f2fe;
      border-radius: 12px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      margin-bottom: 20px;
    }}
    .card {{
      background: white;
      padding: 14px 16px;
      border-radius: 12px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
      margin-bottom: 24px;
    }}
    th, td {{
      border: 1px solid #dbe4ee;
      padding: 8px;
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }}
    th {{
      background: #dbeafe;
      position: sticky;
      top: 0;
    }}
    tr:nth-child(even) {{
      background: #f8fafc;
    }}
    .mono {{
      font-family: Consolas, monospace;
      word-break: break-all;
    }}
  </style>
</head>
<body>
  <h1>Апробаційні книжки та лекції: локальні книжкові знахідки</h1>
  <div class="summary">
    <div>High-confidence holdings: {len(matches)}</div>
    <div>Medium-confidence holdings: {len(medium_matches)}</div>
    <div>Unmatched local docs: {len(unmatched_docs)}</div>
    <div>books.db rows updated with file_path: {updated}</div>
    <div>Generated: {escape(datetime.now().isoformat(timespec="seconds"))}</div>
  </div>
  <div class="grid">
    <div class="card">
      <h2>High-confidence by section</h2>
      <ul>{by_section or '<li>—</li>'}</ul>
    </div>
    <div class="card">
      <h2>Unmatched docs by folder</h2>
      <ul>{unmatched_section or '<li>—</li>'}</ul>
    </div>
  </div>
  <h2>High-confidence holdings</h2>
  <table>
    <thead>
      <tr>
        <th>Section</th>
        <th>Book title</th>
        <th>Author</th>
        <th>Score</th>
        <th>Detected title</th>
        <th>Folder</th>
        <th>Chunks</th>
        <th>Language</th>
        <th>Path</th>
      </tr>
    </thead>
    <tbody>{rows_for(matches)}</tbody>
  </table>
  <h2>Medium-confidence holdings</h2>
  <table>
    <thead>
      <tr>
        <th>Section</th>
        <th>Book title</th>
        <th>Author</th>
        <th>Score</th>
        <th>Detected title</th>
        <th>Folder</th>
        <th>Chunks</th>
        <th>Language</th>
        <th>Path</th>
      </tr>
    </thead>
    <tbody>{rows_for(medium_matches)}</tbody>
  </table>
  <h2>Unmatched local docs</h2>
  <table>
    <thead>
      <tr>
        <th>Folder</th>
        <th>Clean title</th>
        <th>Original OCR title</th>
        <th>Chunks</th>
        <th>Language</th>
        <th>Generic OCR title</th>
        <th>Path</th>
      </tr>
    </thead>
    <tbody>{rows_for(unmatched_docs, unmatched=True)}</tbody>
  </table>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def _clean_title(title: str, path: str) -> str:
    normalized = _normalize(title)
    if normalized in GENERIC_TITLES:
        stem = Path(path).stem
        return stem
    return title.strip()[:220] or Path(path).stem


def _section_from_path(path: str) -> str:
    parts = Path(path).parts
    if len(parts) >= 2:
        return parts[-2]
    return ""


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in _normalize(text).split()
        if len(token) >= 3 and token not in STOPWORDS
    ]


if __name__ == "__main__":
    main()

import csv
import sys
from datetime import datetime
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import BookRepository
from find_files import find_online_sources, render_sources_html


REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def generate_report() -> dict:
    repo = BookRepository()
    try:
        books = repo.get_all()
    finally:
        repo.close()

    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = REPORTS_DIR / f"stomatology_online_sources_{timestamp}.csv"
    html_path = REPORTS_DIR / f"stomatology_online_sources_{timestamp}.html"

    rows = []
    found = 0
    strong = 0

    for index, book in enumerate(books, start=1):
        sources = find_online_sources(book)
        best = sources[0] if sources else None
        if best:
            found += 1
            if best.get("match_score", 0) >= 0.75:
                strong += 1

        rows.append(
            {
                "idx": index,
                "genre": book.genre,
                "title": book.title,
                "author": book.author,
                "year": book.year or "",
                "publisher": book.publisher,
                "best_source": best["source"] if best else "",
                "best_access": best["access"] if best else "",
                "best_score": f'{best["match_score"]:.3f}' if best else "",
                "best_note": best.get("note", "") if best else "",
                "best_url": best["url"] if best else "",
                "all_sources": " | ".join(
                    f'{item["source"]} [{item.get("access", "catalog")}] {item["url"]}'
                    for item in sources[:5]
                ),
                "sources": sources,
            }
        )

    _write_csv(csv_path, rows)
    _write_html(html_path, rows, total=len(rows), found=found, strong=strong)

    return {
        "total": len(rows),
        "found": found,
        "strong": strong,
        "csv_path": csv_path,
        "html_path": html_path,
    }


def main():
    result = generate_report()
    print(f"Books processed: {result['total']}")
    print(f"Books with at least one online lead: {result['found']}")
    print(f"High-confidence matches (score >= 0.75): {result['strong']}")
    print(f"CSV report: {result['csv_path']}")
    print(f"HTML report: {result['html_path']}")


def _write_csv(path: Path, rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "№",
                "Section",
                "Title",
                "Author",
                "Year",
                "Publisher",
                "Best source",
                "Access",
                "Score",
                "Note",
                "URL",
                "Alternative sources",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["idx"],
                    row["genre"],
                    row["title"],
                    row["author"],
                    row["year"],
                    row["publisher"],
                    row["best_source"],
                    row["best_access"],
                    row["best_score"],
                    row["best_note"],
                    row["best_url"],
                    row["all_sources"],
                ]
            )


def _write_html(path: Path, rows: list[dict], total: int, found: int, strong: int):
    html_rows = []
    for row in rows:
        score = row["best_score"] or "-"
        best_url = row["best_url"]
        best_link = (
            f'<a href="{escape(best_url, quote=True)}" target="_blank">open</a>'
            if best_url
            else "-"
        )
        html_rows.append(
            "<tr>"
            f"<td>{row['idx']}</td>"
            f"<td>{escape(row['genre'])}</td>"
            f"<td>{escape(row['title'])}</td>"
            f"<td>{escape(row['author'])}</td>"
            f"<td>{escape(str(row['year']))}</td>"
            f"<td>{escape(row['best_source'])}</td>"
            f"<td>{escape(row['best_access'])}</td>"
            f"<td>{score}</td>"
            f"<td>{escape(row['best_note'])}</td>"
            f"<td>{best_link}</td>"
            f"<td>{render_sources_html(row['sources'])}</td>"
            "</tr>"
        )

    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Stomatology online sources</title>
  <style>
    body {{
      font-family: "Segoe UI", Tahoma, sans-serif;
      margin: 24px;
      color: #1f2937;
      background: #f8fafc;
    }}
    h1 {{
      margin-bottom: 8px;
    }}
    .summary {{
      margin-bottom: 18px;
      padding: 14px 16px;
      background: #e0f2fe;
      border-radius: 10px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
    }}
    th, td {{
      border: 1px solid #dbe4ee;
      padding: 8px;
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #dbeafe;
    }}
    tr:nth-child(even) {{
      background: #f8fafc;
    }}
    .access {{
      color: #475569;
      font-size: 12px;
    }}
    a {{
      color: #0f766e;
      text-decoration: none;
    }}
    a:hover {{
      text-decoration: underline;
    }}
  </style>
</head>
<body>
  <h1>Stomatology literature: online sources</h1>
  <div class="summary">
    <div>Total books: {total}</div>
    <div>Books with at least one online lead: {found}</div>
    <div>High-confidence matches: {strong}</div>
    <div>Generated: {escape(datetime.now().isoformat(timespec="seconds"))}</div>
  </div>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Section</th>
        <th>Title</th>
        <th>Author</th>
        <th>Year</th>
        <th>Best source</th>
        <th>Access</th>
        <th>Score</th>
        <th>Note</th>
        <th>Best link</th>
        <th>Other legal sources</th>
      </tr>
    </thead>
    <tbody>
      {''.join(html_rows)}
    </tbody>
  </table>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "books.db"

WINDOW_TITLE = "Каталог книг — Stomatologie"
WINDOW_MIN_WIDTH = 1050
WINDOW_MIN_HEIGHT = 620

GENRES = [
    "Знайдена література",
    "Orální chirurgie", "Konzervační zubní lékařství", "Parodontologie",
    "Protetika", "Ortodoncie", "Dětské zubní lékařství",
    "Stomatologie (загальне)", "Анатомія", "Фізіологія",
    "Хірургія", "Терапія", "Педіатрія", "Інше"
]

LANGUAGES = ["Čeština", "Slovenčina", "English", "Українська", "Deutsch", "Інша"]

TABLE_COLUMNS = [
    ("title",     "Назва",       300),
    ("author",    "Автор",       200),
    ("genre",     "Розділ",      160),
    ("year",      "Рік",          55),
    ("publisher", "Видавництво", 150),
    ("language",  "Мова",         75),
]
