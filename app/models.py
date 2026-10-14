"""Версионированный формат плана, правил и ответов нейросети."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator
from .geometry import xy, validate_polygon

OBJECT_TYPES = ["house", "garage", "bathhouse", "outbuilding", "septic", "cesspit", "well", "bed", "greenhouse", "shrub", "tree"]
ObjectType = Literal["house", "garage", "bathhouse", "outbuilding", "septic", "cesspit", "well", "bed", "greenhouse", "shrub", "tree"]
Scalar = StrictBool | StrictInt | StrictFloat | StrictStr
Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class Point(Model):
    x: float = Field(ge=-1000, le=1000, strict=True)
    y: float = Field(ge=-1000, le=1000, strict=True)


class Parcel(Model):
    id: Identifier
    name: str = Field(min_length=1, max_length=100)
    role: Literal["own", "neighbor"]
    vertices: list[Point] = Field(min_length=3, max_length=60)

    @model_validator(mode="after")
    def polygon_is_simple(self):
        validate_polygon([xy(p) for p in self.vertices])
        return self


class SiteObject(Model):
    id: Identifier
    type: ObjectType
    name: str = Field(min_length=1, max_length=100)
    parcel_id: Identifier
    x: float = Field(ge=-1000, le=1000, strict=True)
    y: float = Field(ge=-1000, le=1000, strict=True)
    width: float = Field(gt=0, le=200, strict=True)
    height: float = Field(gt=0, le=200, strict=True)
    angle: float = Field(ge=-360, le=360, strict=True)
    attributes: dict[str, Scalar | None] = Field(default_factory=dict, max_length=30)


class Utility(Model):
    id: Identifier
    name: str = Field(min_length=1, max_length=100)
    type: Literal["electricity", "gas", "sewer", "water"]
    parcel_id: Identifier
    points: list[Point] = Field(min_length=2, max_length=60)


class Settings(Model):
    grid_step: float = Field(default=1.0, ge=0.1, le=10, strict=True)
    snap: StrictBool = True
    show_neighbors: StrictBool = True
    show_labels: StrictBool = True


class Plan(Model):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=100)
    parcels: list[Parcel] = Field(min_length=1, max_length=16)
    objects: list[SiteObject] = Field(default_factory=list, max_length=150)
    utilities: list[Utility] = Field(default_factory=list, max_length=80)
    settings: Settings = Field(default_factory=Settings)

    @model_validator(mode="after")
    def references(self):
        items = self.parcels + self.objects + self.utilities
        if len({p.id for p in items}) != len(items):
            raise ValueError("Идентификаторы участков, объектов и коммуникаций должны быть уникальны.")
        if sum(p.role == "own" for p in self.parcels) != 1:
            raise ValueError("В плане должен быть ровно один собственный участок.")
        ids = {p.id for p in self.parcels}
        if any(o.parcel_id not in ids for o in self.objects + self.utilities):
            raise ValueError("Объект или коммуникация ссылается на отсутствующий участок.")
        return self


class Source(Model):
    kind: Literal["educational", "normative", "unknown"] = "unknown"
    title: str = Field(min_length=1, max_length=300)
    edition: str = Field(default="", max_length=100)
    clause: str = Field(default="", max_length=100)
    url: str = Field(default="", max_length=500)
    verified: StrictBool = False


class Condition(Model):
    target: Literal["a", "b"]
    field: str = Field(min_length=1, max_length=80)
    operator: Literal["==", "!=", ">=", ">", "<=", "<"]
    value: Scalar


class Rule(Model):
    id: Identifier
    title: str = Field(min_length=1, max_length=200)
    types_a: list[str] = Field(min_length=1, max_length=15)
    types_b: list[str] = Field(default_factory=list, max_length=15)
    parameter: str = Field(min_length=1, max_length=80)
    operator: Literal["==", "!=", ">=", ">", "<=", "<"]
    value: float | None = Field(default=None, ge=0, le=1000000, strict=True)
    unit: str | None = Field(default=None, max_length=30)
    scope: Literal["any", "same_parcel", "different_parcels", "adjacent_parcels"] = "any"
    conditions: list[Condition] = Field(default_factory=list, max_length=20)
    exceptions: list[Condition] = Field(default_factory=list, max_length=20)
    conditions_text: str = Field(default="", max_length=1000)
    exceptions_text: str = Field(default="", max_length=1000)
    unresolved: list[str] = Field(default_factory=list, max_length=20)
    original_fragment: str = Field(min_length=1, max_length=6000)
    source: Source
    status: Literal["draft", "needs_review", "confirmed", "rejected"] = "draft"
    enabled: StrictBool = False


class RuleBase(Model):
    schema_version: Literal[1] = 1
    rules: list[Rule] = Field(default_factory=list, max_length=150)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError("ID правил не должны повторяться.")
        return self


class Fragment(Model):
    text: str = Field(min_length=1, max_length=6000)
    relevant: StrictBool
    reason: str = Field(min_length=1, max_length=1000)


class Fragments(Model):
    fragments: list[Fragment] = Field(max_length=80)


class Entity(Model):
    text: str = Field(min_length=1, max_length=1000)
    kind: Literal["object", "requirement", "prohibition", "condition", "exception", "value"]
    normalized: str = Field(min_length=1, max_length=1000)


class Entities(Model):
    entities: list[Entity] = Field(max_length=200)


class Candidates(Model):
    rules: list[Rule] = Field(max_length=80)


class AnalyzeRequest(Model):
    text: str = Field(min_length=1, max_length=18000)
    source: Source
    model: str = Field(default="qwen2.5:3b", min_length=1, max_length=150)
    order: Literal["filter_first", "entities_first"] = "filter_first"
    seed: int = Field(default=42, ge=0, le=2147483647)
    temperature: float = Field(default=0, ge=0, le=1)
    num_ctx: int = Field(default=16384, ge=4096, le=32768)
    num_predict: int = Field(default=4096, ge=512, le=8192)


class CheckRequest(Model):
    plan: Plan
    rules: RuleBase | None = None


class Endpoint(Model):
    kind: Literal["point", "object", "boundary"]
    id: str | None = None
    point: Point | None = None


class MeasureRequest(Model):
    plan: Plan
    a: Endpoint
    b: Endpoint
