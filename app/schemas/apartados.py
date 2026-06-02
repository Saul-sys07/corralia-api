from pydantic import BaseModel


class ApartadoRequest(BaseModel):
    cliente_id: int
    id_chiquero: int
    tipo_animal: str
    cantidad: int
    anticipo: float
    fecha_compromiso: str
    notas: str = ""