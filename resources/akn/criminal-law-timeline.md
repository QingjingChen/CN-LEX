# Criminal Law: modification timeline, verification and open questions

This note covers the `passiveModifications` of `criminal-law.akn.xml`.

## Modifying acts

| `passiveRef` | Act | Adopted | In force | `textualMod`s |
|---|---|---|---|---|
| amd_1 | NPCSC Decision on punishing crimes of fraudulent purchase, evasion and illegal trading of foreign exchange | 1998-12-29 | 1998-12-29 | 1 |
| amd_2 | Amendment (I) | 1999-12-25 | 1999-12-25 | 16 |
| amd_3 | Amendment II | 2001-08-31 | 2001-08-31 | 1 |
| amd_4 | Amendment III | 2001-12-29 | 2001-12-29 | 11 |
| amd_5 | Amendment IV | 2002-12-28 | 2002-12-28 | 11 |
| amd_6 | Amendment V | 2005-02-28 | 2005-02-28 | 7 |
| amd_7 | Amendment VI | 2006-06-29 | 2006-06-29 | 30 |
| amd_8 | Amendment VII | 2009-02-28 | 2009-02-28 | 26 |
| amd_9 | NPCSC Decision amending certain laws | 2009-08-27 | 2009-08-27 | 2 |
| amd_10 | Amendment VIII | 2011-02-25 | 2011-05-01 | 74 |
| amd_11 | Amendment IX | 2015-08-29 | 2015-11-01 | 102 |
| amd_12 | Amendment X | 2017-11-04 | 2017-11-04 | 2 |
| amd_13 | Amendment XI | 2020-12-26 | 2021-03-01 | 73 |
| amd_14 | Amendment XII | 2023-12-29 | 2024-03-01 | 11 |

The 1998 Decision (amd_1) is **not** listed in the header of the official consolidated text, which lists only the
other 13 acts. Its Art. 1 replaced Art. 190 of the Criminal Law (逃汇罪), and the 2023 text of Art. 190 is the 1998
wording, so it is recorded as a modifying act.

## Verification

The 1997 text with the 14 acts applied in order was compared with the official consolidated text of 2023-12-29:

- all 505 articles exist on both sides, including every 第N条之K; each inserted article has a source act;
- all paragraph divisions match;
- 502 articles are identical; 3 differ by one character each:

| Article | Reconstruction vs official text | Cause |
|---|---|---|
| Art. 187 | 帐 vs 账 | Editorial character normalisation in the consolidated text; no act changes this word. |
| Art. 308-1 | final 。 missing | Transcription slip in the Wikisource text of Amendment IX. |
| Art. 367 | 色 missing (色情) | Transcription slip in the Wikisource text of the 1997 Criminal Law. |

The AKN body follows the official 2023 text. The intermediate consolidated versions on Wikisource were used only as
a secondary check, since they contain transcription and paragraph-split errors of their own.

## Questions for review

1. **Paragraphs no longer in force.** Ten modifications concern a paragraph that a later act removed (e.g. Art. 68(2),
   deleted by Amendment VIII), or a paragraph dropped when an article was replaced as a whole (Arts. 151, 180, 219,
   433). Their `destination` is the article, because the paragraph has no eId in the 2023 expression.
   Should these point to the paragraph in an earlier expression instead (e.g. `…/zho@2009-08-27#art_68__para_2`)?
2. **Whole-article replacement (将第N条修改为：).** This is split into one `substitution` per paragraph that
   changed, plus `insertion`/`repeal` for paragraphs added or dropped. Would you prefer a single `substitution` on the
   article?
3. **Deleted articles.** Art. 199 was deleted by Amendment IX and is kept as `（删去）` in the official text; it is
   encoded as a `repeal` of `art_199`. Is that the convention you use, or should it be an empty article with a status?
4. **Exact words.** These are in `cnlex:words` inside `old`/`new`, because the schema allows only foreign elements
   there. Is there a convention you prefer, e.g. `ref`s to the `ins`/`del` of the amending act?
5. **Periods.** `@period` on each body element is the group of the last act that changed it; earlier versions of
   that element are reachable only through the `textualMod`s. Should we also produce one AKN expression per version
   (15 expressions, 1997–2024)?
