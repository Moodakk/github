import streamlit as st
import os

st.set_page_config(page_title="Асистент стоматолога", page_icon="🦷", layout="wide")

st.title("🦷 Асистент для іспитів зі стоматології")
st.write("Цей додаток допомагає в підготовці до іспитів зі стоматології (Чехія) шляхом аналізу тестів і пошуку книг.")

with st.sidebar:
    st.header("Налаштування")
    gemini_key = st.text_input("Gemini API Key", type="password", help="Введіть свій Gemini API Key")
    if gemini_key:
        os.environ["GEMINI_API_KEY"] = gemini_key
    st.write("---")
    st.write("Інші налаштування...")

st.subheader("Пошук інформації в інтернеті")
book_title = st.text_input("Назва книги або автор:")
search_btn = st.button("Шукати")

if search_btn:
    if not book_title:
        st.warning("Будь ласка, введіть назву книги.")
    else:
        st.info(f"Шукаю інформацію про '{book_title}'...")
        # Placeholder for search functionality

st.write("---")
st.subheader("Авторизація та Аналіз Тестів")
test_subject = st.selectbox("Оберіть предмет", [
    "Пародонтологія",
    "Терапевтична",
    "Хірургія",
    "Дитяча стоматологія",
    "Ортодонтія",
    "Протетика",
    "Загальна"
])
analyze_btn = st.button("Аналізувати Тести")

if analyze_btn:
    if not os.environ.get("GEMINI_API_KEY"):
        st.error("Будь ласка, введіть Gemini API Key у бічній панелі.")
    else:
        st.info(f"Запуск аналізу для предмету: {test_subject}...")
        # Placeholder for Gemini integration
