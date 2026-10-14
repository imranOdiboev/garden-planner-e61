"""Локальный FastAPI сервер. Данные пользователя не отправляются в облако."""
import json
import threading
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from .models import Plan, RuleBase, Rule, CheckRequest, MeasureRequest, AnalyzeRequest
from .geometry import xy, footprint, polygon_distance, boundary_distance, point_polygon_distance
from .rules import check_plan, assert_activatable, detect_relations

ROOT = Path(__file__).resolve().parent.parent
RULE_PATH = ROOT / "data" / "rules.json"
RULE_LOCK = threading.Lock()
app = FastAPI(title="Планировщик садового участка", version="1.0.0")


@app.middleware("http")
async def local_requests(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    if host not in ("localhost", "127.0.0.1", "[", "testserver"):
        return JSONResponse({"detail": "Приложение доступно только локально через localhost или 127.0.0.1."}, status_code=400)
    origin = request.headers.get("origin")
    if request.method in ("POST", "PUT", "DELETE") and origin and origin not in ("http://"+request.headers.get("host", ""), "https://"+request.headers.get("host", "")):
        return JSONResponse({"detail": "Запрос с другой страницы отклонён. Откройте интерфейс этого приложения."}, status_code=403)
    size = request.headers.get("content-length", "0")
    if size.isdigit() and int(size) > 2_000_000:
        return JSONResponse({"detail": "Файл или запрос больше 2 МБ."}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    problems = []
    labels = {"parcels": "участки", "objects": "объекты", "utilities": "коммуникации", "vertices": "вершины", "points": "точки", "name": "название", "type": "тип", "width": "ширина", "height": "глубина", "angle": "поворот", "parcel_id": "участок", "schema_version": "версия формата", "rules": "правила", "settings": "настройки", "attributes": "характеристики"}
    messages = {"missing": "Обязательное поле отсутствует.", "extra_forbidden": "Лишнее поле не поддерживается.",
                "literal_error": "Неподдерживаемое значение. Проверьте версию формата или тип элемента.",
                "float_type": "Ожидается число, а не текст или логическое значение.", "int_type": "Ожидается целое число.",
                "float_parsing": "Не удалось прочитать число.", "int_parsing": "Не удалось прочитать целое число.",
                "bool_type": "Ожидается логическое значение true/false.", "string_type": "Ожидается текст.",
                "finite_number": "Число должно быть конечным: NaN и бесконечность недопустимы.",
                "list_type": "Ожидается список элементов.", "dict_type": "Ожидается объект JSON.",
                "json_invalid": "Ошибка синтаксиса JSON.", "string_pattern_mismatch": "Недопустимый идентификатор: используйте латинские буквы, цифры, дефис или подчёркивание."}
    for error in exc.errors()[:12]:
        field = " → ".join(labels.get(str(x), str(x)) for x in error["loc"] if x != "body")
        kind, context = error["type"], error.get("ctx", {})
        if kind == "value_error":
            message = str(error["msg"]).removeprefix("Value error, ")
        elif kind in ("too_short", "string_too_short"):
            message = f"Нужно не менее {context.get('min_length', '?')} элементов или символов."
        elif kind in ("too_long", "string_too_long"):
            message = f"Допускается не более {context.get('max_length', '?')} элементов или символов."
        elif kind in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
            limit = next((context[k] for k in ("gt", "ge", "lt", "le") if k in context), "?")
            operator = {"greater_than": ">", "greater_than_equal": ">=", "less_than": "<", "less_than_equal": "<="}[kind]
            message = f"Число должно удовлетворять условию {operator} {limit}."
        else:
            message = messages.get(kind, "Значение не соответствует формату данных.")
        problems.append(f"{field}: {message}")
    return JSONResponse({"detail": "Некорректный формат данных. Проверьте обязательные поля, числа и геометрию.", "errors": problems}, status_code=422)


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


def load_rules():
    return RuleBase.model_validate_json(RULE_PATH.read_text(encoding="utf-8"))


def save_rules(base):
    base = RuleBase.model_validate(base.model_dump())
    temp = RULE_PATH.with_suffix(".tmp")
    temp.write_text(base.model_dump_json(indent=2), encoding="utf-8")
    temp.replace(RULE_PATH)


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/example")
def example():
    return Plan.model_validate_json((ROOT / "data" / "example_plan.json").read_text(encoding="utf-8"))


@app.post("/api/plan/validate")
def validate_plan(plan: Plan):
    return plan


@app.post("/api/check")
def check(body: CheckRequest):
    return check_plan(body.plan, (body.rules or load_rules()).rules)


@app.post("/api/measure")
def measure(body: MeasureRequest):
    def endpoint(e):
        if e.kind == "point":
            if e.point is None:
                raise ValueError("Для точки нужны координаты.")
            return e.kind, xy(e.point)
        collection = body.plan.objects if e.kind == "object" else body.plan.parcels
        selected = next((o for o in collection if o.id == e.id), None)
        if selected is None:
            raise ValueError("Выберите существующий объект или границу участка.")
        return e.kind, footprint(selected) if e.kind == "object" else [xy(p) for p in selected.vertices]
    ka, a = endpoint(body.a)
    kb, b = endpoint(body.b)
    if ka == kb == "point":
        from math import hypot
        distance, p, q = hypot(a[0]-b[0], a[1]-b[1]), a, b
    elif ka == "point":
        distance, p, q = point_polygon_distance(a, b, kb == "boundary")
    elif kb == "point":
        distance, q, p = point_polygon_distance(b, a, ka == "boundary")
    elif ka == "boundary" or kb == "boundary":
        distance, p, q = boundary_distance(a, b)
    else:
        distance, p, q = polygon_distance(a, b)
    return {"distance": round(distance, 4), "unit": "м", "points": [p, q]}


@app.get("/api/rules")
def get_rules():
    return load_rules()


@app.post("/api/rules/relations")
def relations(base: RuleBase):
    return {"relations": detect_relations(base.rules)}


@app.post("/api/rules/confirm")
def confirm(rule: Rule):
    assert_activatable(rule)
    with RULE_LOCK:
        base = load_rules()
        others = [r for r in base.rules if r.id != rule.id]
        active = [r for r in others if r.enabled and r.status == "confirmed"]
        relations = [r for r in detect_relations(active+[rule]) if rule.id in (r["a"], r["b"]) and r["kind"] in ("conflict", "duplicate")]
        if relations:
            return JSONResponse({"detail": "Есть дубли или противоречия с базой. Исправьте кандидат перед подтверждением.", "relations": relations}, status_code=409)
        rule.status, rule.enabled = "confirmed", True
        base.rules = others+[rule]
        save_rules(base)
    return {"rule": rule, "message": "Правило подтверждено человеком и включено в базу."}


@app.post("/api/rules/import")
def import_rules(base: RuleBase):
    for r in base.rules:
        if r.enabled:
            if r.status != "confirmed":
                raise ValueError("Активное правило должно быть подтверждено.")
            assert_activatable(r)
    problems = [r for r in detect_relations([r for r in base.rules if r.enabled]) if r["kind"] in ("conflict", "duplicate")]
    if problems:
        return JSONResponse({"detail": "Активная база содержит дубли или противоречия.", "relations": problems}, status_code=409)
    with RULE_LOCK:
        save_rules(base)
    return base


@app.get("/api/ai/status")
def ai_status(model: str = "qwen2.5:3b"):
    from .neural import OllamaClient
    return OllamaClient().status(model)


@app.post("/api/ai/analyze")
def analyze(body: AnalyzeRequest):
    from .neural import analyze_text, ModelUnavailable, InvalidModelResponse
    try:
        return analyze_text(body)
    except ModelUnavailable as exc:
        return JSONResponse({"detail": str(exc), "code": "model_unavailable"}, status_code=503)
    except InvalidModelResponse as exc:
        return JSONResponse({"detail": str(exc), "code": "invalid_model_response"}, status_code=502)


@app.get("/api/dataset")
def dataset():
    return json.loads((ROOT / "evaluation" / "dataset.json").read_text(encoding="utf-8"))


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
