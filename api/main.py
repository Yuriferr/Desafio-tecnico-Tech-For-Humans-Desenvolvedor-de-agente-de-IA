from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import triage, credit
import uvicorn

app = FastAPI(title="Banco Ágil - Agente de Triagem")

# Configurar CORS (mantido)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(triage.router)
app.include_router(credit.router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, reload_excludes=["data/*", "*.csv", "data/**/*"])
