"""python -m evaluation.evaluate --model qwen2.5:3b --repeats 1

Всегда вызывает реальную модель; --prepare-only только подготавливает описание запуска.
"""
import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from app.models import Rule, AnalyzeRequest
from app.neural import OllamaClient, analyze_text, ModelUnavailable, InvalidModelResponse, PROMPT_VERSION
from app.rules import semantics, condition_key

ROOT=Path(__file__).resolve().parent.parent


def score(predicted, expected):
    p,e=Counter(predicted),Counter(expected)
    tp=sum((p&e).values());fp=sum(p.values())-tp;fn=sum(e.values())-tp
    precision=tp/(tp+fp) if tp+fp else None
    recall=tp/(tp+fn) if tp+fn else None
    f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
    return dict(tp=tp,fp=fp,fn=fn,precision=precision,recall=recall,f1=f1)


def aggregate(scores):
    tp=sum(s['tp'] for s in scores);fp=sum(s['fp'] for s in scores);fn=sum(s['fn'] for s in scores)
    return dict(tp=tp,fp=fp,fn=fn,precision=tp/(tp+fp) if tp+fp else None,
                recall=tp/(tp+fn) if tp+fn else None,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None)


def tokens(rules,field):
    result=[]
    for rule in rules:
        base,context,value,flip=semantics(rule)
        if field=='values':
            if value is not None:result.append((base,rule.operator,round(value,6)))
        elif field=='conditions':
            result.extend((base,'condition',c) for c in condition_key(rule.conditions,flip))
            result.extend((base,'exception',c) for c in condition_key(rule.exceptions,flip))
            result.extend((base,'unresolved',c) for c in rule.unresolved)
    return result


def align_rules(predicted, expected):
    """Однозначное сопоставление кандидатов эталонам, с учётом контекста и цитат."""
    matches={};available=list(expected)
    for rule in predicted:
        sem=semantics(rule)
        options=[r for r in available if semantics(r)[0]==sem[0]]
        if not options:continue
        def quality(r):
            other=semantics(r)
            return (int(' '.join(r.original_fragment.split())==' '.join(rule.original_fragment.split())),
                    int(other[1]==sem[1]),int(other[2]==sem[2] and r.operator==rule.operator))
        chosen=max(options,key=quality);matches[rule.id]=chosen.id;available.remove(chosen)
    return matches


def evaluate_case(case, result):
    gold=[Rule.model_validate(r) for r in case['expected_rules']]
    predicted=[Rule.model_validate(r) for r in result['candidates']]
    expected_entities=sorted({t for r in gold for t in r.types_a+r.types_b})
    predicted_entities=sorted({e['normalized'] for e in result['entities'] if e['kind']=='object'})
    scores=dict(entities=score(predicted_entities,expected_entities),
                values=score(tokens(predicted,'values'),tokens(gold,'values')),
                conditions=score(tokens(predicted,'conditions'),tokens(gold,'conditions')))
    mapping=align_rules(predicted,gold)
    for kind in ['conflict','duplicate']:
        p=[tuple(sorted((mapping.get(r['a'],'UNMATCHED:'+r['a']),mapping.get(r['b'],'UNMATCHED:'+r['b']))))
           for r in result['relations'] if r['kind']==kind]
        e=[tuple(sorted((r['a'],r['b']))) for r in case['expected_relations'] if r['kind']==kind]
        scores[kind]=score(p,e)
    expected_irrelevant=set(case['irrelevant_fragments'])
    correctly_removed=sum(any(s in f['text'] and not f['relevant'] for f in result['fragments']) for s in expected_irrelevant)
    return dict(metrics=scores,matched_rules=mapping,expected_rules=len(gold),predicted_rules=len(predicted),
                irrelevant_fragments=dict(expected=len(expected_irrelevant),correctly_removed=correctly_removed),
                manual_review_relations=sum(r['kind']=='review' for r in result['relations']))


