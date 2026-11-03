"""Dashboard queue scope matches Jobs configuration; no SSH or production data."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix='vasp-dashboard-test-')
os.environ['VASP_WEB_DATA_DIR'] = _DATA.name
os.environ['VASP_AI_KEY_FILE'] = str(Path(_DATA.name) / 'ai.key')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import cluster_status
import dashboard


class DashboardClusterHealthTests(unittest.TestCase):
    def test_queue_list_and_totals_match_jobs_scope_and_order(self):
        names = ['normal_2week', 'ocean_530_1day', 'ocean6226R_1day', 'normal_1day_new', 'charge']
        groups = [{'queue': name, 'prefix': f'n{i}', 'start': 1, 'end': 1} for i, name in enumerate(names)]
        servers = {'selected': {'node_groups': groups + [groups[0]]},
                   'other': {'node_groups': [{'queue': 'other_server'}]}}
        sections = {
            'BHOSTS': 'HOST_NAME STATUS JL/U MAX NJOBS RUN SSUSP USUSP RSV\n',
            'BQUEUES': '\n'.join(
                f'{name} 30 Open:Active - - - - {i+2} {i} 2 0'
                for i, name in enumerate(reversed(names))
            ) + '\nunrelated 30 Open:Active - - - - 9999 9998 1 0\n'
                'other_server 30 Open:Active - - - - 9000 8999 1 0\n',
        }
        nodes, storage = {'total': 20}, {'usedPercent': 12}
        with patch.object(dashboard, 'load_servers', return_value=servers), \
             patch.object(cluster_status, 'load_servers', return_value=servers), \
             patch.object(cluster_status.cluster_probe, 'probe', return_value={'sections': sections}):
            jobs = cluster_status.build_snapshot('selected')
            health = dashboard.build_cluster_health({
                'server': 'selected', 'queues': dashboard.parse_bqueues(sections['BQUEUES']),
                'nodes': nodes, 'storage': storage,
            })
        self.assertEqual([q['queue'] for q in health['queues']], [q['queue'] for q in jobs['queues']])
        self.assertEqual([q['queue'] for q in health['queues']], names)
        self.assertEqual(health['queueTotals'], {'pending': 10, 'running': 10, 'queues': 5})
        self.assertEqual(health['nodes'], nodes)
        self.assertEqual(health['storage'], storage)

    def test_missing_configuration_or_queue_output_does_not_show_unrelated_queues(self):
        for servers in ({}, {'selected': {'node_groups': [{'queue': 'missing'}]}}):
            with self.subTest(servers=servers), patch.object(dashboard, 'load_servers', return_value=servers):
                health = dashboard.build_cluster_health({
                    'server': 'selected', 'queues': [{'queue': 'unrelated', 'pending': 999, 'running': 888}],
                })
                self.assertEqual(health['queues'], [])
                self.assertEqual(health['queueTotals'], {'pending': 0, 'running': 0, 'queues': 0})


if __name__ == '__main__':
    unittest.main()
