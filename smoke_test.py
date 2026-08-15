import os
from google import genai

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

resp = client.models.generate_content(
    model="gemini-3.5-flash",
    contents="Responde solo: ok",
)
print(resp.text)