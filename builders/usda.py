"""USDA PLANTS checklist pack: accepted plant names, common names, families, synonyms (public domain)."""
import argparse, csv, io, os, sys
from collections import defaultdict
import requests

sys.path.insert(0, os.path.dirname(__file__))
from pack import PackWriter, write_manifest, sample_report

URL = 'https://plants.usda.gov/assets/docs/CompletePLANTSList/plantlst.txt'
UA = {'User-Agent': 'NoBarsNeededLibraryBuilder/1.0 (https://github.com/claimtothecity/no-bars-needed-library)'}


def main(out):
    os.makedirs(out, exist_ok=True)
    r = requests.get(URL, headers=UA, timeout=300)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig', 'replace'))))
    print('rows', len(rows), 'columns', list(rows[0].keys()))
    accepted, synonyms = {}, defaultdict(list)
    for row in rows:
        sym = (row.get('Symbol') or '').strip()
        syn = (row.get('Synonym Symbol') or '').strip()
        sci = (row.get('Scientific Name with Author') or '').strip()
        if not sym or not sci:
            continue
        if syn:
            synonyms[sym].append(sci)
        else:
            accepted[sym] = row
    meta = {'id': 'usda-plants', 'name': 'USDA PLANTS checklist', 'version': '1', 'topic': 'plants',
            'description': 'Every plant in the U.S. and territories from the USDA PLANTS Database: common names, '
                           'scientific names, families, and older synonyms. Helps match a common name to the right species.',
            'license': 'Public domain (U.S. Government work).',
            'credit': 'USDA, NRCS. The PLANTS Database (plants.usda.gov). National Plant Data Team, Greensboro, NC, USA.',
            'source': URL}
    out_path = os.path.join(out, 'usda-plants.sqlite')
    w = PackWriter(out_path, meta)
    for sym, row in accepted.items():
        sci = row['Scientific Name with Author'].strip()
        common = (row.get('Common Name') or '').strip()
        family = (row.get('Family') or '').strip()
        title = f'{common} ({sci})' if common else sci
        body = [f'{sci}.' + (f' Common name: {common}.' if common else '') + (f' Family: {family}.' if family else '')
                + f' USDA PLANTS symbol: {sym}.']
        if synonyms.get(sym):
            body.append('Also listed under older names: ' + '; '.join(synonyms[sym][:25]) + '.')
        w.add(title, f'https://plants.usda.gov/plant-profile/{sym}', [('', body)])
    w.close()
    report = [f'rows {len(rows)}, accepted {len(accepted)}, with synonyms {len(synonyms)}']
    report += sample_report(out_path, ['poison ivy', 'cattail', 'dandelion', 'water hemlock'])
    write_manifest('usda-plants', out_path, meta, report)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out')
    main(ap.parse_args().out)
