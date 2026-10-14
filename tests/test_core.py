import json
import math
import unittest
from pathlib import Path
from pydantic import ValidationError
from app.geometry import (footprint, polygon_distance, boundary_distance, segment_distance,
                          polygon_contains, point_inside, validate_polygon, point_polygon_distance)
from app.models import Plan, RuleBase, Rule, SiteObject, Condition
from app.rules import check_plan, detect_relations, assert_activatable, applicability

ROOT = Path(__file__).resolve().parent.parent


def example():
    return Plan.model_validate_json((ROOT / "data/example_plan.json").read_text(encoding="utf-8"))


def demo_rules():
    return RuleBase.model_validate_json((ROOT / "data/demo_rules.json").read_text(encoding="utf-8")).rules


def rectangle(x=0, y=0, width=2, height=2, angle=0):
    return footprint(SiteObject(id="test", type="house", name="test", parcel_id="own", x=x, y=y, width=width, height=height, angle=angle))


class GeometryTests(unittest.TestCase):
    def test_distance_is_between_contours(self):
        self.assertAlmostEqual(polygon_distance(rectangle(width=4), rectangle(x=10))[0], 7)

    def test_90_degree_rotation_swaps_dimensions(self):
        self.assertAlmostEqual(polygon_distance(rectangle(width=4, angle=90), rectangle(x=10))[0], 8)

    def test_45_degree_rotation(self):
        self.assertAlmostEqual(polygon_distance(rectangle(angle=45), rectangle(x=5))[0], 4-math.sqrt(2), places=7)

    def test_distance_is_symmetric(self):
        a,b=rectangle(angle=31),rectangle(x=8,y=3,angle=77)
        self.assertAlmostEqual(polygon_distance(a,b)[0],polygon_distance(b,a)[0])

    def test_crossing_without_contained_vertices(self):
        self.assertEqual(polygon_distance(rectangle(width=6),rectangle(height=6))[0],0)

    def test_nested_footprints_intersect(self):
        self.assertEqual(polygon_distance(rectangle(width=8,height=8),rectangle())[0],0)

    def test_touching_distance_zero(self):
        self.assertEqual(polygon_distance(rectangle(),rectangle(x=2))[0],0)

    def test_diagonal_gap(self):
        self.assertAlmostEqual(polygon_distance(rectangle(),rectangle(x=4,y=5))[0],math.sqrt(13))

    def test_parallel_and_collinear_segments(self):
        self.assertEqual(segment_distance((0,0),(4,0),(1,0),(3,0))[0],0)
        self.assertEqual(segment_distance((0,0),(4,0),(1,2),(3,2))[0],2)

    def test_boundary_distance_of_inside_object_is_positive(self):
        self.assertEqual(boundary_distance(rectangle(width=10,height=10),rectangle())[0],4)
        self.assertEqual(point_polygon_distance((0,0),rectangle())[0],0)
        self.assertEqual(point_polygon_distance((0,0),rectangle(),boundary=True)[0],1)

    def test_concave_containment_checks_edges(self):
        outer=[(0,0),(6,0),(6,6),(4,6),(4,2),(2,2),(2,6),(0,6)]
        inner=[(1,3),(5,3),(5,5),(1,5)]
        self.assertTrue(all(point_inside(p,outer) for p in inner))
        self.assertFalse(polygon_contains(outer,inner))

    def test_boundary_contact_is_contained(self):
        self.assertTrue(polygon_contains(rectangle(width=4,height=4),rectangle(x=1)))

    def test_reject_self_intersection_and_duplicate_vertices(self):
        for points in [[(0,0),(4,4),(0,4),(4,0)],[(0,0),(1,0),(1,1),(0,0)],[(0,0),(2,0),(1,0),(1,1)]]:
            with self.assertRaises(ValueError):validate_polygon(points)


class PlanTests(unittest.TestCase):
    def test_save_load_round_trip_including_utilities_settings(self):
        plan=example();plan.parcels[0].vertices[2].x=28;plan.settings.grid_step=.5
        self.assertEqual(Plan.model_validate_json(plan.model_dump_json()).model_dump(),plan.model_dump())

    def test_reject_version_and_unknown_fields(self):
        for modification in [dict(schema_version=2),dict(secret="ignored?")]:
            data=example().model_dump();data.update(modification)
            with self.assertRaises(ValidationError):Plan.model_validate(data)

    def test_reject_missing_parcel_and_duplicate_ids(self):
        data=example().model_dump();data['objects'][0]['parcel_id']='missing'
        with self.assertRaises(ValidationError):Plan.model_validate(data)
        data=example().model_dump();data['objects'][0]['id']=data['objects'][1]['id']
        with self.assertRaises(ValidationError):Plan.model_validate(data)

    def test_reject_nan_negative_size_and_numeric_strings(self):
        for field,value in [('width',-1),('angle',float('nan')),('x','12'),('y',True)]:
            data=example().model_dump();data['objects'][0][field]=value
            with self.assertRaises(ValidationError):Plan.model_validate(data)

    def test_reject_self_crossing_parcel(self):
        data=example().model_dump();data['parcels'][0]['vertices']=[dict(x=x,y=y) for x,y in [(0,0),(4,4),(0,4),(4,0)]]
        with self.assertRaises(ValidationError):Plan.model_validate(data)


