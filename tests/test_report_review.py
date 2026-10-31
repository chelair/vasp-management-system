"""Report comments reuse the existing isolated HTTP/model fixture and regressions."""
import copy
import unittest
from unittest.mock import patch

import test_report_ai_notes as fixture
import report_review as review
import report_store as store
from report_builder import free_energy_markdown
from report_review_elements import export_markdown
import report_vacancy_fixture as vacancy_fixture
import report_analysis_fixture as analysis_fixture


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

    def analysis_report(self):
        analysis_fixture.install(self.doc)
        store.save_report(self.doc,'frozen analysis report',{'analysis_pdos.svg':analysis_fixture.CHART})
        self.original=copy.deepcopy(self.doc)
        fixture.REVIEW_RESULT=analysis_fixture.result

    def test_review_pdos_analysis_receives_frozen_summary_and_citable_metrics(self):
        import json
        self.analysis_report()
        state,module=self.comment('PDOS · 态密度（PDOS）','分析已有态密度和带中心，保留曲线和交互。')
        with patch('report_interactive.pdos_view',return_value=None):
            response=self.process_comment(state)
            self.assertEqual(response.status_code,200,response.text)
            context=json.loads(fixture.REQUESTS[-1]['messages'][1]['content'])
            self.assertEqual(context['analysis_evidence']['ele']['tasks'][0]['pdos_summary']['range'],[-10.,10.])
            center=next(f for f in context['facts'].values() if f['field']=='band_center_ev' and f['value']==-1.25)
            self.assertEqual(center['source']['task_id'],'e')
            self.assertEqual(center['source']['record_path'],['ele','tasks',0,'pdos_summary','band_centers',0,'value'])
            for endpoint in ('markdown','export.html','export.html?print=1'):
                text=self.client.get('/api/reports/project/rpt_p/'+endpoint).text
                self.assertIn('-1.25 eV',text);self.assertIn('-0.6 eV',text)
                self.assertIn('-10.0 eV',text);self.assertIn('10.0 eV',text)
                self.assertIn('态密度分析',text)
            self.assertIn('@[pdos-chart:e]',review.effective(self.doc)['markdown_sections'][0]['markdown'])
        self.assertEqual(store.load_report('rpt_p')[0],self.original)
        self.assertEqual(set(store.read_edits('rpt_p')['review']['content']),{module['key']})

    def test_review_pdos_new_integration_or_using_band_center_as_total_energy_is_rejected(self):
        self.analysis_report()
        state,module=self.comment('PDOS · 态密度（PDOS）','计算新的能窗和轨道积分')
        self.plan([{'kind':'calculate','target':module['key'],'property_id':'dos.band_center','inputs':{}}])
        response=self.process_comment(state)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['data']['comments'][-1]['status'],'blocked')
        self.assertIn('UNSUPPORTED',response.json()['data']['comments'][-1]['replies'][-1]['text'])
        self.assertEqual(review.effective(self.doc),self.original)
        values=review.facts(self.doc);energy=next(k for k,f in values.items() if f['field']=='efermi')
        self.plan([{'kind':'calculate','target':module['key'],'property_id':'adsorption.estimate',
                    'inputs':{'complex':energy,'surface':energy,'adsorbate':energy}}])
        response=self.process_comment(self.state())
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(review.effective(self.doc),self.original)

    def test_review_adsorption_uses_three_energies_despite_missing_structures_or_unconverged(self):
        self.analysis_report();state,module=self.comment('Adsorbed','计算吸附能，基底为Surface，吸附质为Gas。')
        response=self.process_comment(state)
        self.assertEqual(response.status_code,200,response.text)
        card=next(iter(review.effective(self.doc)['review_elements'].values()))
        self.assertEqual(card['value_ev'],-1.5)
        self.assertEqual(card['inputs']['complex']['source']['task_id'],'ads_complex')
        self.assertEqual(card['inputs']['surface']['source']['task_id'],'ads_surface')
        self.assertEqual(card['inputs']['adsorbate']['source']['task_id'],'ads_gas')
        self.assertEqual(response.json()['data']['comments'][-1]['status'],'done')
        self.assertEqual(store.load_report('rpt_p')[0],self.original)

    def test_review_adsorption_user_units_and_short_reply_keep_role_and_provenance(self):
        self.analysis_report()
        state,module=self.comment('Adsorbed','计算吸附能，吸附质参考能量采用 -1 Ha。')
        reply=self.client.post('/api/reports/project/rpt_p/review',json={'operation':'reply','revision':state['revision'],'comment_id':state['comments'][-1]['id'],'text':'改用-0.5'})
        self.assertEqual(reply.status_code,200,reply.text)
        response=self.process_comment(reply.json()['data'])
        self.assertEqual(response.status_code,200,response.text)
        card=next(iter(review.effective(self.doc)['review_elements'].values()))
        self.assertAlmostEqual(card['value_ev'],10.105693122994)
        source=card['inputs']['adsorbate']['source']
        self.assertEqual(source['original_unit'],'Ha');self.assertEqual(source['statement'],'改用-0.5')
        self.assertTrue(source['reference_context'])

    def test_review_adsorption_missing_gas_is_precise_and_reply_continues_same_comment(self):
        self.analysis_report()
        self.doc['science']['opt']=[r for r in self.doc['science']['opt'] if r['task_id']!='ads_gas']
        store.save_report(self.doc,'missing gas',{})
        state,module=self.comment('Adsorbed','计算吸附能')
        response=self.process_comment(state)
        self.assertEqual(response.status_code,200,response.text)
        state=response.json()['data'];cid=state['comments'][-1]['id']
        self.assertEqual(state['comments'][-1]['status'],'blocked')
        self.assertIn('吸附质参考',state['comments'][-1]['replies'][-1]['text'])
        self.assertFalse(review.effective(self.doc).get('review_elements'))
        response=self.client.post('/api/reports/project/rpt_p/review',json={'operation':'reply','revision':state['revision'],'comment_id':cid,'text':'吸附质参考能量采用 -2 eV'})
        response=self.process_comment(response.json()['data'])
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['data']['comments'][-1]['id'],cid)
        self.assertEqual(response.json()['data']['comments'][-1]['status'],'done')
        self.assertEqual(next(iter(review.effective(self.doc)['review_elements'].values()))['value_ev'],-1.5)

    def test_review_adsorption_can_reuse_prior_gas_reference_with_short_update(self):
        self.analysis_report()
        self.comment('Adsorbed','吸附质参考能量采用 -2 eV。')
        state,module=self.comment('Adsorbed','计算吸附能，沿用吸附质参考')
        response=self.client.post('/api/reports/project/rpt_p/review',json={'operation':'reply','revision':state['revision'],'comment_id':state['comments'][-1]['id'],'text':'沿用-1.5'})
        response=self.process_comment(response.json()['data'])
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(next(iter(review.effective(self.doc)['review_elements'].values()))['value_ev'],-2.0)

    def test_review_neb_work_function_bader_read_frozen_facts_with_correct_units(self):
        self.analysis_report()
        for title,text,expected in [('NEB','解释已有NEB能垒','0.5 eV'),('PDOS · 功函数','解释已有功函数','5.2 eV'),('PDOS · Bader','解释Bader电荷','-0.2 e')]:
            state,module=self.comment(title,text)
            response=self.process_comment(state)
            self.assertEqual(response.status_code,200,response.text)
            markdown=self.client.get('/api/reports/project/rpt_p/markdown').text
            self.assertIn(expected,markdown);self.assertNotIn('-0.2 eV',markdown)
        self.assertEqual(store.load_report('rpt_p')[0],self.original)

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
        self.assertIn('补充的解释',detail['markdown'])
        self.assertIn('-10.0 eV',detail['markdown'])
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
        markdown=self.client.get('/api/reports/project/rpt_p').json()['data']['markdown']
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
        self.assertIn('+2.00000000 eV',self.client.get('/api/reports/project/rpt_p/markdown').text)
        state,module=self.comment('Model','这里计算界面能')
        self.plan([],status='blocked',reply='界面能配方尚未注册，需要明确界面面积、参考体系和能量定义；未编造结果。')
        result=self.process_comment(state);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['data']['comments'][-1]['status'],'blocked')
        state,module=self.comment('Model','继续保留说明，但不要编造界面能')
        self.plan([{'kind':'text','target':module['key'],'text':'已有计算记录仍需结合界面参考态解释。'},
                   {'kind':'calculate','target':module['key'],'property_id':'interface_energy','inputs':{}}])
        result=self.process_comment(state);self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['data']['comments'][-1]['status'],'blocked')
        self.assertIn('已有计算记录仍需结合界面参考态解释。',export_markdown(review.effective(self.doc)))

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
        self.assertIn('+25.21138625 eV',export_markdown(review.effective(self.doc)))
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
        self.assertNotIn('旧版本补充分析',export_markdown(review.effective(changed)))
        state,module=self.comment(text='针对新版数据的批注')
        self.assertFalse(state['stale']);self.assertEqual(len(state['comments']),2)
        self.assertNotEqual(state['comments'][0]['source'],state['source'])

    def vacancy_comment(self, text='计算氧空位形成能，氧气分子能量采用 −8.3 eV。'):
        vacancy_fixture.install(self.doc)
        store.save_report(self.doc,'original frozen report',{})
        self.original=copy.deepcopy(self.doc)
        state,module=self.comment('结构优化',text)
        action=vacancy_fixture.action(review.facts(self.doc,state['comments'][-1]),module['key'])
        return state,module,action

    def test_review_oxygen_card_calls_only_edit_prompt_and_exports_same_frozen_results(self):
        state,module,action=self.vacancy_comment()
        self.plan([action],reply='模型不提供计算数值')
        with patch.object(fixture.ai,'generate_text',side_effect=AssertionError('不应调用科研审查')):
            result=self.process_comment(state)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(len(fixture.REQUESTS),1)
        request=fixture.REQUESTS[-1]
        self.assertEqual(request['messages'][0]['content'],review.PROMPT)
        self.assertNotEqual(request['messages'][0]['content'],fixture.ai.PROMPT)
        import json
        context=json.loads(request['messages'][1]['content'])
        self.assertEqual(len(context['structure_catalog']['single_oxygen_pairs']),3)
        self.assertNotIn('expected_results',context)
        data=self.client.get('/api/reports/project/rpt_p').json()['data']
        elements=data['structured']['review_elements'];self.assertEqual(len(elements),1)
        card=next(iter(elements.values()))
        self.assertEqual(card['type'],'calculation');self.assertEqual(card['target'],module['key'])
        self.assertEqual(card['reference']['value'],-8.3);self.assertEqual(card['mu_O_ev'],-4.15)
        self.assertEqual(card['validation_status'],'PRELIMINARY')
        self.assertEqual([r['value_ev'] for r in card['results']],[r[3] for r in vacancy_fixture.PAIRS])
        self.assertIn('存在负形成能',' '.join(card['warnings']))
        self.assertEqual(card['reference']['source']['statement'],state['comments'][-1]['text'])
        for row in card['results']:
            self.assertEqual(row['compositions']['pristine']['O']-row['compositions']['defect']['O'],1)
            self.assertEqual(row['inputs']['defect']['source']['report_id'],'rpt_p')
        for endpoint in ('markdown','export.html','export.html?print=1'):
            text=self.client.get('/api/reports/project/rpt_p/'+endpoint).text
            for _,_,_,expected in vacancy_fixture.PAIRS:self.assertIn(f'{expected:.8f}',text)
            self.assertIn('E_defect' if endpoint=='markdown' else 'E<sub>defect</sub>',text)
            self.assertIn('-8.3 eV',text);self.assertIn('数据来源',text)
            self.assertNotIn('电荷态、位点对应、晶胞与计算条件仍需核实',text)
            self.assertNotIn('存在负形成能，请核对',text)
            self.assertNotIn(state['comments'][-1]['text'],text)
            self.assertNotIn('模型不提供计算数值',text)
        self.assertIn('data-review-element',next(iter(data['review_elements_html'].values())))
        self.assertEqual(store.load_report('rpt_p')[0],self.original)
        again=self.process_comment(result.json()['data']);self.assertEqual(again.status_code,200)
        self.assertEqual(len(fixture.REQUESTS),1)
        # Explicit reopen reuses the same element identity, with a revision record.
        state=self.state()
        reopened=self.client.post('/api/reports/project/rpt_p/review',json={'operation':'status','revision':state['revision'],
            'comment_id':state['comments'][-1]['id'],'status':'open'}).json()['data']
        self.assertEqual(self.process_comment(reopened).status_code,200)
        saved=store.read_edits('rpt_p')['review']
        self.assertEqual(len(saved['content'][module['key']]['elements']),1)
        self.assertEqual(len(saved['history']),2)
        self.assertLess(len(self.state()['comments'][-1]['replies'][-1]['text']),100)

    def test_review_ai_can_style_existing_calculation_add_cards_and_reorder_columns_without_recalculation(self):
        state,module,action=self.vacancy_comment()
        self.plan([action]);self.assertEqual(self.process_comment(state).status_code,200)
        before=copy.deepcopy(review.effective(self.doc)['review_elements'])
        eid=next(iter(before))
        state,module=self.comment('结构优化','改成紫色紧凑结果卡，添加摘要卡并排展示；不要核实提示。')
        self.plan([{'kind':'presentation','target':module['key'],'element_id':eid,'presentation':{'layout':'compact','accent':'violet'}},
                   {'kind':'card','target':module['key'],'title':'参考条件','text':'采用用户指定的氧气参考能量进行比较。','presentation':{'accent':'teal'}},
                   {'kind':'layout','target':module['key'],'columns':2}])
        with patch('report_review_elements.calculate',side_effect=AssertionError('排版不能重新计算')):
            response=self.process_comment(state)
        self.assertEqual(response.status_code,200,response.text)
        shown=review.effective(self.doc);card=shown['review_elements'][eid]
        self.assertEqual(card['results'],before[eid]['results'])
        self.assertEqual(card['warnings'],before[eid]['warnings'])
        group=next(e for e in shown['review_elements'].values() if e['type']=='layout')
        self.assertEqual(group['columns'],2);self.assertEqual(len(group['items']),2)
        exported=self.client.get('/api/reports/project/rpt_p/export.html').text
        self.assertIn('rr-accent-violet',exported);self.assertIn('rr-results-compact',exported)
        self.assertIn('report-review-layout',exported);self.assertIn('参考条件',exported)
        self.assertNotIn('仍需核实',exported)
        state,module=self.comment('结构优化','把摘要放到计算前面，改成一栏')
        order=[e['id'] for e in reversed(group['items'])]
        self.plan([{'kind':'layout','target':module['key'],'columns':1,'elements':order}])
        self.assertEqual(self.process_comment(state).status_code,200)
        markdown=self.client.get('/api/reports/project/rpt_p/markdown').text
        self.assertLess(markdown.index('参考条件'),markdown.index('**氧空位形成能**'))
        self.assertEqual(store.load_report('rpt_p')[0],self.original)

    def test_review_card_layout_rejects_other_module_elements_and_unsafe_styles(self):
        state,module,action=self.vacancy_comment()
        self.plan([action]);self.assertEqual(self.process_comment(state).status_code,200)
        eid=next(iter(review.effective(self.doc)['review_elements']))
        state,other=self.comment('Model','将另一模块的结果改成卡片')
        self.plan([{'kind':'presentation','target':other['key'],'element_id':eid,'presentation':{'accent':'teal'}}])
        self.assertEqual(self.process_comment(state).status_code,400)
        for presentation in ({'accent':'url(https://example.invalid)'},{'layout':'<script>'},{'value_ev':999}):
            state,module=self.comment('结构优化','只改外观')
            self.plan([{'kind':'presentation','target':module['key'],'element_id':eid,'presentation':presentation}])
            response=self.process_comment(state)
            self.assertEqual(response.status_code,400,response.text)
        state,module=self.comment('结构优化','排成两栏')
        self.plan([{'kind':'layout','target':module['key'],'columns':2,'elements':[eid,'foreign-element']}])
        self.assertEqual(self.process_comment(state).status_code,400)

    def test_review_oxygen_rejects_wrong_composition_and_keeps_valid_partial_results(self):
        state,module,action=self.vacancy_comment()
        action['targets'][0]['defect']=action['targets'][0]['pristine']
        self.plan([action]);response=self.process_comment(state)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['data']['comments'][-1]['status'],'blocked')
        self.assertIn('组成差不是恰好移除一个 O',response.json()['data']['comments'][-1]['replies'][-1]['text'])
        shown=review.effective(self.doc)
        self.assertEqual(len(next(iter(shown['review_elements'].values()))['results']),2)
        self.assertEqual(store.load_report('rpt_p')[0],self.original)

    def test_review_missing_structure_and_oxygen_reference_asks_precisely(self):
        state,module,action=self.vacancy_comment()
        # Re-save the source before creating its comment, so this is missing evidence,
        # not a revision conflict.
        self.doc['science']['opt'][-1]['structure']={}
        store.save_report(self.doc,'missing structure',{})
        state,module=self.comment('结构优化','计算氧空位形成能，O₂ 能量采用 -8.3 eV。')
        action=vacancy_fixture.action(review.facts(self.doc,state['comments'][-1]),module['key'])
        action['targets']=action['targets'][-1:]
        self.plan([action]);response=self.process_comment(state)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('缺少报告冻结结构',response.json()['data']['comments'][-1]['replies'][-1]['text'])
        self.assertFalse(review.effective(self.doc).get('review_elements'))
        state,module=self.comment('结构优化','计算氧空位形成能')
        action['inputs']={'oxygen':'absent'};self.plan([action])
        response=self.process_comment(state)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['data']['comments'][-1]['status'],'blocked')

    def test_review_missing_one_energy_keeps_other_oxygen_results(self):
        state,module,action=self.vacancy_comment()
        action['targets'][1]['pristine']='missing-energy'
        self.plan([action]);response=self.process_comment(state)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['data']['comments'][-1]['status'],'blocked')
        card=next(iter(review.effective(self.doc)['review_elements'].values()))
        self.assertEqual([r['value_ev'] for r in card['results']],[4.73032026,3.09671606])

    def test_review_reference_units_mu_and_fabricated_computation_rejected(self):
        from report_review_elements import calculate
        state,module,action=self.vacancy_comment('计算氧空位形成能，每个氧原子的化学势采用 −4.15 eV。')
        values=review.facts(self.doc,state['comments'][-1]);card=calculate(self.doc,values,action)
        self.assertEqual(card['mu_O_ev'],-4.15)
        self.assertEqual([r['value_ev'] for r in card['results']],[r[3] for r in vacancy_fixture.PAIRS])
        self.plan([{**action,'value_ev':999}]);response=self.process_comment(state)
        self.assertEqual(response.status_code,400,response.text)
        self.assertFalse(review.effective(self.doc).get('review_elements'))
        self.doc['science']['opt'].append({'task_id':'o2','task_name':'O₂','final_energy_ev':-8.3,
            'structure':{'contcar_cif':vacancy_fixture.cif(0,2)}})
        values=review.facts(self.doc)
        action['inputs']={'oxygen':next(k for k,f in values.items() if f['value']==-8.3)}
        card=calculate(self.doc,values,action)
        self.assertEqual(card['mu_O_ev'],-4.15)
        self.assertEqual(card['reference']['source']['task_id'],'o2')

    def test_review_latest_oxygen_reply_overrides_old_binding_and_known_charge_is_blocked(self):
        from report_review_elements import calculate
        state,module,action=self.vacancy_comment()
        comment=copy.deepcopy(state['comments'][-1])
        comment['replies'].append({'author':'alice','text':'氧气分子能量改用 −8.5 eV。'})
        values=review.facts(self.doc,comment)
        card=calculate(self.doc,values,action)
        self.assertEqual(card['mu_O_ev'],-4.25)
        self.assertEqual(card['reference']['source']['statement'],'氧气分子能量改用 −8.5 eV。')
        self.assertAlmostEqual(card['results'][0]['value_ev'],4.63032026,places=8)
        self.doc['science']['opt'][-1]['charge_state']=1
        card=calculate(self.doc,values,action)
        self.assertEqual(len(card['results']),2)
        self.assertIn('带电模型',card['gaps'][0])

    def test_review_reuses_prior_user_oxygen_for_short_replies_and_repairs_model_binding(self):
        self.vacancy_comment()
        for reply in (None,'沿用\n','沿用-8.3','−8.3 eV'):
            with self.subTest(reply=reply):
                state,module=self.comment('结构优化','对比一下三个Ovcc的氧空位形成能')
                comment=state['comments'][-1]
                if reply is not None:
                    response=self.client.post('/api/reports/project/rpt_p/review',json={'operation':'reply','revision':state['revision'],'comment_id':comment['id'],'text':reply})
                    self.assertEqual(response.status_code,200,response.text);state=response.json()['data']
                values=review.facts(self.doc,state['comments'][-1],state['comments'])
                action=vacancy_fixture.action(values,module['key'])
                action['inputs']['oxygen']='user:-8.3'
                self.plan([action])
                response=self.process_comment(state)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['data']['comments'][-1]['status'],'done')
                card=next(e for e in review.effective(self.doc)['review_elements'].values() if e['comment_id']==comment['id'])
                self.assertEqual(card['mu_O_ev'],-4.15)
                self.assertEqual([r['value_ev'] for r in card['results']],[r[3] for r in vacancy_fixture.PAIRS])
                import json
                context=json.loads(fixture.REQUESTS[-1]['messages'][1]['content'])
                self.assertEqual(context['oxygen_references'][0]['value_ev'],-8.3)
                self.assertIn(context['oxygen_references'][0]['fact_id'],context['facts'])
                if reply=='沿用-8.3':
                    self.assertEqual(card['reference']['source']['statement'],reply)
                    self.assertTrue(card['reference']['source']['reference_context'])

    def test_review_short_new_value_inherits_user_units_and_overrides_prior_reference(self):
        from report_review_elements import calculate
        state,module,action=self.vacancy_comment('计算氧空位形成能，氧气分子能量采用 -0.3 Ha。')
        for reply in ('改用-0.4','氧气分子能量改用-0.4'):
            comment=copy.deepcopy(state['comments'][-1]);comment['replies'].append({'author':'alice','text':reply})
            values=review.facts(self.doc,comment)
            action['inputs']['oxygen']='user:-0.4'
            card=calculate(self.doc,values,action)
            self.assertAlmostEqual(card['mu_O_ev'],-.4*27.211386245988/2)
            self.assertEqual(card['reference']['source']['original_unit'],'Ha')
            self.assertEqual(card['reference']['source']['statement'],reply)

    def test_review_ai_only_energy_is_not_promoted_by_confirmation(self):
        vacancy_fixture.install(self.doc)
        store.save_report(self.doc,'no user oxygen reference',{})
        state,module=self.comment('结构优化','计算氧空位形成能')
        comment=copy.deepcopy(state['comments'][-1])
        comment['replies']=[{'author':'AI','text':'是否沿用O₂能量 -8.3 eV？'},{'author':'alice','text':'沿用-8.3'}]
        values=review.facts(self.doc,comment)
        self.assertFalse(any(f.get('reference_kind') for f in values.values()))
        from report_review_elements import calculate,MissingCalculation
        with self.assertRaisesRegex(MissingCalculation,'请补充氧气分子能量'):
            calculate(self.doc,values,{'kind':'calculate','target':module['key'],'property_id':'oxygen_vacancy.neutral_single','inputs':{'oxygen':'user:-8.3'},'targets':[]})

    def test_review_ambiguous_prior_user_references_require_one_clear_choice(self):
        state,module,_=self.vacancy_comment('计算氧空位形成能，氧气分子能量候选 -8.3 eV，氧气分子能量候选 -8.5 eV。')
        state,module=self.comment('结构优化','对比三个氧空位形成能')
        values=review.facts(self.doc,state['comments'][-1],state['comments'])
        action=vacancy_fixture.action(values,module['key'])
        from report_review_elements import calculate,MissingCalculation
        with self.assertRaisesRegex(MissingCalculation,'包含不同的氧参考值'):
            calculate(self.doc,values,action)

    def test_review_element_replace_append_delete_and_atomic_rollback(self):
        state,module=self.comment('Model','将已有分析替换为简短解释，并添加来源与公式')
        element=next(e for e in state['elements'] if e['target']==module['key'] and '原有模型分析' in e.get('text',''))
        fid=next(iter(review.facts(self.doc)))
        self.plan([{'kind':'edit','target':module['key'],'element_id':element['id'],'operation':'replace','text':'替换后的简短说明。'},
                   {'kind':'formula','target':module['key'],'property_id':'relative_energy'},
                   {'kind':'sources','target':module['key'],'facts':[fid]}])
        response=self.process_comment(state);self.assertEqual(response.status_code,200,response.text)
        shown=review.effective(self.doc);text=export_markdown(shown)
        self.assertNotIn('原有模型分析',text);self.assertIn('替换后的简短说明。',text)
        self.assertIn('ΔE',text);self.assertIn('数据来源',text)
        state,module=self.comment('Model','删除公式卡片并补充说明')
        formula=next(e for e in state['elements'] if e['type']=='formula')
        self.plan([{'kind':'edit','target':module['key'],'element_id':formula['id'],'operation':'delete'},
                   {'kind':'edit','target':module['key'],'element_id':element['id'],'operation':'append','text':'只补充这一处。'}])
        self.assertEqual(self.process_comment(state).status_code,200)
        text=export_markdown(review.effective(self.doc));self.assertNotIn('ΔE = E_model',text);self.assertIn('只补充这一处。',text)
        state,module=self.comment('Model','失败不能覆盖之前修改')
        before=store.read_edits('rpt_p')
        self.plan([{'kind':'edit','target':module['key'],'element_id':element['id'],'operation':'delete'},
                   {'kind':'text','target':'section:science','text':'越界'}])
        self.assertEqual(self.process_comment(state).status_code,400)
        self.assertEqual(store.read_edits('rpt_p'),before)
        self.assertEqual(store.load_report('rpt_p')[0],self.original)


if __name__=='__main__':unittest.main()
