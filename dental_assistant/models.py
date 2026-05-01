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
import sys
import re
import shutil
import argparse
from pathlib import Path
from difflib import SequenceMatcher

sys.path.insert(0, str(Path(__file__).resolve().parent))
from database import BookRepository
from config import BASE_DIR

ONEDRIVE_ROOT = Path("C:/Users/vlad_/OneDrive")
FILES_DIR     = BASE_DIR / "files"
FILES_DIR.mkdir(exist_ok=True)

BOOK_EXTENSIONS = {".pdf", ".epub", ".djvu", ".fb2", ".doc", ".docx"}

# Files likely to be tests/study notes rather than actual books
TEST_PATTERNS = re.compile(
    r"test|testy|otázk|zkoušk|státnic|cvičn|подшив|vypracovan|"
    r"srz|srž|opakov|otazk|1[\.\s]část|2[\.\s]část|část\s*\d|"
    r"^\d+[\.\s]část|\bpart\b",
    re.I
)


# ── Text normalisation ────────────────────────────────────────────────────────

def normalise(text: str) -> str:
    """Lowercase, strip accents roughly, remove punctuation/numbers prefix."""
    t = text.lower()
    # remove leading numbering like "10_", "18 "
    t = re.sub(r"^\d+[_\s\.\-]+", "", t)
    # replace underscores / dashes with space
    t = re.sub(r"[_\-]+", " ", t)
    # remove extension
    t = re.sub(r"\.(pdf|epub|djvu|fb2|docx?)$", "", t)
    # collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalise(a), normalise(b)).ratio() * 100


def keyword_overlap(filename: str, book_title: str) -> float:
    """Fraction of significant title words that appear as whole words in the filename."""
    stopwords = {"a", "i", "v", "z", "k", "o", "s", "the", "and", "of",
                 "in", "an", "for", "to", "kol", "et", "al", "ve", "ze"}
    fname_words = set(re.split(r"\W+", normalise(filename)))
    title_words = [w for w in re.split(r"\W+", normalise(book_title))
                   if len(w) > 2 and w not in stopwords]
    if not title_words:
        return 0.0
    hits = sum(1 for w in title_words if w in fname_words)
    return hits / len(title_words) * 100


def author_bonus(filename: str, author: str) -> float:
    """Extra points if author's last name appears in filename."""
    if not author:
        return 0.0
    last_names = [p.strip().split()[0].lower()
                  for p in author.split(",")[:2] if p.strip()]
    fname = normalise(filename)
    return 15.0 if any(ln in fname for ln in last_names if len(ln) > 3) else 0.0


def score(filename: str, book_title: str, author: str = "") -> float:
    if TEST_PATTERNS.search(filename):
        return 0.0  # never match test/exam files
    base = max(similarity(filename, book_title),
               keyword_overlap(filename, book_title))
    return min(100.0, base + author_bonus(filename, author))


# ── File scanning ─────────────────────────────────────────────────────────────

def scan_files(root: Path) -> list[Path]:
    result = []
    for p in root.rglob("*"):
        if p.suffix.lower() in BOOK_EXTENSIONS:
            result.append(p)
    return result


# ── Matching ──────────────────────────────────────────────────────────────────

def match_files_to_books(files: list[Path], books, threshold: float):
    """
    Returns:
      matched   – [(book, file, score)]
      unmatched_files  – [file]
      books_no_file    – [book]
    """
    matched: list[tuple] = []
    used_files: set[Path] = set()
    used_books: set[int]  = set()

    # For each book, find the best-scoring file
    candidates = []
    for book in books:
        if book.file_path:          # already has a file in catalog
            continue
        best_file, best_score = None, 0.0
        for f in files:
            s = score(f.name, book.title, book.author)
            if s > best_score:
                best_score, best_file = s, f
        if best_file and best_score >= threshold:
            candidates.append((best_score, book, best_file))

    # Sort by score descending; greedily assign (one file → one book)
    candidates.sort(key=lambda x: x[0], reverse=True)
    for sc, book, f in candidates:
        if book.id in used_books or f in used_files:
            continue
        matched.append((book, f, sc))
        used_books.add(book.id)
        used_files.add(f)

    unmatched_files  = [f for f in files if f not in used_files]
    books_no_file    = [b for b in books if b.id not in used_books and not b.file_path]
    return matched, unmatched_files, books_no_file


# ── Link ──────────────────────────────────────────────────────────────────────

def link_match(repo: BookRepository, book, src_path: Path) -> str:
    """Copy file to catalog files/ folder and update DB."""
    safe_name = f"{book.id}_{re.sub(r'[^a-zA-Z0-9._-]', '_', src_path.name)}"
    dest = FILES_DIR / safe_name
    if not dest.exists():
        shutil.copy2(str(src_path), str(dest))
    repo.set_file_path(book.id, safe_name)
    return safe_name


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(matched, unmatched_files, books_no_file, apply: bool):
    W = 70
    print("\n" + "=" * W)
    print(" ЗВІТ СИНХРОНІЗАЦІЇ OneDrive ↔ Каталог")
    print("=" * W)

    print(f"\n✅ ЗНАЙДЕНО ЗБІГИ ({len(matched)}):")
    print("-" * W)
    for book, f, sc in sorted(matched, key=lambda x: -x[2]):
        status = "→ ПРИВ'ЯЗАНО" if apply else "→ (запусти з --apply)"
        print(f"  [{sc:5.1f}%]  📖 {book.title[:45]:<45}")
        print(f"             📄 {f.name}")
        print(f"             {status}")
        print()

    print(f"\n📚 КНИГИ БЕЗ ФАЙЛУ ({len(books_no_file)}):")
    print("-" * W)
    for b in books_no_file:
        print(f"  • {b.title[:60]}")

    print(f"\n📁 НЕЗІСТАВЛЕНІ ФАЙЛИ З ONEDRIVE ({len(unmatched_files)}):")
    print("-" * W)
    # Show only book-like files (skip test files, etc.)
    interesting = [f for f in unmatched_files
                   if not re.search(r"test|testy|otázk|zkoušk|státnic|cvičn|подшив",
                                    f.name, re.I)]
    for f in interesting[:30]:
        print(f"  • {f.name}")
    if len(interesting) > 30:
        print(f"  … та ще {len(interesting)-30} файлів")

    print("\n" + "=" * W)
    print(f" Збіги: {len(matched)}  |  Без файлу: {len(books_no_file)}  |  Нерозпізнано: {len(unmatched_files)}")
    print("=" * W + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync OneDrive files with book catalog")
    parser.add_argument("--apply",     action="store_true", help="Link matched files to catalog")
    parser.add_argument("--threshold", type=float, default=70, help="Match threshold %% (default 70)")
    parser.add_argument("--folder",    default=str(ONEDRIVE_ROOT), help="OneDrive root folder")
    args = parser.parse_args()

    root = Path(args.folder)
    print(f"\n🔍 Сканую: {root}")
    files = scan_files(root)
    print(f"   Знайдено файлів: {len(files)}")

    repo  = BookRepository()
    books = repo.get_all()
    print(f"   Книг у каталозі: {len(books)}")
    print(f"   Порогова схожість: {args.threshold}%\n")

    matched, unmatched_files, books_no_file = match_files_to_books(
        files, books, args.threshold
    )

    if args.apply:
        print("⚙  Прив'язую знайдені файли…")
        for book, f, sc in matched:
            saved = link_match(repo, book, f)
            print(f"   ✓ {book.title[:50]} ← {f.name}")
        repo.close()

    print_report(matched, unmatched_files, books_no_file, args.apply)


if __name__ == "__main__":
    main()
