from pydantic import BaseModel


class FotoChecadorRequest(BaseModel):
    foto_base64: str
    tipo: str
