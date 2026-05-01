import sys
import argparse
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests
from database import BookRepository
from models import Book

REPO = BookRepository()

SOURCES = ["openlibrary", "googlebooks", "crossref"]


# ── Sources ───────────────────────────────────────────────────────────────────

def search_openlibrary(query: str, limit: int) -> list[dict]:
    print("  [OpenLibrary] Шукаю…", end=" ", flush=True)
    try:
        r = requests.get(
            "https://openlibrary.org/search.json",
            params={
                "q": query, "limit": limit,
                "fields": "key,title,author_name,first_publish_year,publisher,isbn,language,number_of_pages_median"
            },
            timeout=10,
        )
        docs = r.json().get("docs", [])
        results = []
        for doc in docs:
            authors = doc.get("author_name") or []
            isbns   = doc.get("isbn") or []
            langs   = doc.get("language") or []
            results.append({
                "source": "OpenLibrary",
                "title":     doc.get("title", "").strip(),
                "author":    ", ".join(authors[:3]),
                "year":      doc.get("first_publish_year"),
                "publisher": (doc.get("publisher") or [""])[0],
                "isbn":      isbns[0] if isbns else "",
                "language":  langs[0].upper() if langs else "",
                "pages":     doc.get("number_of_pages_median"),
                "notes":     f"OpenLibrary: {doc.get('key', '')}",
            })
        print(f"знайдено {len(results)}")
        return results
    except Exception as e:
        print(f"помилка: {e}")
        return []


def search_googlebooks(query: str, limit: int) -> list[dict]:
    print("  [Google Books] Шукаю…", end=" ", flush=True)
    try:
        r = requests.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": query, "maxResults": min(limit, 40), "printType": "books"},
            timeout=10,
        )
        items = r.json().get("items", [])
        results = []
        for item in items:
            info  = item.get("volumeInfo", {})
            isbns = {i["type"]: i["identifier"] for i in info.get("industryIdentifiers", [])}
            year  = None
            pd = info.get("publishedDate", "")
            if pd and len(pd) >= 4 and pd[:4].isdigit():
                year = int(pd[:4])
            results.append({
                "source":    "Google Books",
                "title":     info.get("title", "").strip(),
                "author":    ", ".join(info.get("authors", [])[:3]),
                "year":      year,
                "publisher": info.get("publisher", ""),
                "isbn":      isbns.get("ISBN_13") or isbns.get("ISBN_10", ""),
                "language":  info.get("language", "").upper(),
                "pages":     info.get("pageCount"),
                "notes":     (info.get("description", "")[:300] or ""),
            })
        print(f"знайдено {len(results)}")
        return results
    except Exception as e:
        print(f"помилка: {e}")
        return []


def search_crossref(query: str, limit: int) -> list[dict]:
    """CrossRef — наукові статті та книги з DOI."""
    print("  [CrossRef]    Шукаю…", end=" ", flush=True)
    try:
        r = requests.get(
            "https://api.crossref.org/works",
            params={"query": query, "rows": limit},
            headers={"User-Agent": "BookCatalogBot/1.0 (mailto:catalog@local)"},
            timeout=10,
        )
        msg = r.json().get("message", {})
        items = msg.get("items", []) if isinstance(msg, dict) else []
        results = []
        for item in items:
            titles  = item.get("title") or []
            authors = item.get("author") or []
            author_str = ", ".join(
                f"{a.get('family', '')} {a.get('given', '')}".strip()
                for a in authors[:3]
            )
            year = None
            pub = item.get("published-print") or item.get("published-online") or {}
            pp = pub.get("date-parts", [[]])[0] if isinstance(pub, dict) else []
            if pp:
                year = pp[0]
            isbns = item.get("ISBN") or []
            results.append({
                "source":    "CrossRef",
                "title":     titles[0].strip() if titles else "",
                "author":    author_str,
                "year":      year,
                "publisher": item.get("publisher", ""),
                "isbn":      isbns[0] if isbns else "",
                "language":  item.get("language", "").upper(),
                "pages":     None,
                "notes":     (item.get("abstract", "") or "")[:300],
            })
        print(f"знайдено {len(results)}")
        return results
    except Exception as e:
        print(f"помилка: {e}")
        return []


# ── Dedup + Save ──────────────────────────────────────────────────────────────

def deduplicate(results: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for r in results:
        key = (r["title"].lower().strip(), r["author"].lower().strip())
        if key[0] and key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def save_to_db(results: list[dict]) -> tuple[int, int]:
    existing = {(b.title.lower(), b.author.lower()) for b in REPO.get_all()}
    added, skipped = 0, 0
    for r in results:
        key = (r["title"].lower(), r["author"].lower())
        if key in existing:
            skipped += 1
            continue
        book = Book(
            title=r["title"],
            author=r["author"],
            genre="Знайдена література",
            year=r.get("year"),
            publisher=r.get("publisher", ""),
            language=r.get("language", ""),
            isbn=r.get("isbn", ""),
            pages=r.get("pages"),
            notes=f"[{r['source']}] {r.get('notes','')}".strip(),
        )
        REPO.add_book(book)
        existing.add(key)
        added += 1
    return added, skipped


# ── Main ──────────────────────────────────────────────────────────────────────

def run_bot(query: str, limit: int = 20, sources: list[str] | None = None):
    if sources is None:
        sources = SOURCES

    print(f"\n{'='*55}")
    print(f" БОТ ПОШУКУ ЛІТЕРАТУРИ")
    print(f" Запит : «{query}»")
    print(f" Ліміт : {limit} на джерело")
    print(f"{'='*55}\n")

    all_results = []

    if "openlibrary" in sources:
        all_results += search_openlibrary(query, limit)
        time.sleep(0.3)

    if "googlebooks" in sources:
        all_results += search_googlebooks(query, limit)
        time.sleep(0.3)

    if "crossref" in sources:
        all_results += search_crossref(query, limit)
        time.sleep(0.3)

    print(f"\n Разом знайдено : {len(all_results)}")
    unique = deduplicate(all_results)
    print(f" Після дедублікації: {len(unique)}")

    print(f"\n Зберігаю в базу даних…")
    added, skipped = save_to_db(unique)

    print(f"\n{'='*55}")
    print(f" РЕЗУЛЬТАТ:")
    print(f"   Додано нових   : {added}")
    print(f"   Вже існували   : {skipped}")
    print(f"   Всього в базі  : {REPO.count()}")
    print(f"{'='*55}\n")

    return added, skipped


def main():
    parser = argparse.ArgumentParser(description="Literature Search Bot")
    parser.add_argument("query", help="Search query (e.g. 'periodontology')")
    parser.add_argument("--limit", type=int, default=20, help="Results per source (default: 20)")
    parser.add_argument(
        "--sources", nargs="+",
        choices=SOURCES, default=SOURCES,
        help="Sources to search (default: all)"
    )
    args = parser.parse_args()
    run_bot(args.query, args.limit, args.sources)


if __name__ == "__main__":
    main()
