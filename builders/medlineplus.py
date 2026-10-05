"""MedlinePlus health topics (U.S. National Library of Medicine), English, from the official XML download.
Health topic summaries are written by NLM and are in the public domain."""
import argparse, os, re, sys, xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from pack import PackWriter, write_manifest, sample_report, clean_ws

UA = {'User-Agent': 'NoBarsNeededLibraryBuilder/1.0 (https://github.com/claimtothecity/no-bars-needed-library)'}


def find_xml():
    page = requests.get('https://medlineplus.gov/xml.html', headers=UA, timeout=60).text
    names = sorted(set(re.findall(r'(mplus_topics_\d{4}-\d{2}-\d{2}\.xml)', page)))
    if not names:
        sys.exit('MedlinePlus XML link not found on xml.html:\n' + page[:2000])
    return 'https://medlineplus.gov/xml/' + names[-1], names[-1]


def main(out):
    os.makedirs(out, exist_ok=True)
    url, name = find_xml()
    print('downloading', url, flush=True)
    data = requests.get(url, headers=UA, timeout=600).content
    root = ET.fromstring(data)
    meta = {'id': 'medlineplus', 'name': 'MedlinePlus health topics', 'version': name[13:23], 'topic': 'medical',
            'description': '',
            'license': 'Public domain (U.S. Government work, National Library of Medicine).',
            'credit': 'MedlinePlus (medlineplus.gov), U.S. National Library of Medicine. Not an endorsement of this app.',
            'source': url}
    out_path = os.path.join(out, 'medlineplus.sqlite')
    w = PackWriter(out_path, meta)
    n = 0
    for t in root.iter('health-topic'):
        if t.get('language') != 'English':
            continue
        title = t.get('title', '').strip()
        summary_el = t.find('full-summary')
        if not title or summary_el is None or not (summary_el.text or '').strip():
            continue
        soup = BeautifulSoup(summary_el.text, 'lxml')
        paras = [clean_ws(el.get_text(' ')) for el in soup.find_all(['p', 'li', 'h3', 'h2'])]
        paras = [('• ' + p if el.name == 'li' else p) for p, el in zip(paras, soup.find_all(['p', 'li', 'h3', 'h2'])) if p]
        also = [clean_ws(a.text or '') for a in t.findall('also-called') if (a.text or '').strip()]
        groups = [clean_ws(g.text or '') for g in t.findall('group') if (g.text or '').strip()]
        head = []
        if also:
            head.append('Also called: ' + ', '.join(also) + '.')
        if groups:
            head.append('Topic area: ' + ', '.join(groups) + '.')
        if w.add(title, t.get('url'), [('', head + paras)]):
            n += 1
    w.close()
    report = [f'{name}: {n} English health topics']
    report += sample_report(out_path, ['migraine', 'dehydration', 'tick bite', 'high blood pressure'])
    write_manifest('medlineplus', out_path, meta, report)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out')
    main(ap.parse_args().out)
