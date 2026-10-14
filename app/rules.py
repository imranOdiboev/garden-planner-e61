"""Применение правил и консервативная проверка совместимости кандидатов."""
import json
from itertools import combinations
from math import inf
from .models import Rule, Plan, OBJECT_TYPES
from .geometry import EPS, footprint, xy, polygon_distance, boundary_distance, polygon_contains

UNIT_FACTORS = {"m": 1.0, "м": 1.0, "cm": 0.01, "см": 0.01, "mm": 0.001, "мм": 0.001}


def compare(actual, operator, required):
    if actual is None or required is None:
        return None
    # bool не считается числом при проверке атрибутов.
    if isinstance(actual, bool) != isinstance(required, bool):
        return None
    if operator in ("==", "!="):
        equal = actual == required
        if isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(required, (int, float)):
            equal = abs(actual-required) <= EPS
        return equal if operator == "==" else not equal
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not isinstance(required, (int, float)):
        return None
    return {">=": actual >= required-EPS, ">": actual > required+EPS,
            "<=": actual <= required+EPS, "<": actual < required-EPS}[operator]


def supported(rule):
    if rule.parameter not in ("distance", "boundary_distance", "height_m"):
        return "Параметр пока не поддерживается вычислителем; требуется ручная проверка."
    if rule.value is None or rule.unit not in UNIT_FACTORS:
        return "Не задано числовое значение или поддерживаемая единица длины (м, см, мм)."
    if any(t not in OBJECT_TYPES for t in rule.types_a):
        return "Неизвестный тип объекта в роли a."
    if rule.parameter == "distance" and (not rule.types_b or any(t not in OBJECT_TYPES for t in rule.types_b)):
        return "Для расстояния нужны известные типы объектов в роли b."
    if rule.parameter == "boundary_distance" and rule.types_b != ["boundary"]:
        return "Для отступа types_b должно быть [boundary]."
    if rule.parameter == "height_m" and rule.types_b:
        return "Правило высоты должно иметь пустое types_b."
    if rule.parameter != "distance" and any(c.target == "b" for c in rule.conditions + rule.exceptions):
        return "Условие с target b требует второго объекта; для границы и высоты используйте target a."
    if rule.unresolved or (rule.conditions_text and not rule.conditions) or (rule.exceptions_text and not rule.exceptions):
        return "Есть условия или исключения, не переведённые в проверяемую форму."
    return None


def assert_activatable(rule):
    if rule.source.kind == "unknown":
        raise ValueError("Укажите учебный источник или проверенный нормативный документ.")
    if rule.source.kind == "normative" and not (rule.source.verified and rule.source.title and rule.source.edition and rule.source.clause and rule.source.url):
        raise ValueError("Для нормативного правила нужны документ, редакция, пункт, ссылка и подтверждение проверки источника человеком.")
    problem = supported(rule)
    if problem:
        raise ValueError(problem)


def applicability(rule, a, b):
    missing = []
    false_condition = False
    for condition in rule.conditions:
        obj = a if condition.target == "a" else b
        actual = obj.attributes.get(condition.field) if obj is not None else None
        result = compare(actual, condition.operator, condition.value)
        if result is None:
            missing.append(f"{condition.target}.{condition.field}")
        elif not result:
            false_condition = True
    if false_condition:
        return "skip", "Условия применения не выполняются."
    for exception in rule.exceptions:
        obj = a if exception.target == "a" else b
        actual = obj.attributes.get(exception.field) if obj is not None else None
        result = compare(actual, exception.operator, exception.value)
        if result:
            return "skip", "Применяется исключение из правила."
        if result is None:
            missing.append(f"{exception.target}.{exception.field}")
    if missing:
        return "unknown", "Не заполнены или несовместимы характеристики: " + ", ".join(sorted(set(missing)))
    return "apply", "Условия выполнены; исключения не применяются."


def describe_conditions(rule):
    def value(v):
        return "да" if v is True else "нет" if v is False else str(v)
    conditions = rule.conditions_text or "; ".join(f"{c.target}.{c.field} {c.operator} {value(c.value)}" for c in rule.conditions) or "Без дополнительных условий"
    exceptions = rule.exceptions_text or "; ".join(f"{c.target}.{c.field} {c.operator} {value(c.value)}" for c in rule.exceptions)
    return conditions + (". Исключения: " + exceptions if exceptions else "")


