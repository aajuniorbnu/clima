"""NowCast local de partículas (EPA 2026); não é AQI oficial multipoluente."""
import math
import os
from datetime import datetime, timedelta, timezone
import httpx
from fastapi import HTTPException

BANDS={'pm25':[(0,9,0,50),(9.1,35.4,51,100),(35.5,55.4,101,150),(55.5,125.4,151,200),(125.5,225.4,201,300),(225.5,325.4,301,500)],
       'pm10':[(0,54,0,50),(55,154,51,100),(155,254,101,150),(255,354,151,200),(355,424,201,300),(425,604,301,500)]}

def utc(value):
    date=datetime.fromisoformat(value.replace('Z','+00:00'))
    if date.tzinfo is None: raise ValueError('Fuso ausente')
    return date.astimezone(timezone.utc)

def calcular(rows, pollutant, now):
    end=now.astimezone(timezone.utc).replace(minute=0,second=0,microsecond=0)
    slots={}; invalid=set()
    for row in rows:
        try:
            parameter=row['parameter']
            if parameter['name']!=pollutant or parameter['units'].replace('μ','µ') not in ('µg/m³','µg/m3'): continue
            value=row['value']
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0: continue
            if row.get('flagInfo',{}).get('hasFlags') is not False: continue
            coverage=row.get('coverage') or {}
            if coverage.get('percentCoverage',0)<75 or coverage.get('percentComplete',0)<75: continue
            period=row['period']; start=utc(period['datetimeFrom']['utc']); finish=utc(period['datetimeTo']['utc'])
            if finish-start!=timedelta(hours=1) or start.minute or start.second or start.microsecond: continue
            age=int((end-finish).total_seconds()/3600)
            if finish>end or not 0<=age<12: continue
            if age in slots and slots[age]!=value: invalid.add(age)
            slots[age]=value
        except (KeyError,ValueError,TypeError,AttributeError): continue
    for age in invalid: slots.pop(age,None)
    if len([i for i in slots if i<3])<2: return None
    high=max(slots.values()); low=min(slots.values())
    weight=max(.5,low/high) if high else 1
    concentration=sum(v*weight**i for i,v in slots.items())/sum(weight**i for i in slots)
    factor=10 if pollutant=='pm25' else 1
    concentration=math.floor(concentration*factor+1e-9)/factor
    bands=BANDS[pollutant]
    lo,hi,ilo,ihi=next((b for b in bands if b[0]<=concentration<=b[1]),bands[-1])
    index=math.floor((ihi-ilo)/(hi-lo)*(concentration-lo)+ilo+.5)
    return {'poluente':pollutant,'valor':index,'concentracao_nowcast':concentration,'unidade':'µg/m³',
      'horas_validas':len(slots),'horas_recentes_validas':sum(i<3 for i in slots),
      'inicio':(end-timedelta(hours=12)).isoformat(),'fim':end.isoformat(),
      'medido_em':(end-timedelta(hours=min(slots))).isoformat(), 'peso':weight}

async def indice_estacao(station, now):
    from air_search import requisitar
    end=now.astimezone(timezone.utc).replace(minute=0,second=0,microsecond=0)
    indices=[]; pending=[]
    async with httpx.AsyncClient(base_url='https://api.openaq.org/v3/',headers={'X-API-Key':os.getenv('OPENAQ_API_KEY','')},timeout=15) as client:
        for sensor in station.get('sensors',[]):
            pollutant=sensor.get('parameter',{}).get('name')
            if pollutant not in BANDS: continue
            try:
                rows=[];page=1
                while True:
                    batch=await requisitar(client,f"sensors/{sensor['id']}/hours",{'datetime_from':(end-timedelta(hours=12)).isoformat(),
                      'datetime_to':end.isoformat(),'limit':100,'page':page})
                    rows.extend(batch)
                    if len(batch)<100: break
                    page+=1
                result=calcular(rows,pollutant,now)
                if result:
                    result['sensor_id']=sensor['id'];indices.append(result)
                else: pending.append(f'{pollutant}: histórico horário insuficiente ou inválido.')
            except HTTPException as error: pending.append(f'{pollutant}: {error.detail}')
    if not indices: return None, pending or ['A estação não oferece histórico de PM2.5/PM10 para NowCast.']
    worst=max(indices,key=lambda item:item['valor'])
    return {'valor':worst['valor'],'escala':'US_AQI','metodo':'EPA_NowCast','fonte':'OpenAQ; cálculo local Atmosfera',
       'medido_em':min(i['medido_em'] for i in indices),'estacao_id':station['id'],
       'escopo':'particulas','parcial':True,'subindices':indices,
       'observacao':'Indicador calculado para partículas disponíveis, não AQI oficial da cidade. Ozônio e outros gases não estão avaliados.'},pending
