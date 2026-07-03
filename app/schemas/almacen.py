from pydantic import BaseModel


class CompraItem(BaseModel):
    producto: str
    cantidad: float
    unidad: str
    costo: float
    categoria: str


class CompraRequest(BaseModel):
    items: list[CompraItem]
    descuento: float = 0.0
    ticket_url: str | None = None


class RevolturaRequest(BaseModel):
    maiz: float
    salvado: float
    soya: float
    sal: float
    melaza: float


class FotoTicketRequest(BaseModel):
    foto_base64: str
    compra_notas: str = ""


class RacionRequest(BaseModel):
    id_chiquero: int
    producto: str
    cantidad: float
    unidad: str


class SalidaAlimentoRequest(BaseModel):
    id_chiquero: int
    producto: str
    cantidad: float
    unidad: str
    turno: str
