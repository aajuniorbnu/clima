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

import banco
import relatorio

MOCK = os.getenv("MODO_MOCK", "true").lower() == "true"
MAX_IDADE_HORAS = int(os.getenv("MAX_IDADE_HORAS", "3"))
CIDADES = json.loads((BASE / "cidades.json").read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(app):
    banco.iniciar()
    yield


app = FastAPI(title="Pessoa B - Qualidade do Ar", version="1.0.0", lifespan=lifespan)


class Medicao(BaseModel):
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
                poluente=parametro["name"],
                valor=valor,
                unidade=parametro["units"],
                medido_em=medido,
                desatualizado=idade > MAX_IDADE_HORAS * 3600 or idade < -300,
            )
        )
    return medicoes


async def consultar(cidade: str) -> Resposta:
    chave = normalizar(cidade)
    config = CIDADES.get(chave)
    if not config:
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
        estacao_id = config.get("estacao_id")
        if not isinstance(estacao_id, int) or estacao_id <= 0:
            raise HTTPException(503, "Cadastre uma estação OpenAQ verificada para esta cidade.")

        estacao, leituras = await buscar_openaq(estacao_id)
        try:
            medicoes = converter(estacao, leituras, agora)
            nome = estacao["name"]
        except (KeyError, ValueError, TypeError):
            raise HTTPException(502, "Formato de medição inesperado na OpenAQ.")
        if not medicoes:
            raise HTTPException(404, "A estação não possui medições válidas disponíveis.")

        resposta = Resposta(
            cidade=config["nome"],
            fonte="openaq",
            estacao_id=estacao_id,
            estacao_nome=nome,
            consultado_em=agora,
            medicoes=medicoes,
        )

    banco.salvar_consulta(chave, resposta.fonte, agora.isoformat(), resposta.model_dump_json())
    return resposta


@app.get("/saude")
def saude():
    return {"status": "ok", "modo": "mock" if MOCK else "openaq"}


@app.get("/qualidade-ar", response_model=Resposta)
async def qualidade_ar(cidade: str = Query(..., min_length=1, max_length=100)):
    return await consultar(cidade)


@app.get("/historico", response_model=List[Resposta])
def historico(
    cidade: str = Query(..., min_length=1, max_length=100),
    limite: int = Query(20, ge=1, le=100),
):
    return banco.historico(normalizar(cidade), limite)


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
    banco.salvar_relatorio(normalizar(cidade), bucket, chave, resposta.consultado_em.isoformat())
    return RelatorioCriado(
        cidade=resposta.cidade,
        bucket=bucket,
        chave=chave,
        url=url,
        expira_em_segundos=relatorio.EXPIRA,
    )