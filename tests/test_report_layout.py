"""Manual layout HTTP/storage/export contract, using an isolated data directory."""
import copy
import json
import unittest
from unittest.mock import patch

import test_report_ai_notes as fixture
import report_store as store
from report_layout import Layout, LayoutObject


class ReportLayoutTests(unittest.TestCase):
    setUpClass = classmethod(fixture.ReportAINotesTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.ReportAINotesTests.tearDownClass.__func__)
    setUp = fixture.ReportAINotesTests.setUp

    def state(self, report='rpt_p'):
        return self.client.get(f'/api/reports/project/{report}/layout').json()['data']

    def obj(self, kind='text', **patches):
        value=LayoutObject(id=kind,report_id='rpt_p',region='science',kind=kind,x=40,y=50,width=160,height=160,
            text='科研排版 <script>window.LAYOUT_XSS=1</script>\nSecond line',
            style={'arrow_start':kind=='double-arrow'}).model_dump()
        value.update(patches)
        return value

    def put(self, objects, revision=0, report='rpt_p'):
        return self.client.put(f'/api/reports/project/{report}/layout',json={'version':1,'revision':revision,'objects':objects})

    def test_empty_old_report_and_permissions(self):
        self.assertEqual(self.state(),Layout().model_dump())
        self.assertNotIn('data-layout-region=',self.client.get('/api/reports/project/rpt_p/export.html?interactive=0').text.split('<body>')[1])
        for method in ('get','put'):
            kwargs={'headers':{'x-test-user':'bob'}}
            if method=='put':kwargs['json']={'version':1,'revision':0,'objects':[]}
            self.assertEqual(getattr(self.client,method)('/api/reports/project/rpt_p/layout',**kwargs).status_code,403)

    def test_all_shapes_roundtrip_styles_and_export(self):
        kinds=['text','rectangle','rounded','square','circle','ellipse','triangle','diamond','line','arrow','double-arrow']
        objects=[self.obj(kind,z=i) for i,kind in enumerate(kinds)]
        objects[0]['style'].update(fill='#12ab34',fill_opacity=.3,stroke_opacity=.6,dash='dotted',font_weight=700,italic=True,align='center',vertical='end',padding=16)
        result=self.put(objects)
        self.assertEqual(result.status_code,200,result.text)
        data=self.state();self.assertEqual(len(data['objects']),11);self.assertEqual(data['revision'],1)
        self.assertTrue(all(o['created_at'] and o['updated_at'] for o in data['objects']))
        self.assertEqual(data['objects'][0]['style'],objects[0]['style'])
        detail=self.client.get('/api/reports/project/rpt_p').json()['data']
        self.assertEqual(detail['edits']['layout'],data)
        for url in ('export.html?interactive=0','export.html?interactive=0&print=1'):
            html=self.client.get('/api/reports/project/rpt_p/'+url).text
            self.assertEqual(html.count('data-layout-object='),11)
            self.assertIn('&lt;script&gt;window.LAYOUT_XSS=1&lt;/script&gt;',html)
            self.assertNotIn('<script>window.LAYOUT_XSS',html)
            self.assertIn('fill-opacity="0.3"',html);self.assertIn('stroke-opacity="0.6"',html)
            self.assertIn('break-inside:avoid',html);self.assertIn('<foreignObject',html)
            for ui in ('data-handle=', 'report-layout-toolbar', '<textarea'):
                self.assertNotIn(ui,html)
        entry=store.list_reports()[0]
        self.assertIn('data-layout-object=',(store.REPORTS_DIR/entry['html_path']).read_text())
        self.assertEqual(store.load_report('rpt_p')[0],self.doc)
        self.assertEqual(fixture.REQUESTS,[])

    def test_replace_not_append_conflict_and_delete(self):
        self.assertEqual(self.put([self.obj()]).status_code,200)
        changed=self.state()['objects'];changed[0].update(x=240,text='已修改')
        self.assertEqual(self.put(changed,1).status_code,200)
        self.assertEqual(len(self.state()['objects']),1)
        stale=self.put([],1);self.assertEqual(stale.status_code,409)
        self.assertEqual(self.state()['objects'][0]['text'],'已修改')
        self.assertEqual(self.put([],2).status_code,200)
        self.assertEqual(self.state()['objects'],[])
        self.assertNotIn('data-layout-object=',self.client.get('/api/reports/project/rpt_p/export.html').text)

    def test_regeneration_preserves_layout_and_recovers_missing_region(self):
        self.put([self.obj()]);before=self.state()
        updated=copy.deepcopy(self.doc);updated['markdown_sections']=[{'key':'summary','title':'摘要','markdown':'重新生成正文'}]
        store.save_report(updated,'new',{})
        self.assertEqual(self.state(),before)
        self.assertNotIn('data-layout-object=',self.client.get('/api/reports/project/rpt_p/export.html').text)
        invalid=copy.deepcopy(before['objects']);invalid[0]['region']='invented'
        self.assertEqual(self.put(invalid,1).status_code,400)
        moved=before['objects'];moved[0]['region']='summary'
        self.assertEqual(self.put(moved,1).status_code,200)
        self.assertIn('data-layout-region="summary"',self.client.get('/api/reports/project/rpt_p/export.html').text)

    def test_report_isolation_and_ownership(self):
        self.put([self.obj()]);other=copy.deepcopy(self.doc)
        other['metadata'].update(report_id='rpt_q',project_id='q',project_name='Off')
        store.save_report(other,'other',{})
        self.assertEqual(self.state('rpt_q')['objects'],[])
        self.assertEqual(self.put([self.obj()],report='rpt_q').status_code,400)
        self.assertEqual(self.put([self.obj(report_id='rpt_q')],report='rpt_q').status_code,200)
        self.assertEqual(self.state()['objects'][0]['report_id'],'rpt_p')

    def test_input_validation_and_finite_bounds(self):
        bad=[self.obj(x=959),self.obj(kind='square',height=140),self.obj(kind='circle',height=140),
             self.obj(kind='arrow',dx=-100),self.obj(kind='text',rotation=180,x=900),
             {**self.obj(), 'kind':'unknown'},self.obj(text='x'*4001),self.obj(region='missing')]
        style=self.obj();style['style']['fill']='url(https://example.invalid)';bad.append(style)
        style=self.obj();style['style']['stroke']='red" onload="alert(1)';bad.append(style)
        for obj in bad:
            with self.subTest(obj=obj['kind']):
                self.assertIn(self.put([obj]).status_code,(400,422))
        self.assertEqual(self.put([self.obj(),self.obj()]).status_code,422)
        self.assertEqual(self.put([self.obj(report_id='rpt_wrong')]).status_code,400)
        self.assertEqual(self.client.put('/api/reports/project/rpt_p/layout',json={'version':2,'revision':0,'objects':[]}).status_code,422)
        self.assertEqual(self.state()['revision'],0)

    def test_reverse_endpoints_and_rotated_shape(self):
        objects=[self.obj('double-arrow',x=400,y=400,dx=-300,dy=-350),self.obj('diamond',x=350,y=160,rotation=45)]
        self.assertEqual(self.put(objects).status_code,200)
        html=self.client.get('/api/reports/project/rpt_p/export.html?interactive=0').text
        self.assertIn('L-300.0 -350.0',html)
        self.assertIn('rotate(45.0',html)

    def test_hidden_scope_and_notes_review_preserved(self):
        store.save_edits('rpt_p',[],['task:science:Model'])
        store.save_note('rpt_p','t','人工注解','论文文字')
        store.save_review('rpt_p',{'comments':[],'content':{}},store.note_revision(store.read_edits('rpt_p')))
        review_revision=store.note_revision(store.read_edits('rpt_p'))
        self.put([self.obj()])
        self.assertEqual(review_revision,store.note_revision(store.read_edits('rpt_p')))
        self.assertIn('review',store.read_edits('rpt_p'));self.assertIn('人工注解',str(store.read_notes('rpt_p')))
        store.save_edits('rpt_p',[],['section:science'])
        self.assertEqual(len(self.state()['objects']),1)
        html=self.client.get('/api/reports/project/rpt_p/export.html').text
        self.assertNotIn('data-layout-object=',html)
        self.assertNotIn('data-layout-object=',self.client.get('/api/reports/project/rpt_p/export.html?sections=risks').text)

    def test_atomic_failure_does_not_claim_success(self):
        self.put([self.obj()]);before=self.state()
        with patch('report_store.os.replace',side_effect=OSError('disk full')):
            result=self.put([],1)
        self.assertEqual(result.status_code,500)
        self.assertEqual(self.state(),before)

    def test_snapshot_copy_failure_is_explicit_but_layout_saved(self):
        original=store.os.replace
        def replace(src,dst):
            if str(src).endswith('.layout.tmp'):raise OSError('copy failure')
            return original(src,dst)
        with patch('report_store.os.replace',side_effect=replace):
            result=self.put([self.obj()])
        self.assertEqual(result.status_code,200)
        self.assertIn('副本更新失败',result.json()['data']['snapshot_warning'])
        self.assertEqual(self.state()['revision'],1)

    def test_explicit_report_deletion_removes_layout(self):
        self.put([self.obj()]);self.assertTrue(store._edits_path('rpt_p').exists())
        self.assertEqual(self.client.request('DELETE','/api/reports/project/rpt_p').status_code,200)
        self.assertNotIn('layout',store.read_edits('rpt_p'))


if __name__=='__main__':unittest.main()
