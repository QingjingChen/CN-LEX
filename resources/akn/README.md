# Akoma Ntoso documents of the Chinese Civil Code and Criminal Law

| File | Work / Expression | Content |
|---|---|---|
| `civil-code.akn.xml` | `/akn/cn/act/2020-05-28/civil-code` / `zho@` (original version) | 7 books + supplementary provisions, 8 parts, 84 chapters, 37 sections, 1,260 articles, 1,752 paragraphs, 374 items |
| `criminal-law.akn.xml` | `/akn/cn/act/1997-03-14/criminal-law` / `zho@2023-12-29` (consolidated after Amendment XII) | 2 books + supplementary provisions, 15 chapters, 37 sections, 505 articles (incl. 第N条之K), 898 paragraphs, 263 items |

Both validate against the OASIS Akoma Ntoso 3.0 schema (`../schema/akn/akomantoso30.xsd`, OASIS Standard, 29 August 2018):

```sh
xmllint --noout --schema ../schema/akn/akomantoso30.xsd civil-code.akn.xml
```

## Mapping

| Chinese unit | Akoma Ntoso | eId |
|---|---|---|
| 编 (book) | `book` | `book_7` |
| 分编 (part of a book) | `part` | `book_2__part_4` |
| 章 (chapter) | `chapter` | `book_7__chp_3` |
| 节 (section) | `section` | `book_1__chp_2__sec_1` |
| 附则 (supplementary provisions) | `book` | `book_suppl` |
| 条 / 第N条之K (article) | `article` | `art_1199`, `art_17_1` |
| 款 (paragraph, unnumbered in Chinese statutes) | `paragraph` | `art_1199__para_1` |
| 项 (item) | `list` / `point` | `art_143__para_1__list_1__point_2` |

Article and paragraph eIds are the fragments of the URIs by which the LegalRuleML rules and the RDF graph cite their
sources (`lrml:LegalSource/@sameAs`); all 5,968 such URIs resolve to an element of these documents.

## Metadata

- `identification`: FRBR Work, Expression (language `zho`) and Manifestation; author `#npc`.
- `publication` (Civil Code): Presidential Order No. 45, 2020-05-28.
- `lifecycle`: adoption and entry into force (Civil Code 2021-01-01, Art. 1260; Criminal Law 1997-10-01, Art. 452).
  For the Criminal Law, one event per modifying act and a second event where the act entered into force later than
  it was adopted (Amendments VIII, IX, XI, XII): 14 modifying acts, 20 events.
- `analysis/passiveModifications` (Criminal Law): 367 `textualMod`s (193 substitution, 165 insertion, 9 repeal), each
  with the modifying act (`source` → `passiveRef`), the provision changed (`destination`, the paragraph or item where
  it still exists) and the period from which the change applies (`force/@period` → `temporalGroup`).
- `temporalData`: `tg_1` = original text in force from 1997-10-01; `tg_k+1` = in force from the entry into force of
  the k-th modifying act. Every modified article, paragraph and item carries `@period` = the group of the last act
  that changed it, so the version of each provision can be dated.
- `references`: the original act and the 14 modifying acts (`passiveRef amd_1` … `amd_14`).

### Exact words changed

`textualMod/old` and `new` may only contain elements of another namespace (`anyOtherType`). The words are therefore
carried in a CN-LEX extension element, `cnlex:words` (`xmlns:cnlex="https://github.com/QingjingChen/CN-LEX/ns"`):

```xml
<textualMod eId="pmod_104" type="substitution">
  <source href="#amd_9"/>                     <!-- 2009 NPCSC decision amending certain laws -->
  <destination href="#art_381__para_1"/>
  <force period="#tg_10"/>
  <new><cnlex:words n="1">征收、</cnlex:words></new>   <!-- 征用 → 征收、征用 -->
</textualMod>
```

For substitutions with at most three changed spans, `old`/`new` hold those spans, paired by `@n`. For insertions,
repeals and extensive rewrites, they hold the whole paragraph text.

### How the modifications were derived and checked

`tools/akn_timeline.py` starts from the 1997 text, applies the modifying acts in order, parses each instruction
(增加…作为第N条之K, 将第N条第M款修改为, 中的“x”修改为“y”, 删去…), and writes `data/statutes/criminal_timeline.json`.
No instruction needed manual handling. The reconstructed text was compared with the official consolidated text of
2023-12-29 (`data/statutes/criminal_law_2023-12-29.txt`). All 505 articles and paragraph divisions match, and three
articles differ by one character each. See `criminal-law-timeline.md` for these differences and the open modelling
questions. The texts of the acts (zh.wikisource.org) are listed with hashes in
`data/statutes/criminal_versions/sources.json`.

## Known limitations

- No `publication` for the Criminal Law: the promulgation order of the 1997 revision has not been verified.
- The modifying acts are taken from Wikisource transcriptions, not from the official gazette; they are checked only
  through the reconstruction above.
- The URIs of the modifying acts are assigned by CN-LEX following the Akoma Ntoso naming convention; these acts are
  not yet available as Akoma Ntoso documents, so `activeModifications` are not encoded. Judicial interpretations and
  guiding cases are not yet encoded.
- The Civil Code has not been amended; its repeal of nine laws (Art. 1260) is not yet encoded as `activeModifications`.
- `eId`s only; `wId`s are not assigned. Text is Chinese only.

Rebuild with `python tools/akn_timeline.py` (timeline) and then `python tools/build_akn.py` (documents).
