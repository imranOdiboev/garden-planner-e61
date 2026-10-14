import unittest
from evaluation.evaluate import score, tokens, evaluate_case
from app.models import Rule
from test_core import demo_rules


class EvaluationTests(unittest.TestCase):
    def test_false_positives_and_missing_conditions_reduce_score(self):
        actual=score(['house','well','tree'],['house','garage','tree'])
        self.assertEqual((actual['tp'],actual['fp'],actual['fn']),(2,1,1))
        self.assertAlmostEqual(actual['f1'],2/3)

    def test_empty_gold_is_not_100_percent_accuracy(self):
        self.assertIsNone(score([],[])['f1'])
        self.assertEqual(score(['invented'],[])['f1'],0)

    def test_values_respect_units_and_context(self):
        rule=demo_rules()[1];other=rule.model_copy(deep=True);other.value=1200;other.unit='cm'
        self.assertEqual(tokens([rule],'values'),tokens([other],'values'))
        other.types_a=['tree'];self.assertNotEqual(tokens([rule],'values'),tokens([other],'values'))

    def test_false_conflict_on_different_conditions_is_penalized(self):
        a=demo_rules()[1];b=a.model_copy(deep=True);b.id='b'
        case=dict(expected_rules=[a.model_dump(),b.model_dump()],expected_relations=[],irrelevant_fragments=[])
        result=dict(candidates=[a.model_dump(),b.model_dump()],entities=[],fragments=[],relations=[dict(a=a.id,b=b.id,kind='conflict')])
        self.assertEqual(evaluate_case(case,result)['metrics']['conflict']['fp'],1)


if __name__=='__main__':unittest.main()
