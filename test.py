from google import genai

client = genai.Client()  # 自动从环境变量 GOOGLE_API_KEY 读取

response = client.models.generate_content(
    model="gemini-1.5-flash",
    contents="你好，请介绍一下自己"
)

print(response.text)
