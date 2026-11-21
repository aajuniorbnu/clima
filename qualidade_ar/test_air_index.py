from datetime import datetime, timedelta, timezone
import pytest
from air_index import calcular

NOW=datetime(2026,11,21,12,15,tzinfo=timezone.utc)
def row(age,value=9,pol='pm25'):
    end=NOW.replace(minute=0)-timedelta(hours=age)
    return {'value':value,'parameter':{'name':pol,'units':'µg/m³'},'flagInfo':{'hasFlags':False},
            'coverage':{'percentCoverage':100,'percentComplete':100},'period':{
                'datetimeFrom':{'utc':(end-timedelta(hours=1)).isoformat()},'datetimeTo':{'utc':end.isoformat()}}}

def test_constant_and_boundary():
    assert calcular([row(i) for i in range(12)],'pm25',NOW)['valor']==50
    assert calcular([row(i,35.4) for i in range(12)],'pm25',NOW)['valor']==100
    assert calcular([row(i,54,'pm10') for i in range(12)],'pm10',NOW)['valor']==50

def test_missing_recent():
    assert calcular([row(i) for i in range(2,12)],'pm25',NOW) is None
    assert calcular([row(0),row(2)],'pm25',NOW)['horas_validas']==2

@pytest.mark.parametrize('change',[{'value':-1},{'value':float('nan')},{'flagInfo':{'hasFlags':True}},
 {'coverage':{'percentCoverage':50,'percentComplete':100}}, {'parameter':{'name':'pm25','units':'ppm'}}])
def test_invalid(change):
    rows=[row(0),row(1)];rows[1].update(change)
    assert calcular(rows,'pm25',NOW) is None

def test_conflicting_duplicate():
    assert calcular([row(0),row(0,30),row(1)],'pm25',NOW) is None

def test_weighted():
    r=calcular([row(0,20),row(1,10)],'pm25',NOW)
    assert r['peso']==.5 and r['concentracao_nowcast']==16.6

def test_zero():
    assert calcular([row(0,0),row(1,0)],'pm25',NOW)['valor']==0
