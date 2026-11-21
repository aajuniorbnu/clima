import asyncio
import sqlite3
from contextlib import closing, suppress
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from postgres_sync import preparar, sincronizar
from air_search import resolver, descobrir
import banco
import relatorio
import json
import math
import os
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")


DB = Path(os.getenv("DB_PATH", str(BASE / "qualidade_ar.db")))

MOCK = os.getenv("MODO_MOCK", "true").lower() == "true"
MAX_IDADE_HORAS = int(os.getenv("MAX_IDADE_HORAS", "3"))
CIDADES = json.loads((BASE / "cidades.json").read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(app):
    banco.iniciar(DB)
    preparar(DB)
    async def worker():
        while True:
            app.state.postgres = await run_in_threadpool(sincronizar, DB)
            await asyncio.sleep(30)
    app.state.postgres = {"status": "iniciando"}
    task = asyncio.create_task(worker())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="dev2 - Qualidade do Ar", version="1.0.0", lifespan=lifespan)


class Medicao(BaseModel):
    sensor_id: Optional[int] = None
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
    local_id: Optional[int] = None
    distancia_km: Optional[float] = None
    provedor: Optional[str] = None


class RelatorioCriado(BaseModel):
    cidade: str
    bucket: str
    chave: str
    url: str
    expira_em_segundos: int


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto.strip().lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")


async def buscar_openaq(estacao_id: int):
    chave = os.getenv("OPENAQ_API_KEY")
    if not chave:
        raise HTTPException(503, "Configure OPENAQ_API_KEY no servidor.")
    try:
        async with httpx.AsyncClient(
            base_url="https://api.openaq.org/v3/", headers={"X-API-Key": chave}, timeout=10
        ) as client:
            detalhe = await client.get(f"locations/{estacao_id}")
            detalhe.raise_for_status()
            ultimas = await client.get(f"locations/{estacao_id}/latest", params={"limit": 100})
            ultimas.raise_for_status()
            return detalhe.json()["results"][0], ultimas.json()["results"]
    except httpx.TimeoutException:
        raise HTTPException(504, "A OpenAQ demorou para responder.")
    except httpx.HTTPStatusError as erro:
        codigo = erro.response.status_code
        if codigo == 429:
            raise HTTPException(503, "Limite de consultas da OpenAQ atingido.")
        raise HTTPException(502, f"Falha na OpenAQ (HTTP {codigo}).")
    except (httpx.RequestError, ValueError, KeyError, IndexError):
        raise HTTPException(502, "Resposta inválida ou falha de conexão com a OpenAQ.")


def converter(estacao: dict, leituras: list, agora: datetime) -> List[Medicao]:
    sensores = {s["id"]: s["parameter"] for s in estacao["sensors"]}
    medicoes = []
    for leitura in leituras:
        parametro = sensores.get(leitura["sensorsId"])
        valor = float(leitura["value"])
        if not parametro or not math.isfinite(valor) or valor < 0:
            continue
        medido = datetime.fromisoformat(leitura["datetime"]["utc"].replace("Z", "+00:00"))
        if medido.tzinfo is None:
            medido = medido.replace(tzinfo=timezone.utc)
        idade = (agora - medido).total_seconds()
        medicoes.append(
            Medicao(
                sensor_id=leitura["sensorsId"],
                poluente=parametro["name"],
                valor=valor,
                unidade=parametro["units"],
                medido_em=medido,
                desatualizado=idade > MAX_IDADE_HORAS * 3600 or idade < -300,
            )
        )
    return medicoes


async def consultar(cidade: str, local_id=None) -> Resposta:
    chave = normalizar(cidade)
    config = CIDADES.get(chave)
    if MOCK and not config:
        raise HTTPException(404, "Cidade não cadastrada em cidades.json.")

    agora = datetime.now(timezone.utc)

    if MOCK:
        resposta = Resposta(
            cidade=config["nome"],
            fonte="mock",
            estacao_nome="Estação fictícia para integração",
            consultado_em=agora,
            medicoes=[
                Medicao(poluente="pm25", valor=12.0, unidade="µg/m³", medido_em=agora, desatualizado=False)
            ],
        )
    else:
        local = await resolver(cidade, local_id)
        estacao, medicoes, distancia = await descobrir(local, converter, agora)
        resposta = Resposta(
            cidade=', '.join(filter(None,[local['nome'],local['estado'],local['pais']])),
            fonte='openaq', estacao_id=estacao['id'],
            estacao_nome=estacao.get('name') or 'Estação OpenAQ',
            consultado_em=agora, medicoes=medicoes, local_id=local['id'],
            distancia_km=distancia, provedor=(estacao.get('provider') or {}).get('name'))
        chave = f"local:{local['id']}"

    banco.salvar_consulta(DB, chave, resposta.fonte, agora.isoformat(), resposta.model_dump_json())
    return resposta


@app.get("/saude")
def saude():
    return {"status": "ok", "modo": "mock" if MOCK else "openaq", "postgres": getattr(app.state, "postgres", {"status": "iniciando"})}


@app.get("/qualidade-ar", response_model=Resposta)
async def qualidade_ar(cidade: str = Query("", max_length=100), local_id: Optional[int] = Query(None, gt=0)):
    if not cidade.strip() and not local_id:
        raise HTTPException(422, "Informe cidade ou local_id.")
    return await consultar(cidade, local_id)


@app.get("/historico", response_model=List[Resposta])
def historico(
    cidade: str = Query("", max_length=100),
    local_id: Optional[int] = Query(None, gt=0),
    limite: int = Query(20, ge=1, le=100),
):
    return banco.historico(DB, f"local:{local_id}" if local_id else normalizar(cidade), limite)


@app.post("/relatorio", response_model=RelatorioCriado)
async def criar_relatorio(cidade: str = Query(..., min_length=1, max_length=100)):
    resposta = await consultar(cidade)
    pdf = await run_in_threadpool(relatorio.gerar_pdf, resposta.model_dump(mode="json"))
    chave = f"relatorios/{normalizar(cidade)}/{resposta.consultado_em:%Y%m%dT%H%M%SZ}.pdf"
    try:
        bucket, url = await run_in_threadpool(relatorio.enviar_s3, pdf, chave)
    except RuntimeError as erro:
        raise HTTPException(503, str(erro))
    except (BotoCoreError, ClientError):
        raise HTTPException(502, "Falha ao enviar o relatório para o S3.")
    banco.salvar_relatorio(DB, normalizar(cidade), bucket, chave, resposta.consultado_em.isoformat())
    return RelatorioCriado(
        cidade=resposta.cidade,
        bucket=bucket,
        chave=chave,
        url=url,
        expira_em_segundos=relatorio.EXPIRA,
    )

from weather import router as weather_router
app.include_router(weather_router)
app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')

@app.get('/', include_in_schema=False)
def frontend():
    return FileResponse(BASE / 'static' / 'index.html')
