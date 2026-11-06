from pydantic import BaseModel, ConfigDict


class Poi(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    distance: int | None = None
    type: str | None = None
    address: str | None = None
    lat: float
    lng: float
    rating: str | None = None
    cost: str | None = None
    tel: str | None = None


class Meta(BaseModel):
    cachedAt: int | None = None
    stale: bool = False
    degraded: str | None = None
    seed: str | None = None


class Envelope(BaseModel):
    data: object
    meta: Meta
