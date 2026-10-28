"""Shared content read/write using real recipes/renderers and temporary data only."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=tempfile.TemporaryDirectory(prefix='vasp-topic-content-')
os.environ['VASP_WEB_DATA_DIR']=ROOT.name
os.environ['VASP_AI_KEY_FILE']=str(Path(ROOT.name)/'ai.key')
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parent)]
import ai_chat_store as store
import storage
import topic_simple as simple
import topic_reports as topics
import topic_tools as tools


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.user={'user_id':'tester-id','username':'tester','role':'user'}
        self.guard=patch('ssh.run_remote',side_effect=AssertionError('no SSH'))
        self.guard.start();self.addCleanup(self.guard.stop)

    def conversation(self,project):
        return store.create_conversation(self.user['user_id'],'content review',None,None,project['project_id'])

    def adsorption(self):
        project={'project_id':'p','name':'P','owner':'tester','tasks':[
            {'task_id':'surface','model_name':'surface','task_type':'ele','last_energy':-100},
            {'task_id':'gas','model_name':'gas','task_type':'opt','last_energy':-3},
            {'task_id':'complex','model_name':'gas@surface','task_type':'ele','last_energy':-105}]}
        storage.save_db({'projects':[project]})
        conv=self.conversation(project)
        doc=simple.create(self.user,conv,'分析吸附能',{'property_id':'adsorption.simple','model_queries':['surface'],'adsorbate_query':'gas',
            'objective':'比较已有吸附能','notes':'INTERNAL_NOTE_NOT_BODY','assessment':{'conclusion':'已得到初步结果，需结合参考态理解。'}})
        return conv,doc

    def test_adsorption_readback_matches_rendering_and_includes_latest_human_edits(self):
        conv,doc=self.adsorption();frozen=json.loads(json.dumps(doc['data']))
        first=tools.dispatch(self.user,conv,'','get_topic_report',{'topic_id':doc['topic_id']})
        self.assertIn('-2.000000',first['content']['text'])
        self.assertIn('已得到初步结果',first['content']['text'])
        self.assertNotIn('INTERNAL_NOTE_NOT_BODY',first['content']['text'])
        self.assertNotIn('window.',first['content']['text'])
        changed=simple.update_content(self.user,doc['topic_id'],{'expected_revision':1,'objective':'人工修改的分析重点',
            'assessment':{'conclusion':'人工确认后的解释。','recommendation':'结合相同参考态比较。'}})
        latest=tools.dispatch(self.user,conv,'','get_topic_report',{'topic_id':doc['topic_id']})
        self.assertIn('人工确认后的解释',latest['content']['text'])
        self.assertEqual(latest['editable_content']['objective'],'人工修改的分析重点')
        self.assertEqual(changed['data'],frozen)
        original=tools.dispatch(self.user,conv,'','get_topic_report',{'topic_id':doc['topic_id'],'revision':1})
        self.assertEqual(first['content']['sha256'],original['content']['sha256'])
        self.assertNotIn('人工确认后的解释',original['content']['text'])
        other=self.conversation({'project_id':'p'})
        with self.assertRaises(Exception):tools.dispatch(self.user,other,'','get_topic_report',{'topic_id':doc['topic_id']})
        self.assertEqual(tools.dispatch(self.user,other,'','list_topic_reports',{})['items'],[])
        self.assertEqual(tools.dispatch(self.user,conv,'','list_topic_reports',{})['items'][0]['topic_id'],doc['topic_id'])

    def test_saved_response_returns_visible_content_and_pages_stay_on_selected_revision(self):
        conv,doc=self.adsorption()
        result=tools.dispatch(self.user,conv,'','update_topic_report',{'topic_id':doc['topic_id'],'expected_revision':1,
            'assessment':{'conclusion':'需要结合参考态理解。'*150,'recommendation':'先核对输入来源。'*100}})
        self.assertIn('先核对输入来源',simple.render_html(topics.load(self.user,doc['topic_id'])))
        revision=result['revision'];text='';offset=0
        while True:
            page=tools.dispatch(self.user,conv,'','get_topic_report',{'topic_id':doc['topic_id'],'revision':revision,'offset':offset,'limit':1000})
            text+=page['content']['text'];offset=page['content']['next_offset']
            if offset is None:break
            if page['content']['offset']==0:
                simple.update_content(self.user,doc['topic_id'],{'expected_revision':revision,'assessment':{'conclusion':'后来的手工编辑。'}})
        self.assertIn('先核对输入来源',text)
        self.assertNotIn('后来的手工编辑',text)
        self.assertEqual(len(text),page['content']['total_chars'])

    def test_dos_and_registered_energy_recipe_share_the_content_round_trip(self):
        import r3_fixtures
        from r2_science_fixtures import seed_science
        root=Path(ROOT.name);project,rows=r3_fixtures.seed(root)
        seed_science(root,project)
        row=copy.deepcopy(rows[0]);row.update(task_id='t_ele',task_type='ele',remote_dir='R3P/ele/Electronic')
        row['current_output']={'latest_dir':'','dir':'R3P/ele/Electronic'};rows.append(row)
        (root/'checks/check_results_r3.json').write_text(json.dumps(rows));storage.save_db({'projects':[project]})
        import properties
        properties.evaluate({'projects':[project]},self.user,r3_fixtures.request(),persist=True)
        conv=self.conversation(project)
        for pid,queries in [('dos.comparison',['Electronic']),('oxygen_vacancy.neutral_single',['LMR','LIC@LMR'])]:
            doc=simple.create(self.user,conv,'比较已有结果',{'property_id':pid,'model_queries':queries,
                'assessment':{'conclusion':'围绕当前已有证据解释结果。'}})
            frozen=copy.deepcopy(doc['data'])
            read=tools.dispatch(self.user,conv,'','get_topic_report',{'topic_id':doc['topic_id']})
            self.assertIn('围绕当前已有证据',read['content']['text'])
            if pid=='dos.comparison':
                self.assertEqual(read['science']['status'],'VISUAL_ONLY')
                self.assertEqual(read['science']['results'],[])
                self.assertIn('pdos-chart',simple.render_html(doc))
                bid=next(b['block_id'] for b in read['evidence_index'] if b['type']=='ele.pdos')
                raw=tools.dispatch(self.user,conv,'','get_topic_report',{'topic_id':doc['topic_id'],'block_id':bid})
                evidence=json.loads(raw['evidence']['json'])
                block=next(b for b in doc['blocks'] if b['block_id']==bid)
                original=doc['data']['library']['evidence'][block['source_refs'][0]['evidence_id']]['payload']['view']
                self.assertEqual(evidence[0]['data']['view'],original)
            else:
                self.assertEqual(read['science']['property_id'],pid)
                self.assertEqual([r['value'] for r in read['science']['results']],[3,4,1])
            changed=tools.dispatch(self.user,conv,'','update_topic_report',{'topic_id':doc['topic_id'],'expected_revision':doc['revision'],
                'assessment':{'recommendation':'按已有结果继续核对。'}})
            self.assertIn('按已有结果继续核对',changed['content']['text'])
            self.assertEqual(topics.load(self.user,doc['topic_id'])['data'],frozen)


if __name__=='__main__':unittest.main()
