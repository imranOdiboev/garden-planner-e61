"""Воспроизводимое создание СИНТЕТИЧЕСКИХ учебных данных (не нормативы)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def write(path, data):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def source(title="Синтетический учебный текст Е61", clause=""):
    return dict(kind="educational", title=title, edition="учебная версия 1", clause=clause, url="", verified=False)


def condition(field, value, target="a", operator="=="):
    return dict(target=target, field=field, operator=operator, value=value)


def rule(id, title, a, b, value, text, conditions=None, exceptions=None, operator=">=", parameter="distance", scope="any", unit="m"):
    return dict(id=id, title=title, types_a=a, types_b=b, parameter=parameter, operator=operator,
                value=value, unit=unit, scope=scope, conditions=conditions or [], exceptions=exceptions or [],
                conditions_text="", exceptions_text="", unresolved=[], original_fragment=text,
                source=source(clause=id), status="confirmed", enabled=True)


def rectangle(id, name, role, x, y, w, h):
    return dict(id=id, name=name, role=role, vertices=[dict(x=px, y=py) for px, py in [(x,y), (x+w,y), (x+w,y+h), (x,y+h)]])


def obj(id, type, name, x, y, w, h, angle=0, parcel="own", **attrs):
    return dict(id=id, type=type, name=name, parcel_id=parcel, x=x, y=y, width=w, height=h, angle=angle, attributes=attrs)


def prepare():
    rules = [
        rule("demo_house_boundary", "Учебный отступ дома", ["house"], ["boundary"], 3,
             "СИНТЕТИЧЕСКИЙ ПРИМЕР: расстояние от контура дома до границы его участка должно быть не менее 3 м.", parameter="boundary_distance"),
        rule("demo_well_septic", "Учебное расстояние колодец — септик", ["well"], ["septic"], 12,
             "СИНТЕТИЧЕСКИЙ ПРИМЕР: расстояние между колодцем и септиком должно быть не менее 12 м."),
        rule("demo_wood_buildings", "Учебное правило для деревянных построек", ["house"], ["bathhouse"], 6,
             "СИНТЕТИЧЕСКИЙ ПРИМЕР: если дом и баня деревянные, расстояние между их контурами должно быть не менее 6 м.",
             [condition("material", "wood"), condition("material", "wood", "b")]),
        rule("demo_tree_boundary", "Учебный отступ высокого дерева", ["tree"], ["boundary"], 2,
             "СИНТЕТИЧЕСКИЙ ПРИМЕР: если высота дерева не менее 3 м, отступ его условного контура от границы должен быть не менее 2 м.",
             [condition("height_m", 3, operator=">=")], parameter="boundary_distance"),
        rule("demo_cesspit_well", "Учебное расстояние от негерметичной ямы", ["cesspit"], ["well"], 18,
             "СИНТЕТИЧЕСКИЙ ПРИМЕР: если выгребная яма негерметична, расстояние до колодца должно быть не менее 18 м.", [condition("watertight", False)]),
        rule("demo_greenhouse_boundary", "Учебный отступ теплицы", ["greenhouse"], ["boundary"], 1,
             "СИНТЕТИЧЕСКИЙ ПРИМЕР: расстояние от теплицы до границы должно быть не менее 1 м.", parameter="boundary_distance")]
    write("data/rules.json", dict(schema_version=1, rules=rules))
    write("data/demo_rules.json", dict(schema_version=1, rules=rules))
    plan = dict(schema_version=1, name="Учебный сад • 30 × 40 м", parcels=[
        rectangle("own", "Мой участок", "own", 0, 0, 30, 40),
        rectangle("left", "Соседний участок слева", "neighbor", -20, 0, 20, 40),
        rectangle("right", "Соседний участок справа", "neighbor", 30, 0, 20, 40)], objects=[
            obj("home", "house", "Дом", 12, 12, 10, 8, material="wood", height_m=6),
            obj("garage", "garage", "Гараж", 23, 6, 6, 5, material="stone", height_m=3),
            obj("bath", "bathhouse", "Баня", 5, 27, 5, 4, material=None, height_m=3),
            obj("shed", "outbuilding", "Сарай", 3, 12, 3, 4, material="wood"),
            obj("septic", "septic", "Септик", 23, 32, 3, 2, watertight=True),
            obj("well", "well", "Колодец", 10, 34, 1.4, 1.4),
            obj("bed", "bed", "Грядка", 14, 24, 6, 1.8, angle=-15),
            obj("greenhouse", "greenhouse", "Теплица", 24, 23, 5, 3),
            obj("shrub", "shrub", "Смородина", 3, 5, 1.6, 1.6, height_m=1.5),
            obj("tree", "tree", "Яблоня", 3, 35, 4, 4, height_m=5.2, tree_class="tall"),
            obj("neighbor_home", "house", "Дом соседа", 39, 18, 10, 8, angle=10, parcel="right", material="stone"),
            obj("neighbor_pit", "cesspit", "Яма соседа", -12, 32, 2, 2, parcel="left", watertight=None)
        ], utilities=[dict(id="line_"+kind, name=name, type=kind, parcel_id="own", points=[dict(x=x,y=y) for x,y in pts])
                       for kind,name,pts in [
                           ("electricity", "Электричество", [(12,-4),(12,2),(12,8)]),
                           ("gas", "Газ", [(32,2),(18,2),(18,10)]),
                           ("sewer", "Канализация", [(17,14),(23,14),(23,32)]),
                           ("water", "Водоснабжение", [(10,34),(10,28),(8,28),(8,16)])]],
        settings=dict(grid_step=1, snap=True, show_neighbors=True, show_labels=True))
    write("data/example_plan.json", plan)
    cases = []
    def case(id, text, expected, relations=None, irrelevant=None):
        for r in expected:
            r["enabled"], r["status"] = False, "draft"
        cases.append(dict(id=id, synthetic=True, text=text, source=source(clause=id),
                          expected_rules=expected, expected_relations=relations or [], irrelevant_fragments=irrelevant or []))
    t = "Учебный текст. Расстояние между домом и гаражом должно быть не менее 4 м. Цвет забора выбирает владелец."
    case("T01", t, [rule("t01_r1", "Дом и гараж", ["house"], ["garage"], 4, "Расстояние между домом и гаражом должно быть не менее 4 м.")], irrelevant=["Цвет забора выбирает владелец."])
    t = "Если дом деревянный, расстояние до бани должно быть не менее 6 м. Это требование не применяется, если баня каменная."
    case("T02", t, [rule("t02_r1", "Деревянный дом", ["house"], ["bathhouse"], 6, t, [condition("material", "wood")], [condition("material", "stone", "b")])])
    t1, t2 = "Расстояние между колодцем и септиком должно быть не менее 10 м.", "Расстояние от септика до колодца должно составлять минимум 1000 см."
    case("T03", t1+" "+t2, [rule("t03_r1", "Колодец", ["well"], ["septic"], 10, t1), rule("t03_r2", "Септик", ["septic"], ["well"], 1000, t2, unit="cm")], [dict(a="t03_r1", b="t03_r2", kind="duplicate")])
    t1, t2 = "Расстояние между домом и баней должно быть не менее 8 м.", "Расстояние между домом и баней должно быть не более 5 м."
    case("T04", t1+" "+t2, [rule("t04_r1", "Минимум", ["house"], ["bathhouse"], 8, t1), rule("t04_r2", "Максимум", ["house"], ["bathhouse"], 5, t2, operator="<=")], [dict(a="t04_r1", b="t04_r2", kind="conflict")])
    t1, t2 = "Если дом деревянный, расстояние до гаража должно быть не менее 6 м.", "Если дом каменный, расстояние до гаража должно быть не менее 3 м."
    case("T05", t1+" "+t2, [rule("t05_r1", "Дерево", ["house"], ["garage"], 6, t1, [condition("material", "wood")]), rule("t05_r2", "Камень", ["house"], ["garage"], 3, t2, [condition("material", "stone")])])
    t1, t2 = "Расстояние между теплицей и домом должно быть не менее 2 м.", "Расстояние между теплицей и домом должно быть не менее 4 м."
    case("T06", t1+" "+t2, [rule("t06_r1", "Два", ["greenhouse"], ["house"], 2, t1), rule("t06_r2", "Четыре", ["greenhouse"], ["house"], 4, t2)], [dict(a="t06_r1", b="t06_r2", kind="compatible")])
    t = "Если дерево выше 4 м, расстояние от его контура до границы участка должно быть не менее 2 м."
    case("T07", t, [rule("t07_r1", "Дерево", ["tree"], ["boundary"], 2, t, [condition("height_m", 4, operator=">")], parameter="boundary_distance")])
    t = "Осенью листья желтеют. Владельцы любят отдыхать в саду. В тексте нет требований к размещению."
    case("T08", t, [], irrelevant=["Осенью листья желтеют.", "Владельцы любят отдыхать в саду."])
    t = "Если выгребная яма негерметична, расстояние до колодца должно быть не менее 15 м."
    case("T09", t, [rule("t09_r1", "Яма", ["cesspit"], ["well"], 15, t, [condition("watertight", False)])])
    t = "Запрещается размещать гараж ближе 2 м к границе участка."
    case("T10", t, [rule("t10_r1", "Запрет", ["garage"], ["boundary"], 2, t, parameter="boundary_distance")])
    write("evaluation/dataset.json", dict(schema_version=1, synthetic=True, description="10 синтетических текстов. Числа вымышлены для проверки метода; это НЕ строительные нормы.", cases=cases))
    for c in cases:
        target = ROOT / "evaluation" / "texts" / (c["id"]+".txt")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("СИНТЕТИЧЕСКИЙ УЧЕБНЫЙ ТЕКСТ. НЕ НОРМАТИВНЫЙ ДОКУМЕНТ.\n\n"+c["text"]+"\n", encoding="utf-8")


if __name__ == "__main__":
    prepare()
    print("Synthetic data prepared. Existing rule base was reset to the educational examples.")
