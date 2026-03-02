from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import uvicorn
from scraper import filtrar, calcular_score, salvar_postgres, extrair_dados_tavily

app = FastAPI()
DB_URL = "postgresql://postgres:dgSwyEqtRNbiJaNMtLfFQrfHOaWTrIBm@postgres:5432/busca_imobiliaria_inteligente"

class TavilyItem(BaseModel):
    titulo: str
    link: str
    content: str
    cidade: str

class EstruturarRequest(BaseModel):
    itens: List[TavilyItem]
    area_min: float
    area_max: float
    preco_min: float
    preco_max: float

@app.post("/estruturar")
def estruturar(request: EstruturarRequest):
    todos = []
    for item in request.itens:
    dados = extrair_dados_tavily(item.titulo, item.content)
    if not dados or not isinstance(dados, dict):
        # Usa dados mínimos do próprio Tavily sem Groq
        resultado = {
            "titulo": item.titulo,
            "descricao": item.content[:200],
            "link": item.link,
            "preco": None,
            "area_m2": None,
            "telefone": None,
            "fotos": [],
            "is_imovel": True,
            "fonte": item.link.split("/")[2] if item.link else "",
            "cidade": item.cidade
        }
        todos.append(resultado)
        continue
        resultado = {
            "titulo": item.titulo,
            "descricao": dados.get("descricao") or item.content[:200],
            "link": item.link,
            "preco": dados.get("preco"),
            "area_m2": dados.get("area_m2"),
            "telefone": dados.get("telefone"),
            "fotos": [],
            "is_imovel": dados.get("is_imovel", True),
            "fonte": item.link.split("/")[2] if item.link else "",
            "cidade": item.cidade
        }
        todos.append(resultado)

    validos = [im for im in todos if im.get('is_imovel', True) and im.get('link')]
    for im in validos:
        im["score"] = calcular_score(im)
    validos.sort(key=lambda x: x.get("score", 0), reverse=True)
    salvar_postgres(validos, DB_URL)

    return {
        "total_encontrado": len(todos),
        "total_valido": len(validos),
        "resultados": validos
    }

class ScrapeRequest(BaseModel):
    urls: List[str]
    cidade: str
    area_min: float
    area_max: float
    preco_min: float
    preco_max: float

@app.post("/scrape")
def scrape(request: ScrapeRequest):
    todos = []
    for url in request.urls:
        dados = scrape_anuncio(url)
        if not dados:
            continue
        resultado = {
            "titulo": "",
            "descricao": dados.get("descricao") or "",
            "link": url,
            "preco": dados.get("preco"),
            "area_m2": dados.get("area_m2"),
            "telefone": dados.get("telefone"),
            "fotos": dados.get("fotos", []),
            "is_imovel": dados.get("is_imovel", True),
            "fonte": url.split("/")[2] if url else "",
            "cidade": request.cidade
        }
        todos.append(resultado)

    validos = filtrar(todos, request.area_min, request.area_max, request.preco_max)
    for im in validos:
        im["score"] = calcular_score(im)
    validos.sort(key=lambda x: x.get("score", 0), reverse=True)
    salvar_postgres(validos, DB_URL)

    return {
        "total_encontrado": len(todos),
        "total_valido": len(validos),
        "resultados": validos
    }

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
