# Critérios de triagem v1.0

GET /alerta?local_id=ID&sensivel=false, porta 8003.
O ID é obtido em GET /api/locais na API 8081. Clima e ar usam o mesmo ID.
URL_CLIMA e URL_AR são configuráveis por ambiente, padrão http://127.0.0.1:8081.
Não há modo mock nem valores substitutos para dados faltantes.

## Decisão

A avaliação é das condições atuais, não de todo o dia. Qualquer dado obrigatório ausente, inválido, simulado, antigo ou de local diferente gera status indisponivel e bom_para_correr=null. Os riscos já identificados continuam sendo exibidos. Com dados completos: risco gera nao_recomendado/false; cuidados geram atencao/true; ausência de ambos gera favoravel/true. True indica apenas ausência de bloqueio pelos critérios do projeto, não segurança garantida.

## Limites operacionais do projeto

Estes limites são escolhas conservadoras de produto, não limites médicos universais ou uma implementação de WBGT/índice de calor.

| Fator | Bloqueio | Cuidados |
|---|---|---|
| Temperatura | <10 ou ≥32 °C; sensação ≥32 °C | ≥28 °C |
| Umidade | <20%; ou ≥80% junto com temperatura ≥28 °C | <30% ou ≥80% |
| UV horário | ≥8 | ≥3: proteção solar e sombra |
| Chuva | Precipitação atual >0 mm | Verificar piso |
| Vento | ≥30 km/h ou rajadas ≥40 km/h | Condições locais podem variar |
| Eventos | Trovoada, neve, precipitação congelante | Ausência de código de trovoada não garante ausência de raios |


Clima: máximo 1 hora. UV: máximo 90 minutos, valor da hora mais recente anterior à leitura atual, nunca o máximo diário. Ar: máximo 3 horas. Tolerância de relógio futuro: 5 minutos. Datas climáticas sem offset são interpretadas no fuso da cidade.

## Qualidade do ar: concentrações não são AQI

A integração OpenAQ existente fornece últimas concentrações com unidades e horários. Esses dados sozinhos NÃO permitem converter corretamente para um índice de exposição: falta a série e a janela de média apropriada de cada poluente. Não comparamos uma leitura instantânea com limites de média diária e não assumimos AQI zero.

Por isso o contrato atual produz pendência de índice validado. Para habilitar uma conclusão favorável no futuro, a API de ar deverá fornecer indice_validado com valor numérico, escala US_AQI, método EPA_AQI ou EPA_NowCast, fonte e medido_em. Esse objeto deve vir de um serviço confiável que tenha calculado o índice conforme a metodologia EPA e preservado sua proveniência; o avaliador não calcula nem certifica o índice. Não há campo público para o usuário inserir um AQI arbitrário.

Com índice validado: AQI >100 bloqueia; para perfil sensível, >50 bloqueia por escolha conservadora. 51–100 gera cuidados nos demais perfis. Isso não representa proibição oficial universal para todas as pessoas. Sem índice validado, mesmo concentrações baixas não liberam corrida. Dados simulados nunca habilitam conclusão.

## Referências

- OMS, proteção solar a partir de UV 3: https://www.who.int/news-room/fact-sheets/detail/ultraviolet-radiation
- CDC, calor e atividade física: https://www.cdc.gov/heat-health/risk-factors/heat-and-athletes.html
- AirNow, categorias AQI: https://smoke.airnow.gov/aqi/aqi-basics/
- EPA, metodologia e períodos por poluente: https://document.airnow.gov/technical-assistance-document-for-the-reporting-of-daily-air-quailty.pdf

Pessoas com condições de saúde precisam considerar orientação individual, alertas oficiais e sinais de mal-estar. A triagem não avalia intensidade, duração, aclimatação, hidratação ou histórico clínico.

## Executar

Na raiz do projeto:

```bash
qualidade_ar/.venv/bin/python -m uvicorn main:app --app-dir api-alertas --port 8003
qualidade_ar/.venv/bin/pytest -q api-alertas/test_criterios.py
```

A API 8081 precisa estar em execução. As duas consultas externas são concorrentes; falhas produzem avaliação indisponível, sem expor detalhes internos. A documentação está em http://localhost:8003/docs.


Terreno removido do escopo: a avaliação usa somente clima e qualidade do ar. O painel consulta alertas ao selecionar uma cidade e ao alterar o perfil sensível. Não há monitoramento contínuo nem notificações em segundo plano.

## Atualização 1.1: histórico OpenAQ e consistência

A API B agora produz indice_validado para partículas quando há histórico suficiente da mesma estação exibida. Consulta /v3/sensors/{id}/hours nas 12 horas completas anteriores à hora UTC atual. Exige unidade µg/m³, valor finito não negativo, ausência explícita de flags, intervalo de uma hora e cobertura/completude de pelo menos 75% por hora (critério conservador adicional do projeto). Horas duplicadas conflitantes são descartadas. São necessárias pelo menos duas das três últimas horas completas. Lacunas mantêm seu peso temporal original.

NowCast: peso=max(0.5,mínimo/máximo); série toda zero usa peso 1. Média ponderada por peso elevado à idade da hora. Trunca PM2.5 em uma decimal e PM10 em inteiro; interpola e arredonda pelas faixas EPA vigentes (documento maio/2026). Acima de 500, preserva extrapolação; nunca limita artificialmente um risco extremo. Índice da estação é o maior subíndice de partículas disponíveis. Proveniência, sensores, janela e cobertura acompanham o resultado.

Este cálculo local não certifica a calibração do sensor nem equivale ao AQI oficial da cidade. Gases não são convertidos com a fórmula de partículas. Por isso parcial=true continua gerando limitação na conclusão geral, mas índices elevados geram riscos explícitos. Sem série suficiente, não há cálculo inventado. A estação selecionada não é substituída silenciosamente por outra para obter resultado.

O clima usa uma resposta compartilhada por local_id durante no máximo cinco minutos, com o horário original. O serviço de alertas retorna os dados utilizados; o painel mostra esse mesmo objeto de ar. Buscar ar também seleciona a cidade de clima, evitando misturar cidades. Fontes têm periodicidades diferentes: os horários são exibidos, não artificialmente igualados.

Fonte metodológica: https://document.airnow.gov/technical-assistance-document-for-the-reporting-of-daily-air-quailty.pdf
