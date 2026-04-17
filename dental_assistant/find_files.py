import html
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import quote_plus

import requests
from models import Book

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "BookCatalogBot/1.0 (educational use)"})
TIMEOUT = 10
MAX_CANDIDATES_PER_SOURCE = 3


def find_online_sources(book: Book) -> list[dict]:
    """
    Returns ranked legal online sources for a book.

    Each result may contain:
      source, url, access, title, author, year, match_score, note
    """
    results = []
    seen: set[tuple[str, str]] = set()

    for finder in (
        _search_czech_library_sources,
        _search_mzk_sources,
        _search_google_books,
        _search_open_library_sources,
        _search_internet_archive_sources,
        _search_worldcat_sources,
    ):
        for candidate in finder(book):
            key = (candidate["source"], candidate["url"])
            if key in seen:
                continue
            seen.add(key)
            results.append(candidate)

    results.sort(
        key=lambda item: (
            _czech_library_boost(book, item),
            _access_rank(item.get("access", "")),
            item.get("match_score", 0),
            _source_rank(item.get("source", ""), item.get("access", "")),
            item.get("source", ""),
        ),
        reverse=True,
    )
    return results


def find_file_for_book(book: Book) -> dict | None:
    """
    Try all sources. Returns dict with keys:
      url, source, format ('pdf'|'epub'), size_mb (optional)
    or None if nothing found.
    """
    result = (
        _try_internet_archive(book)
        or _try_open_library(book)
        or _try_unpaywall(book)
    )
    return result


# ── Internet Archive ──────────────────────────────────────────────────────────

def _try_internet_archive(book: Book) -> dict | None:
    query_parts = [f'title:("{book.title}")']
    if book.author:
        last = book.author.split(",")[0].split()[-1]
        query_parts.append(f'creator:("{last}")')

    params = {
        "q": " AND ".join(query_parts),
        "fl[]": ["identifier", "title", "format"],
        "rows": 5,
        "page": 1,
        "output": "json",
        "mediatype": "texts",
    }
    try:
        r = SESSION.get("https://archive.org/advancedsearch.php", params=params, timeout=TIMEOUT)
        docs = r.json().get("response", {}).get("docs", [])
    except Exception:
        return None

    for doc in docs:
        ident = doc.get("identifier", "")
        if not ident:
            continue
        # Check available formats
        try:
            meta = SESSION.get(f"https://archive.org/metadata/{ident}/files", timeout=TIMEOUT).json()
        except Exception:
            continue

        files = meta.get("result", [])
        # Prefer PDF, then epub
        for fmt in ("pdf", "epub"):
            for f in files:
                name = f.get("name", "")
                if name.lower().endswith(f".{fmt}") and not name.startswith("__"):
                    url = f"https://archive.org/download/{ident}/{name}"
                    size = f.get("size")
                    size_mb = round(int(size) / 1_048_576, 1) if size else None
                    return {
                        "url": url,
                        "source": "Internet Archive",
                        "format": fmt,
                        "size_mb": size_mb,
                        "identifier": ident,
                    }
    return None


def _search_internet_archive_sources(book: Book) -> list[dict]:
    query_parts = [f'title:("{book.title}")']
    if book.author:
        last = book.author.split(",")[0].split()[-1]
        query_parts.append(f'creator:("{last}")')

    params = {
        "q": " AND ".join(query_parts),
        "fl[]": ["identifier", "title", "creator", "year", "format"],
        "rows": MAX_CANDIDATES_PER_SOURCE,
        "page": 1,
        "output": "json",
        "mediatype": "texts",
    }
    try:
        r = SESSION.get(
            "https://archive.org/advancedsearch.php",
            params=params,
            timeout=TIMEOUT,
        )
        docs = r.json().get("response", {}).get("docs", [])
    except Exception:
        docs = []

    results = []
    for doc in docs:
        ident = doc.get("identifier", "")
        if not ident:
            continue
        title = doc.get("title", "") or book.title
        author = _first_value(doc.get("creator")) or book.author
        year = _safe_int(_first_value(doc.get("year")))
        results.append(
            _build_candidate(
                book,
                source="Internet Archive",
                url=f"https://archive.org/details/{ident}",
                access="catalog",
                title=title,
                author=author,
                year=year,
                note="Borrow/preview or open scan when available",
            )
        )

    if not results:
        results.append(
            _build_search_candidate(
                book,
                source="Internet Archive",
                url="https://archive.org/search?query=" + quote_plus(
                    _search_terms(book)
                ),
            )
        )
    return results


# ── Open Library ──────────────────────────────────────────────────────────────