def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description='Оценка двух порядков нейросетевого извлечения (реальная Ollama)')
    parser.add_argument('--model',default='qwen2.5:3b');parser.add_argument('--repeats',type=int,default=1)
    parser.add_argument('--seed',type=int,default=42);parser.add_argument('--temperature',type=float,default=0)
    parser.add_argument('--num-ctx',type=int,default=16384);parser.add_argument('--num-predict',type=int,default=4096)
    parser.add_argument('--cases',nargs='*');parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--output',default=str(ROOT/'evaluation/results'))
    args=parser.parse_args()
    if not 1<=args.repeats<=10:parser.error('repeats: от 1 до 10')
    dataset_path=ROOT/'evaluation/dataset.json';dataset=json.loads(dataset_path.read_text(encoding='utf-8'))
    cases=[c for c in dataset['cases'] if not args.cases or c['id'] in args.cases]
    if not cases:parser.error('Не выбраны тексты')
    if args.cases and set(args.cases)-{c['id'] for c in dataset['cases']}:parser.error('Неизвестный ID текста')
    out=Path(args.output);orders=['filter_first','entities_first']
    options=dict(seed=args.seed,temperature=args.temperature,num_ctx=args.num_ctx,num_predict=args.num_predict)
    # Параметры проверяются той же серверной схемой до выполнения любых вызовов.
    AnalyzeRequest(text=cases[0]['text'],source=cases[0]['source'],model=args.model,**options)
    protocol=dict(created_at=datetime.now(timezone.utc).isoformat(),model=args.model,options=options,orders=orders,
                  repeats=args.repeats,cases=[c['id'] for c in cases],prompt_version=PROMPT_VERSION,
                  dataset_sha256=hashlib.sha256(dataset_path.read_bytes()).hexdigest(),python=sys.version,
                  platform=platform.platform(),processor=platform.processor(),synthetic=True)
    if args.prepare_only:
        write(out/'status.json',dict(status='not_run',reason='Подготовлен протокол; модель в этом запуске не вызывалась.',protocol=protocol,metrics=None))
        print('Prepared protocol only. No extraction experiment was executed.');return 0
    client=OllamaClient();status=client.status(args.model)
    if not status['available']:
        write(out/'status.json',dict(status='not_run',reason=status['message'],protocol=protocol,ollama=status,metrics=None))
        print('NOT RUN: Ollama or selected model unavailable. Metrics were not generated.');return 2
    protocol['model_digest']=status['selected']['digest'];protocol['ollama_version']=status['ollama_version']
    runs=[]
    for repeat in range(args.repeats):
        # Чередование порядка уменьшает влияние первого прогрева модели на сравнение времени.
        current_orders=orders if repeat%2==0 else list(reversed(orders))
        for case in cases:
            for order in current_orders:
                print(f"{case['id']} {order} repeat={repeat+1}",flush=True)
                request=AnalyzeRequest(text=case['text'],source=case['source'],model=args.model,order=order,**options)
                record=dict(case_id=case['id'],order=order,repeat=repeat+1,request=request.model_dump())
                try:
                    result=analyze_text(request,client);record.update(status='completed',result=result,evaluation=evaluate_case(case,result))
                except (ModelUnavailable,InvalidModelResponse) as exc:
                    record.update(status='failed',error=str(exc))
                write(out/f"{case['id']}-{order}-{repeat+1}.json",record);runs.append(record)
    summaries={}
    for order in orders:
        successful=[r for r in runs if r['order']==order and r['status']=='completed']
        failed=sum(r['order']==order and r['status']=='failed' for r in runs)
        summaries[order]=dict(completed=len(successful),failed=failed,planned=len(cases)*args.repeats,
                              metrics={k:aggregate([r['evaluation']['metrics'][k] for r in successful]) for k in ['entities','values','conditions','conflict','duplicate']} if successful else None,
                              mean_seconds=sum(r['result']['run']['seconds'] for r in successful)/len(successful) if successful else None)
    write(out/'status.json',dict(status='completed' if all(r['status']=='completed' for r in runs) else 'partial',protocol=protocol,summaries=summaries,
                                note='Метрики только для завершённых запусков. Смотрите покрытие completed/planned; ошибки не считаются успешным извлечением.'))
    lines=['# Фактическое сравнение порядков','',f"Модель `{args.model}`; digest `{protocol['model_digest']}`. Синтетический корпус.",'',
           '| Порядок | Выполнено / запланировано | Ошибки | Время, с | F1 сущностей | F1 значений | F1 условий | F1 противоречий | F1 дублей |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    def number(v):return '—' if v is None else f'{v:.3f}'
    for order,s in summaries.items():
        values=[number(s['metrics'][k]['f1']) if s['metrics'] else '—' for k in ['entities','values','conditions','conflict','duplicate']]
        lines.append(f"| {order} | {s['completed']} / {s['planned']} | {s['failed']} | {number(s['mean_seconds'])} | "+' | '.join(values)+' |')
    lines.extend(['','Метрики рассчитаны только для завершённых запусков. Дефис означает отсутствие оцениваемых примеров. Подробные ответы и ошибки — в JSON.'])
    (out/'comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return 0 if all(r['status']=='completed' for r in runs) else 1


if __name__=='__main__':raise SystemExit(main())
