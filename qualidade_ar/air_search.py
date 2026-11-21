"""Descoberta geográfica de estações OpenAQ, sem cadastro fixo de cidades."""
import os
import math
import httpx
from fastapi import HTTPException
from weather import get_json, GEO, locais

async def resolver(cidade, local_id=None):
    if local_id:
        place = await get_json(GEO + '/get', {'id': local_id, 'language': 'pt'})
        if not place or 'id' not in place:
            raise HTTPException(404, 'Local não encontrado.')
        return {'id':place['id'], 'nome':place['name'], 'estado':place.get('admin1',''),
                'pais':place.get('country',''), 'latitude':place['latitude'], 'longitude':place['longitude']}
    options = await locais(cidade)
    if not options:
        raise HTTPException(404, 'Cidade não encontrada. Tente apenas o nome da cidade.')
    if len(options) > 1:
        raise HTTPException(409, 'Há mais de um local com esse nome. Selecione uma opção usando /api/locais e informe local_id.')
    return options[0]

async def requisitar(client, path, params=None):
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()['results']
    except httpx.TimeoutException:
        raise HTTPException(504, 'A OpenAQ demorou para responder.')
    except httpx.HTTPStatusError as error:
        code = error.response.status_code
        if code in (401,403):
            raise HTTPException(503, 'A OpenAQ recusou a chave configurada. Verifique a credencial no servidor.')
        if code == 429:
            raise HTTPException(503, 'Limite de consultas OpenAQ atingido. Tente mais tarde.')
        raise HTTPException(502, f'Falha na OpenAQ (HTTP {code}).')
    except (httpx.RequestError, ValueError, KeyError):
        raise HTTPException(502, 'Falha de conexão ou resposta inválida da OpenAQ.')

def distancia(local, station):
    a,b=local['latitude'], local['longitude']
    c,d=station['coordinates']['latitude'],station['coordinates']['longitude']
    r=math.pi/180
    h=math.sin((c-a)*r/2)**2+math.cos(a*r)*math.cos(c*r)*math.sin((d-b)*r/2)**2
    return 6371*2*math.asin(min(1,math.sqrt(h)))

async def descobrir(local, converter, agora):
    key=os.getenv('OPENAQ_API_KEY')
    if not key: raise HTTPException(503,'Configure OPENAQ_API_KEY no servidor.')
    async with httpx.AsyncClient(base_url='https://api.openaq.org/v3/', headers={'X-API-Key':key},timeout=10) as client:
        stations=[]
        page=1
        while True:
            batch=await requisitar(client,'locations',{'coordinates':f"{local['latitude']:.4f},{local['longitude']:.4f}",
                 'radius':25000,'limit':100,'page':page,'mobile':'false'})
            stations.extend(batch)
            if len(batch)<100: break
            page+=1
        eligible=[]
        for station in stations:
            if not station.get('coordinates'): continue
            distance=distancia(local,station)
            if distance<=25 and any(s.get('parameter',{}).get('name') in ('pm25','pm10','o3','no2','so2','co') for s in station.get('sensors',[])):
                eligible.append((distance,station))
        eligible.sort(key=lambda item:item[0])
        if not eligible:
            raise HTTPException(404, 'Sem estação de qualidade do ar na OpenAQ em um raio de 25 km deste local. Isso não significa que o ar esteja bom.')
        stale=None
        for distance,station in eligible:
            readings=[];page=1
            while True:
                batch=await requisitar(client,f"locations/{station['id']}/latest",{'limit':100,'page':page})
                readings.extend(batch)
                if len(batch)<100: break
                page+=1
            try:
                measurements=[m for m in converter(station,readings,agora) if m.poluente in ('pm25','pm10','o3','no2','so2','co')]
            except (KeyError,TypeError,ValueError): continue
            if not measurements: continue
            result=(station,measurements,round(distance,2))
            if any(not m.desatualizado for m in measurements): return result
            if stale is None: stale=result
        if stale: return stale
        raise HTTPException(404,'Estações encontradas, mas sem medições válidas disponíveis na OpenAQ.')
