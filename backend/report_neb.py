"""Freeze the same locally synchronized NEB structures used by inspection details."""

from cif_convert import read_neb_image_cifs


def attach_structures(project, task, item):
    cifs = read_neb_image_cifs(project, task)
    by_label = {str(int(label)) if label.isdigit() else label: cif for label, cif in cifs.items()}
    for image in item["images"]:
        label = image["label"]
        image["cif"] = by_label.get(str(int(label)) if label.isdigit() else label)


def has_structures(item):
    return any(image.get("cif") for image in item.get("images", []))


def widget_html(key):
    from html import escape
    from report_interactive import neb_css

    return ("<style>" + neb_css() + "</style>"
            + '<div class="report-widget" data-report-widget="neb-3d" data-task-id="'
            + escape(str(key), quote=True) + '"></div>')


def append_review_blocks(project, reviews, blocks, evidence, frozen=None):
    import copy
    import hashlib
    import json
    from report_panels import neb_panel

    tasks = {task['task_id']: task for task in project['tasks']}
    for review in reviews:
        key = review['path_task_id']
        block_id = 'blk_neb_' + hashlib.sha256(key.encode()).hexdigest()[:20]
        old = next((b for b in (frozen or {}).get('blocks', []) if b['block_id'] == block_id), None)
        if old:
            eid = old['source_refs'][0]['evidence_id']
            blocks.append(copy.deepcopy(old))
            evidence[eid] = copy.deepcopy(frozen['data']['library']['evidence'][eid])
            continue
        # Answering a saved report must not pull in structures synchronized later.
        if frozen:
            continue
        images = [{'label': str(row['label']), 'relative_energy_ev': row.get('relative'),
                   'energy_ev': row.get('energy'), 'max_force_ev_per_a': row.get('max_force')}
                  for row in (review.get('energy_profile') or {}).get('images', [])]
        item = {'task_id': key, 'task_name': review['path_name'], 'images': images}
        attach_structures(project, tasks[key], item)
        if not images:
            continue
        payload = {'items': [item], 'charts': [neb_panel(item, title=review['path_name'])]}
        version = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        eid = 'ev_neb_' + hashlib.sha256(key.encode()).hexdigest()[:20]
        evidence[eid] = {'evidence_id': eid, 'version': version, 'availability': 'available',
                         'payload': payload, 'validation': {'status': 'CONDITIONAL'},
                         'provenance': [{'task_id': key, 'source': 'local_latest_inspection',
                                         'observed_at': review['energy_profile'].get('observed_at')}]}
        blocks.append({'block_id': block_id, 'type': 'group.neb', 'renderer': 'neb_panel',
                       'origin': 'r2', 'title': review['path_name'] + ' · NEB 映像',
                       'section': 'structures', 'review_path': key,
                       'source_refs': [{'evidence_id': eid, 'version': version}],
                       'options': {}, 'task_id': key, 'data_status': 'available'})


def review_html(doc, path_id, deleted):
    from report_compositions import _block_body
    return ''.join(_block_body(block, doc['data']['library']['evidence'][block['source_refs'][0]['evidence_id']])
                   for block in doc['blocks'] if block['renderer'] == 'neb_panel'
                   and block.get('review_path') == path_id and block['block_id'] not in deleted)
