"""Проверка реального локального HTTP-сервера без дополнительных библиотек."""
import json
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parent.parent
opener=build_opener(ProxyHandler({}))


def call(path,data=None,expected=200,origin=None):
    headers={'Content-Type':'application/json'}
    if origin:headers['Origin']=origin
    request=Request('http://127.0.0.1:8000'+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
    try:
        with opener.open(request,timeout=15) as response:
            code,raw=response.status,response.read()
    except HTTPError as exc:code,raw=exc.code,exc.read()
    assert code==expected,(path,code,raw.decode('utf-8'))
    return json.loads(raw)


def main():
    evidence=[]
    assert call('/api/health')['status']=='ok';evidence.append('health')
    plan=call('/api/example');assert call('/api/plan/validate',plan)==plan;evidence.append('JSON round trip over HTTP')
    bad=json.loads(json.dumps(plan));bad['objects'][0]['width']=-1
    assert 'detail' in call('/api/plan/validate',bad,422);evidence.append('invalid size rejected')
    assert 'detail' in call('/api/plan/validate',plan,403,origin='https://outside.invalid');evidence.append('foreign origin rejected')
    measure=call('/api/measure',dict(plan=plan,a=dict(kind='object',id='home'),b=dict(kind='boundary',id='own')))
    assert abs(measure['distance']-7)<1e-6;evidence.append('object to boundary = 7 m')
    base=call('/api/rules');result=call('/api/check',dict(plan=plan,rules=base))
    assert result['counts']==dict(violation=2,complies=15,insufficient_data=2);evidence.append('three check statuses')
    status=call('/api/ai/status');evidence.append('Ollama status read')
    if not status['available']:
        answer=call('/api/ai/analyze',dict(text='Учебный текст',source=dict(kind='educational',title='Синтетический пример')),503)
        assert answer['code']=='model_unavailable';evidence.append('offline model returns honest 503')
    output=dict(status='passed',checks=evidence,example_counts=result['counts'],ollama=status)
    path=ROOT/'docs'/'api-verification.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