def _try_open_library(book: Book) -> dict | None:
    try:
        r = SESSION.get(
            "https://openlibrary.org/search.json",
            params={"title": book.title, "author": book.author, "limit": 5,
                    "fields": "key,title,ia,lending_edition_s,public_scan_b"},
            timeout=TIMEOUT,
        )
        docs = r.json().get("docs", [])
    except Exception:
        return None

    for doc in docs:
        # public domain scan available
        if doc.get("public_scan_b") and doc.get("ia"):
            ia_id = doc["ia"][0] if isinstance(doc["ia"], list) else doc["ia"]
            return {
                "url": f"https://archive.org/download/{ia_id}/{ia_id}.pdf",
                "source": "Open Library (public domain)",
                "format": "pdf",
                "size_mb": None,
                "identifier": ia_id,
            }
    return None


def _search_open_library_sources(book: Book) -> list[dict]:
    try:
        r = SESSION.get(
            "https://openlibrary.org/search.json",
            params={
                "title": book.title,
                "author": book.author,
                "limit": MAX_CANDIDATES_PER_SOURCE,
                "fields": (
                    "key,title,author_name,first_publish_year,"
                    "ia,public_scan_b,ebook_access"
                ),
            },
            timeout=TIMEOUT,
        )
        docs = r.json().get("docs", [])
    except Exception:
        docs = []

    results = []
    for doc in docs:
        key = doc.get("key")
        if not key:
            continue
        access = "catalog"
        note = "Catalog page"
        if doc.get("public_scan_b"):
            access = "open"
            note = "Public-domain scan available"
        elif doc.get("ebook_access") not in ("no_ebook", None):
            access = "borrow"
            note = "Borrow/preview may be available"

        results.append(
            _build_candidate(
                book,
                source="Open Library",
                url=f"https://openlibrary.org{key}",
                access=access,
                title=doc.get("title", "") or book.title,
                author=", ".join(doc.get("author_name", [])[:3]) or book.author,
                year=_safe_int(doc.get("first_publish_year")),
                note=note,
            )
        )

    if not results:
        results.append(
            _build_search_candidate(
                book,
                source="Open Library",
                url="https://openlibrary.org/search?q=" + quote_plus(
                    _search_terms(book)
                ),
            )
        )
    return results


def _search_google_books(book: Book) -> list[dict]:
    try:
        r = SESSION.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={
                "q": f'intitle:"{book.title}" inauthor:"{book.author}"',
                "maxResults": MAX_CANDIDATES_PER_SOURCE,
                "printType": "books",
            },
            timeout=TIMEOUT,
        )
        items = r.json().get("items", [])
    except Exception:
        items = []

    results = []
    for item in items:
        info = item.get("volumeInfo", {})
        sale = item.get("saleInfo", {})
        access_info = item.get("accessInfo", {})
        preview_link = info.get("previewLink") or info.get("infoLink")
        if not preview_link:
            continue

        access = "catalog"
        note = "Book details"
        if access_info.get("pdf", {}).get("isAvailable") or access_info.get("epub", {}).get("isAvailable"):
            access = "open"
            note = "Google Books shows downloadable content"
        elif access_info.get("viewability") not in ("NO_PAGES", None):
            access = "preview"
            note = "Preview available"
        elif sale.get("saleability") == "FOR_SALE":
            access = "store"
            note = "Purchase page"

        results.append(
            _build_candidate(
                book,
                source="Google Books",
                url=preview_link,
                access=access,
                title=info.get("title", "") or book.title,
                author=", ".join(info.get("authors", [])[:3]) or book.author,
                year=_extract_year(info.get("publishedDate", "")),
                note=note,
            )
        )

    if not results:
        results.append(
            _build_search_candidate(
                book,
                source="Google Books",
                url="https://books.google.com/books?q=" + quote_plus(
                    _search_terms(book)
                ),
            )
        )
    return results


def _search_czech_library_sources(book: Book) -> list[dict]:
    query = _search_terms(book)
    return [
        _build_search_candidate(
            book,
            source="Knihovny.cz",
            url="https://www.knihovny.cz/Search/Results?lookfor=" + quote_plus(query),
            access="library",
            note="Czech libraries portal",
        )
    ]


def _search_mzk_sources(book: Book) -> list[dict]:
    query = _search_terms(book)
    return [
        _build_search_candidate(
            book,
            source="MZK",
            url="https://vufind.mzk.cz/Search/Results?lookfor=" + quote_plus(query),
            access="library",
            note="Moravian Library catalog",
        )
    ]


def _search_worldcat_sources(book: Book) -> list[dict]:
    return [
        _build_search_candidate(
            book,
            source="WorldCat",
            url="https://search.worldcat.org/search?q=" + quote_plus(
                _search_terms(book, include_author=False)
            ),
            access="library",
            note="Library holdings search",
        )
    ]


# ── Unpaywall (DOI → open access PDF) ────────────────────────────────────────

def _try_unpaywall(book: Book) -> dict | None:
    # First find a DOI via CrossRef
    doi = _crossref_doi(book)
    if not doi:
        return None
    try:
        r = SESSION.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": "catalog@local"},
            timeout=TIMEOUT,
        )
        data = r.json()
    except Exception:
        return None

    if not data.get("is_oa"):
        return None

    best = data.get("best_oa_location") or {}
    url = best.get("url_for_pdf") or best.get("url")
    if url:
        return {
            "url": url,
            "source": "Unpaywall (open access)",
            "format": "pdf",
            "size_mb": None,
            "identifier": doi,
        }
    return None


