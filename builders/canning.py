"""USDA Complete Guide to Home Canning (2015 revision; public domain), from the Kiwix "usda-2015_en" ZIM.

The ZIM holds the guide's PDFs. Each PDF ("Guide 1 … Guide 7" plus the introduction) is turned into text with
pdftotext and split into sections at headings (short lines without a final period).
"""
import argparse, os, re, subprocess, sys, tempfile

import requests
from libzim.reader import Archive

sys.path.insert(0, os.path.dirname(__file__))
from pack import PackWriter, write_manifest, sample_report, clean_ws

KIWIX = 'https://download.kiwix.org/zim/other/'
UA = {'User-Agent': 'NoBarsNeededLibraryBuilder/1.0 (https://github.com/claimtothecity/no-bars-needed-library)'}
SITE = 'https://nchfp.uga.edu/'
GUIDES = {
    'intro': 'USDA canning guide: introduction and how to use it',
    '1': 'USDA canning guide 1: principles of home canning',
    '2': 'USDA canning guide 2: fruit and fruit products',
    '3': 'USDA canning guide 3: tomatoes and tomato products',
    '4': 'USDA canning guide 4: vegetables and vegetable products',
    '5': 'USDA canning guide 5: poultry, red meats and seafood',
    '6': 'USDA canning guide 6: fermented foods and pickled vegetables',
    '7': 'USDA canning guide 7: jams and jellies',
}
NOISE = re.compile(r'^(\d{1,3}|Page \d+.*|USDA Complete Guide to Home Canning.*|\d-\d+|Guide \d+\s*$)$', re.I)


def newest():
    html = requests.get(KIWIX, headers=UA, timeout=60).text
    hits = sorted(set(re.findall(r'href="(usda-2015_en_\d{4}-\d{2}\.zim)"', html)))
    return hits[-1] if hits else None


def heading(s):
    return (4 < len(s) < 75 and not s.endswith(('.', ',', ';', ':')) and s[0].isupper()
            and len(s.split()) <= 10 and not re.search(r'\d{2,}\s*(minutes|min|°F|pounds|lb)', s))


def sections_from_text(text):
    secs, head, paras, buf = [], '', [], ''
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            if buf:
                paras.append(buf); buf = ''
            continue
        if NOISE.match(s):
            continue
        if heading(s) and not buf:
            if paras:
                secs.append((head, paras))
            head, paras = s, []
            continue
        if buf.endswith('-') and not buf.endswith(' -'):
            buf = buf[:-1] + s
        else:
            buf = f'{buf} {s}'.strip()
    if buf:
        paras.append(buf)
    if paras:
        secs.append((head, paras))
    # merge tiny sections into the previous one (tables split into many short "headings")
    merged = []
    for h, p in secs:
        if merged and sum(len(x) for x in p) < 150:
            merged[-1][1].extend([f'{h}:'] + p if h else p)
        else:
            merged.append((h, list(p)))
    return [(h, [clean_ws(x) for x in p]) for h, p in merged]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--id', default='usda-canning')
    ap.add_argument('--out', default='out')
    ap.add_argument('--work', default='work')
    ap.add_argument('--queries', default='pressure canner altitude;botulism;pickles;jam pectin;green beans')
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True); os.makedirs(args.work, exist_ok=True)
    name = newest()
    if not name:
        sys.exit('usda-2015 ZIM not found')
    zpath = os.path.join(args.work, name)
    subprocess.run(['curl', '-fL', '--retry', '5', '-sS', '-o', zpath, KIWIX + name], check=True)
    meta = {'id': args.id, 'name': 'USDA home canning guide',
            'description': 'USDA Complete Guide to Home Canning',
            'version': re.search(r'(\d{4}-\d{2})\.zim$', name).group(1), 'topic': 'food',
            'license': 'Public domain (U.S. Government work)',
            'credit': 'USDA Complete Guide to Home Canning (2015 revision), U.S. Department of Agriculture / '
                      'National Institute of Food and Agriculture. Public domain. Via Kiwix.',
            'source': name}
    out_path = os.path.join(args.out, f'{args.id}.sqlite')
    w = PackWriter(out_path, meta)
    zim = Archive(zpath)
    report = []
    for i in range(zim.all_entry_count):
        e = zim._get_entry_by_id(i)
        if e.is_redirect:
            continue
        item = e.get_item()
        if item.mimetype != 'application/pdf':
            continue
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tf:
            tf.write(bytes(item.content)); pdf = tf.name
        subprocess.run(['pdftotext', '-enc', 'UTF-8', '-nopgbrk', pdf, pdf + '.txt'], check=True)
        text = open(pdf + '.txt', encoding='utf-8', errors='replace').read().replace('\u00a0', ' ').replace('\ufffd', ' ')
        text = '\n'.join(l for l in text.splitlines() if '....' not in l)  # table-of-contents leader lines
        os.remove(pdf); os.remove(pdf + '.txt')
        m = re.search(r'GUIDE0?(\d)', e.path, re.I)
        title = GUIDES.get(m.group(1) if m else 'intro', 'USDA Complete Guide to Home Canning')
        secs = sections_from_text(text)
        added = w.add(title, SITE, secs)
        report.append(f'pdf {e.path}: {title} -> {len(secs)} sections, {len(text)} chars, added={added}')
        print(report[-1], flush=True)
    w.close()
    report += sample_report(out_path, args.queries.split(';'))
    write_manifest(args.id, out_path, meta, report)


if __name__ == '__main__':
    main()
