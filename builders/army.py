"""Build packs from public-domain U.S. Army field manuals.

  --pack survival  : ATP 3-50.21 Survival (2018) + TC 4-02.1 First Aid (if reachable)
  --pack wildplants: FM 3-05.70 Survival (2002) chapters on plant use and poisonous plants,
                     plus Appendix B (edible & medicinal plants) and C (poisonous plants)

Text comes from the Internet Archive's OCR text of each manual (or pdftotext for PDFs).
"""
import argparse, os, re, subprocess, sys
import requests

sys.path.insert(0, os.path.dirname(__file__))
from pack import PackWriter, write_manifest, sample_report

UA = {'User-Agent': 'NoBarsNeededLibraryBuilder/1.0 (https://github.com/claimtothecity/no-bars-needed-library)'}

SOURCES = {
    'atp': {
        'label': 'ATP 3-50.21 Survival (2018)',
        'ia': 'survival-atp-3-50-21',
        'url': 'https://armypubs.army.mil/ProductMaps/PubForm/Details.aspx?PUB_ID=1005316',
    },
    'fm': {
        'label': 'FM 3-05.70 Survival (2002)',
        'ia': 'fm-3-05.70-survival-2002',
        'url': 'https://archive.org/details/fm-3-05.70-survival-2002',
    },
    'tc': {
        'label': 'TC 4-02.1 First Aid',
        'pdf': [
            'https://rdl.train.army.mil/catalog-ws/view/100.ATSC/B0A32FAD-8C7A-44A6-8FF4-F754A32F1C30-1453986206542/tc4-02.1wc1x2.pdf',
            'https://upload.wikimedia.org/wikipedia/commons/0/0b/TC_4-02.1_First_Aid_%28Change_2%2C_ARN14135-TC_4-02.1-002-WEB-3%29.pdf',
        ],
        'commons_title': 'File:TC_4-02.1_First_Aid_(Change_2,_ARN14135-TC_4-02.1-002-WEB-3).pdf',
        'url': 'https://armypubs.army.mil/',
    },
}

HEAD_RE = re.compile(r'^(chapter|appendix)\s+([0-9]+|[a-z])\b\.?\s*(.*)$', re.I)
NOISE_RE = re.compile(r'^(\d+(-\d+)?|[ivxlc]+|[A-Z]-\d+|ATP 3-50\.21.*|FM 3-05\.70.*|TC 4-02\.1.*|'
                      r'\d+ (January|February|March|April|May|June|July|August|September|October|November|December) \d{4}|'
                      r'This page intentionally left blank\.?)$', re.I)


def fetch_text(src, work):
    if 'ia' in src:  # Internet Archive item: find its OCR text file
        import urllib.parse
        files = requests.get(f'https://archive.org/metadata/{src["ia"]}/files', headers=UA, timeout=120).json()['result']
        names = [f['name'] for f in files if f['name'].endswith('_djvu.txt')]
        if not names:
            print('no _djvu.txt in', src['ia'], [f['name'] for f in files]); return None
        url = f'https://archive.org/download/{src["ia"]}/{urllib.parse.quote(names[0])}'
        print('text:', url)
        r = requests.get(url, headers=UA, timeout=300)
        r.raise_for_status()
        return r.text
    urls = list(src['pdf'])
    if src.get('commons_title'):
        try:
            j = requests.get('https://commons.wikimedia.org/w/api.php', headers=UA, timeout=60, params={
                'action': 'query', 'titles': src['commons_title'], 'prop': 'imageinfo', 'iiprop': 'url',
                'format': 'json', 'formatversion': 2}).json()
            urls.insert(0, j['query']['pages'][0]['imageinfo'][0]['url'])
        except Exception as ex:
            print('commons lookup failed', ex)
    for u in urls:
        try:
            pdf = os.path.join(work, 'doc.pdf')
            r = requests.get(u, headers=UA, timeout=180)
            r.raise_for_status()
            if not r.content.startswith(b'%PDF'):
                raise ValueError('not a PDF')
            open(pdf, 'wb').write(r.content)
            subprocess.run(['pdftotext', '-layout', '-nopgbrk', pdf, pdf + '.txt'], check=True)
            print('got', u)
            return open(pdf + '.txt', encoding='utf-8', errors='replace').read()
        except Exception as ex:
            print('failed', u, ex)
    return None


def paragraphs(lines):
    """Join OCR lines into paragraphs; blank lines separate paragraphs; fix hyphenation."""
    out, buf = [], ''
    for ln in lines:
        s = ln.strip()
        if not s:
            if buf:
                out.append(buf); buf = ''
            continue
        if NOISE_RE.match(s):
            continue
        if buf.endswith('-') and not buf.endswith(' -'):
            buf = buf[:-1] + s
        else:
            buf = f'{buf} {s}'.strip()
    if buf:
        out.append(buf)
    return out


PAGE_RE = re.compile(r'^[0-9A-Z]{1,2}-\d+$')
VERB_RE = re.compile(r'^(discusses|covers|focuses|provides|describes|explains|contains|presents)\b', re.I)


def _title_like(t):
    return bool(t) and len(t) < 70 and not t.endswith('.') and not PAGE_RE.match(t) and not VERB_RE.match(t)


