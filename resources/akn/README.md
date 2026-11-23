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
- `lifecycle`: adoption and entry into force (Civil Code 2021-01-01, Art. 1260; Criminal Law 1997-10-01, Art. 452);
  for the Criminal Law, the 13 amending acts listed in the header of the consolidated text, as `passiveRef`s.
- `temporalData`: the in-force interval.

## Known limitations

- No `publication` for the Criminal Law: the promulgation order of the 1997 revision has not been verified.
- Amendments are recorded as lifecycle events only; their `textualMod`s (which provisions each amendment changed)
  and their own dates of entry into force are not yet encoded in `analysis`.
- The URIs of the amending acts are assigned by CN-LEX following the Akoma Ntoso naming convention; these acts are
  not yet available as Akoma Ntoso documents. Judicial interpretations and guiding cases are not yet encoded.
- `eId`s only; `wId`s are not assigned. Text is Chinese only.

Rebuild from the official texts in `data/statutes/` with `python tools/build_akn.py`.
