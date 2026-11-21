from fastapi import FastAPI, HTTPException
import requests
from app.database import engine, SessionLocal
from app.models import Base, ConsultaClima

Base.metadata.create_all(bind=engine)

app = FastAPI()
app = FastAPI(
    docs_url="/",
    redoc_url=None
)

@app.get("/clima")
def consultar_clima(cidade: str):

    dados = buscar_meteo(cidade)

    if not dados.get("results"):
        raise HTTPException(status_code=404, detail="Cidade não encontrada")

    resultado = dados["results"][0]

    nome_cidade = resultado["name"]
    latitude = resultado["latitude"]
    longitude = resultado["longitude"]

    previsao = buscar_previsao(latitude, longitude)
    atual = previsao["current"]
    db = SessionLocal()
    consulta = ConsultaClima(
    cidade=nome_cidade,
    temperatura=atual["temperature_2m"],
    umidade=atual["relative_humidity_2m"],
    vento=atual["wind_speed_10m"]
)

    db.add(consulta)
    db.commit()
    db.refresh(consulta)
    db.close()

    return {
        "cidade": nome_cidade,
        "latitude": latitude,
        "longitude": longitude,
        "previsao": previsao
    }


def buscar_meteo(cidade: str):
    url = "https://geocoding-api.open-meteo.com/v1/search"

    resposta = requests.get(url, params={
        "name": cidade,
        "count": 1,
        "language": "pt",
        "format": "json"
    })

    return resposta.json()

def buscar_previsao(latitude, longitude):
    url = "https://api.open-meteo.com/v1/forecast"

    resposta = requests.get(url, params={
        "latitude": latitude,
        "longitude": longitude,
        "current": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m"],
        "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_probability_max"],
        "timezone": "America/Sao_Paulo"
    })

    return resposta.json()
