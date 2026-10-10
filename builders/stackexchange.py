"""Build a Q&A pack from one or more Stack Exchange sites (Kiwix "stack_exchange" ZIMs, text only).

  python builders/stackexchange.py --id se-cooking --sites cooking.stackexchange.com,coffee.stackexchange.com \
      --name 'Cooking Q&A' --description '...' --queries 'brine;sourdough starter'

Each question becomes one document: the question, then the accepted answer and the best-voted answers
(up to --answers, score >= --min-answer-score). Every passage names its author, and the source link points
to the original question, as Stack Exchange's attribution rules ask. Comments, user and tag pages are skipped.
Content license: CC BY-SA (4.0 for posts since 2018, 3.0 / 2.5 for older ones).
"""
import argparse, os, re, subprocess, sys
from multiprocessing import Pool

import requests
from bs4 import BeautifulSoup
from libzim.reader import Archive

sys.path.insert(0, os.path.dirname(__file__))
from pack import PackWriter, write_manifest, sample_report, clean_ws

KIWIX = 'https://download.kiwix.org/zim/stack_exchange/'
UA = {'User-Agent': 'NoBarsNeededLibraryBuilder/1.0 (https://github.com/claimtothecity/no-bars-needed-library)'}
Q_PATH = re.compile(r'^(?:C/)?questions/(\d+)/[^/]+$')

MAX_ANSWERS = 3
MIN_ANSWER_SCORE = 1
MIN_QUESTION_SCORE = 0
ANSWER_CHARS = 3500   # keep the pack small: long answers are cut (the link has the rest)


def newest(site):
    html = requests.get(KIWIX, headers=UA, timeout=60).text
    pat = re.compile(rf'href="({re.escape(site)}_(?:en|mul)_all_(\d{{4}}-\d{{2}})\.zim)"')
    hits = sorted(((m.group(2), m.group(1)) for m in pat.finditer(html)), reverse=True)
    return hits[0][1] if hits else None


def download(name, work):
    path = os.path.join(work, name)
    if not os.path.exists(path):
        print(f'downloading {name}', flush=True)
        subprocess.run(['curl', '-fL', '--retry', '5', '--retry-delay', '10', '-sS', '-o', path + '.part', KIWIX + name],
                       check=True)
        os.rename(path + '.part', path)
    print(f'{name}: {os.path.getsize(path) / 1e6:.0f} MB', flush=True)
    return path


def prose(el):
    """Paragraphs from a post body (.s-prose); code blocks kept short, images/links reduced to text."""
    out = []
    if el is None:
        return out
    for bad in el.select('img, svg, script, style'):
        bad.decompose()
    for node in el.find_all(['p', 'li', 'pre', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'table'], recursive=True):
        if node.find_parent(['li', 'blockquote', 'pre', 'table']) is not None:
            continue
        if node.name == 'table':
            rows = [' | '.join(clean_ws(c.get_text(' ')) for c in tr.find_all(['th', 'td'])) for tr in node.find_all('tr')]
            text = '\n'.join(r for r in rows if r.strip())[:800]
        elif node.name == 'pre':
            text = node.get_text('\n').strip()
            if len(text) > 500:
                text = text[:500] + ' …'
        else:
            text = clean_ws(node.get_text(' '))
            text = re.sub(r'\s+([,.;:)!?])', r'\1', text)
        if not text:
            continue
        if node.name == 'li':
            text = '• ' + text
        elif node.name == 'blockquote':
            text = '“' + text + '”'
        elif node.name.startswith('h'):
            text = text + ':'
        out.append(text)
    if not out:  # body without block elements
        t = clean_ws(el.get_text(' '))
        if t:
            out.append(t)
    return out


def author(post, verb):
    """Name on the signature card whose time says 'asked …' / 'answered …' (falls back to the last card)."""
    cards = post.select('.s-user-card')
    pick = None
    for c in cards:
        t = c.select_one('.s-user-card--time')
        if t and t.get_text(' ').strip().lower().startswith(verb):
            pick = c
    pick = pick or (cards[-1] if cards else None)
    if pick is None:
        return 'a community member'
    link = pick.select_one('.s-user-card--link') or pick.select_one('.s-user-card--info')
    name = clean_ws(link.get_text(' ')) if link else ''
    return name or 'a community member'


def score(div):
    try:
        return int(div.get('data-score', '0'))
    except ValueError:
        return 0


def cap(paras, limit):
    out, n = [], 0
    for p in paras:
        if n + len(p) > limit:
            rest = limit - n
            if rest > 200:
                out.append(p[:rest].rsplit(' ', 1)[0] + ' …')
            out.append('(Answer shortened; the full text is at the source link.)')
            break
        out.append(p); n += len(p)
    return out