def split_parts(text):
    """Split a manual into (label, lines) by 'Chapter N' / 'Appendix X' headings.
    Running page headers (same chapter again) are dropped; table-of-contents and summary
    mentions are merged by chapter, keeping the longest body and the best-looking title."""
    lines = text.splitlines()
    parts = []  # [key, title, lines]
    key, cur = ('front', ''), []
    titles = {}
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        m = HEAD_RE.match(s)
        if m and len(s) < 80:
            k = (m.group(1).lower(), m.group(2).upper())
            title = re.sub(r'\s*\.{2,}.*$|\s+[0-9A-Z]{1,2}-\d+$', '', m.group(3).strip()).strip()
            # look at the next non-empty line: a title or a page number?
            j = i + 1
            while j < len(lines) and not lines[j].strip() and j < i + 4:
                j += 1
            nxt = lines[j].strip() if j < len(lines) else ''
            if k == key:  # running header inside the same chapter
                if PAGE_RE.match(nxt):
                    i = j
                i += 1
                continue
            if not title and (_title_like(nxt) or PAGE_RE.match(nxt)):
                title = '' if PAGE_RE.match(nxt) else nxt
                i = j
            parts.append((key, cur))
            key, cur = k, []
            if _title_like(title):
                titles.setdefault(k, []).append(title)
        else:
            cur.append(lines[i])
        i += 1
    parts.append((key, cur))
    best, order = {}, []
    for k, body in parts:
        if k not in best or len(body) > len(best[k]):
            best[k] = body
        if k not in order:
            order.append(k)
    out = []
    for k in order:
        if k[0] == 'front':
            label = 'Front matter'
        else:
            t = titles.get(k, [''])[0]
            label = f'{k[0].title()} {k[1]}' + (f': {t.title()}' if t else '')
        out.append((label, best[k]))
    return out


def plant_entries(paras):
    """Appendix B/C: entries look like  Name / Scientific name / Description: ... / Habitat ... / Edible parts ...
    Returns list of (entry_title, [paragraphs]); falls back to one block."""
    idx = [k for k, p in enumerate(paras) if p.lower().startswith('description:')]
    if len(idx) < 5:
        return [('', paras)]
    entries = []
    starts = []
    for k in idx:
        st = max(0, k - 2)
        starts.append(st)
    starts.append(len(paras))
    if starts[0] > 0:
        entries.append(('', paras[:starts[0]]))
    for a, b in zip(starts, starts[1:]):
        block = paras[a:b]
        head = [p for p in block[:2] if not p.lower().startswith('description:') and len(p) < 120]
        title = ' — '.join(head) if head else ''
        body = [p for p in block if p not in head]
        entries.append((title, (head[:1] + body) if head else body))
    return entries


def build(pack, out, work):
    os.makedirs(out, exist_ok=True); os.makedirs(work, exist_ok=True)
    common = {'license': 'Public domain (U.S. Government work). Approved for public release; distribution unlimited.',
              'version': '1'}
    if pack == 'survival':
        meta = {**common, 'id': 'army-survival', 'name': 'Army survival & first aid',
                'description': 'U.S. Army survival manual (ATP 3-50.21) and first-aid manual (TC 4-02.1): shelter, water, '
                               'fire, navigation, signaling, survival medicine, bleeding, burns, fractures.',
                'topic': 'survival',
                'credit': 'U.S. Department of the Army, ATP 3-50.21 Survival (2018) and TC 4-02.1 First Aid. Public domain.'}
        keys = ['atp', 'tc']
        queries = ['purify water', 'build a fire', 'tourniquet bleeding', 'hypothermia', 'snake bite']
    else:
        meta = {**common, 'id': 'army-wild-plants', 'name': 'Wild edible & poisonous plants',
                'description': 'U.S. Army field manual chapters on finding and testing wild food plants, the universal edibility test, '
                               'edible and medicinal plants, and poisonous plants to avoid.',
                'topic': 'plants',
                'credit': 'U.S. Department of the Army, FM 3-05.70 Survival (2002), plant chapters and Appendices B and C. Public domain.'}
        keys = ['fm']
        queries = ['universal edibility test', 'cattail', 'poison hemlock', 'acorn', 'mushroom']
    report = []
    out_path = os.path.join(out, meta['id'] + '.sqlite')
    w = PackWriter(out_path, meta)
    for key in keys:
        src = SOURCES[key]
        text = fetch_text(src, work)
        if not text:
            report.append(f'!! {src["label"]}: could not download, skipped')
            continue
        parts = split_parts(text)
        report.append(f'{src["label"]}: {len(text)} chars, {len(parts)} parts')
        for label, lines in parts:
            paras = paragraphs(lines)
            n = sum(len(p) for p in paras)
            keep = True
            if pack == 'wildplants':
                low = label.lower()
                keep = ('plant' in low) or low.startswith(('appendix b', 'appendix c'))
            elif label == 'Front matter':
                keep = False
            report.append(f'   {"KEEP" if keep else "skip"} {label} ({n} chars)')
            if not keep or n < 200:
                continue
            title = f'{src["label"].split(" (")[0]} — {label}'
            if pack == 'wildplants' and label.lower().startswith(('appendix b', 'appendix c')):
                for entry_title, entry_paras in plant_entries(paras):
                    w.add(f'{title}: {entry_title}' if entry_title else title, src['url'], [('', entry_paras)])
            else:
                w.add(title, src['url'], [('', paras)])
    if w.docs == 0:
        sys.exit('\n'.join(report) + '\nno content')
    w.close()
    report += sample_report(out_path, queries)
    write_manifest(meta['id'], out_path, meta, report)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack', choices=['survival', 'wildplants'], required=True)
    ap.add_argument('--out', default='out')
    ap.add_argument('--work', default='work')
    a = ap.parse_args()
    build(a.pack, a.out, a.work)
