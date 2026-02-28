from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import uvicorn
from scraper import buscar_google, filtrar, calcular_score, salvar_postgres

app = FastAPI()

DB_URL = "postgresql://postgres:dgSwyEqtRNbiJaNMtLfFQrfHOaWTrIBm@postgres:5432/busca_imobiliaria_inteligente"

class QueryItem(BaseModel):
    query: str
    cidade: str
    area_min: float
    area_max: float
    preco_min: float
    preco_max: float

class BuscaRequest(BaseModel):
    queries: List[QueryItem]

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/buscar")
def buscar(request: BuscaRequest):
    todos = []
    for item in request.queries:
        resultados = buscar_google(item.query)
        for r in resultados:
            r['cidade'] = item.cidade
        todos.extend(resultados)

    validos = filtrar(todos,
                      request.queries[0].area_min,
                      request.queries[0].area_max,
                      request.queries[0].preco_max)

    for im in validos:
        im['score'] = calcular_score(im)

    validos.sort(key=lambda x: x.get('score', 0), reverse=True)
    salvar_postgres(validos, DB_URL)

    return {
        "total_encontrado": len(todos),
        "total_valido": len(validos),
        "resultados": validos
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
