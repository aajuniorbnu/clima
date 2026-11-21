from io import BytesIO
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
import main
import weather


@pytest.fixture
def forecast():
    return {'local': {'id': 1, 'nome': 'Itajaí', 'estado': 'Santa Catarina', 'pais': 'Brasil'},
            'fuso': 'America/Sao_Paulo', 'consultado_em': '2026-11-21T12:00:00+00:00',
            'dias': [{'data': f'2026-11-{day}', 'min_c': 17.5, 'max_c': 26,
                      'chuva_probabilidade': None, 'chuva_mm': 0, 'vento_kmh': 15,
                      'condicao': 'Parcialmente nublado'} for day in range(21,28)]}


def test_pdf_sete_dias(forecast):
    reader = PdfReader(BytesIO(weather.gerar_pdf(forecast)))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert 'Itajaí' in text and 'N/D' in text and 'Open-Meteo' in text
    for day in range(21,28): assert f'{day}/11' in text


def test_upload_boto3(forecast, monkeypatch):
    calls = []
    class Client:
        def upload_fileobj(self, stream, bucket, key, ExtraArgs):
            calls.append((stream.read(), bucket, key, ExtraArgs))
    class Session:
        def __init__(self, **kwargs): pass
        def client(self, *args, **kwargs): return Client()
    monkeypatch.setenv('S3_BUCKET', 'bucket-teste')
    monkeypatch.setattr(weather.boto3, 'Session', Session)
    result = weather.enviar_s3(weather.gerar_pdf(forecast), 1)
    assert result['status'] == 'salvo'
    assert calls[0][0].startswith(b'%PDF')
    assert calls[0][1] == 'bucket-teste'
    assert calls[0][3]['ContentType'] == 'application/pdf'
    assert 'ACL' not in calls[0][3]


def test_s3_sem_config(monkeypatch):
    monkeypatch.delenv('S3_BUCKET', raising=False)
    with TestClient(main.app) as client:
        assert client.post('/api/relatorios', json={'local_id':1}).status_code == 503
        assert client.post('/api/relatorios', json={'local_id':0}).status_code == 422


def test_upload_erro(monkeypatch):
    from botocore.exceptions import NoCredentialsError
    class Session:
        def __init__(self, **kwargs): raise NoCredentialsError()
    monkeypatch.setenv('S3_BUCKET', 'teste')
    monkeypatch.setattr(weather.boto3,'Session',Session)
    with pytest.raises(weather.HTTPException) as error:
        weather.enviar_s3(b'%PDF',1)
    assert error.value.status_code == 502


def test_previsao_incompleta(monkeypatch):
    async def fake(url, params):
        if url.endswith('/get'):
            return {'id':1,'name':'Teste','latitude':0,'longitude':0}
        return {'daily': {'time': []}}
    monkeypatch.setattr(weather,'get_json',fake)
    with TestClient(main.app) as client:
        assert client.get('/api/previsao?local_id=1').status_code == 502
