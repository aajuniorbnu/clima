import os
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4
from xml.sax.saxutils import escape

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix='/api', tags=['Clima e relatórios'])
GEO = 'https://geocoding-api.open-meteo.com/v1'
FORECAST = 'https://api.open-meteo.com/v1/forecast'
FIELDS = ['temperature_2m_min', 'temperature_2m_max', 'precipitation_probability_max',
          'precipitation_sum', 'wind_speed_10m_max', 'weather_code']


async def get_json(url, params):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException:
        raise HTTPException(504, 'O serviço de previsão demorou para responder. Tente novamente.')
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Não foi possível consultar a Open-Meteo. Tente novamente.')


def local_publico(item):
    return {'id': item['id'], 'nome': item['name'], 'estado': item.get('admin1', ''),
            'pais': item.get('country', ''), 'latitude': item['latitude'],
            'longitude': item['longitude']}


@router.get('/locais')
async def locais(nome: str = Query(..., min_length=2, max_length=100)):
    if len(nome.strip()) < 2:
        raise HTTPException(422, 'Digite pelo menos dois caracteres.')
    data = await get_json(GEO + '/search', {'name': nome.strip(), 'count': 8, 'language': 'pt'})
    try:
        return [local_publico(item) for item in data.get('results', [])]
    except (KeyError, TypeError):
        raise HTTPException(502, 'Resposta de localização inválida.')


def condicao(code):
    if code == 0: return 'Céu limpo'
    if code in (1, 2): return 'Parcialmente nublado'
    if code == 3: return 'Nublado'
    if code in (45, 48): return 'Nevoeiro'
    if code in (51, 53, 55, 56, 57): return 'Garoa'
    if code in (61, 63, 65, 66, 67): return 'Chuva'
    if code in (71, 73, 75, 77, 85, 86): return 'Neve'
    if code in (80, 81, 82): return 'Pancadas de chuva'
    if code in (95, 96, 99): return 'Trovoadas'
    return 'Não informado'


@router.get('/previsao')
async def previsao(local_id: int = Query(..., gt=0)):
    place = await get_json(GEO + '/get', {'id': local_id, 'language': 'pt'})
    if not place or 'id' not in place:
        raise HTTPException(404, 'Local não encontrado. Faça uma nova busca.')
    try:
        local = local_publico(place)
        data = await get_json(FORECAST, {'latitude': local['latitude'], 'longitude': local['longitude'],
            'daily': ','.join(FIELDS), 'timezone': 'auto', 'forecast_days': 7,
            'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,is_day,weather_code,wind_speed_10m',
            'temperature_unit': 'celsius', 'wind_speed_unit': 'kmh', 'precipitation_unit': 'mm'})
        daily = data['daily']
        if len(daily['time']) != 7 or any(len(daily[field]) != 7 for field in FIELDS):
            raise ValueError('Previsão incompleta')
        days = []
        for i, day in enumerate(daily['time']):
            days.append({'data': day, 'min_c': daily[FIELDS[0]][i], 'max_c': daily[FIELDS[1]][i],
                'chuva_probabilidade': daily[FIELDS[2]][i], 'chuva_mm': daily[FIELDS[3]][i],
                'vento_kmh': daily[FIELDS[4]][i], 'condicao': condicao(daily[FIELDS[5]][i])})
        return {'local': local, 'fuso': data['timezone'], 'fonte': 'Open-Meteo',
                'consultado_em': datetime.now(timezone.utc).isoformat(), 'dias': days,
                'atual': {'temperatura_c': data.get('current', {}).get('temperature_2m'),
                    'sensacao_c': data.get('current', {}).get('apparent_temperature'),
                    'umidade': data.get('current', {}).get('relative_humidity_2m'),
                    'vento_kmh': data.get('current', {}).get('wind_speed_10m'),
                    'condicao': condicao(data.get('current', {}).get('weather_code')),
                    'codigo': data.get('current', {}).get('weather_code'),
                    'horario': data.get('current', {}).get('time')}}
    except (KeyError, TypeError, ValueError, IndexError):
        raise HTTPException(502, 'O provedor retornou uma previsão incompleta ou inválida.')


def numero(value, suffix=''):
    return 'N/D' if value is None else f'{value:g}{suffix}'.replace('.', ',')