class RuleTests(unittest.TestCase):
    def test_example_has_three_result_states(self):
        results=check_plan(example(),demo_rules())
        self.assertEqual(results['counts'],dict(violation=2,complies=15,insufficient_data=2))
        for row in results['results']:
            for field in ['object_names','actual','required','conditions','explanation','source']:
                self.assertIn(field,row)

    def test_missing_attribute_is_not_compliance(self):
        plan=example();rule=demo_rules()[2]
        results=[r for r in check_plan(plan,[rule])['results'] if r['rule_id']==rule.id]
        self.assertTrue(any(r['status']=='insufficient_data' for r in results))

    def test_false_condition_skips_rule(self):
        plan=example();plan.objects[0].attributes['material']='stone';rule=demo_rules()[2]
        results=[r for r in check_plan(plan,[rule])['results'] if r['rule_id']==rule.id]
        self.assertEqual(results,[])

    def test_exception_skips_rule(self):
        plan=example();rule=demo_rules()[2].model_copy(deep=True);rule.conditions=[];rule.exceptions=[Condition(target='b',field='material',operator='==',value='stone')]
        a=plan.objects[0];b=next(o for o in plan.objects if o.type=='bathhouse');b.attributes['material']='stone'
        self.assertEqual(applicability(rule,a,b)[0],'skip')

    def test_unknown_exception_does_not_assume_it_absent(self):
        plan=example();rule=demo_rules()[2].model_copy(deep=True);rule.conditions=[];rule.exceptions=[Condition(target='b',field='material',operator='==',value='stone')]
        self.assertEqual(applicability(rule,plan.objects[0],plan.objects[2])[0],'unknown')

    def test_different_parcel_scope(self):
        plan=example();rule=demo_rules()[2].model_copy(deep=True);rule.conditions=[];rule.scope='different_parcels'
        rows=[r for r in check_plan(plan,[rule])['results'] if r['rule_id']==rule.id]
        self.assertEqual(len(rows),1);self.assertIn('neighbor_home',rows[0]['object_ids'])

    def test_outside_boundary_is_not_reported_as_compliant_setback(self):
        plan=example();plan.objects[0].x=45;rule=demo_rules()[0]
        rows=[r for r in check_plan(plan,[rule])['results'] if r['object_ids']==['home']]
        self.assertEqual({r['status'] for r in rows},{'violation','insufficient_data'})

    def test_disabled_rules_ignored(self):
        rule=demo_rules()[0];rule.enabled=False
        self.assertEqual(check_plan(example(),[rule])['checked_rules'],0)

    def test_unstructured_conditions_block_activation(self):
        rule=demo_rules()[0];rule.conditions_text='при особых обстоятельствах'
        with self.assertRaises(ValueError):assert_activatable(rule)

    def test_normative_source_requires_human_verification(self):
        rule=demo_rules()[0];rule.source.kind='normative'
        with self.assertRaises(ValueError):assert_activatable(rule)

    def test_only_disjoint_intervals_are_conflicts(self):
        a=demo_rules()[1].model_copy(deep=True);b=a.model_copy(deep=True);b.id='other';a.value=4;b.value=6
        self.assertEqual(detect_relations([a,b])[0]['kind'],'compatible')
        a.value=8;b.value=5;b.operator='<='
        self.assertEqual(detect_relations([a,b])[0]['kind'],'conflict')

    def test_units_and_symmetric_objects_in_duplicates(self):
        a=demo_rules()[1].model_copy(deep=True);b=a.model_copy(deep=True);b.id='other';b.types_a,b.types_b=b.types_b,b.types_a;b.value=1200;b.unit='cm'
        self.assertEqual(detect_relations([a,b])[0]['kind'],'duplicate')

    def test_different_conditions_not_conflicts(self):
        a=demo_rules()[1].model_copy(deep=True);b=a.model_copy(deep=True);b.id='other';a.conditions=[Condition(target='a',field='material',operator='==',value='wood')];b.conditions=[Condition(target='a',field='material',operator='==',value='stone')];b.value=2;b.operator='<='
        self.assertEqual(detect_relations([a,b]),[])

    def test_unknown_condition_overlap_requires_review(self):
        a=demo_rules()[1].model_copy(deep=True);b=a.model_copy(deep=True);b.id='other';a.conditions=[Condition(target='a',field='height_m',operator='>=',value=4)];b.value=2;b.operator='<='
        self.assertEqual(detect_relations([a,b])[0]['kind'],'review')

    def test_dataset_relations_match_gold(self):
        dataset=json.loads((ROOT/'evaluation/dataset.json').read_text(encoding='utf-8'))
        for case in dataset['cases']:
            actual=detect_relations([Rule.model_validate(r) for r in case['expected_rules']])
            triples=lambda rows:{(r['a'],r['b'],r['kind']) for r in rows}
            self.assertEqual(triples(actual),triples(case['expected_relations']),case['id'])


if __name__=='__main__':unittest.main()
