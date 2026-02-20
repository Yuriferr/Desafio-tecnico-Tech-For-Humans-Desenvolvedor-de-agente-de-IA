from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import triagem, credito, entrevista, cambio
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

app.include_router(triagem.router)
app.include_router(credito.router)
app.include_router(entrevista.router)
app.include_router(cambio.router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, reload_excludes=["data/*", "*.csv", "data/**/*"])