def gerar_pdf(data):
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Brand', fontName='Helvetica-Bold', fontSize=12,
                              textColor=colors.HexColor('#416c55'), spaceAfter=18))
    styles.add(ParagraphStyle(name='ReportTitle', fontName='Helvetica-Bold', fontSize=28,
                              leading=33, textColor=colors.HexColor('#173c34'), spaceAfter=16))
    styles.add(ParagraphStyle(name='SmallReport', fontSize=9, leading=14, textColor=colors.HexColor('#52675e')))
    styles.add(ParagraphStyle(name='CellReport', fontSize=8, leading=11))
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=38, leftMargin=38,
                            topMargin=40, bottomMargin=40, title='Previsão do tempo - 7 dias', author='Atmosfera')
    local = data['local']
    label = ', '.join(filter(None, [local['nome'], local['estado'], local['pais']]))
    dates = [datetime.fromisoformat(d['data']).strftime('%d/%m/%Y') for d in data['dias']]
    content = [Paragraph('ATMOSFERA / MONITOR DA CIDADE', styles['Brand']),
               Paragraph('Sua semana.<br/>A previsão completa.', styles['ReportTitle']),
               Paragraph(escape(label), styles['Heading2']),
               Paragraph(f'{dates[0]} a {dates[-1]} | Fuso: {escape(data["fuso"])}', styles['SmallReport']),
               Spacer(1, 22)]
    rows = [['Data', 'Condição', 'Mín. / Máx.', 'Chuva¹', 'Volume', 'Vento²']]
    for day in data['dias']:
        rows.append([datetime.fromisoformat(day['data']).strftime('%d/%m'),
            Paragraph(escape(day['condicao']), styles['CellReport']),
            f'{numero(day["min_c"])} / {numero(day["max_c"], " °C")}',
            numero(day['chuva_probabilidade'], '%'), numero(day['chuva_mm'], ' mm'),
            numero(day['vento_kmh'], ' km/h')])
    table = Table(rows, colWidths=[44, 125, 105, 60, 65, 120-38], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#173c34')),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white), ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),8), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),12), ('BOTTOMPADDING',(0,0),(-1,-1),12),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#eef4ed'),colors.white]),
        ('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#dce5df'))]))
    content += [table, Spacer(1, 20),
        Paragraph('¹ Probabilidade máxima de precipitação no dia. ² Velocidade máxima do vento a 10 m. '
                  'Volume: precipitação acumulada no dia. N/D: dado não disponível.', styles['SmallReport']),
        Spacer(1, 14), Paragraph('Previsão para hoje e os próximos seis dias, no fuso do local. '
                  'As condições previstas podem mudar; este documento é um retrato da consulta.', styles['SmallReport']),
        Spacer(1, 14), Paragraph('Fonte: Open-Meteo (https://open-meteo.com), CC BY 4.0. '
                  'Localização: GeoNames via Open-Meteo.', styles['SmallReport']),
        Paragraph('Consulta (UTC): ' + escape(data['consultado_em']), styles['SmallReport'])]
    doc.build(content)
    return buffer.getvalue()


@router.get('/previsao/pdf')
async def baixar_pdf(local_id: int = Query(..., gt=0)):
    data = await previsao(local_id)
    pdf = await run_in_threadpool(gerar_pdf, data)
    return Response(pdf, media_type='application/pdf', headers={
        'Content-Disposition': f'attachment; filename="previsao-{local_id}-7-dias.pdf"'})


class PedidoRelatorio(BaseModel):
    local_id: int = Field(gt=0)


def enviar_s3(pdf, local_id):
    bucket = os.getenv('S3_BUCKET', '').strip()
    if not bucket:
        raise HTTPException(503, 'S3 ainda não configurado. Defina S3_BUCKET e as credenciais AWS no servidor.')
    prefix = os.getenv('S3_PREFIX', 'previsoes').strip('/')
    key = '/'.join(filter(None, [prefix, datetime.now(timezone.utc).strftime('%Y/%m/%d'),
                                f'previsao-{local_id}-{uuid4().hex}.pdf']))
    try:
        session = boto3.Session(profile_name=os.getenv('AWS_PROFILE') or None)
        s3 = session.client('s3', region_name=os.getenv('AWS_DEFAULT_REGION') or 'sa-east-1',
                            config=Config(connect_timeout=5, read_timeout=20, retries={'max_attempts': 2}))
        s3.upload_fileobj(BytesIO(pdf), bucket, key, ExtraArgs={'ContentType': 'application/pdf',
                          'ContentDisposition': f'attachment; filename="previsao-{local_id}.pdf"'})
    except (BotoCoreError, ClientError):
        raise HTTPException(502, 'Falha ao salvar no S3. Confira credenciais, região, bucket e permissão s3:PutObject.')
    return {'status': 'salvo', 'bucket': bucket, 'chave': key, 'uri': f's3://{bucket}/{key}'}


@router.post('/relatorios', status_code=201)
async def salvar_relatorio(pedido: PedidoRelatorio):
    if not os.getenv('S3_BUCKET', '').strip():
        raise HTTPException(503, 'S3 ainda não configurado. Você pode baixar o PDF enquanto isso.')
    data = await previsao(pedido.local_id)
    pdf = await run_in_threadpool(gerar_pdf, data)
    return await run_in_threadpool(enviar_s3, pdf, pedido.local_id)
