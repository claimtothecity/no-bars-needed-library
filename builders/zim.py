"""Build a pack from one or more Kiwix Wikipedia ZIM files (text only).

  python builders/zim.py --id wikimed --flavours medicine_nopic --name ... --out out/

For each flavour (e.g. "medicine_nopic") the newest wikipedia_en_<flavour>_YYYY-MM.zim on
download.kiwix.org is used. Several flavours are merged (duplicate titles skipped).
"""
import argparse, os, re, subprocess, sys, urllib.parse
from multiprocessing import Pool

import requests
from bs4 import BeautifulSoup
from libzim.reader import Archive

sys.path.insert(0, os.path.dirname(__file__))
from pack import PackWriter, write_manifest, sample_report, clean_ws

KIWIX_ROOT = 'https://download.kiwix.org/zim/'
KIWIX = KIWIX_ROOT + 'wikipedia/'  # changed by --dir
UA = {'User-Agent': 'NoBarsNeededLibraryBuilder/1.0 (https://github.com/claimtothecity/no-bars-needed-library)'}

SKIP_SECTIONS = {'references', 'external links', 'see also', 'further reading', 'notes', 'bibliography',
                 'sources', 'citations', 'footnotes', 'gallery', 'works cited', 'explanatory notes',
                 'general references', 'notes and references', 'references and notes', 'publications', 'literature'}
DROP_SELECTORS = ['table', 'figure', 'style', 'script', 'sup', '.reference', '.references', '.reflist',
                  '.mw-references-wrap', '.navbox', '.infobox', '.thumb', '.hatnote', '.mw-editsection',
                  '.metadata', '.noprint', '.ambox', '.gallery', 'math', '.mwe-math-element', 'img',
                  '.portal', '.sistersitebox', '.shortdescription', '.mw-empty-elt', '#catlinks', '.catlinks',
                  '.mw-hidden-catlinks', 'footer', '.printfooter', 'nav', '#mw-navigation', '.authority-control',
                  '.side-box', '.mbox-small', '.plainlinks.metadata']
# maintenance/category lines that sometimes survive as list items
MAINT_RE = re.compile(r'^(All |Articles |Pages |Use (mdy|dmy|American|British|Australian|Canadian|Indian)|CS1 |Webarchive|'
                      r'Short description|Wikipedia |Commons category|Good articles|Featured articles|Harv and Sfn|'
                      r'Official website|Coordinates on Wikidata|EngvarB|Infobox |Template:|Category:)')


def list_zims():
    html = requests.get(KIWIX, headers=UA, timeout=60).text
    return sorted(set(re.findall(r'href="([a-z0-9_\-]+?_\d{4}-\d{2}\.zim)"', html)))


PREFIX = 'wikipedia_en_'  # changed by --prefix
TITLE_PREFIX = ''  # changed by --title-prefix
SKIP_TRANSLATIONS = False  # --english-only


def newest(all_files, flavour):
    pat = re.compile(rf'^{re.escape(PREFIX)}{re.escape(flavour)}_(\d{{4}}-\d{{2}})\.zim$')
    hits = sorted((m.group(1), f) for f in all_files if (m := pat.match(f)))
    return hits[-1][1] if hits else None


def download(name, dest_dir):
    path = os.path.join(dest_dir, name)
    if not os.path.exists(path):
        print(f'downloading {name}', flush=True)
        subprocess.run(['curl', '-fL', '--retry', '5', '--retry-delay', '10', '-sS', '-o', path + '.part',
                        KIWIX + name], check=True)
        os.rename(path + '.part', path)
    print(f'{name}: {os.path.getsize(path) / 1e6:.0f} MB', flush=True)
    return path


def html_to_sections(html):
    soup = BeautifulSoup(html, 'lxml')
    body = soup.body or soup
    for sel in DROP_SELECTORS:
        for el in body.select(sel):
            el.decompose()
    sections, heading, paras, skipping = [], '', [], False
    for el in body.find_all(['h2', 'h3', 'h4', 'p', 'li', 'dd']):
        if el.name in ('h2', 'h3', 'h4'):
            text = clean_ws(el.get_text(' '))
            if el.name == 'h2':
                if paras and not skipping:
                    sections.append((heading, paras))
                heading, paras = text, []
                skipping = text.lower() in SKIP_SECTIONS
            elif not skipping and text:
                paras.append(f'{text}:')
            continue
        if skipping:
            continue
        # skip list items nested inside another captured element
        if el.find_parent(['li', 'dd']) is not None:
            continue
        text = clean_ws(el.get_text(' '))
        text = re.sub(r'\s+([,.;:)])', r'\1', text)
        if len(text) < 25 and el.name != 'p':
            continue
        if MAINT_RE.match(text):
            continue
        if el.name == 'li':
            text = '• ' + text
        paras.append(text)
    if paras and not skipping:
        sections.append((heading, paras))
    # merge orphan "Heading:" lines into the next paragraph
    return sections


