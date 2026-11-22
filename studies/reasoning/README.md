# Study III: item 526, end to end (Sect. 6)

LawExamQA item 526 (adapted from the 2017 bar examination, Paper III, Q. 2); gold answer B.

**LEGO** (Qwen3-8B reader, temperature 0) retrieves Arts. 19, 145, 144, 20, 18, 22, 21, 24 and answers **C**:
it applies the pure-benefit branch of Art. 145 to a seven-year-old (Art. 20 and Art. 144 make the act void), voids the
piano gift although Art. 145 requires only one of "purely beneficial" or "age-appropriate", and treats Xiao Te as fully
capable at 15 (Art. 18(2) applies from 16).

**CN-LEX rules**: `reasoning/cases/q526.json` gives the structured facts for each option and the expected conclusions.

```sh
sh engine/fetch_ddl.sh                                   # once
python tools/run_cases.py reasoning/cases/q526.json -v   # derivations for options A-D
```

**From text** (three development runs of a prototype that extracts facts with an LLM): the binding of the harmonica
to Xiao Te at 7 was lost; final answers B, A, B, with no complete proof of Art. 144.
