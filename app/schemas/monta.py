from pydantic import BaseModel


class MontaRequest(BaseModel):
    lote_id: int
    fecha_monta: str
    foto_base64: str | None = None


class VerificarPreñezRequest(BaseModel):
    lote_id: int
    confirma_preñez: bool