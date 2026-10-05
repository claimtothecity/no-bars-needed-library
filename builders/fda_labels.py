"""U.S. drug labels (FDA Structured Product Labeling via openFDA bulk download). Public domain.
One entry per generic name (newest label), key sections only, trimmed to keep the pack small."""
import argparse, io, os, re, sys, zipfile
import ijson
import requests

sys.path.insert(0, os.path.dirname(__file__))
from pack import PackWriter, write_manifest, sample_report, clean_ws

UA = {'User-Agent': 'NoBarsNeededLibraryBuilder/1.0 (https://github.com/claimtothecity/no-bars-needed-library)'}
SECTIONS = [  # (field, heading, max chars)
    ('boxed_warning', 'Boxed warning', 1500),
    ('indications_and_usage', 'Uses', 1500),
    ('dosage_and_administration', 'Dosage', 2500),
    ('dosage_forms_and_strengths', 'Forms and strengths', 600),
    ('contraindications', 'Contraindications', 1000),
    ('warnings_and_cautions', 'Warnings and precautions', 2000),
    ('warnings', 'Warnings', 2000),
    ('adverse_reactions', 'Side effects', 1500),
    ('drug_interactions', 'Drug interactions', 1500),
    ('use_in_specific_populations', 'Pregnancy and special groups', 1200),
    ('pregnancy', 'Pregnancy', 800),
    ('overdosage', 'Overdose', 800),
    ('purpose', 'Purpose (OTC)', 300),
    ('do_not_use', 'Do not use (OTC)', 600),
    ('stop_use', 'Stop use (OTC)', 600),
]


def trim(text, n):
    t = clean_ws(text)
    t = re.sub(r'^\d+(\.\d+)*\s+[A-Z][A-Z &/,-]{3,}\s+', '', t)  # drop leading "5 WARNINGS AND PRECAUTIONS"
    return t if len(t) <= n else t[:n].rsplit(' ', 1)[0] + '…'


def main(out, limit_parts):
    os.makedirs(out, exist_ok=True)
    index = requests.get('https://api.fda.gov/download.json', headers=UA, timeout=60).json()
    parts = index['results']['drug']['label']['partitions']
    export = index['results']['drug']['label'].get('export_date', '')
    if limit_parts:
        parts = parts[:limit_parts]
    best = {}  # generic -> (effective_time, label dict)
    brands = {}
    seen = 0
    for p in parts:
        print('downloading', p['file'], flush=True)
        data = requests.get(p['file'], headers=UA, timeout=1800).content
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            with z.open(z.namelist()[0]) as f:
                for r in ijson.items(f, 'results.item'):
                    seen += 1
                    o = r.get('openfda') or {}
                    ptype = (o.get('product_type') or [''])[0]
                    if ptype not in ('HUMAN PRESCRIPTION DRUG', 'HUMAN OTC DRUG'):
                        continue
                    gen = (o.get('generic_name') or [''])[0].strip().lower()
                    if not gen or len(gen) > 120:
                        continue
                    for b in o.get('brand_name') or []:
                        bs = brands.setdefault(gen, [])
                        b = b.strip().title()
                        if b and b.lower() != gen and b not in bs and len(bs) < 6:
                            bs.append(b)
                    eff = r.get('effective_time', '0')
                    keep = {k: trim(r[k][0], n) for k, _, n in SECTIONS if r.get(k)}  # trimmed now to save memory
                    keep['_ptype'] = ptype
                    keep['_route'] = ', '.join((o.get('route') or [])[:3])
                    keep['_set_id'] = r.get('set_id', '')
                    # prefer prescription labels (fuller) over OTC, then newest
                    rank = (ptype == 'HUMAN PRESCRIPTION DRUG', eff)
                    if gen not in best or rank > best[gen][0]:
                        best[gen] = (rank, keep)
        del data
        print(f'  {seen} labels read, {len(best)} drugs so far', flush=True)
    meta = {'id': 'fda-labels', 'name': 'FDA drug labels', 'version': export[:10] or 'latest', 'topic': 'medical',
            'description': '',
            'license': 'Public domain (U.S. Government work, U.S. Food and Drug Administration).',
            'credit': 'U.S. FDA drug labeling via openFDA (open.fda.gov). Not an endorsement of this app.',
            'source': 'https://open.fda.gov/apis/drug/label/'}
    out_path = os.path.join(out, 'fda-labels.sqlite')
    w = PackWriter(out_path, meta)
    for gen, (_, lab) in sorted(best.items()):
        name = gen.title()
        title = f"{name} ({', '.join(brands.get(gen, [])[:4])})" if brands.get(gen) else name
        kind = 'Prescription' if lab['_ptype'] == 'HUMAN PRESCRIPTION DRUG' else 'Over the counter'
        secs = [('', [f'{name}. {kind} drug label' + (f", route: {lab['_route'].lower()}" if lab['_route'] else '') + '.'])]
        for field, heading, n in SECTIONS:
            if field == 'warnings' and 'warnings_and_cautions' in lab:
                continue
            if field == 'pregnancy' and 'use_in_specific_populations' in lab:
                continue
            if lab.get(field):
                secs.append((heading, [lab[field]]))
        url = f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={lab['_set_id']}" if lab['_set_id'] else None
        w.add(title, url, secs)
    w.close()
    report = [f'labels read {seen}; unique drugs {len(best)}; export {export}']
    report += sample_report(out_path, ['sumatriptan dosage', 'ibuprofen kidney', 'amoxicillin allergy', 'warfarin interactions'])
    write_manifest('fda-labels', out_path, meta, report)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out'); ap.add_argument('--limit-parts', type=int, default=0)
    a = ap.parse_args(); main(a.out, a.limit_parts)
