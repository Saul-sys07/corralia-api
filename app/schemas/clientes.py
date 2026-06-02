from pydantic import BaseModel


class ClienteRequest(BaseModel):
    nombre: str
    telefono: str
    tipo: str
    usuario_id: int