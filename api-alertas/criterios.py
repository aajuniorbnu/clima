"""Triagem conservadora do projeto, não uma autorização médica."""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def numero(value, low, high):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and low <= value <= high


def recente(value, now, hours, zone='UTC'):
    try:
        date=datetime.fromisoformat(value.replace('Z','+00:00'))
        if date.tzinfo is None: date=date.replace(tzinfo=ZoneInfo(zone))
        return -300 <= (now-date).total_seconds() <= hours*3600
    except (ValueError,TypeError,AttributeError,KeyError): return False


def avaliar(clima, ar, sensivel=False, now=None):
    now=now or datetime.now(timezone.utc)
    faltas=[]; riscos=[]; cuidados=[]
    atual=(clima or {}).get('atual',{})
    if not clima or clima.get('fonte')!='Open-Meteo': faltas.append('Clima real indisponível ou fonte não reconhecida.')
    if not recente(atual.get('horario'),now,1,(clima or {}).get('fuso','UTC')):
        faltas.append('Horário do clima ausente, futuro ou com mais de uma hora.')
    fields={'temperatura_c':(-90,65),'sensacao_c':(-100,80),'umidade':(0,100),
            'uv':(0,30),'chuva_mm':(0,1000),'vento_kmh':(0,500),'rajada_kmh':(0,500),'codigo':(0,99)}
    for key,(low,high) in fields.items():
        if not numero(atual.get(key),low,high): faltas.append(f'Dado climático ausente ou inválido: {key}.')
    def valid(key): return numero(atual.get(key),*fields[key])
    if valid('temperatura_c'):
        t=atual['temperatura_c']
        if t<10 or t>=32: riscos.append('Temperatura fora da faixa operacional de 10 a menos de 32 °C.')
        elif t>=28: cuidados.append('Calor: reduzir intensidade, buscar sombra e levar água.')
    if valid('sensacao_c') and atual['sensacao_c']>=32: riscos.append('Sensação térmica de pelo menos 32 °C.')
    if valid('umidade'):
        h=atual['umidade']
        if h<20: riscos.append('Umidade abaixo de 20%.')
        elif h<30 or h>=80: cuidados.append('Umidade exige atenção à hidratação e ao esforço.')
        if h>=80 and valid('temperatura_c') and atual['temperatura_c']>=28: riscos.append('Combinação de calor e umidade elevada.')
    if valid('uv'):
        if atual['uv']>=8: riscos.append('UV muito alto: adiar a atividade para horário com menor exposição.')
        elif atual['uv']>=3: cuidados.append('UV ≥ 3: proteção solar, roupa adequada e sombra.')
    if valid('chuva_mm') and atual['chuva_mm']>0: riscos.append('Precipitação atual: adiar e verificar condições do piso.')
    if valid('codigo') and atual['codigo'] in (56,57,66,67,71,73,75,77,85,86,95,96,99): riscos.append('Condição meteorológica adversa: gelo, neve ou trovoada.')
    if (valid('vento_kmh') and atual['vento_kmh']>=30) or (valid('rajada_kmh') and atual['rajada_kmh']>=40): riscos.append('Vento ≥ 30 km/h ou rajadas ≥ 40 km/h.')
    if not recente(atual.get('uv_horario'),now,1.5,(clima or {}).get('fuso','UTC')): faltas.append('UV horário ausente ou desatualizado.')
    if not ar or ar.get('fonte')!='openaq': faltas.append('Qualidade do ar real indisponível ou simulada.')
    else:
        medicoes=ar.get('medicoes',[])
        if not medicoes or any(m.get('desatualizado') is not False or not recente(m.get('medido_em'),now,3) for m in medicoes):
            faltas.append('Medições de qualidade do ar ausentes ou antigas.')
        # Concentrações instantâneas não têm a janela temporal exigida para AQI.
        indice=ar.get('indice_validado') or {}
        if not (indice.get('escala')=='US_AQI' and indice.get('metodo') in ('EPA_NowCast','EPA_AQI')
                and indice.get('fonte') and numero(indice.get('valor'),0,10000)
                and recente(indice.get('medido_em'),now,3)):
            faltas.append('OpenAQ fornece concentrações; falta índice AQI com método, fonte e período validados. Não é possível liberar corrida a partir de uma leitura isolada.')
        else:
            if indice.get('parcial'):
                faltas.append('Indicador de partículas disponível; ozônio e demais gases não avaliados. A conclusão geral permanece limitada.')
            aqi=indice['valor']
            if aqi>100 or (sensivel and aqi>50): riscos.append('AQI acima do limite conservador do projeto para este perfil.')
            elif aqi>50: cuidados.append('AQI moderado: considerar reduzir esforço e duração.')
    status='indisponivel' if faltas else 'nao_recomendado' if riscos else 'atencao' if cuidados else 'favoravel'
    return {'status':status,'bom_para_correr':None if faltas else not bool(riscos),
            'mensagem':{'indisponivel':'Avaliação indisponível: faltam dados confiáveis.',
            'nao_recomendado':'Adie a corrida nas condições avaliadas.',
            'atencao':'Condições exigem precauções; avaliação não garante segurança.',
            'favoravel':'Nenhum impedimento identificado pelos critérios do projeto.'}[status],
            'pendencias':faltas,'riscos':riscos,'cuidados':cuidados,
            'criterio_versao':'1.0','escopo':'Condições atuais; não é previsão para o dia inteiro nem orientação médica individual.'}
