"""Reasoning payload compatibility, no upstream network or persisted user data."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import ai_reasoning as r

class ReasoningTests(unittest.TestCase):
    def connection(self,**kwargs):return {'base_url':'https://api.openai.com/v1','model':'gpt-5.2',**kwargs}
    def test_deepseek_levels_and_payloads(self):
        c=self.connection(base_url='https://api.deepseek.com',model='deepseek-flash')
        self.assertEqual([o['value'] for o in r.capabilities(c)['options']],['default','none','low','high','max'])
        for level in ('low','high','max'):
            self.assertEqual(r.parameters({**c,'reasoning_effort':level}),{'reasoning_effort':level,'thinking':{'type':'enabled'}})
        self.assertEqual(r.parameters({**c,'reasoning_effort':'none'}),{'reasoning_effort':'none','thinking':{'type':'disabled'}})
        with self.assertRaises(ValueError):r.parameters({**c,'reasoning_effort':'medium'})
    def test_model_specific_openai_and_date_snapshots(self):
        for model,good,bad in [('gpt-5','minimal','none'),('gpt-5.1','none','xhigh'),('gpt-5.2-2025-12-11','xhigh','max'),('gpt-5.4','xhigh','max'),('gpt-5.6','max','minimal'),('gpt-6.1-sol','max','none'),('gpt-6-astra','high','minimal')]:
            c=self.connection(model=model,reasoning_effort=good)
            self.assertEqual(r.parameters(c),{'reasoning_effort':good})
            with self.assertRaises(ValueError):r.parameters({**c,'reasoning_effort':bad})
    def test_default_and_unrecognized_gateway_never_add_parameters(self):
        for c in (self.connection(),self.connection(base_url='https://proxy.example/v1'),self.connection(model='gpt-4o'),self.connection(model='new-unknown-model')):
            self.assertEqual(r.parameters(c),{})
        with self.assertRaises(ValueError):r.parameters(self.connection(base_url='https://proxy.example/v1',reasoning_effort='high'))
    def test_explicit_compatible_gateway_is_opt_in(self):
        c=self.connection(base_url='http://127.0.0.1:8888/v1',model='custom-model',reasoning_api='openai',reasoning_effort='max')
        self.assertEqual(r.parameters(c),{'reasoning_effort':'max'})
        self.assertFalse(r.capabilities(c)['verified'])
        c.update(reasoning_api='deepseek',reasoning_effort='low')
        self.assertEqual(r.parameters(c),{'reasoning_effort':'low','thinking':{'type':'enabled'}})
    def test_legacy_deepseek_switch_and_explicit_setting_priority(self):
        c=self.connection(base_url='https://api.deepseek.com',model='deepseek-v4-pro',thinking_mode='disabled')
        self.assertEqual(r.effective(c),'none');self.assertEqual(r.parameters(c),{'thinking':{'type':'disabled'}})
        c['reasoning_effort']='max'
        self.assertEqual(r.effective(c),'max');self.assertEqual(r.parameters(c)['thinking'],{'type':'enabled'})
        c.update(model='deepseek-reasoner',reasoning_effort='default')
        self.assertEqual(r.parameters(c),{})
    def test_chat_tool_constraints_never_silently_lower_effort(self):
        for model in ('gpt-6-astra','gpt-6.1-sol'):
            with self.assertRaises(ValueError):r.validate_tools(self.connection(model=model,reasoning_effort='high'),True)
            r.validate_tools(self.connection(model=model,reasoning_effort='high'),False)
        for model in ('gpt-6-sol','gpt-6-luna'):
            with self.assertRaises(ValueError):r.validate_tools(self.connection(model=model,reasoning_effort='default'),True)
            r.validate_tools(self.connection(model=model,reasoning_effort='none'),True)
    def test_invalid_api_or_effort_rejected(self):
        for kwargs in ({'reasoning_api':'shell'},{'reasoning_effort':'invented'}):
            with self.assertRaises(ValueError):r.parameters(self.connection(**kwargs))

if __name__=='__main__':unittest.main()