def record(rule_id, title, status, ids, names, actual, required, operator, conditions, explanation, source, unit="м", points=None):
    return dict(rule_id=rule_id, title=title, status=status, object_ids=ids, object_names=names,
                actual=actual, required=required, operator=operator, unit=unit, conditions=conditions,
                explanation=explanation, source=source, points=points)


def check_plan(plan: Plan, rules: list[Rule]):
    results = []
    parcels = {p.id: p for p in plan.parcels}
    outlines = {o.id: footprint(o) for o in plan.objects}
    source = {"kind": "educational", "title": "Геометрическая целостность учебной схемы (не строительная норма)", "edition": "1", "clause": "geometry", "url": "", "verified": False}
    for obj in plan.objects:
        poly = [xy(p) for p in parcels[obj.parcel_id].vertices]
        distance, p, q = boundary_distance(outlines[obj.id], poly)
        inside = polygon_contains(poly, outlines[obj.id])
        results.append(record("geometry_inside", "Принадлежность участку", "complies" if inside else "violation", [obj.id], [obj.name, parcels[obj.parcel_id].name], round(distance, 4), None, "inside", "Контур должен полностью лежать в назначенном участке", "Контур внутри участка." if inside else "Контур выходит за границы назначенного участка.", source, points=[p, q]))
    for a, b in combinations(plan.objects, 2):
        distance, p, q = polygon_distance(outlines[a.id], outlines[b.id])
        if distance <= EPS:
            results.append(record("geometry_overlap", "Пересечение контуров", "violation", [a.id, b.id], [a.name, b.name], 0.0, 0.0, ">", "Геометрическое предупреждение: любые объекты, включая касание", "Контуры пересекаются, вложены или касаются. Допустимость совмещения оценивается человеком.", source, points=[p, q]))
    for rule in rules:
        if not rule.enabled or rule.status != "confirmed":
            continue
        first = [o for o in plan.objects if o.type in rule.types_a]
        seen = set()
        for a in first:
            second = [o for o in plan.objects if o.type in rule.types_b and o.id != a.id] if rule.parameter == "distance" else [None]
            for b in second:
                if b:
                    key = tuple(sorted((a.id, b.id)))
                    # Направленные условия на a/b нельзя сворачивать в неупорядоченную пару.
                    if not rule.conditions and not rule.exceptions:
                        if key in seen:
                            continue
                        seen.add(key)
                    if rule.scope == "same_parcel" and a.parcel_id != b.parcel_id:
                        continue
                    if rule.scope in ("different_parcels", "adjacent_parcels") and a.parcel_id == b.parcel_id:
                        continue
                    if rule.scope == "adjacent_parcels":
                        pa, pb = ([xy(p) for p in parcels[x.parcel_id].vertices] for x in (a, b))
                        if boundary_distance(pa, pb)[0] > EPS:
                            continue
                problem = supported(rule)
                state, reason = applicability(rule, a, b)
                if state == "skip" and not problem:
                    continue
                points = None
                if rule.parameter == "distance" and b:
                    actual, p, q = polygon_distance(outlines[a.id], outlines[b.id])
                    points = [p, q]
                elif rule.parameter == "boundary_distance":
                    actual, p, q = boundary_distance(outlines[a.id], [xy(p) for p in parcels[a.parcel_id].vertices])
                    points = [p, q]
                    if not polygon_contains([xy(p) for p in parcels[a.parcel_id].vertices], outlines[a.id]):
                        problem = "Объект выходит за границу: отступ внутри участка определить нельзя."
                elif rule.parameter == "height_m":
                    actual = a.attributes.get("height_m")
                    if not isinstance(actual, (int, float)) or isinstance(actual, bool) or actual < 0:
                        actual = None
                        problem = "Не заполнена корректная высота объекта height_m."
                else:
                    actual = None
                required = rule.value * UNIT_FACTORS.get(rule.unit, 1) if rule.value is not None else None
                decision = compare(actual, rule.operator, required)
                status = "insufficient_data" if problem or state == "unknown" or decision is None else ("complies" if decision else "violation")
                names = [a.name] + ([b.name] if b else ([parcels[a.parcel_id].name] if rule.parameter == "boundary_distance" else []))
                explanation = problem or reason
                if status != "insufficient_data":
                    explanation += " " + ("Требование выполнено." if status == "complies" else "Требование не выполнено.")
                if rule.source.kind == "educational":
                    explanation = "УЧЕБНОЕ правило, не действующая норма. " + explanation
                results.append(record(rule.id, rule.title, status, [a.id] + ([b.id] if b else []), names, round(actual, 4) if actual is not None else None, required, rule.operator, describe_conditions(rule), explanation, rule.source.model_dump(), points=points))
    counts = {s: sum(r["status"] == s for r in results) for s in ("violation", "complies", "insufficient_data")}
    return {"results": results, "counts": counts, "checked_rules": sum(r.enabled and r.status == "confirmed" for r in rules)}


