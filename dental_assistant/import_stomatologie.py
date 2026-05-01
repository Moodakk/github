import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import BookRepository
from models import Book

BOOKS = [
    # ── Orální chirurgie ──────────────────────────────────────────────────────
    Book(title="Stomatologická chirurgie", author="Toman J., Halmoš J.",
         genre="Orální chirurgie", year=1984),
    Book(title="Repetitorium stomatologické chirurgie I.–III.",
         author="Pazderka J.", genre="Orální chirurgie",
         publisher="UP Olomouc", year=1996),
    Book(title="Traumatologie orofaciální oblasti",
         author="Mazánek J.", genre="Orální chirurgie",
         publisher="Grada Publishing", year=2006, language="Čeština"),
    Book(title="Nádory orofaciální oblasti",
         author="Mazánek J.", genre="Orální chirurgie",
         publisher="Viktoria Publishing", year=1997, language="Čeština"),
    Book(title="Dentální implantologie",
         author="Šimůnek A.", genre="Orální chirurgie",
         publisher="Nucleus", year=2001, language="Čeština"),

    # ── Konzervační zubní lékařství ───────────────────────────────────────────
    Book(title="Konzervační zubní lékařství",
         author="Stejskalová J. a kol.", genre="Konzervační zubní lékařství",
         publisher="Galén", year=2003, language="Čeština"),
    Book(title="Základy klinické endodoncie",
         author="Peřinka L.", genre="Konzervační zubní lékařství",
         publisher="Quintessenz", year=2003, language="Čeština"),
    Book(title="Záchovná stomatologie a parodontologie",
         author="Hellwig E., Klimek J., Attin T.",
         genre="Konzervační zubní lékařství",
         publisher="Grada Avicenum", year=2000, language="Čeština"),
    Book(title="Základy záchovné stomatologie",
         author="Novák L. A a kol.", genre="Konzervační zubní lékařství",
         publisher="Avicenum", year=1981, language="Čeština"),
    Book(title="Prevence ve stomatologii",
         author="Killman J. a kol.", genre="Konzervační zubní lékařství",
         publisher="Galén", year=1999, language="Čeština"),
    Book(title="Příručka stomatologa v praxi",
         author="Kolektiv autorů", genre="Konzervační zubní lékařství",
         publisher="Avicenum", year=1987, language="Čeština"),

    # ── Parodontologie ────────────────────────────────────────────────────────
    Book(title="Praktické parodontologie",
         author="Slezák K.", genre="Parodontologie",
         publisher="Quintessenz", year=1995, language="Čeština"),
    Book(title="Infekční choroby ústní sliznice",
         author="Slezák K., Dřízhal I. a kol.", genre="Parodontologie",
         publisher="Grada Publishing", year=1997, language="Čeština"),
    Book(title="Záchovná stomatologie a parodontologie",
         author="Hellwig E., Klimek J., Attin T.", genre="Parodontologie",
         publisher="Grada Avicenum", year=2000, language="Čeština"),
    Book(title="Praktická parodontologie — klinické postupy",
         author="Mutschelknauss R. E.", genre="Parodontologie",
         publisher="Quintessenz", year=2002, language="Čeština"),
    Book(title="Repetitorium onemocnění sliznice ústní",
         author="Holá L., Fassmann A.", genre="Parodontologie", year=2003,
         language="Čeština"),
    Book(title="Atlas onemocnění ústní sliznice",
         author="Slezák K., Dřízhal I.", genre="Parodontologie",
         publisher="Quintessenz", year=2004, language="Čeština"),
    Book(title="Stomatologické repetitorium (1. vydání)",
         author="Mazánek J., Urban F. a kol.", genre="Parodontologie",
         publisher="Grada", year=2003, language="Čeština"),
    Book(title="Prevence ve stomatologii",
         author="Killman J. a kol.", genre="Parodontologie",
         publisher="Karolinum", year=1999, language="Čeština"),
    Book(title="Lindhe's Clinical Periodontology and Implant Dentistry (2 vol.)",
         author="Lindhe J. et al.", genre="Parodontologie",
         publisher="John Wiley and Sons Ltd", year=2021, language="English"),
    Book(title="Clinical Periodontology and Implantology (14th ed.)",
         author="Newman M., Takei H., Carranza F., Klokvold P.",
         genre="Parodontologie", year=2023, language="English"),
    Book(title="Clinical Periodontology (9th Edition) [e-book]",
         author="Newman M.G., Takei H.H., Carranza F.A.",
         genre="Parodontologie", year=2003, language="English"),
    Book(title="Clinical Periodontology and Implant Dentistry [e-book]",
         author="Lindhe J., Lang N.P., Karring T.",
         genre="Parodontologie", publisher="Blackwell Munksgaard",
         year=2008, language="English"),
    Book(title="Periodontal Disease and Overall Health: A Clinician's Guide [e-book]",
         author="Genco R.J., Williams R.C.",
         genre="Parodontologie",
         publisher="Professional Audience Communications", year=2010,
         language="English"),

    # ── Protetika ─────────────────────────────────────────────────────────────
    Book(title="Stomatologická protetika",
         author="Andrik P.", genre="Protetika", language="Slovenčina"),
    Book(title="Protetická technologie",
         author="Bittner J.", genre="Protetika", year=2001, language="Čeština"),
    Book(title="Stomatologická propedeutika",
         author="Svoboda O.", genre="Protetika",
         publisher="Avicenum", year=1984, language="Čeština"),
    Book(title="Fixní zubní náhrady",
         author="Krňoulová J., Hubálková H.", genre="Protetika",
         publisher="Quintessenz", year=2002, language="Čeština"),
    Book(title="Fixní a snímatelná protetika",
         author="Dostálová T.", genre="Protetika",
         publisher="Grada Publishing", year=2004, language="Čeština"),
    Book(title="Částečné snímatelné náhrady",
         author="Zicha A.", genre="Protetika",
         publisher="Karolinum", year=1998, language="Čeština"),
    Book(title="Protetická stomatologia — liečba a prevencia",
         author="Tvrdoň M.", genre="Protetika",
         publisher="Science", year=2001, language="Slovenčina"),
    Book(title="Základy gnatologie",
         author="Šedý J.", genre="Protetika",
         publisher="Triton", year=2023, language="Čeština"),
    Book(title="Klinická anatomie zubů a čelistí",
         author="Šedý J., Foltán R.", genre="Protetika",
         publisher="Triton", year=2009, language="Čeština"),
    Book(title="Kompendium stomatologie I (2. rozš. vydání)",
         author="Šedý J.", genre="Protetika",
         publisher="Triton", year=2022, language="Čeština"),
    Book(title="Kompendium stomatologie II",
         author="Šedý J.", genre="Protetika",
         publisher="Triton", language="Čeština"),

    # ── Ortodoncie ────────────────────────────────────────────────────────────
    Book(title="Ortodoncie I.–II.",
         author="Kamínek M., Štefková M.", genre="Ortodoncie",
         publisher="UP Olomouc", language="Čeština"),
    Book(title="Ortodontický průvodce praktického zubního lékaře",
         author="Koťová M.", genre="Ortodoncie",
         publisher="Grada Avicenum", year=2006, language="Čeština"),
    Book(title="Vybrané kapitoly z ortodoncie",
         author="Šubrtová I.", genre="Ortodoncie",
         publisher="Karolinum", year=1993, language="Čeština"),

    # ── Dětské zubní lékařství ────────────────────────────────────────────────
    Book(title="Prevence ve stomatologii (2. vydání)",
         author="Killman J. a kol.", genre="Dětské zubní lékařství",
         publisher="Galén-Karolinum", year=1999, language="Čeština"),
    Book(title="Dětská stomatologie",
         author="Komínek J., Rozkovcová E., Seman M.",
         genre="Dětské zubní lékařství", year=1998, language="Čeština"),
    Book(title="Orálna hygiena",
         author="Kovalová E., Čierný M.", genre="Dětské zubní lékařství",
         publisher="Prešov", year=1994, language="Slovenčina"),
    Book(title="Vybrané kapitoly z pedostomatologie",
         author="Fialová S., Nováková K.", genre="Dětské zubní lékařství",
         publisher="Olomouc", year=2000, language="Čeština"),
    Book(title="Pediatric Dentistry: A Clinical Approach",
         author="Poulsen S., Koch G.", genre="Dětské zubní lékařství",
         publisher="Copenhagen", year=2002, language="English"),
    Book(title="Ortodoncie",
         author="Kamínek M. et al.", genre="Dětské zubní lékařství",
         publisher="Galén", year=2014, language="Čeština"),
    Book(title="Atlas ortodontických anomálií",
         author="Koťová M.", genre="Dětské zubní lékařství",
         publisher="Česká stomatologická komora", year=2008, language="Čeština"),
    Book(title="Dětské zubní lékařství (1. vydání)",
         author="Koberová Ivančaková R., Merglová V.",
         genre="Dětské zubní lékařství",
         publisher="Advertis group", year=2014, language="Čeština"),
    Book(title="Dětská stomatologie (4. vydání)",
         author="Komínek J. a kol.", genre="Dětské zubní lékařství",
         publisher="Avicenum", year=1988, language="Čeština"),
    Book(title="Paediatric Dentistry",
         author="Welbury R., Duggal M.S., Hosey M.T.",
         genre="Dětské zubní lékařství",
         publisher="Oxford University Press", year=2018, language="English"),
]


def main():
    repo = BookRepository()
    existing = {(b.title.lower(), b.author.lower()) for b in repo.get_all()}
    added = 0
    skipped = 0
    for book in BOOKS:
        key = (book.title.lower(), book.author.lower())
        if key in existing:
            skipped += 1
        else:
            repo.add_book(book)
            existing.add(key)
            added += 1
    repo.close()
    print(f"Done. Added: {added}, skipped (duplicates): {skipped}")
    print(f"Total books in DB: {added + skipped} new / check books.db for full count")


if __name__ == "__main__":
    main()