def _crossref_doi(book: Book) -> str | None:
    try:
        r = SESSION.get(
            "https://api.crossref.org/works",
            params={"query.title": book.title, "query.author": book.author, "rows": 1},
            timeout=TIMEOUT,
        )
        items = r.json().get("message", {}).get("items", [])
        if items:
            return items[0].get("DOI")
    except Exception:
        pass
    return None


def render_sources_html(sources: list[dict]) -> str:
    if not sources:
        return ""
    links = []
    for item in sources[:4]:
        label = html.escape(item["source"])
        access = html.escape(item.get("access", "catalog"))
        links.append(
            f'<a href="{html.escape(item["url"], quote=True)}">{label}</a>'
            f' <span class="access">{access}</span>'
        )
    return "<br>".join(links)


def _build_candidate(
    book: Book,
    source: str,
    url: str,
    access: str,
    title: str,
    author: str,
    year: int | None = None,
    note: str = "",
) -> dict:
    return {
        "source": source,
        "url": url,
        "access": access,
        "title": title,
        "author": author,
        "year": year,
        "match_score": _score_candidate(book, title, author, year),
        "note": note,
    }


def _build_search_candidate(
    book: Book,
    source: str,
    url: str,
    access: str = "search",
    note: str = "Search page",
) -> dict:
    return {
        "source": source,
        "url": url,
        "access": access,
        "title": book.title,
        "author": book.author,
        "year": book.year,
        "match_score": 0.15,
        "note": note,
    }


def _search_terms(book: Book, include_author: bool = True) -> str:
    parts = [_clean_search_fragment(book.title)]
    author = _clean_author_for_search(book.author) if include_author else ""
    if author:
        parts.append(author)
    return " ".join(part for part in parts if part).strip()


def _score_candidate(book: Book, title: str, author: str, year: int | None) -> float:
    title_ratio = SequenceMatcher(
        None,
        _normalize_text(book.title),
        _normalize_text(title),
    ).ratio()
    author_ratio = 0.0
    if book.author and author:
        author_ratio = SequenceMatcher(
            None,
            _normalize_text(book.author),
            _normalize_text(author),
        ).ratio()

    score = title_ratio * 0.75 + author_ratio * 0.2
    if book.year and year:
        if book.year == year:
            score += 0.05
        elif abs(book.year - year) <= 1:
            score += 0.02

    return round(min(score, 0.99), 3)


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _clean_search_fragment(value: str) -> str:
    value = value or ""
    value = value.replace("—", " ").replace("–", " ")
    value = re.sub(r"\b[IVX]+\b(?:\s*[\.\-–]\s*\b[IVX]+\b)?", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^0-9A-Za-zÀ-ž\s]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _clean_author_for_search(value: str) -> str:
    value = value or ""
    value = re.sub(r"\bet\s+al\.?\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\ba\s+kol\.?\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\bkol\.?\b", " ", value, flags=re.IGNORECASE)
    value = value.split(",")[0]
    value = _clean_search_fragment(value)
    return value


def _extract_year(value: str) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", value or "")
    return int(match.group(0)) if match else None


def _safe_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_value(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _access_rank(access: str) -> int:
    return {
        "open": 6,
        "borrow": 5,
        "preview": 4,
        "store": 3,
        "library": 2,
        "catalog": 1,
        "search": 0,
    }.get(access, 0)


def _source_rank(source: str, access: str) -> int:
    if access == "search":
        return {
            "Knihovny.cz": 5,
            "MZK": 4,
            "WorldCat": 4,
            "Google Books": 3,
            "Open Library": 2,
            "Internet Archive": 1,
        }.get(source, 0)
    return {
        "Knihovny.cz": 5,
        "MZK": 4,
        "Google Books": 4,
        "Open Library": 3,
        "Internet Archive": 2,
        "WorldCat": 1,
    }.get(source, 0)


def _czech_library_boost(book: Book, item: dict) -> int:
    if item.get("source") not in {"Knihovny.cz", "MZK", "WorldCat"}:
        return 0
    if _prefer_czech_libraries(book):
        return {
            "Knihovny.cz": 3,
            "MZK": 2,
            "WorldCat": 1,
        }.get(item.get("source"), 0)
    return 0


def _prefer_czech_libraries(book: Book) -> bool:
    language = (book.language or "").lower()
    publisher = _normalize_text(book.publisher)
    title = _normalize_text(book.title)
    author = _normalize_text(book.author)

    if language in {"cestina", "cesky", "slovencina", "slovensky"}:
        return True

    czech_markers = (
        "praha", "olomouc", "brno", "karolinum", "galen", "grada",
        "avicenum", "triton", "up olomouc", "univerzita palackeho",
        "ceska", "czech",
    )
    haystack = " ".join(part for part in (publisher, title, author) if part)
    return any(marker in haystack for marker in czech_markers)
