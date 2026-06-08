from pydantic import BaseModel


class PieCriaUpdate(BaseModel):
    lote_id: int
    estado: str
    fecha_monta: str | None = None


class AnimalRequest(BaseModel):
    id_chiquero: int
    tipo_animal: str
    cantidad: int


class CorralRequest(BaseModel):
    nombre: str
    tipo: str = "Comunal"
    zona: str
    largo: float | None = None
    ancho: float | None = None
    capacidad_max: int | None = None


class CorralEditRequest(BaseModel):
    nombre: str
    tipo: str
    zona: str
    capacidad_max: int
    largo: float | None = None
    ancho: float | None = None


class NuclearRequest(BaseModel):
    confirmacion: str


class SolicitudCorralRequest(BaseModel):
    nombre: str
    zona: str
    tipo: str = "Comunal"
    notas: str = ""