"""Synthetic frozen analysis evidence for the existing report comment chain."""

CHART = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 180"><rect width="480" height="180" fill="#f7faff"/><path d="M20 150L100 120L180 30L240 80L320 110L460 150" fill="none" stroke="#2563eb" stroke-width="3"/></svg>'


def install(doc):
    doc['science']['opt'] += [
        {'task_id':'ads_complex','task_name':'Adsorbed','final_energy_ev':-103.5,'converged':False},
        {'task_id':'ads_surface','task_name':'Surface','final_energy_ev':-100.0,'converged':True},
        {'task_id':'ads_gas','task_name':'Gas','final_energy_ev':-2.0,'converged':True}]
    item=doc['science']['ele']['tasks'][0]
    item.update(efermi=-.6,pdos_summary={'available':True,'task_id':item['task_id'],'efermi':-.6,'range':[-10.,10.],
        'spin_polarized':True,'elements':['Fe','O'],'default_curves':['Fe d ↑','Fe d ↓'],
        'band_centers':[{'name':'Fe d ↑','value':-1.25},{'name':'Fe d ↓','value':.75}],
        'chart':'charts/analysis_pdos.svg','source':'synthetic saved PDOS'},
        work_function_summary={'work_function':5.2,'vacuum_level':4.6,'efermi':-.6,'axis':'c'},
        bader_summary={'total_charge':3.8,'net_charge':-.2})
    doc['markdown_sections'][0]['markdown']+='''
### 吸附分析

#### Adsorbed

已有吸附构型的计算记录。

### 电子结构

#### PDOS · 态密度（PDOS）

![已有态密度图](charts/analysis_pdos.svg)

@[pdos-chart:e]

#### PDOS · 功函数

已有功函数结果。

#### PDOS · Bader

已有电荷结果。

### NEB 过渡态

#### NEB

已有路径结果。
'''


def result(context):
    """Mock model binds the real server fact catalog; never computes outputs."""
    target=context['comment']['target'];text=context['comment']['text'];facts=context['facts']
    def ref(field, task=None, value=None):
        return next(key for key,f in facts.items() if f['field']==field and
                    (task is None or f['source'].get('task_id')==task) and (value is None or f['value']==value))
    if '态密度' in text:
        center=ref('band_center_ev',value=-1.25);fermi=ref('efermi',task='e')
        lo=ref('pdos_range_min_ev');hi=ref('pdos_range_max_ev')
        return {'reply':'已按已保存数据整理。','status':'done','actions':[{'kind':'card','target':target,
            'title':'态密度分析','text':f'Fe d ↑ 带中心为 [[{center}]]，费米能级为 [[{fermi}]]。积分范围为 [[{lo}]] 至 [[{hi}]]，沿用原图和自旋区分。','presentation':{'accent':'violet'}}]}
    if '吸附能' in text:
        given=next((key for key,f in reversed(list(facts.items())) if f['field']=='provided_energy_ev'),None)
        gas=given or next((key for key,f in facts.items() if f['field']=='final_energy_ev' and f['source'].get('task_id')=='ads_gas'),'missing-gas')
        return {'reply':'计算完成。','status':'done','actions':[{'kind':'calculate','target':target,'property_id':'adsorption.estimate',
            'inputs':{'complex':ref('final_energy_ev','ads_complex'),'surface':ref('final_energy_ev','ads_surface'),
                      'adsorbate':gas}}]}
    field='work_function' if '功函数' in text else 'net_charge' if 'Bader' in text else 'barrier_ev'
    return {'reply':'已整理已有结果。','status':'done','actions':[
        {'kind':'card','target':target,'title':'结果说明','text':f'已保存结果为 [[{ref(field)}]]。'},
        {'kind':'sources','target':target,'facts':[ref(field)]}]}
