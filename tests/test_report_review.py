"""Report comments reuse the existing isolated HTTP/model fixture and regressions."""
import copy
import unittest
from unittest.mock import patch

import test_report_ai_notes as fixture
import report_review as review
import report_store as store
from report_builder import free_energy_markdown


class ReportReviewTests(fixture.ReportAINotesTests):
    def setUp(self):
        super().setUp()
        if not self._testMethodName.startswith('test_review_'):return
        self.doc['science']['opt'].append({'task_id':'t2','task_name':'Second','final_energy_ev':-8.0,'converged':True})
        path=self.doc['science']['free_energy'][0]
        path.update(structure_count=5,chart='charts/g_step.svg')
        path['structures']=[{'opt_task_id':f'f{i}','structure_label':str(i),'dft_energy_ev':-10+i,
                             'correction_ev':.5,'free_energy_ev':-9.5+i,'converged':True,'corrected':True,
                             'cif':'data_structure\n_cell_length_a 5\n_cell_length_b 5\n_cell_length_c 5\n'} for i in range(5)]
        self.doc['markdown_sections'][0]['markdown']='### 结构优化\n\n#### Model\n\n原有模型分析\n\n@[structure-3d:t]\n\n#### Second\n\n其他模型\n\n### 自由能路径\n\n'+free_energy_markdown(path)
        store.save_report(self.doc,'original markdown',{'g_step.svg':'<svg>original figure</svg>'})
        self.original=copy.deepcopy(self.doc)
        fixture.REVIEW_RESULT={}

    def state(self):
        result=self.client.get('/api/reports/project/rpt_p/review')
        self.assertEqual(result.status_code,200,result.text)
        return result.json()['data']

    def comment(self,title='Model',text='私有批注：补充解释，保留交互图'):
        state=self.state();module=next(m for m in state['modules'] if m['title']==title)
        result=self.client.post('/api/reports/project/rpt_p/review',json={'operation':'add','revision':state['revision'],'target':module['key'],'text':text})
        self.assertEqual(result.status_code,200,result.text)
        return result.json()['data'],module

    def process_comment(self,state,**overrides):
        return self.client.post('/api/reports/project/rpt_p/review/process',json={'revision':state['revision'],'comment_id':state['comments'][-1]['id'],'connection_id':self.connection['id'],**overrides})

    def plan(self,actions,status='done',reply='私有AI回复：已经按批注处理'):
        fixture.REVIEW_RESULT={'reply':reply,'status':status,'actions':actions}

    def test_review_persists_replies_status_and_existing_hide_edits(self):
        state,module=self.comment();comment=state['comments'][0]
        changed=self.client.put('/api/reports/project/rpt_p/edits',json={'hidden_elements':['figure:science:0'],'hidden_sections':[]})
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(self.state()['comments'][0]['text'],comment['text'])
        stale=self.client.post('/api/reports/project/rpt_p/review',json={'operation':'status','revision':state['revision'],'comment_id':comment['id'],'status':'done'})
        self.assertEqual(stale.status_code,409)
        current=self.state()
        result=self.client.post('/api/reports/project/rpt_p/review',json={'operation':'reply','revision':current['revision'],'comment_id':comment['id'],'text':'补充说明，无需重输批注'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.state()['comments'][0]['replies'][0]['text'],'补充说明，无需重输批注')
        self.assertEqual(store.read_edits('rpt_p')['hidden_elements'],['figure:science:0'])

    def test_review_real_model_text_scope_completion_and_export_exclusion(self):
        state,module=self.comment()
        fid=next(k for k,v in review.facts(self.doc).items() if v['field']=='final_energy_ev' and v['value']==-10)
        self.plan([{'kind':'text','target':module['key'],'text':f'补充的解释：已有能量为 [[{fid}]]，应结合计算条件理解。'}])
        result=self.process_comment(state)
        self.assertEqual(result.status_code,200,result.text)
        changed=result.json()['data'];self.assertEqual(changed['comments'][0]['status'],'done')
        self.assertEqual(changed['comments'][0]['replies'][-1]['author'],'AI')
        count=len(fixture.REQUESTS)
        self.assertEqual(self.process_comment(changed).status_code,200)
        self.assertEqual(len(fixture.REQUESTS),count)
        detail=self.client.get('/api/reports/project/rpt_p').json()['data']
        self.assertIn('补充的解释',detail['markdown_sections'][0]['markdown'])
        self.assertIn('-10.0 eV',detail['markdown_sections'][0]['markdown'])
        self.assertIn('@[structure-3d:t]',detail['markdown_sections'][0]['markdown'])
        self.assertEqual(store.load_report('rpt_p')[0],self.original)
        for endpoint in ('export.html','export.html?print=1','markdown'):
            exported=self.client.get('/api/reports/project/rpt_p/'+endpoint)
            self.assertEqual(exported.status_code,200,exported.text[:500])
            self.assertIn('补充的解释',exported.text)
            self.assertNotIn('私有批注',exported.text);self.assertNotIn('私有AI回复',exported.text)
        self.assertEqual(self.client.get('/api/reports/project/rpt_p/review',headers={'x-test-user':'bob'}).status_code,403)

    def test_review_parent_scope_can_reorder_children_without_losing_widgets(self):
        state,module=self.comment('结构优化','把两个模型的展示顺序换一下')
        self.plan([{'kind':'order','target':module['key'],'children':list(reversed(module['children']))}])
        result=self.process_comment(state);self.assertEqual(result.status_code,200,result.text)
        markdown=self.client.get('/api/reports/project/rpt_p').json()['data']['markdown_sections'][0]['markdown']
        self.assertLess(markdown.index('#### Second'),markdown.index('#### Model'))
        self.assertIn('@[structure-3d:t]',markdown)

    def test_review_reorder_keeps_hidden_figure_identity_and_regeneration_mapping(self):
        section=self.doc['markdown_sections'][0]
        section['markdown']=section['markdown'].replace('原有模型分析','原有模型分析\n\n![模型图](charts/model.svg)').replace('其他模型','其他模型\n\n![其他图](charts/second.svg)')
        store.save_report(self.doc,'original',{})
        store.save_edits('rpt_p',[],['figure:science:0'])
        state,module=self.comment('结构优化','调整展示顺序，已隐藏的图仍保持隐藏')
        self.plan([{'kind':'order','target':module['key'],'children':list(reversed(module['children']))}])
        result=self.process_comment(state);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(store.read_edits('rpt_p')['hidden_elements'],['figure:science:1'])
        store.save_report(self.doc,'same report',{})
        self.assertEqual(store.read_edits('rpt_p')['hidden_elements'],['figure:science:1'])
        changed=copy.deepcopy(self.doc);changed['science']['opt'][0]['final_energy_ev']=-20
        store.save_report(changed,'new snapshot',{})
        self.assertEqual(store.read_edits('rpt_p')['hidden_elements'],['figure:science:0'])

    def test_review_four_selected_structures_share_table_chart_and_interactive_data(self):
        state,module=self.comment('Path','按指定顺序只对比四个结构')
        self.plan([{'kind':'structures','target':module['key'],'tasks':['f4','f2','f1','f0']}])
        result=self.process_comment(state);self.assertEqual(result.status_code,200,result.text)
        effective=self.client.get('/api/reports/project/rpt_p').json()['data']
        path=effective['structured']['science']['free_energy'][0]
        self.assertEqual([s['opt_task_id'] for s in path['structures']],['f4','f2','f1','f0'])
        markdown=effective['markdown_sections'][0]['markdown']
        self.assertNotIn('#fe-3d:g:3:f3',markdown)
        self.assertIn('#fe-3d:g:0:f4',markdown)
        self.assertIn('@[free-energy-3d:g]',markdown)
        self.assertEqual(len(store.load_report('rpt_p')[0]['science']['free_energy'][0]['structures']),5)
        chart=self.client.get('/api/reports/project/rpt_p/files/g_step.svg')
        self.assertEqual(chart.status_code,200);self.assertNotIn('original figure',chart.text)
        exported=self.client.get('/api/reports/project/rpt_p/export.html')
        self.assertEqual(exported.status_code,200,exported.text[:500])
        self.assertIn('data-report-widget="free-energy-3d"',exported.text)
        self.assertNotIn('original figure',exported.text)

    def test_review_python_calculation_and_unsupported_request_reply(self):
        state,module=self.comment('科学结果','比较已有两个模型的相对能量')
        values=review.facts(self.doc)
        refs={v['value']:k for k,v in values.items() if v['field']=='final_energy_ev'}
        self.plan([{'kind':'calculate','target':module['key'],'property_id':'relative_energy','inputs':{'reference':refs[-10],'model':refs[-8]}}])
        result=self.process_comment(state);self.assertEqual(result.status_code,200,result.text)
        markdown=self.client.get('/api/reports/project/rpt_p').json()['data']['markdown_sections'][0]['markdown']
        self.assertIn('+2.00000000 eV',markdown)
        state,module=self.comment('Model','这里计算界面能')
        self.plan([],status='blocked',reply='界面能配方尚未注册，需要明确界面面积、参考体系和能量定义；未编造结果。')
        result=self.process_comment(state);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['data']['comments'][-1]['status'],'blocked')
        state,module=self.comment('Model','继续保留说明，但不要编造界面能')
        self.plan([{'kind':'text','target':module['key'],'text':'已有计算记录仍需结合界面参考态解释。'},
                   {'kind':'calculate','target':module['key'],'property_id':'interface_energy','inputs':{}}])
        result=self.process_comment(state);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['data']['comments'][-1]['status'],'blocked')
        self.assertIn('已有计算记录仍需结合界面参考态解释。',review.effective(self.doc)['markdown_sections'][0]['markdown'])

    def test_review_invalid_scope_and_fabricated_numbers_leave_report_unchanged(self):
        state,module=self.comment()
        for action in ({'kind':'text','target':'section:science','text':'越界修改'},
                       {'kind':'text','target':module['key'],'text':'模型编造结果 999.123 eV'},
                       {'kind':'text','target':module['key'],'text':'@[structure-3d:forged]'}):
            self.plan([action]);response=self.process_comment(state)
            self.assertEqual(response.status_code,400,response.text)
            self.assertEqual(self.state()['comments'][0]['status'],'open')
            self.assertEqual(review.effective(self.doc),self.original)

    def test_review_user_reference_energy_needs_no_molecule_task_and_keeps_quote(self):
        quote='气体参考能量就用 -1 Ha，不需要新建任务。'
        state,module=self.comment('Model',quote)
        values=review.facts(self.doc,state['comments'][-1])
        given=next(k for k,v in values.items() if v['field']=='provided_energy_ev')
        total={v['value']:k for k,v in values.items() if v['field']=='final_energy_ev'}
        self.plan([{'kind':'calculate','target':module['key'],'property_id':'adsorption.estimate',
                    'inputs':{'complex':total[-10],'surface':total[-8],'adsorbate':given}}])
        response=self.process_comment(state);self.assertEqual(response.status_code,200,response.text)
        self.assertIn('+25.21138625 eV',review.effective(self.doc)['markdown_sections'][0]['markdown'])
        calculation=store.read_edits('rpt_p')['review']['content'][module['key']]['calculations'][state['comments'][-1]['id']]
        self.assertEqual(calculation['inputs']['adsorbate']['source']['statement'],quote)
        self.assertEqual(calculation['validation_status'],'PRELIMINARY')

    def test_review_generation_conflict_cancellation_and_private_connections(self):
        state,module=self.comment()
        self.plan([{'kind':'text','target':module['key'],'text':'不会写入的修改'}])
        def change(*args,**kwargs):
            store.save_edits('rpt_p',[],['section:actions'])
            return fixture.REVIEW_RESULT,'mock'
        with patch.object(fixture.service,'readonly_json_completion',side_effect=change):
            response=self.process_comment(state)
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(self.state()['comments'][0]['status'],'open')
        state=self.state()
        other=fixture.connections.save_connection('bob',{'name':'other','model':'mock','base_url':f'http://127.0.0.1:{self.provider.server_port}','api_key':fixture.KEY,'max_tokens':2048})
        before=len(fixture.REQUESTS)
        self.assertEqual(self.process_comment(state,connection_id=other['id']).status_code,403)
        self.assertEqual(len(fixture.REQUESTS),before)
        control=fixture.service.TextGenerationControl();control.cancel()
        with self.assertRaises(Exception):review.process('rpt_p',self.user,state['comments'][0]['id'],state['revision'],self.connection['id'],control)
        self.assertEqual(self.state()['comments'][0]['status'],'open')

    def test_review_regeneration_preserves_old_comments_without_applying_stale_edits(self):
        state,module=self.comment();self.plan([{'kind':'text','target':module['key'],'text':'旧版本补充分析'}])
        self.assertEqual(self.process_comment(state).status_code,200)
        changed=copy.deepcopy(self.doc);changed['science']['opt'][0]['final_energy_ev']=-20
        store.save_report(changed,'new data',{})
        self.assertTrue(self.state()['stale'])
        self.assertNotIn('旧版本补充分析',review.effective(changed)['markdown_sections'][0]['markdown'])
        state,module=self.comment(text='针对新版数据的批注')
        self.assertFalse(state['stale']);self.assertEqual(len(state['comments']),2)
        self.assertNotEqual(state['comments'][0]['source'],state['source'])


if __name__=='__main__':unittest.main()
