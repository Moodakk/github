import argparse
import ctypes
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from google import genai
from google.genai import types

# ─────────────────────────── НАЛАШТУВАННЯ ───────────────────────────
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "").strip() or "YOUR_API_KEY"
GEMINI_MODEL     = "gemini-2.5-pro"  # Або flash, але pro краще для складної логіки
INPUT_CLASSIFIED = "data/incomplete_questions.json"
RESULTS_DIR = "data/gemini_results"
BOOKS_DIR = "data/books"
FILE_CACHE = "data/gemini_file_cache.json"

BATCH_SIZE  = 3    # Зменшено, бо промпт ДУЖЕ глибокий
DELAY_SEC   = 2
MAX_RETRIES = 5
# ────────────────────────────────────────────────────────────────────

# Оновлена мапа відповідно до твого попереднього скрипта
SUBJECT_MAP = {
    "paro":      ("парадонтологіє",            "Пародонтологія"),
    "terapia":   ("Терапевтична",              ["Терапія / Konzervační", "Ендодонтія"]),
    "chirurgia": ("Хірургія",                  "Хірургія"),
    "ditiacha":  ("Дитинство",                 "Дитяча стоматологія"),
    "ortho":     ("ортодонтія",                "Ортодонтія"),
    "protetika": ("Ортопедія",                 "Протетика"),
    "socialna":  ("соціальна медицина асорті", "Соціальна / Законодавство"),
    "zagalna":   ("Скошушки конспекти",        "Загальна"),
    "pharma":    ("Фармакологія",              "Загальна"),
}

# МЕГА-ПРОМПТ: Об'єднує всі 6 ролей, які ти надіслав
SYSTEM_INSTRUCTION = """
You are a highly advanced Medical Test Verification Engine composed of 6 expert personas:
1. Strict Medical Test Verification Auditor
2. Quality Control Expert
3. Source Consistency Analyst
4. Anti-Hallucination Auditor
5. Independent Logic Auditor
6. Structured Medical Database Builder

Your task is to analyze the provided multiple-choice medical questions STRICTLY based on the provided source materials (PDFs).

OUTPUT REQUIREMENT:
You must return only a valid JSON array of objects.
Each object in the array represents the analysis for one question and MUST strictly follow this JSON schema matching your 6 personas:
{
  "results": [
    {
      "question_id": 123,
      "verification_audit": {
         "extracted_facts_with_citations": ["Fact 1 (Title, p.X)", "Fact 2..."],
         "option_analysis": {"A": "Supported", "B": "Contradicted", "C": "Unsupported", "D": "Unsupported"},
         "verified_correct_answers": ["A"],
         "confidence_level": "HIGH|MEDIUM|LOW",
         "final_verdict": "VERIFIED|PARTIALLY VERIFIED|INVALID QUESTION"
      },
      "quality_control": {
         "question_validity_status": "VALID|WEAK|INVALID",
         "detected_issues": ["Explanation of issue 1...", "none"],
         "risk_level_for_exam_usage": "LOW|MEDIUM|HIGH",
         "suggested_correction": "How to fix..."
      },
      "source_consistency": {
          "agreement_vs_contradiction": "Description of consensus explicitly mapped to sources",
          "most_defensible_answer": "Option A"
      },
      "anti_hallucination": {
          "verified_facts_only": true,
          "assumptions_made": ["none"],
          "risk_of_hallucination": "LOW|MEDIUM|HIGH"
      },
      "logic_audit": {
          "valid_reasoning_parts": ["Extracted fact strictly supports Option A"],
          "broken_logic_points": [],
          "final_trust_score": 95
      },
      "database_entry": {
          "subject": "Periodontology|Endodontics|etc...",
          "tags": ["diagnosis", "treatment", "pharmacology", "anatomy"],
          "difficulty": "EASY|MEDIUM|HARD",
          "status": "VERIFIED|PROBABLE|UNVERIFIED",
          "normalized_correct_answer_text": "The exact wording of the confirmed correct answer"
      }
    }
  ]
}

CRITICAL RULES:
1. DO NOT GUESS. If evidence is missing, state INSUFFICIENT EVIDENCE and mark Risk High.
2. NO HALLUCINATIONS. Check that every claim is in the provided source PDFs.
3. Detect multiple correct answers hidden as single-choice.
4. Detect ambiguous wording.
"""

