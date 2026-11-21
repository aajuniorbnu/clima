from copy import deepcopy
from datetime import datetime, timezone
import pytest
from criterios import avaliar

NOW=datetime(2026,11,21,12,tzinfo=timezone.utc)
STAMP=NOW.isoformat()

def dados():
    return ({'fonte':'Open-Meteo','fuso':'UTC','atual':{'horario':STAMP,'uv_horario':STAMP,
       'temperatura_c':24,'sensacao_c':24,'umidade':50,'uv':2,'chuva_mm':0,
       'vento_kmh':10,'rajada_kmh':15,'codigo':0}},
       {'fonte':'openaq','medicoes':[{'desatualizado':False,'medido_em':STAMP}],
        'indice_validado':{'escala':'US_AQI','metodo':'EPA_NowCast','fonte':'fixture', 'valor':35,'medido_em':STAMP}})

def test_sem_aqi_nao_libera():
    c,a=dados();del a['indice_validado']
    r=avaliar(c,a,now=NOW)
    assert r['status']=='indisponivel' and r['bom_para_correr'] is None

@pytest.mark.parametrize('key,value',[('temperatura_c',32),('sensacao_c',32),('umidade',19),('uv',8),('chuva_mm',.1),('vento_kmh',30),('rajada_kmh',40),('codigo',95)])
def test_riscos(key,value):
    c,a=dados();c['atual'][key]=value
    r=avaliar(c,a,now=NOW)
    assert r['status']=='nao_recomendado' and r['bom_para_correr'] is False

@pytest.mark.parametrize('key',['temperatura_c','umidade','uv','chuva_mm','vento_kmh','rajada_kmh'])
def test_ausencia(key):
    c,a=dados();del c['atual'][key]
    assert avaliar(c,a,now=NOW)['bom_para_correr'] is None

def test_mock_antigo_terreno():
    c,a=dados();a['fonte']='mock'
    assert avaliar(c,a,now=NOW)['status']=='indisponivel'
    c,a=dados();a['medicoes'][0]['medido_em']='2020-01-01T12:00:00Z'
    assert avaliar(c,a,now=NOW)['status']=='indisponivel'
    c,a=dados()
    assert avaliar(c,a,now=NOW)['status']=='favoravel'

def test_favoravel_e_perfil():
    c,a=dados()
    assert avaliar(c,a,now=NOW)['status']=='favoravel'
    a['indice_validado']['valor']=75
    assert avaliar(c,a,sensivel=True,now=NOW)['status']=='nao_recomendado'
    assert avaliar(c,a,now=NOW)['status']=='atencao'

def test_risco_preservado_quando_falta_ar():
    c,a=dados();c['atual']['codigo']=95
    r=avaliar(c,None,now=NOW)
    assert r['status']=='indisponivel' and r['riscos']
