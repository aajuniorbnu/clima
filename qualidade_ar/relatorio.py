"""Relatório da qualidade do ar; previsão semanal permanece em weather.py."""
import os
from io import BytesIO
from xml.sax.saxutils import escape
import boto3
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

EXPIRA = 900

def gerar_pdf(data):
    stream=BytesIO()
    styles=getSampleStyleSheet()
    content=[Paragraph('Qualidade do ar',styles['Title']),
             Paragraph(escape(data['cidade']),styles['Heading2']),
             Paragraph('Fonte: '+escape(data['fonte']),styles['Normal'])]
    for medicao in data['medicoes']:
        content.extend([Spacer(1,12),Paragraph(escape(f"{medicao['poluente']}: {medicao['valor']} {medicao['unidade']} | {medicao['medido_em']}"),styles['Normal'])])
    SimpleDocTemplate(stream).build(content)
    return stream.getvalue()

def enviar_s3(pdf,chave):
    bucket=os.getenv('S3_BUCKET','').strip()
    if not bucket: raise RuntimeError('Configure S3_BUCKET no servidor.')
    client=boto3.Session(profile_name=os.getenv('AWS_PROFILE') or None).client('s3',region_name=os.getenv('AWS_DEFAULT_REGION','sa-east-1'))
    client.upload_fileobj(BytesIO(pdf),bucket,chave,ExtraArgs={'ContentType':'application/pdf'})
    url=client.generate_presigned_url('get_object',Params={'Bucket':bucket,'Key':chave},ExpiresIn=EXPIRA)
    return bucket,url
