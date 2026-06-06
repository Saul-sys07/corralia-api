from pydantic import BaseModel


class VacunaRequest(BaseModel):
    id_chiquero: int
    tipo_animal: str
    vacuna: str
    nombre_comercial: str = ""
    cantidad: int
    notas: str = ""
