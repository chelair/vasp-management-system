"""Bounded candidate relationships for the R4 adsorption recipe, read-only."""
from adsorption_science import relationship


def find(queries,pools,references,selectors,inspected,project_id):
    targets,choices,gaps=[],[],[]
    def selector(pair):
        p,t=pair;return selectors[(p['project_id'],t['task_id'])]
    def data(pair):
        p,t=pair;return inspected[(p['project_id'],t['task_id'])]['data']
    def candidate(pair):
        p,t=pair;return {'task_id':t['task_id'],'model_name':t.get('model_name'),'project_id':p['project_id'],'selector':selector(pair), **{k:inspected[(p['project_id'],t['task_id'])].get(k,[]) for k in ('status','checks','observations')}}
    for query,pool in zip(queries,pools):
        relations=[];total=0
        for ref in references:
            for complex_pair in pool:
                for surface_pair in pool:
                    if selector(complex_pair)['task_id']==selector(surface_pair)['task_id']:continue
                    checks,site=relationship(data(complex_pair),data(surface_pair),data(ref))
                    if site and all(c['status']=='AVAILABLE' for c in checks):
                        total+=1
                        if len(relations)<24:relations.append({'complex':selector(complex_pair),'surface':selector(surface_pair),'adsorbate':selector(ref),'site':site})
        if total==1:
            targets.append({'label':query,**{r:relations[0][r] for r in ('complex','surface','adsorbate')}})
        else:
            targets.append({'label':query,'complex':{'project_id':project_id,'query':query},'surface':{'project_id':project_id,'query':query},
                            'adsorbate':selector(references[0]) if len(references)==1 else {'project_id':project_id}})
            gaps.append({'check':'adsorption_binding','status':'AMBIGUOUS' if total>1 else 'MISSING',
                         'detail':query+'：'+('多个吸附位置、表面或参考任务可匹配，须明确选择，不能随机绑定。' if total>1 else '需要洁净表面、保持表面输入原子映射的吸附复合体系和一个吸附物参考；当前没有可验证的完整关系。')})
        choices.append({'label':query,'adsorption_relations':relations,'total':total,'truncated':total>24})
        if total==0:
            for role,pairs in (('surface',pool),('complex',pool),('adsorbate',references)):
                choices.append({'label':query+' · '+role,'target_label':query,'role':role,'tasks':[candidate(p) for p in pairs]})
    if not references:gaps.append({'check':'adsorbate_reference','status':'MISSING','detail':'缺少明确的吸附物参考计算；不能用猜测的分子能量、半个分子或氧化学势代替。请确认吸附物名称及已有参考任务，确实缺失才建议补算。'})
    return targets,choices,gaps
