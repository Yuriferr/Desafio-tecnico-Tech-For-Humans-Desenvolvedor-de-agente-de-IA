import google.generativeai as genai
import os
from dotenv import load_dotenv


# Carregar variáveis de ambiente
load_dotenv(os.path.join("api", ".env"))
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("ERRO: GOOGLE_API_KEY não encontrada no arquivo .env")
    exit(1)

genai.configure(api_key=api_key)

print("Listando modelos disponíveis para sua chave...")
try:
    models = genai.list_models()
    found = False
    for m in models:
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name} (Display Name: {m.display_name})")
            found = True
    
    if not found:
        print("Nenhum modelo compatível com 'generateContent' encontrado.")
        
except Exception as e:
    print(f"Erro ao listar modelos: {e}")
