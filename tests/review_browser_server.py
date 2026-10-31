"""One temporary report writer and local mock model for the review browser test."""
import json
import time
import copy
from unittest.mock import patch
from test_report_review import ReportReviewTests
import test_report_ai_notes as fixture
import report_review
import report_store
import report_vacancy_fixture as vacancy_fixture
import report_analysis_fixture as analysis_fixture

ReportReviewTests.setUpClass()
case=ReportReviewTests('test_review_real_model_text_scope_completion_and_export_exclusion')
case.setUp()
cif='''data_fixture
_cell_length_a 5
_cell_length_b 5
_cell_length_c 5
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Li1 Li 0 0 0
O1 O .5 .5 .5
'''
case.doc['science']['opt'][0]['structure']={'poscar_cif':cif,'contcar_cif':cif}
for structure in case.doc['science']['free_energy'][0]['structures']:structure['cif']=cif
vacancy_fixture.install(case.doc)
analysis_fixture.install(case.doc)
report_store.save_report(case.doc,'browser fixture',{'g_step.svg':'<svg>fallback</svg>','analysis_pdos.svg':analysis_fixture.CHART})
target=next(m for m in report_review.view(case.doc)['modules'] if m['title']=='Model')
def result(value):
    if any(word in value['comment']['text'] for word in ('态密度','吸附能','Bader','功函数')):
        return analysis_fixture.result(value)
    if '只调整外观' in value['comment']['text']:
        card=next(e for e in value['elements'] if e['type']=='calculation')
        return {'reply':'已调整卡片排版。','status':'done','actions':[
            {'kind':'presentation','target':value['comment']['target'],'element_id':card['id'],
             'presentation':{'accent':'teal','layout':'compact'}},
            {'kind':'card','target':value['comment']['target'],'title':'计算说明','text':'使用已选定的参考能量，结果及输入能量保持一致。','presentation':{'accent':'teal'}},
            {'kind':'layout','target':value['comment']['target'],'columns':2}]}
    if '氧空位形成能' in value['comment']['text']:
        action=vacancy_fixture.action(value['facts'],value['comment']['target'])
        if '对比一下三个' in value['comment']['text']:action['inputs']['oxygen']='user:-8.3'
        return {'reply':'已计算','status':'done','actions':[action]}
    if '只对比四个结构' in value['comment']['text']:
        return {'reply':'已经复用原台阶图、结构窗口和表格，按要求显示所选四项。','status':'done',
                'actions':[{'kind':'structures','target':value['comment']['target'],'tasks':['f4','f2','f1','f0']}]}
    return {'reply':'批注回复专用内容。<script>window.REVIEW_XSS=1</script> ![leak](https://example.invalid/leak)',
            'status':'done','actions':[{'kind':'text','target':target['key'],'text':'浏览器核对后的报告解释，原有结构交互继续保留。'}]}
fixture.REVIEW_RESULT=result
def build(pid, *, progress):
    progress(1,1,'整理已有项目数据')
    return {'report':copy.deepcopy(case.doc),'markdown':'browser generated report','charts':{'g_step.svg':'<svg>fallback</svg>','analysis_pdos.svg':analysis_fixture.CHART}}
with patch('report_builder.build_report',side_effect=build):
    print(json.dumps({'base':case.client.base,'connection':case.connection['id']}),flush=True)
    try:
        while True:time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        case.doCleanups();ReportReviewTests.tearDownClass()
