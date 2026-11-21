import asyncio
import os
from typing import Literal
import httpx
from fastapi import FastAPI, Query
from criterios import avaliar

app=FastAPI(title='dev3 - Alertas de atividade ao ar livre')
URL_CLIMA=os.getenv('URL_CLIMA','http://127.0.0.1:8081').rstrip('/')
URL_AR=os.getenv('URL_AR','http://127.0.0.1:8081').rstrip('/')

@app.get('/alerta')
async def verificar_corrida(local_id:int=Query(...,gt=0),
    sensivel:bool=False):
    async with httpx.AsyncClient(timeout=120) as client:
        async def buscar(url):
            try:
                r=await client.get(url,params={'local_id':local_id})
                r.raise_for_status()
                data=r.json()
                return data if isinstance(data,dict) else None
            except (httpx.HTTPError,ValueError): return None
        clima,ar=await asyncio.gather(buscar(URL_CLIMA+'/api/previsao'),buscar(URL_AR+'/qualidade-ar'))
    if clima and clima.get('local',{}).get('id')!=local_id: clima=None
    if ar and ar.get('local_id')!=local_id: ar=None
    return {'local_id':local_id,'dados_ar':ar, 'dados_clima':clima,**avaliar(clima,ar,sensivel=sensivel)}

@app.get('/saude')
def saude(): return {'status':'ok'}
