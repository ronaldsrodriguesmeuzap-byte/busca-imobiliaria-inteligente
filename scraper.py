import requests
from bs4 import BeautifulSoup
import time
import random
import re
import psycopg2
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

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

def scrape_olx(query, cidade):
    resultados = []
    try:
        q = query.replace(' ', '+')
        url = f"https://sc.olx.com.br/regiao-de-criciuma-e-sul-catarinense/imoveis/terrenos-sitios-e-fazendas?q={q}"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, 'html.parser')
        anuncios = soup.select('li[data-lurker-detail="list_id"]')[:10]

        for a in anuncios:
            try:
                titulo = a.select_one('h2')
                preco_el = a.select_one('span[aria-label*="preço"], .OLXad-list-item-price')
                link_el = a.select_one('a')
                descricao_el = a.select_one('p')

                resultado = {
                    'titulo': titulo.text.strip() if titulo else '',
                    'preco': extrair_preco(preco_el.text if preco_el else ''),
                    'area_m2': None,
                    'cidade': cidade,
                    'link': link_el['href'] if link_el else '',
                    'telefone': None,
                    'descricao': descricao_el.text.strip() if descricao_el else '',
                    'fonte': 'OLX'
                }
                resultados.append(resultado)
            except Exception:
                continue
        delay()
    except Exception as e:
        print(f"Erro OLX: {e}")
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
                fonte VARCHAR(50),
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

