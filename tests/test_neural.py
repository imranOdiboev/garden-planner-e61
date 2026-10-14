import json
import unittest
from unittest.mock import patch
from app.models import AnalyzeRequest, Source, Fragments, Entities, Candidates
from app.neural import OllamaClient, ModelUnavailable, InvalidModelResponse, analyze_text
from test_core import demo_rules


def request(order='filter_first'):
    return AnalyzeRequest(text=demo_rules()[1].original_fragment,source=Source(kind='educational',title='Синтетический пример'),order=order)


class FixtureClient:
    """Тестовая заглушка транспорта; не используется приложением и экспериментами."""
    def __init__(self):self.calls=[]
    def status(self,model):return dict(available=True,selected=dict(digest='TEST_FIXTURE'),ollama_version='TEST_FIXTURE')
    def chat(self,schema,task,content,options,model):
        self.calls.append(schema)
        text=demo_rules()[1].original_fragment
        if schema is Fragments:data=dict(fragments=[dict(text=text,relevant=True,reason='Требование')])
        elif schema is Entities:data=dict(entities=[dict(text='колодцем',kind='object',normalized='well')])
        else:data=dict(rules=[demo_rules()[1].model_dump()])
        result=schema.model_validate(data)
        return result,dict(seconds=0,response=result.model_dump(),prompt_eval_count=None,eval_count=None)


class NeuralTests(unittest.TestCase):
    def test_real_transport_payload_contains_json_schema_and_options(self):
        client=OllamaClient();payload={}
        def response(path,data):
            payload.update(data)
            return dict(done=True,message=dict(content='{"entities":[]}'))
        with patch.object(client,'_request',side_effect=response):
            result,_=client.chat(Entities,'task',{},dict(seed=42,temperature=0), 'test-model')
        self.assertFalse(payload['stream']);self.assertIsInstance(payload['format'],dict);self.assertEqual(payload['options']['seed'],42);self.assertEqual(result.entities,[])

    def test_malformed_or_hallucinated_structure_is_rejected(self):
        for raw in ['not json','{"entities":"wrong"}','{"entities":[],"unexpected":1}','{"entities":[{"text":"x","kind":"invented","normalized":"x"}]}']:
            client=OllamaClient()
            with patch.object(client,'_request',return_value=dict(done=True,message=dict(content=raw))):
                with self.assertRaises(InvalidModelResponse):client.chat(Entities,'task',{}, {},'test')

    def test_invalid_numeric_values_boolean_condition_are_rejected(self):
        data=demo_rules()[1].model_dump();data['value']='twelve'
        client=OllamaClient()
        with patch.object(client,'_request',return_value=dict(done=True,message=dict(content=json.dumps(dict(rules=[data]))))):
            with self.assertRaises(InvalidModelResponse):client.chat(Candidates,'task',{}, {},'test')

    def test_truncated_response_is_rejected(self):
        client=OllamaClient()
        with patch.object(client,'_request',return_value=dict(done=True,done_reason='length',message=dict(content='{"entities":[]}'))):
            with self.assertRaises(InvalidModelResponse):client.chat(Entities,'task',{}, {},'test')

    def test_pipeline_orders_are_actually_different(self):
        first,second=FixtureClient(),FixtureClient()
        analyze_text(request(),first);analyze_text(request('entities_first'),second)
        self.assertEqual(first.calls,[Fragments,Entities,Candidates]);self.assertEqual(second.calls,[Entities,Fragments,Candidates])

    def test_model_cannot_activate_candidate(self):
        result=analyze_text(request(),FixtureClient());candidate=result['candidates'][0]
        self.assertFalse(candidate['enabled']);self.assertEqual(candidate['status'],'draft');self.assertFalse(candidate['source']['verified'])

    def test_fabricated_quote_is_rejected(self):
        fake=FixtureClient();original=fake.chat
        def chat(schema,*args):
            data,trace=original(schema,*args)
            if schema is Candidates:data.rules[0].original_fragment='Этой цитаты нет в тексте.'
            return data,trace
        fake.chat=chat
        with self.assertRaises(InvalidModelResponse):analyze_text(request(),fake)

    def test_unavailable_model_is_not_simulated(self):
        fake=FixtureClient();fake.status=lambda model:dict(available=False,message='Offline')
        with self.assertRaises(ModelUnavailable):analyze_text(request(),fake)
        self.assertEqual(fake.calls,[])

    def test_ollama_url_is_local_only(self):
        for url in ['https://127.0.0.1:11434','http://example.org','http://127.0.0.1:11434/path','http://user@localhost:11434']:
            with self.assertRaises(ValueError):OllamaClient(url)


if __name__=='__main__':unittest.main()
