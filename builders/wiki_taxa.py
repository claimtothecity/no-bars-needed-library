"""Wikipedia plants & fungi pack.

1. Ask Wikidata (QLever, falling back to WDQS) for English Wikipedia articles about taxa under
   Plantae (Q756) or Fungi (Q764) that have an English common name.
2. Fetch each article's lead section as plain text (TextExtracts API, 20 per request).
3. For articles whose lead mentions edibility, toxicity or medicinal use, fetch the full text too.
"""
import argparse, os, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
import requests

sys.path.insert(0, os.path.dirname(__file__))
from pack import PackWriter, write_manifest, sample_report

UA = {'User-Agent': 'NoBarsNeededLibraryBuilder/1.0 (https://github.com/claimtothecity/no-bars-needed-library; ClaimToTheCity@gmail.com)'}
API = 'https://en.wikipedia.org/w/api.php'
PREFIXES = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX schema: <http://schema.org/>
PREFIX wikibase: <http://wikiba.se/ontology#>
"""
# Broad: taxa with an English common name OR widely covered (10+ Wikipedia language editions)
SPARQL_BROAD = PREFIXES + """
SELECT DISTINCT ?article WHERE {
  VALUES ?root { wd:Q756 wd:Q764 }
  ?item wdt:P171+ ?root .
  ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> .
  ?item wikibase:sitelinks ?links .
  OPTIONAL { ?item wdt:P1843 ?common . FILTER(LANG(?common) = "en") }
  FILTER(BOUND(?common) || ?links >= 10)
}
"""
SPARQL = PREFIXES + """
SELECT DISTINCT ?article WHERE {
  VALUES ?root { wd:Q756 wd:Q764 }
  ?item wdt:P171+ ?root .
  ?item wdt:P1843 ?common . FILTER(LANG(?common) = "en")
  ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> .
}
"""
MUST_HAVE = ['Amanita phalloides', 'Morchella', 'Typha latifolia', 'Taraxacum officinale', 'Urtica dioica',
             'Toxicodendron radicans', 'Cicuta maculata', 'Conium maculatum', 'Chanterelle', 'Amanita muscaria',
             'Quercus', 'Vaccinium', 'Rubus', 'Sambucus', 'Allium tricoccum', 'Plantago major']
FULLTEXT_WORDS = ('edible', 'toxic', 'poison', 'medicinal', 'eaten', 'food', 'cultivated', 'invasive', 'foraging')
SKIP_HEADINGS = ('references', 'external links', 'see also', 'further reading', 'notes', 'bibliography',
                 'sources', 'gallery', 'citations')

session = requests.Session(); session.headers.update(UA)


def titles_from_wikidata():
    q = 'https://qlever.cs.uni-freiburg.de/api/wikidata'
    hdr = {'Accept': 'application/sparql-results+json'}
    endpoints = [(q, SPARQL_BROAD), (q, SPARQL), ('https://query.wikidata.org/sparql', SPARQL)]
    for url, query in endpoints:
        try:
            r = session.post(url, data={'query': query}, headers=hdr, timeout=900)
            r.raise_for_status()
            rows = r.json()['results']['bindings']
            titles = sorted({urllib.parse.unquote(b['article']['value'].rsplit('/wiki/', 1)[1]).replace('_', ' ')
                             for b in rows})
            print(f'{url}: {len(titles)} articles', flush=True)
            if titles:
                return sorted(set(titles) | set(MUST_HAVE)), url + (' (broad)' if query is SPARQL_BROAD else '')
        except Exception as ex:
            print('sparql failed', url, ex, flush=True)
    sys.exit('no titles from Wikidata')


def api(params, tries=5):
    params = {**params, 'format': 'json', 'formatversion': 2, 'maxlag': 5}
    for k in range(tries):
        try:
            r = session.get(API, params=params, timeout=60)
            if r.status_code == 200:
                j = r.json()
                if 'error' not in j:
                    return j
            time.sleep(5 * (k + 1))
        except Exception:
            time.sleep(5 * (k + 1))
    return {}


def intros(batch):
    j = api({'action': 'query', 'prop': 'extracts', 'exintro': 1, 'explaintext': 1, 'exlimit': 20,
             'redirects': 1, 'titles': '|'.join(batch)})
    return [(p['title'], p.get('extract', '')) for p in j.get('query', {}).get('pages', []) if p.get('extract')]


def full_text(title):
    j = api({'action': 'query', 'prop': 'extracts', 'explaintext': 1, 'exsectionformat': 'wiki',
             'redirects': 1, 'titles': title})
    pages = j.get('query', {}).get('pages', [])
    return pages[0].get('extract', '') if pages else ''


def sections_from_wikitext_plain(text):
    """explaintext + exsectionformat=wiki gives '== Heading ==' lines."""
    sections, heading, paras, skip = [], '', [], False
    for ln in text.split('\n'):
        s = ln.strip()
        if s.startswith('==') and s.endswith('=='):
            level = len(s) - len(s.lstrip('='))
            name = s.strip('= ').strip()
            if level == 2:
                if paras and not skip:
                    sections.append((heading, paras))
                heading, paras, skip = name, [], name.lower() in SKIP_HEADINGS
            continue
        if s and not skip:
            paras.append(s)
    if paras and not skip:
        sections.append((heading, paras))
    return sections


def main(out, limit):
    os.makedirs(out, exist_ok=True)
    titles, endpoint = titles_from_wikidata()
    if limit:
        titles = titles[:limit]
    batches = [titles[i:i + 20] for i in range(0, len(titles), 20)]
    got = {}
    with ThreadPoolExecutor(3) as ex:
        for n, res in enumerate(ex.map(intros, batches)):
            for t, e in res:
                got[t] = e
            if n % 200 == 0:
                print(f'intros {n}/{len(batches)} batches, {len(got)} pages', flush=True)
    want_full = [t for t, e in got.items() if any(w in e.lower() for w in FULLTEXT_WORDS)]
    print(f'full text for {len(want_full)} articles', flush=True)
    full = {}
    with ThreadPoolExecutor(3) as ex:
        for n, (t, txt) in enumerate(zip(want_full, ex.map(full_text, want_full))):
            if txt:
                full[t] = txt
            if n % 1000 == 0:
                print(f'full {n}/{len(want_full)}', flush=True)

    meta = {'id': 'wiki-plants-fungi', 'name': 'Wikipedia plants & fungi', 'version': time.strftime('%Y-%m'),
            'topic': 'plants',
            'description': 'Wikipedia articles on plants, trees, wildflowers, mushrooms and other fungi that have a common '
                           'English name; full articles for species described as edible, toxic or medicinal.',
            'license': 'CC BY-SA 4.0',
            'credit': 'Text from Wikipedia, the free encyclopedia (Wikipedia contributors). Licensed CC BY-SA 4.0. '
                      'Species list from Wikidata (CC0).',
            'source': f'Wikidata taxa under Plantae/Fungi via {endpoint}; text via the Wikipedia API'}
    out_path = os.path.join(out, 'wiki-plants-fungi.sqlite')
    w = PackWriter(out_path, meta)
    for t, intro in sorted(got.items()):
        url = 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(t.replace(' ', '_'))
        secs = sections_from_wikitext_plain(full[t]) if t in full else [('', intro.split('\n'))]
        w.add(t, url, secs)
    w.close()
    report = [f'titles {len(titles)} from {endpoint}; intros {len(got)}; full {len(full)}']
    report += [f'must-have {t}: {"ok" if t in got else "MISSING"}' for t in MUST_HAVE]
    report += sample_report(out_path, ['death cap', 'cattail edible', 'poison ivy rash', 'morel', 'elderberry', 'stinging nettle'])
    write_manifest('wiki-plants-fungi', out_path, meta, report)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='out')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    main(a.out, a.limit)
