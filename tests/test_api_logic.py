import unittest
from pathlib import Path
from unittest.mock import patch
from app import main
from app.models import RuleBase, Endpoint, Point, MeasureRequest
from test_core import example, demo_rules, ROOT


class APIWorkflowTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'tests'/'artifacts';folder.mkdir(exist_ok=True)
        self.path=folder/'rules-test.json'
        self.path.write_text(RuleBase(rules=demo_rules()).model_dump_json(),encoding='utf-8')
        self.patcher=patch.object(main,'RULE_PATH',self.path);self.patcher.start()

    def tearDown(self):
        self.patcher.stop();self.path.unlink(missing_ok=True);self.path.with_suffix('.tmp').unlink(missing_ok=True)

    def test_reviewed_candidate_persisted_and_enabled(self):
        rule=demo_rules()[0];rule.id='candidate_garage';rule.types_a=['garage'];rule.status='draft';rule.enabled=False
        response=main.confirm(rule)
        self.assertEqual(response['rule'].status,'confirmed')
        loaded=main.load_rules();saved=next(r for r in loaded.rules if r.id==rule.id)
        self.assertTrue(saved.enabled);self.assertEqual(len(loaded.rules),7)

    def test_conflicting_candidate_returns_409_and_leaves_base_intact(self):
        rule=demo_rules()[1];rule.id='contradiction';rule.operator='<=';rule.value=5
        response=main.confirm(rule)
        self.assertEqual(response.status_code,409);self.assertEqual(len(main.load_rules().rules),6)

    def test_duplicate_candidate_returns_409(self):
        rule=demo_rules()[1];rule.id='duplicate'
        self.assertEqual(main.confirm(rule).status_code,409)

    def test_disabled_duplicate_does_not_block_review(self):
        base=main.load_rules();base.rules[1].enabled=False;main.save_rules(base)
        rule=demo_rules()[1];rule.id='reviewed_replacement'
        self.assertTrue(main.confirm(rule)['rule'].enabled)

    def test_edit_same_id_updates_instead_of_duplicating(self):
        rule=demo_rules()[0];rule.value=4;main.confirm(rule)
        self.assertEqual(len(main.load_rules().rules),6)
        self.assertEqual(next(r for r in main.load_rules().rules if r.id==rule.id).value,4)

    def test_active_import_rejects_draft(self):
        base=main.load_rules();base.rules[0].status='draft'
        with self.assertRaises(ValueError):main.import_rules(base)

    def test_point_and_object_measurements(self):
        plan=example()
        result=main.measure(MeasureRequest(plan=plan,a=Endpoint(kind='point',point=Point(x=0,y=0)),b=Endpoint(kind='point',point=Point(x=3,y=4))))
        self.assertEqual(result['distance'],5)
        result=main.measure(MeasureRequest(plan=plan,a=Endpoint(kind='object',id='home'),b=Endpoint(kind='boundary',id='own')))
        self.assertEqual(result['distance'],7)

    def test_missing_measurement_endpoint_is_clear_error(self):
        with self.assertRaisesRegex(ValueError,'существующий'):
            main.measure(MeasureRequest(plan=example(),a=Endpoint(kind='object',id='missing'),b=Endpoint(kind='boundary',id='own')))


if __name__=='__main__':unittest.main()
