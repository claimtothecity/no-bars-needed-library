"""USDA PLANTS checklist pack: accepted plant names, common names, families, synonyms (public domain)."""
import argparse, csv, io, os, sys
from collections import defaultdict
import requests

sys.path.insert(0, os.path.dirname(__file__))
from pack import PackWriter, write_manifest, sample_report

URLS = [
    'https://plants.sc.egov.usda.gov/DocumentLibrary/Txt/plantlst.txt',
    'https://plants.usda.gov/DocumentLibrary/Txt/plantlst.txt',
    'https://plants.usda.gov/assets/docs/CompletePLANTSList/plantlst.txt',
    'https://plants.sc.egov.usda.gov/assets/docs/CompletePLANTSList/plantlst.txt',
    'https://plantsorig.sc.egov.usda.gov/DocumentLibrary/Txt/plantlst.txt',
]
URL = URLS[0]


def fetch_rows():
    tried = []
    for u in URLS:
        try:
            r = requests.get(u, headers=UA, timeout=300)
            text = r.content.decode('utf-8-sig', 'replace')
            head = text[:300].replace('\n', ' | ')
            tried.append(f'{u}: HTTP {r.status_code}, {len(text)} chars, starts {head!r}')
            if r.ok and 'Symbol' in text[:200] and text.count('\n') > 1000:
                return u, list(csv.DictReader(io.StringIO(text))), tried
        except Exception as ex:
            tried.append(f'{u}: {ex}')
    sys.exit('\n'.join(['USDA list not found:'] + tried))
UA = {'User-Agent': 'NoBarsNeededLibraryBuilder/1.0 (https://github.com/claimtothecity/no-bars-needed-library)'}


def main(out):
    os.makedirs(out, exist_ok=True)
    url, rows, tried = fetch_rows()
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
            'source': url}
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
    report = tried + [f'rows {len(rows)}, accepted {len(accepted)}, with synonyms {len(synonyms)}']
    report += sample_report(out_path, ['poison ivy', 'cattail', 'dandelion', 'water hemlock'])
    write_manifest('usda-plants', out_path, meta, report)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out')
    main(ap.parse_args().out)
