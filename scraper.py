import requests
import httpx
import asyncio
import time
import random
import re
import os
import json
import psycopg2
from datetime import datetime
from bs4 import BeautifulSoup
from groq import Groq


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

SEARLO_API_KEY = os.getenv("SEARLO_API_KEY")
SEARLO_URL = "https://api.searlo.tech/api/v1/search/web"
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

def delay():
    time.sleep(random.uniform(1, 3))

def extrair_numero(texto):
    if not texto:
        return None
    nums = re.findall(r'\d+[\.,]?\d*', texto.replace('.', '').replace(',', '.'))
    return float(nums[0]) if nums else None

def extrair_area_m2(texto):
    if not texto:
        return None
    texto = texto.lower()
    num = extrair_numero(texto)
    if not num:
        return None
    if 'hectare' in texto or ' ha' in texto:
        return num * 10000
    if 'km' in texto:
        return num * 1000000
    return num

def extrair_preco(texto):
    if not texto:
        return None
    texto = texto.replace('R$', '').replace('.', '').replace(',', '.').strip()
    return extrair_numero(texto)

def calcular_score(imovel, area_ideal_min=90000, area_ideal_max=110000, preco_max=1000000):
    score = 0
    area = imovel.get('area_m2', 0) or 0
    preco = imovel.get('preco', 0) or 0
    descricao = (imovel.get('descricao', '') or '').lower()

    if area_ideal_min <= area <= area_ideal_max:
        score += 30
    if preco > 0 and preco < preco_max:
        score += 30
    if 'proprietário' in descricao or 'direto' in descricao:
        score += 20
    palavras_agricolas = ['terra fértil', 'apta para agricultura', 'produção agrícola', 'agricultável']
    if any(p in descricao for p in palavras_agricolas):
        score += 20

    return score

def scrape_anuncio(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'lxml')

        # Remove elementos desnecessários
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'iframe']):
            tag.decompose()

        texto = soup.get_text(separator=' ', strip=True)
        texto = ' '.join(texto.split())
        texto = texto[:4000]  # Limita para não estourar tokens

        client = Groq(api_key=GROQ_API_KEY)

        prompt = f"""
Você é um extrator de dados de anúncios imobiliários.
Analise o texto abaixo e extraia as informações em JSON.

Texto do anúncio:
{texto}

Retorne APENAS um JSON válido com esta estrutura:
{{
  "preco": <número em reais ou null>,
  "area_m2": <área em m² como número ou null>,
  "descricao": <descrição completa do imóvel ou null>,
  "telefone": <telefone de contato ou null>,
  "fotos": []
}}

Regras:
- preco deve ser número puro (ex: 950000, não "R$ 950.000")
- area_m2 deve ser em m² (converter hectares: 1ha = 10000m²)
- Se não encontrar o campo, retorne null
- Retorne APENAS o JSON, sem explicações
"""

        resposta = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        conteudo = resposta.choices[0].message.content.strip()
        dados = json.loads(conteudo)
        return dados

    except Exception as e:
        print(f"Erro ao scraping {url}: {e}")
        return None

def buscar_google(query):
    resultados = []
    try:
        async def _search():
            headers = {
                "x-api-key": SEARLO_API_KEY,
                "Content-Type": "application/json"
            }
            params = {
                "q": query,
                "limit": 10,
                "gl": "br"
            }
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(SEARLO_URL, headers=headers, params=params)
                response.raise_for_status()
                return response.json()

        data = asyncio.run(_search())

        for item in data.get("organic", []):
            snippet = item.get("snippet", "")
            link = item.get("link", "")

            # Dados base do snippet
            area_m2 = extrair_area_m2(snippet)
            preco = extrair_preco(snippet)

            # Enriquece com scraping da página
            dados_scraping = scrape_anuncio(link) if link else None

            if dados_scraping:
                area_m2 = dados_scraping.get("area_m2") or area_m2
                preco = dados_scraping.get("preco") or preco
                descricao = dados_scraping.get("descricao") or snippet
                telefone = dados_scraping.get("telefone")
            else:
                descricao = snippet
                telefone = None

            resultado = {
                "titulo": item.get("title", ""),
                "descricao": descricao,
                "link": link,
                "preco": preco,
                "area_m2": area_m2,
                "telefone": telefone,
                "fonte": item.get("domain", "")
            }
            resultados.append(resultado)
            delay()

    except Exception as e:
        print(f"Erro SEARLO Search: {e}")
    return resultados

def filtrar(imoveis, area_min, area_max, preco_max):
    validos = []
    for im in imoveis:
        if not im.get('link'):
            continue
        preco = im.get('preco')
        area = im.get('area_m2')
        if preco and preco > preco_max:
            continue
        if area and (area < area_min or area > area_max):
            continue
        validos.append(im)
    return validos

def salvar_postgres(imoveis, db_url):
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rural_opportunities (
                id SERIAL PRIMARY KEY,
                cidade VARCHAR(100),
                area_m2 FLOAT,
                preco FLOAT,
                preco_por_hectare FLOAT,
                telefone VARCHAR(50),
                link TEXT,
                score INTEGER,
                fonte VARCHAR(100),
                descricao TEXT,
                data_coleta TIMESTAMP,
                status_contato VARCHAR(20) DEFAULT 'novo'
            )
        """)
        for im in imoveis:
            area = im.get('area_m2')
            preco = im.get('preco')
            preco_ha = (preco / (area / 10000)) if area and preco else None
            cur.execute("""
                INSERT INTO rural_opportunities 
                (cidade, area_m2, preco, preco_por_hectare, telefone, link, score, fonte, descricao, data_coleta)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                im.get('cidade'), area, preco, preco_ha,
                im.get('telefone'), im.get('link'), im.get('score', 0),
                im.get('fonte'), im.get('descricao'), datetime.now()
            ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Erro ao salvar: {e}")
