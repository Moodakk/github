import fitz  # PyMuPDF
import os
import pytesseract
from PIL import Image
import io

def get_file_size_mb(filepath):
    """Returns file size in MB"""
    return os.path.getsize(filepath) / (1024 * 1024)

def split_pdf(input_path, output_dir, max_size_mb=190, use_ocr=False, progress_callback=None):
    """
    Splits a PDF into multiple PDFs, ensuring each is under max_size_mb.
    Includes an optional OCR step for scanned pages.
    max_size_mb is set to 190 to be safely under the 200MB NotebookLM limit.
    """
    doc = fitz.open(input_path)
    base_name = os.path.splitext(os.path.basename(input_path))[0]

    current_doc = fitz.open()
    part_num = 1
    output_files = []

    temp_path = os.path.join(output_dir, f"temp_part.pdf")

    # Store OCR text to output to a parallel text file since invisible text
    # overlay with complex fonts in pure Python is fragile.
    current_ocr_text = []

    total_pages = len(doc)

    for page_num in range(total_pages):
        # Update progress if callback provided
        if progress_callback:
            progress_callback(page_num, total_pages, f"Обробка сторінки {page_num + 1}/{total_pages}")

        page = doc.load_page(page_num)

        # Add page to current document
        current_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

        # Optional OCR
        if use_ocr:
            text = page.get_text()
            if not text.strip():  # Only OCR if there's no extracted text (likely scanned)
                # Render page to image
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for better OCR
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                # Perform OCR (Czech language)
                ocr_text = pytesseract.image_to_string(img, lang='ces')
                if ocr_text.strip():
                    current_ocr_text.append(f"--- Page {page_num + 1} ---\n{ocr_text}\n")

        # Save temporarily to check size
        current_doc.save(temp_path, garbage=3, deflate=True)
        current_size = get_file_size_mb(temp_path)

        if current_size >= max_size_mb and len(current_doc) > 1:
            # Document is getting too big, remove the last added page, save the part, and start a new one
            current_doc.delete_page(-1)
            final_part_path = os.path.join(output_dir, f"{base_name}_part_{part_num}.pdf")
            current_doc.save(final_part_path, garbage=3, deflate=True)
            output_files.append(final_part_path)

            # Save companion txt file if OCR was used
            if use_ocr and current_ocr_text:
                txt_path = os.path.join(output_dir, f"{base_name}_part_{part_num}_OCR.txt")
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.writelines(current_ocr_text)
                output_files.append(txt_path)
                current_ocr_text = [] # reset for next part

            # Start new document with the page we just removed
            current_doc.close()
            current_doc = fitz.open()
            current_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            part_num += 1

            # Add OCR text for the page we moved to the new document
            if use_ocr and not text.strip() and ocr_text.strip():
                current_ocr_text.append(f"--- Page {page_num + 1} ---\n{ocr_text}\n")

    # Save the remaining pages
    if len(current_doc) > 0:
        final_part_path = os.path.join(output_dir, f"{base_name}_part_{part_num}.pdf")
        current_doc.save(final_part_path, garbage=3, deflate=True)
        output_files.append(final_part_path)

        # Save companion txt file if OCR was used
        if use_ocr and current_ocr_text:
            txt_path = os.path.join(output_dir, f"{base_name}_part_{part_num}_OCR.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.writelines(current_ocr_text)
            output_files.append(txt_path)

    current_doc.close()
    doc.close()

    if os.path.exists(temp_path):
        os.remove(temp_path)

    return output_files
