from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import triage
import uvicorn

app = FastAPI(title="Banco Ágil - Agente de Triagem")

# Configurar CORS para permitir que o frontend (qualquer origem local ou file://) acesse a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite todas as origens (simplificado para desenvolvimento)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(triage.router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
