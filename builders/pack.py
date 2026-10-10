"""Shared pack writer for No Bars Needed AI library packs.

A pack is a single SQLite file the app downloads and searches offline:
  meta(key, value)                         pack name, version, license, credit ...
  docs(id INTEGER PRIMARY KEY, title, url) one row per source article/section
  chunks  (FTS5: title, body, doc)         ~700-character passages, keyword-searchable
"""
import json, os, re, sqlite3, time

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE docs(id INTEGER PRIMARY KEY, title TEXT NOT NULL, url TEXT);
CREATE VIRTUAL TABLE chunks USING fts5(
  title, body, doc UNINDEXED,
  tokenize = 'porter unicode61 remove_diacritics 2'
);
"""

TARGET = 700   # aim for ~700 characters per chunk
HARD_MAX = 1100


def clean_ws(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()


def chunk_paragraphs(paragraphs, target=TARGET, hard_max=HARD_MAX):
    """Greedy-pack paragraphs into ~target-sized chunks; split long ones on sentences."""
    out, cur = [], ''
    for p in paragraphs:
        p = clean_ws(p)
        if not p:
            continue
        pieces = [p]
        if len(p) > hard_max:
            sents = re.split(r'(?<=[.!?])\s+', p)
            pieces, buf = [], ''
            for s in sents:
                if buf and len(buf) + len(s) + 1 > target:
                    pieces.append(buf); buf = s
                else:
                    buf = f'{buf} {s}'.strip()
            if buf:
                pieces.append(buf)
        for piece in pieces:
            if cur and len(cur) + len(piece) + 1 > target:
                out.append(cur); cur = piece
            else:
                cur = f'{cur}\n{piece}'.strip()
    if cur:
        out.append(cur)
    # hard-cut anything still too long (e.g. one giant sentence)
    final = []
    for c in out:
        while len(c) > hard_max * 2:
            final.append(c[:hard_max]); c = c[hard_max:]
        final.append(c)
    return final


class PackWriter:
    def __init__(self, path, meta: dict):
        if os.path.exists(path):
            os.remove(path)
        self.path = path
        self.meta = dict(meta)
        self.db = sqlite3.connect(path)
        self.db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;' + SCHEMA)
        self.docs = 0
        self.chunks = 0
        self.chars = 0
        self.started = time.time()

    def add(self, title, url, sections):
        """sections: list of (section_heading or '', [paragraphs])"""
        rows = []
        for heading, paras in sections:
            label = f'{title} — {heading}' if heading else title
            for body in chunk_paragraphs(paras):
                if len(body) < 40:
                    continue
                rows.append((label, body))
        if not rows:
            return False
        cur = self.db.execute('INSERT INTO docs(title, url) VALUES(?, ?)', (title, url))
        doc_id = cur.lastrowid
        self.db.executemany('INSERT INTO chunks(title, body, doc) VALUES(?, ?, ?)',
                            [(t, b, doc_id) for t, b in rows])
        self.docs += 1
        self.chunks += len(rows)
        self.chars += sum(len(b) for _, b in rows)
        if self.docs % 5000 == 0:
            self.db.commit()
            print(f'  {self.docs} docs, {self.chunks} chunks, {time.time() - self.started:.0f}s', flush=True)
        return True

    def close(self):
        if self.docs == 0:
            self.db.close(); os.remove(self.path)
            raise SystemExit('pack is empty - refusing to publish it')
        self.meta.update({'docs': str(self.docs), 'chunks': str(self.chunks),
                          'built': time.strftime('%Y-%m-%d'), 'format': '1'})
        self.db.executemany('INSERT INTO meta VALUES(?, ?)', [(k, str(v)) for k, v in self.meta.items()])
        self.db.commit()
        self.db.execute("INSERT INTO chunks(chunks) VALUES('optimize')")
        self.db.commit()
        self.db.execute('VACUUM')
        self.db.close()
        size = os.path.getsize(self.path)
        if size > 1_950_000_000:  # GitHub release assets must be under 2 GiB; don't publish a manifest for a file that can't upload
            raise SystemExit(f'pack is {size / 1e9:.2f} GB - over the 2 GB release limit; build it smaller (e.g. --max-article-chars)')
        print(f'done: {self.docs} docs, {self.chunks} chunks, {self.chars / 1e6:.1f} M chars, '
              f'{size / 1e6:.1f} MB in {time.time() - self.started:.0f}s')
        return size


def write_manifest(pack_id, sqlite_path, meta, report_lines):
    """Writes <id>.json (catalog entry) and <id>.report.txt next to the pack."""
    import hashlib
    h = hashlib.sha256()
    with open(sqlite_path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    entry = {
        'id': pack_id,
        'file': os.path.basename(sqlite_path),
        'bytes': os.path.getsize(sqlite_path),
        'sha256': h.hexdigest(),
        **{k: meta[k] for k in ('name', 'description', 'version', 'license', 'credit', 'source', 'topic') if k in meta},
    }
    base = os.path.splitext(sqlite_path)[0]
    with open(base + '.json', 'w') as f:
        json.dump(entry, f, indent=2)
    with open(base + '.report.txt', 'w') as f:
        f.write('\n'.join(report_lines) + '\n')
    print(json.dumps(entry, indent=2))


def sample_report(sqlite_path, queries):
    """Quick sanity check: run a few searches and show the top hits."""
    db = sqlite3.connect(sqlite_path)
    lines = []
    for k, v in db.execute('SELECT key, value FROM meta'):
        lines.append(f'meta {k} = {v}')
    for q in queries:
        lines.append(f'\n## query: {q}')
        match = ' OR '.join(f'"{w}"' for w in q.split())
        for title, body, score in db.execute(
                'SELECT title, body, bm25(chunks, 5.0, 1.0) s FROM chunks WHERE chunks MATCH ? ORDER BY s LIMIT 3',
                (match,)):
            lines.append(f'- [{score:.1f}] {title}: {body[:220]!r}')
    titles = [t for (t,) in db.execute('SELECT title FROM docs ORDER BY random() LIMIT 40')]
    lines.append('\n## random doc titles')
    lines += [f'- {t}' for t in titles]
    db.close()
    return lines