def parse(args):
    site, qid, title, html = args
    try:
        soup = BeautifulSoup(html, 'lxml')
        q = soup.select_one('#question')
        if q is None or score(q) < MIN_QUESTION_SCORE:
            return None
        h1 = soup.select_one('#question-header h1')
        if h1:
            title = clean_ws(h1.get_text(' '))
        title = re.sub(r'\s+-\s+[^-]+Stack Exchange$', '', title)
        answers = []
        for a in soup.select('#answers .answer'):
            accepted = 'accepted-answer' in (a.get('class') or [])
            s = score(a)
            if accepted or s >= MIN_ANSWER_SCORE:
                answers.append((accepted, s, a))
        if not answers:
            return None
        answers.sort(key=lambda x: (not x[0], -x[1]))
        q_paras = prose(q.select_one('.js-post-body') or q.select_one('.s-prose'))
        if q_paras:
            q_paras = cap(q_paras, 2000)
            q_paras.append(f'(Question asked by {author(q, "asked")}; score {score(q)}.)')
        sections = [('Question', q_paras)]
        for accepted, s, a in answers[:MAX_ANSWERS]:
            body = prose(a.select_one('.js-post-body') or a.select_one('.s-prose'))
            if not body:
                continue
            who = author(a, 'answered')
            label = f'{"Accepted answer" if accepted else "Answer"} by {who} (score {s})'
            sections.append((label, cap(body, ANSWER_CHARS)))
        if len(sections) < 2:
            return None
        return site, qid, title, sections
    except Exception:
        return None


def iter_questions(site, zim_path):
    zim = Archive(zim_path)
    for i in range(zim.all_entry_count):
        e = zim._get_entry_by_id(i)
        if e.is_redirect:
            continue
        m = Q_PATH.match(e.path)
        if not m:
            continue
        try:
            item = e.get_item()
        except Exception:
            continue
        if not item.mimetype.startswith('text/html'):
            continue
        yield site, m.group(1), e.title, bytes(item.content).decode('utf-8', 'replace')


def main():
    global MAX_ANSWERS, MIN_ANSWER_SCORE, MIN_QUESTION_SCORE
    ap = argparse.ArgumentParser()
    ap.add_argument('--id', required=True)
    ap.add_argument('--sites', required=True, help='comma list, e.g. cooking.stackexchange.com,coffee.stackexchange.com')
    ap.add_argument('--name', required=True)
    ap.add_argument('--description', required=True)
    ap.add_argument('--topic', default='general')
    ap.add_argument('--queries', default='how to;why does')
    ap.add_argument('--answers', type=int, default=3)
    ap.add_argument('--min-answer-score', type=int, default=1)
    ap.add_argument('--min-question-score', type=int, default=0)
    ap.add_argument('--out', default='out')
    ap.add_argument('--work', default='work')
    args = ap.parse_args()
    MAX_ANSWERS, MIN_ANSWER_SCORE, MIN_QUESTION_SCORE = args.answers, args.min_answer_score, args.min_question_score
    os.makedirs(args.out, exist_ok=True); os.makedirs(args.work, exist_ok=True)

    sites = [s.strip() for s in args.sites.split(',') if s.strip()]
    chosen = []
    report = []
    for s in sites:
        f = newest(s)
        report.append(f'site {s} -> {f}')
        if f:
            chosen.append((s, f))
    if not chosen:
        print('\n'.join(report)); sys.exit('no ZIM found')
    version = max(re.search(r'(\d{4}-\d{2})\.zim$', f).group(1) for _, f in chosen)
    names = ', '.join(s for s, _ in chosen)
    meta = {'id': args.id, 'name': args.name, 'description': args.description, 'version': version, 'topic': args.topic,
            'license': 'CC BY-SA 4.0 (older posts CC BY-SA 3.0 / 2.5)',
            'credit': f'Questions and answers from {names} (Stack Exchange contributors; each answer names its author and '
                      'links to the original question), via Kiwix. Licensed CC BY-SA. Reformatted as plain text; '
                      'comments and long code removed.',
            'source': ', '.join(f for _, f in chosen)}
    out_path = os.path.join(args.out, f'{args.id}.sqlite')
    w = PackWriter(out_path, meta)
    kept = skipped = 0
    for site, f in chosen:
        zim_path = download(f, args.work)
        with Pool(os.cpu_count() or 2) as pool:
            for res in pool.imap_unordered(parse, iter_questions(site, zim_path), chunksize=32):
                if not res:
                    skipped += 1
                    continue
                s, qid, title, sections = res
                if w.add(title, f'https://{s}/questions/{qid}', sections):
                    kept += 1
        os.remove(zim_path)
    report.append(f'questions kept {kept}, skipped (no good answer / low score) {skipped}')
    print(report[-1], flush=True)
    w.close()
    report += sample_report(out_path, args.queries.split(';'))
    write_manifest(args.id, out_path, meta, report)


if __name__ == '__main__':
    main()
