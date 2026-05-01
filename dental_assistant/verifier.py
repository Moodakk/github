import google.generativeai as genai
from anthropic import Anthropic
from openai import OpenAI

SYSTEM_PROMPT = """Ти – висококваліфікований, надзвичайно логічний і суворий колега-стоматолог.
Твоя мета – допомогти з підготовкою до стоматологічної апробації (медичного іспиту) в Чехії.

Умови оцінювання питань:
1. Тести базуються на правилі "ВСЕ АБО НІЧОГО" (All or Nothing). Якщо хоча б один правильний варіант не вибрано, або вибрано хоча б один неправильний – все питання вважається невірним.
2. Не фантазуй і не придумуй інформацію. Якщо в тебе немає точної інформації, чесно скажи про це.
3. Аналізуй питання крок за кроком, використовуючи доказову медицину та сучасні стоматологічні протоколи.
4. Пояснюй свій хід думок логічно і чітко.

Формат твоєї відповіді має бути наступним:
- **Аналіз питання**: [короткий огляд того, що запитується]
- **Оцінка варіантів**: [аналіз кожного варіанту: чому він правильний або неправильний]
- **Фінальний висновок (Правильні варіанти)**: [чіткий перелік правильних варіантів, пам'ятаючи про "все або нічого"]"""

def generate_prompt_only(question):
    return f"""Будь ласка, проаналізуй наступне тестове питання згідно з такими правилами:
1. Ти - висококваліфікований стоматолог. Не фантазуй.
2. Правило "ВСЕ АБО НІЧОГО": питання зараховується тільки якщо обрані всі правильні варіанти і жодного неправильного.
3. Проаналізуй кожен варіант окремо з точки зору доказової медицини.
4. Надай фінальний висновок.

ПИТАННЯ:
{question}
"""

def query_gemini(question, api_key):
    if not api_key:
        return "Помилка: API ключ для Google Gemini не знайдено."
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        response = model.generate_content(f"{SYSTEM_PROMPT}\n\nПИТАННЯ:\n{question}")
        return response.text
    except Exception as e:
        return f"Помилка при запиті до Gemini: {str(e)}"

def query_claude(question, api_key):
    if not api_key:
        return "Помилка: API ключ для Anthropic Claude не знайдено."
    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": question}
            ]
        )
        return response.content[0].text
    except Exception as e:
        return f"Помилка при запиті до Claude: {str(e)}"

def query_openai(question, api_key):
    if not api_key:
        return "Помилка: API ключ для OpenAI не знайдено."
    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Помилка при запиті до OpenAI: {str(e)}"
