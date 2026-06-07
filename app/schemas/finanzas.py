from pydantic import BaseModel


class DepositoRequest(BaseModel):
    monto: float
    notas: str = ""
    entrego: str = ""
    metodo: str = ""


class SueldoItem(BaseModel):
    nombre: str
    monto: float
    dias: int


class NominaRequest(BaseModel):
    items: list[SueldoItem]
    semana: str


class SueldoConfig(BaseModel):
    usuario_id: int
    sueldo_diario: float