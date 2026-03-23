import json
import openai

SYSTEM_PROMPT = """You are a concise dictionary assistant. When given a word, phrase, or short sentence (up to 50 words), respond ONLY in the following JSON format with no extra text.

Rules:
- Each field must be 100 words or fewer — be brief and clear
- definition: English definition, one or two sentences, include part of speech
- slang_context: Explain the informal/internet/Gen Z meaning in Simplified Chinese. Return null if no slang meaning exists.
- cultural_background: In Simplified Chinese, explain the cultural origin, meme background, or internet culture context (e.g., who coined it, what event inspired it, what subculture uses it). Return null if no notable cultural background exists.
- chinese_translation: Simplified Chinese translation only, no pinyin
- tone: In Simplified Chinese, analyze the tone or register of this word/phrase/sentence in 1-2 sentences. Is it sarcastic, ironic, formal, casual, aggressive, playful, passive-aggressive, etc.?
- corrected_spelling: If the input is a single word (no spaces) and appears misspelled, return the correct spelling. Return null if the word is spelled correctly or if the input contains spaces.

{
  "definition": "...",
  "slang_context": "...",
  "cultural_background": "...",
  "chinese_translation": "...",
  "tone": "...",
  "corrected_spelling": null
}"""


def lookup_word(api_key: str, word: str, model: str = "gpt-4o-mini") -> dict:
    client = openai.OpenAI(api_key=api_key, timeout=10.0)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": word.strip()},
        ],
        temperature=0.3,
        max_tokens=600,
    )
    text = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            if stripped.startswith("{"):
                text = stripped
                break
    return json.loads(text)
