from pydantic import BaseModel


class MuerteRequest(BaseModel):
    id_chiquero: int
    tipo_animal: str
    cantidad: int
    causa: str


class TrasladoRequest(BaseModel):
    id_origen: int
    id_destino: int
    tipo_animal: str
    cantidad: int
    nueva_etapa: str | None = None


class EtapaRequest(BaseModel):
    id_chiquero: int
    tipo_animal: str
    nueva_etapa: str
    cantidad: int


class PartoRequest(BaseModel):
    id_chiquero: int
    crias_vivas: int
    no_logradas: int