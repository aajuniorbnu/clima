from fastapi import FastAPI, HTTPException
import httpx

app = FastAPI(title="API de Alertas - Pessoa C")

URL_PESSOA_A = "http://localhost:8080"
URL_PESSOA_B = "http://localhost:8081"

# Deixe True para testar SOZINHO agora.
# Quando a Pessoa A e B ligarem as APIs delas, mude para False!
USAR_MOCK = True

@app.get("/")
def inicio():
    return {"mensagem": "API de Alertas no ar! Acesse /docs ou /alerta?cidade=Itajai"}

@app.get("/alerta")
def verificar_corrida(cidade: str = "Itajai"):
    # 1. Pega dados da Pessoa A (Clima)
    if USAR_MOCK:
        clima = {
            "cidade": cidade,
            "temperatura": 24,
            "chovendo": False,
            "descricao": "Ensolarado"
        }
    else:
        try:
            resposta_a = httpx.get(
                f"{URL_PESSOA_A}/clima",
                params={"cidade": cidade},
                timeout=5.0
            )
            resposta_a.raise_for_status()
            clima = resposta_a.json()
        except Exception as erro:
            raise HTTPException(
                status_code=503,
                detail=f"Erro ao falar com a API de Clima (Pessoa A): {erro}"
            )

    # 2. Pega dados da Pessoa B (Qualidade do Ar)
    if USAR_MOCK:
        ar = {
            "cidade": cidade,
            "aqi": 35,
            "qualidade": "Boa"
        }
    else:
        try:
            resposta_b = httpx.get(
                f"{URL_PESSOA_B}/qualidade-ar",
                params={"cidade": cidade},
                timeout=5.0
            )
            resposta_b.raise_for_status()
            ar = resposta_b.json()
        except Exception as erro:
            raise HTTPException(
                status_code=503,
                detail=f"Erro ao falar com a API de Qualidade do Ar (Pessoa B): {erro}"
            )

    # 3. Regra pra decidir se é bom dia pra correr
    motivos = []

    temperatura = clima.get("temperatura", 25)
    chovendo = clima.get("chovendo", False)
    aqi = ar.get("aqi", 0)

    if chovendo:
        motivos.append("Está chovendo.")
    if temperatura > 32:
        motivos.append(f"Muito calor ({temperatura}°C).")
    elif temperatura < 10:
        motivos.append(f"Muito frio ({temperatura}°C).")
    if aqi > 100:
        motivos.append(f"Qualidade do ar ruim (AQI: {aqi}).")

    bom_para_correr = len(motivos) == 0

    if bom_para_correr:
        mensagem = f"Sim! Ótimo dia para correr ao ar livre em {cidade}."
    else:
        mensagem = f"Não é recomendado correr hoje em {cidade}."

    return {
        "cidade": cidade,
        "bom_para_correr": bom_para_correr,
        "mensagem": mensagem,
        "motivos": motivos,
        "dados_clima": clima,
        "dados_ar": ar
    }