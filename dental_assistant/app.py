import streamlit as st
import os

# Set up page config
st.set_page_config(
    page_title="Dental Exam Assistant",
    page_icon="🦷",
    layout="wide"
)

# Sidebar for configuration
with st.sidebar:
    st.header("⚙️ Налаштування API")
    st.markdown("Введіть ключі для сервісів, які хочете використовувати (всі не обов'язкові).")

    openai_api_key = st.text_input("OpenAI API Key (ChatGPT)", type="password")
    anthropic_api_key = st.text_input("Anthropic API Key (Claude)", type="password")
    gemini_api_key = st.text_input("Google Gemini API Key", type="password")

    st.divider()
    st.info("💡 Ці ключі зберігаються лише у вашому браузері на час поточної сесії і нікуди не відправляються.")

# Main app title
st.title("🦷 Асистент Стоматолога: Підготовка до апробації")

# Create tabs
tab1, tab2 = st.tabs(["📄 Обробка файлів (NotebookLM)", "🤖 Верифікатор тестів"])

with tab1:
    st.header("Підготовка бази знань")
    st.markdown("""
    Тут ви можете завантажити великі PDF-файли. Програма автоматично:
    1. Перевірить їх розмір.
    2. Розділить на частини до 200 МБ (ліміт NotebookLM).
    3. (Опціонально) Проведе розпізнавання тексту (OCR) чеською мовою для сканованих сторінок і видасть окремий `.txt` файл з розпізнаним текстом для завантаження в NotebookLM разом з PDF.
    """)

    uploaded_file = st.file_uploader("Завантажте PDF файл", type=['pdf'])
    use_ocr = st.checkbox("Застосувати OCR (Розпізнавання тексту чеською) - може зайняти багато часу", value=False)

    if st.button("Обрізати та обробити", type="primary"):
        if uploaded_file is not None:
            import tempfile
            from file_processor import split_pdf

            # Create a temporary directory to save output files
            with tempfile.TemporaryDirectory() as temp_dir:
                # Save uploaded file
                temp_input_path = os.path.join(temp_dir, uploaded_file.name)
                with open(temp_input_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                # Progress bar
                progress_bar = st.progress(0)
                status_text = st.empty()

                def update_progress(current, total, message):
                    progress = int((current / total) * 100)
                    progress_bar.progress(progress)
                    status_text.text(message)

                try:
                    with st.spinner("Обробка файлу..."):
                        output_files = split_pdf(
                            input_path=temp_input_path,
                            output_dir=temp_dir,
                            max_size_mb=190, # Under 200MB limit
                            use_ocr=use_ocr,
                            progress_callback=update_progress
                        )

                    progress_bar.progress(100)
                    status_text.text("Обробка завершена!")
                    st.success(f"Файл успішно оброблено. Отримано файлів: {len(output_files)}.")

                    # Provide download links
                    for i, out_file in enumerate(output_files):
                        file_ext = os.path.splitext(out_file)[1]
                        mime_type = "application/pdf" if file_ext.lower() == ".pdf" else "text/plain"
                        with open(out_file, "rb") as f:
                            file_bytes = f.read()
                            st.download_button(
                                label=f"Завантажити: {os.path.basename(out_file)}",
                                data=file_bytes,
                                file_name=os.path.basename(out_file),
                                mime=mime_type,
                                key=f"download_{i}_{os.path.basename(out_file)}"
                            )
                except Exception as e:
                    st.error(f"Виникла помилка: {str(e)}")
        else:
            st.warning("Будь ласка, завантажте файл.")

with tab2:
    st.header("Розумний Верифікатор")
    st.markdown("""
    Введіть тестове питання нижче. Асистент сформує ідеальний медичний промпт з правилом **"все або нічого"** і відправить його до обраного ШІ (або дозволить вам скопіювати його для вашого Pro-акаунту).
    """)

    # Model selection
    selected_model = st.selectbox(
        "Оберіть ШІ для перевірки (потрібен API ключ у налаштуваннях):",
        ["Тільки генерація запиту (для моїх Pro-версій)", "Google Gemini", "Anthropic Claude", "OpenAI ChatGPT"]
    )

    question_text = st.text_area("Введіть текст тестового питання з варіантами відповідей:", height=200)

    if st.button("Перевірити / Згенерувати запит", type="primary"):
        if question_text:
            from verifier import generate_prompt_only, query_gemini, query_claude, query_openai

            if selected_model == "Тільки генерація запиту (для моїх Pro-версій)":
                st.info("Скопіюйте цей текст та вставте його у ваш ChatGPT/Claude Pro:")
                st.code(generate_prompt_only(question_text), language="text")

            elif selected_model == "Google Gemini":
                with st.spinner("Очікуємо відповідь від Gemini..."):
                    response = query_gemini(question_text, gemini_api_key)
                    st.markdown("### Відповідь Gemini:")
                    st.write(response)

            elif selected_model == "Anthropic Claude":
                with st.spinner("Очікуємо відповідь від Claude..."):
                    response = query_claude(question_text, anthropic_api_key)
                    st.markdown("### Відповідь Claude:")
                    st.write(response)

            elif selected_model == "OpenAI ChatGPT":
                with st.spinner("Очікуємо відповідь від ChatGPT..."):
                    response = query_openai(question_text, openai_api_key)
                    st.markdown("### Відповідь ChatGPT:")
                    st.write(response)
        else:
            st.warning("Будь ласка, введіть тестове питання.")
