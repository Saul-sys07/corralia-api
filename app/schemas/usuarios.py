from pydantic import BaseModel


class UsuarioRequest(BaseModel):
    nombre: str
    rol: str
    pin_temporal: str


class ActivarRequest(BaseModel):
    usuario_id: int
    nuevo_pin: str


class ResetPinRequest(BaseModel):
    usuario_id: int
    nuevo_pin: str
