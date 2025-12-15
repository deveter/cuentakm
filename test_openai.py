from dotenv import load_dotenv
from pathlib import Path
import os
import openai

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

api_key = os.getenv("OPENAI_API_KEY")
print("API KEY QUE LEE EL SCRIPT:", api_key)

openai.api_key = api_key

try:
    resp = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": "Dime 'hola' en una sola palabra."}
        ],
        temperature=0,
    )
    print("SALIDA:", resp["choices"][0]["message"]["content"])
except Exception as e:
    print("ERROR LLAMANDO A OPENAI:", e)

