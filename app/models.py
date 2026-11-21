from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class ConsultaClima(Base):
    __tablename__ = "consultas_clima"

    id = Column(Integer, primary_key=True, index=True)
    cidade = Column(String, nullable=False)
    temperatura = Column(Float, nullable=False)
    umidade = Column(Integer, nullable=False)
    vento = Column(Float, nullable=False)
    data_consulta = Column(DateTime, default=datetime.now, nullable=False)