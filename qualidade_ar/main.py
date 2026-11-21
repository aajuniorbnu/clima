import json
import math
import os
import sqlite3
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')
DB = Path(os.getenv('DB_PATH', str(BASE / 'qualidade_ar.db')))
MOCK = os.getenv('MODO_MOCK', 'true').lower() == 'true'
MAX_AGE = int(os.getenv('MAX_IDADE_HORAS', '3'))


def normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto.strip().lower())
                   if unicodedata.category(c) != 'Mn')


def conectar():
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def iniciar_banco():
    with conectar() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS consultas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cidade TEXT NOT NULL,
            fonte TEXT NOT NULL,
            consultado_em TEXT NOT NULL,
            resposta_json TEXT NOT NULL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_cidade_id ON consultas(cidade, id)')


@asynccontextmanager
async def lifespan(app):
    iniciar_banco()
    yield


app = FastAPI(title='Pessoa B - Qualidade do Ar', version='1.0.0', lifespan=lifespan)


class Medicao(BaseModel):
    sensor_id: int
    poluente: str
    valor: float
    unidade: str
    medido_em: datetime
    desatualizado: bool


class Resposta(BaseModel):
    cidade: str
    fonte: str
    estacao_id: Optional[int] = None
    estacao_nome: str
    consultado_em: datetime
    medicoes: List[Medicao]


async def buscar_openaq(estacao_id):
    key = os.getenv('OPENAQ_API_KEY')
    if not key:
        raise HTTPException(503, 'Configure OPENAQ_API_KEY no servidor.')
    try:
        async with httpx.AsyncClient(base_url='https://api.openaq.org/v3/',
                                     headers={'X-API-Key': key}, timeout=10) as client:
            detail = await client.get(f'locations/{estacao_id}')
            detail.raise_for_status()
            station = detail.json()['results'][0]
            readings = []
            page = 1
            while True:
                latest = await client.get(f'locations/{estacao_id}/latest',
                                          params={'limit': 100, 'page': page})
                latest.raise_for_status()
                batch = latest.json()['results']
                readings.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            return station, readings
    except httpx.TimeoutException:
        raise HTTPException(504, 'A OpenAQ demorou para responder.')
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 429:
            raise HTTPException(503, 'Limite de consultas da OpenAQ atingido.')
        raise HTTPException(502, f'Falha na OpenAQ (HTTP {code}).')
    except (httpx.RequestError, ValueError, KeyError, IndexError):
        raise HTTPException(502, 'Resposta inválida ou falha de conexão com OpenAQ.')


def converter(station, readings, now):
    sensors = {s['id']: s['parameter'] for s in station['sensors']}
    result = []
    for reading in readings:
        parameter = sensors.get(reading['sensorsId'])
        if not parameter:
            continue
        value = float(reading['value'])
        if not math.isfinite(value) or value < 0:
            continue
        measured = datetime.fromisoformat(reading['datetime']['utc'].replace('Z', '+00:00'))
        if measured.tzinfo is None:
            raise ValueError('Data sem fuso horário')
        age = (now - measured).total_seconds()
        result.append(Medicao(sensor_id=reading['sensorsId'], poluente=parameter['name'],
                              valor=value, unidade=parameter['units'], medido_em=measured,
                              desatualizado=age > MAX_AGE * 3600 or age < -300))
    return result


@app.get('/saude')
def saude():
    return {'status': 'ok', 'modo': 'mock' if MOCK else 'openaq'}


@app.get('/qualidade-ar', response_model=Resposta)
async def qualidade_ar(cidade: str = Query(..., min_length=1, max_length=100)):
    key = normalizar(cidade)
    cidades = json.loads((BASE / 'cidades.json').read_text())
    if key not in cidades:
        raise HTTPException(404, 'Cidade não cadastrada em cidades.json.')
    config = cidades[key]
    now = datetime.now(timezone.utc)
    station_id = config.get('estacao_id')
    if MOCK:
        station_name = 'Estação fictícia para integração'
        measurements = [Medicao(sensor_id=0, poluente='pm25', valor=12.0,
                                unidade='µg/m³', medido_em=now, desatualizado=False)]
        station_id = None
    else:
        if not isinstance(station_id, int) or station_id <= 0:
            raise HTTPException(503, 'Cadastre uma estação OpenAQ verificada para esta cidade.')
        station, readings = await buscar_openaq(station_id)
        try:
            station_name = station['name']
            measurements = converter(station, readings, now)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(502, 'Formato de medição inesperado na OpenAQ.')
        if not measurements:
            raise HTTPException(404, 'A estação não possui medições válidas disponíveis.')
    response = Resposta(cidade=config['nome'], fonte='mock' if MOCK else 'openaq',
                        estacao_id=station_id, estacao_nome=station_name,
                        consultado_em=now, medicoes=measurements)
    with conectar() as conn:
        conn.execute('INSERT INTO consultas(cidade, fonte, consultado_em, resposta_json) VALUES (?, ?, ?, ?)',
                     (key, response.fonte, now.isoformat(), response.model_dump_json()))
    return response


@app.get('/historico', response_model=List[Resposta])
def historico(cidade: str = Query(..., min_length=1, max_length=100),
              limite: int = Query(20, ge=1, le=100)):
    with conectar() as conn:
        rows = conn.execute('SELECT resposta_json FROM consultas WHERE cidade = ? ORDER BY id DESC LIMIT ?',
                            (normalizar(cidade), limite)).fetchall()
    return [json.loads(row['resposta_json']) for row in rows]


app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')


@app.get('/', include_in_schema=False)
def frontend():
    return FileResponse(BASE / 'static' / 'index.html')

from weather import router as weather_router
app.include_router(weather_router)