client = None

def load_cache():
    p = Path(FILE_CACHE)
    return json.load(open(p, encoding="utf-8")) if p.exists() else {}

def save_cache(cache):
    json.dump(cache, open(FILE_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def upload_books(subject: str) -> list[str]:
    # (Спрощена версія завантаження з кешем для демо-коду)
    # Повна імплементація як у v5_1 з перевіркою ASCII назв і processing check
    folder = SUBJECT_MAP[subject][0]
    books_path = Path(BOOKS_DIR) / folder
    if not books_path.exists():
        print(f"Помилка: папка {books_path} не знайдена.")
        return []

    pdfs = sorted(books_path.glob("*.pdf"))
    if not pdfs:
        return []

    cache = load_cache()
    uris = []
    print(f"Знайдено {len(pdfs)} PDF для {subject}. Перевірка завантажень...")

    for pdf in pdfs:
        key = str(pdf.absolute())
        if key in cache:
            uris.append(cache[key]["uri"])
            continue

        print(f"Завантаження {pdf.name} ...", end=" ", flush=True)
        try:
            f = client.files.upload(file=str(pdf.resolve()), config=types.UploadFileConfig(mime_type="application/pdf"))
            # Чекаємо на PROCESSING
            while f.state.name == "PROCESSING":
                time.sleep(2)
                f = client.files.get(name=f.name)

            if f.state.name == "FAILED":
                print("FAILED")
                continue

            cache[key] = {"uri": f.uri, "name": f.name}
            save_cache(cache)
            uris.append(f.uri)
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")

    return uris

def format_batch(questions: list) -> str:
    lines = []
    for q in questions:
        answers = q.get("c", [])
        lines.append(f"QUESTION ID: {q['id']}")
        lines.append(q["q"])
        for k, v in q["a"].items():
            mark = " (Candidate Correct)" if k in answers else ""
            lines.append(f"  {k}. {v}{mark}")
        lines.append("")
    return "\n".join(lines)

def run_verification(subject: str, all_questions: list, start_batch: int = 1):
    folder, label = SUBJECT_MAP[subject]
    labels_list = label if isinstance(label, list) else [label]
    questions = [q for q in all_questions if q.get("subject") in labels_list]

    if not questions:
        print(f"Не знайдено питань для {subject}.")
        return

    uris = upload_books(subject)
    if not uris:
        print("Немає джерел PDF для верифікації. Пропуск.")
        return

    Path(RESULTS_DIR).mkdir(parents=True, exist_ok=True)

    for i in range(0, len(questions), BATCH_SIZE):
        batch = questions[i: i+BATCH_SIZE]
        bn = i // BATCH_SIZE + start_batch
        fname = os.path.join(RESULTS_DIR, f"{subject}_advanced_batch_{bn:03d}.json")

        if os.path.exists(fname):
            continue

        print(f"Обробка батчу {bn} ({len(batch)} питань)...")

        contents = [types.Part.from_uri(file_uri=u, mime_type="application/pdf") for u in uris]
        contents.append(f"Verify these questions strictly against the documents:\n\n{format_batch(batch)}")

        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.0,
                    response_mime_type="application/json"
                )
            )

            raw_text = resp.text or "{}"
            result_json = json.loads(raw_text)

            with open(fname, "w", encoding="utf-8") as f:
                json.dump(result_json, f, ensure_ascii=False, indent=2)

            print(f" ✓ Збережено: {fname}")

        except Exception as e:
            print(f" ПОМИЛКА: {e}")

        time.sleep(DELAY_SEC)

def main():
    parser = argparse.ArgumentParser(description="Advanced AI Certification Engine")
    parser.add_argument("--subject", required=True, choices=list(SUBJECT_MAP.keys()), help="Subject to process")
    args = parser.parse_args()

    if not os.path.exists(INPUT_CLASSIFIED):
        print(f"Помилка: файл питань {INPUT_CLASSIFIED} відсутній.")
        return

    global client
    client = genai.Client(api_key=GEMINI_API_KEY)

    all_q = json.load(open(INPUT_CLASSIFIED, encoding="utf-8"))
    run_verification(args.subject, all_q)

if __name__ == "__main__":
    main()