def condition_key(conditions, flip=False):
    rows = []
    for c in conditions:
        target = ({"a": "b", "b": "a"}[c.target]) if flip else c.target
        value = c.value
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            value = float(value)
        rows.append(json.dumps([target, c.field, c.operator, value], ensure_ascii=False, sort_keys=True))
    return tuple(sorted(rows))


def semantics(rule):
    a, b = tuple(sorted(set(rule.types_a))), tuple(sorted(set(rule.types_b)))
    flip = rule.parameter == "distance" and b < a
    if flip:
        a, b = b, a
    unit = "m" if rule.unit in UNIT_FACTORS else rule.unit
    value = rule.value * UNIT_FACTORS.get(rule.unit, 1) if rule.value is not None else None
    base = (a, b, rule.parameter, unit, rule.scope)
    context = (condition_key(rule.conditions, flip), condition_key(rule.exceptions, flip), tuple(sorted(rule.unresolved)))
    return base, context, value, flip


def contexts_disjoint(a, b, flip_a=False, flip_b=False):
    def equalities(rule, flip):
        return {(("b" if c.target == "a" else "a") if flip else c.target, c.field): c.value for c in rule.conditions if c.operator == "=="}
    ca, cb = equalities(a, flip_a), equalities(b, flip_b)
    return any(ca[k] != cb[k] for k in ca.keys() & cb.keys())


def incompatible(op_a, x, op_b, y):
    lower, upper, lower_open, upper_open, excluded = 0.0, inf, False, False, set()
    for op, v in ((op_a, x), (op_b, y)):
        if op in (">", ">=", "=="):
            if v > lower:
                lower, lower_open = v, op == ">"
            elif v == lower:
                lower_open |= op == ">"
        if op in ("<", "<=", "=="):
            if v < upper:
                upper, upper_open = v, op == "<"
            elif v == upper:
                upper_open |= op == "<"
        if op == "!=":
            excluded.add(v)
    return lower > upper or (abs(lower-upper) <= EPS and (lower_open or upper_open or lower in excluded))


def detect_relations(rules):
    relations = []
    for a, b in combinations(rules, 2):
        ba, ca, x, fa = semantics(a)
        bb, cb, y, fb = semantics(b)
        if ba != bb:
            # Пересекающиеся множества типов и разные области действия требуют ручного анализа.
            if ba[2:4] == bb[2:4] and set(ba[0]) & set(bb[0]) and (set(ba[1]) & set(bb[1]) or not ba[1] and not bb[1]):
                if not contexts_disjoint(a, b, fa, fb):
                    relations.append(dict(a=a.id, b=b.id, kind="review", explanation="Возможно пересечение типов объектов или областей применения; нужна ручная проверка."))
            continue
        if ca != cb:
            if not contexts_disjoint(a, b, fa, fb):
                relations.append(dict(a=a.id, b=b.id, kind="review", explanation="Условия или исключения различаются; их пересечение не доказано."))
            continue
        text_only = (a.conditions_text and not a.conditions) or (b.conditions_text and not b.conditions) or (a.exceptions_text and not a.exceptions) or (b.exceptions_text and not b.exceptions)
        if a.unresolved or b.unresolved or text_only or x is None or y is None or a.unit not in UNIT_FACTORS or b.unit not in UNIT_FACTORS:
            kind, explanation = "review", "Недостаточно структурированных данных для вывода о противоречии."
        elif a.source.kind == b.source.kind == "normative" and (a.source.title, a.source.edition) != (b.source.title, b.source.edition):
            kind, explanation = "review", "Разные нормативные документы или редакции: сначала уточните область и приоритет источников."
        elif a.operator == b.operator and abs(x-y) <= EPS:
            kind, explanation = "duplicate", "Совпадают объекты, параметр, единицы, условия, исключения и требование."
        elif incompatible(a.operator, x, b.operator, y):
            kind, explanation = "conflict", "При одинаковых условиях интервалы допустимых значений не пересекаются."
        else:
            kind, explanation = "compatible", "Требования совместимы; разные числовые значения сами по себе не образуют противоречие."
        relations.append(dict(a=a.id, b=b.id, kind=kind, explanation=explanation))
    return relations