def iter_articles(zim_path):
    zim = Archive(zim_path)
    for i in range(zim.all_entry_count):
        e = zim._get_entry_by_id(i)
        if e.is_redirect:
            continue
        try:
            item = e.get_item()
        except Exception:
            continue
        if not item.mimetype.startswith('text/html'):
            continue
        path = e.path
        if path.startswith('C/'):
            path = path[2:]
        if path.startswith(('-/', 'I/', 'M/', 'X/', 'W/')) or path in ('index', 'mainPage', 'Main_Page'):
            continue
        if SKIP_TRANSLATIONS and re.search(r'/[a-z]{2,3}(-[a-z]+)?$', path):
            continue  # e.g. "Rainwater_harvesting/ja" (translated copies)
        if TITLE_PREFIX and not (e.title.startswith(TITLE_PREFIX) or path.startswith(TITLE_PREFIX)):
            continue  # skip before the (slow) HTML parsing
        yield e.title, path, bytes(item.content).decode('utf-8', 'replace')


def _work(args):
    title, path, html = args
    try:
        return title, path, html_to_sections(html)
    except Exception as ex:  # one bad page shouldn't stop a 70k-page build
        return title, path, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--id', required=True)
    ap.add_argument('--flavours', required=True, help='comma list, e.g. medicine_nopic or physics_nopic,chemistry_nopic')
    ap.add_argument('--name', required=True)
    ap.add_argument('--description', required=True)
    ap.add_argument('--topic', default='general')
    ap.add_argument('--queries', default='headache;fever;fracture')
    ap.add_argument('--out', default='out')
    ap.add_argument('--work', default='work')
    ap.add_argument('--dir', default='wikipedia', help='Kiwix folder: wikipedia, wikivoyage, wikibooks, other ...')
    ap.add_argument('--prefix', default='wikipedia_en_', help='file name prefix before the flavour')
    ap.add_argument('--site', default='https://en.wikipedia.org/wiki/', help='article URL base for sources')
    ap.add_argument('--credit', default='Text from Wikipedia, the free encyclopedia (Wikipedia contributors), via Kiwix. '
                    'Licensed CC BY-SA 4.0. Reformatted as plain-text passages.')
    ap.add_argument('--license', default='CC BY-SA 4.0')
    ap.add_argument('--english-only', action='store_true', help='skip translated pages like Page/es')
    ap.add_argument('--title-prefix', default='', help='only keep articles whose title starts with this (e.g. Cookbook:)')
    args = ap.parse_args()
    global KIWIX, PREFIX, TITLE_PREFIX, SKIP_TRANSLATIONS
    SKIP_TRANSLATIONS = args.english_only
    KIWIX = f'{KIWIX_ROOT}{args.dir}/'
    PREFIX = args.prefix
    TITLE_PREFIX = args.title_prefix
    os.makedirs(args.out, exist_ok=True); os.makedirs(args.work, exist_ok=True)

    files = list_zims()
    report = [f'kiwix {args.dir} ZIMs available: {len(files)}']
    report += [f'  {f}' for f in files if '_en_' in f or not f.startswith(('wikipedia_', 'wiki'))][:200]
    chosen = []
    for fl in args.flavours.split(','):
        f = None
        for alt in fl.strip().split('|'):  # "top_mini|top_nopic" = first one that exists
            f = newest(files, alt)
            if f:
                break
        report.append(f'flavour {fl} -> {f}')
        if f:
            chosen.append(f)
    if not chosen:
        print('\n'.join(report)); sys.exit('no ZIM found for ' + args.flavours)

    version = max(re.search(r'(\d{4}-\d{2})\.zim$', f).group(1) for f in chosen)
    meta = {'id': args.id, 'name': args.name, 'description': args.description, 'version': version,
            'topic': args.topic,
            'license': args.license,
            'credit': args.credit,
            'source': ', '.join(chosen)}
    out_path = os.path.join(args.out, f'{args.id}.sqlite')
    w = PackWriter(out_path, meta)
    seen = set()
    for f in chosen:
        zim_path = download(f, args.work)
        with Pool(os.cpu_count() or 2) as pool:
            for title, path, sections in pool.imap(_work, iter_articles(zim_path), chunksize=32):
                if title in seen:
                    continue
                if args.title_prefix and not (title.startswith(args.title_prefix) or path.startswith(args.title_prefix)):
                    continue
                seen.add(title)
                url = args.site + urllib.parse.quote(path)
                w.add(title, url, sections)
        os.remove(zim_path)
    w.close()
    report += sample_report(out_path, args.queries.split(';'))
    write_manifest(args.id, out_path, meta, report)


if __name__ == '__main__':
    main()
