# No Bars Needed AI — Library packs

Offline reference packs for the **No Bars Needed AI** app. Each pack is one SQLite file with a
full-text (FTS5) index. The app downloads a pack only when the user taps **Download** in the
Library tab, then searches it on the phone with no internet and passes the best passages to the
AI model, showing the sources under the answer.

Packs are built by GitHub Actions (`Build library packs` workflow) and published as assets of the
[`packs` release](../../releases/tag/packs), together with `catalog.json`, which the app reads.

## Packs, sources and licenses

| Pack | Source | License |
|---|---|---|
| WikiMed medical encyclopedia | Wikipedia medicine articles (Kiwix `wikipedia_en_medicine_nopic`) | CC BY-SA 4.0, Wikipedia contributors |
| Wikipedia essentials | Lead sections of Wikipedia's most-read articles (Kiwix `wikipedia_en_top_mini`) | CC BY-SA 4.0, Wikipedia contributors |
| Wikipedia science | Kiwix physics, chemistry, molecular & cell biology, astronomy, mathematics, earth-science selections | CC BY-SA 4.0, Wikipedia contributors |
| Army survival & first aid | U.S. Army ATP 3-50.21 *Survival* (2018); TC 4-02.1 *First Aid* | Public domain (U.S. Government work) |
| USDA PLANTS checklist | USDA NRCS PLANTS Database complete checklist | Public domain (U.S. Government work) |
| Wild edible & poisonous plants | U.S. Army FM 3-05.70 *Survival* (2002): plant chapters, Appendices B and C | Public domain (U.S. Government work) |
| Wikipedia plants & fungi | Wikipedia articles on taxa under Plantae/Fungi with English common names (list from Wikidata, CC0) | CC BY-SA 4.0, Wikipedia contributors |
| MedlinePlus health topics | U.S. National Library of Medicine health topics XML | Public domain (U.S. Government work) |
| FDA drug labels | openFDA drug label bulk download (SPL) | Public domain (U.S. Government work) |
| Navigation & emergency preparedness | Army TC 3-25.26 Map Reading & Land Navigation; FEMA *Are You Ready?* | Public domain (U.S. Government work) |
| Wikipedia history / geography | Kiwix `wikipedia_en_history_nopic`, `wikipedia_en_geography_nopic` | CC BY-SA 4.0, Wikipedia contributors |
| Wikivoyage travel guide | Kiwix `wikivoyage_en_all` | CC BY-SA 4.0, Wikivoyage contributors |
| Appropedia (off-grid how-to) | Kiwix `appropedia_en_all` | CC BY-SA 4.0, Appropedia contributors |
| Wikibooks Cookbook | Kiwix `wikibooks_en_all` (Cookbook: pages only) | CC BY-SA 4.0, Wikibooks contributors |

Wikipedia text is reformatted into plain-text passages (tables, images and references removed).
Under CC BY-SA, these packs are shared under the same license; each pack carries its credit line
in its `meta` table, and the app shows it on the Library screen.

Not included on purpose: OpenStax, wikiHow and iFixit (non-commercial licenses), StatPearls (NC-ND), MedlinePlus
drug and encyclopedia pages (licensed from third parties; only NLM-written health topics are used).

## Pack format (version 1)

```sql
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);      -- id, name, version, license, credit, docs, chunks
CREATE TABLE docs(id INTEGER PRIMARY KEY, title TEXT, url TEXT);
CREATE VIRTUAL TABLE chunks USING fts5(title, body, doc UNINDEXED,
  tokenize = 'porter unicode61 remove_diacritics 2');      -- ~700-character passages
```

Search: `SELECT title, body, doc, bm25(chunks, 5.0, 1.0) AS s FROM chunks WHERE chunks MATCH ? ORDER BY s LIMIT 8`.

## Rebuilding

Actions → **Build library packs** → Run workflow. Enter `all` or a comma list of pack ids from
`packs.json`. Each pack uploads `<id>.sqlite`, `<id>.json` and `<id>.report.txt` (a sanity
report with sample searches), then `catalog.json` is regenerated.

> Plant identification note shown in the app: never eat a wild plant or mushroom based on an AI
> answer or a photo match alone.
