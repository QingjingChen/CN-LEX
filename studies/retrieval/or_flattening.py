"""How much logical form survives verbalisation? Compares each civil rule's LegalRuleML body with the
text the retriever encodes (verbalised_rules.jsonl). Reported in Sect. 5 of the paper."""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
lrml = (HERE.parents[1] / 'resources' / 'civil' / 'civil_review.lrml').read_text(encoding='utf-8')
body = {m.group(1): m.group(2).split('<ruleml:then>')[0] for m in re.finditer(
    r'<lrml:(?:Constitutive|Prescriptive)Statement key="([^"]+)">(.*?)</lrml:(?:Constitutive|Prescriptive)Statement>', lrml, re.S)}
rules = [json.loads(l) for l in open(HERE / 'verbalised_rules.jsonl', encoding='utf-8')]

disj = [r for r in rules if '<ruleml:Or' in body.get(r['id'], '')]
lost = [r for r in disj if not re.search(r'或|之一', r['text'].split('；则')[0])]
naf = [r for r in rules if '<ruleml:Naf' in body.get(r['id'], '')]
print(f'{len(rules)} verbalised rules')
print(f'Or in LegalRuleML: {len(disj)}; verbalised without any word for "or": {len(lost)} '
      f'({len(lost) / len(disj):.1%}, {len({r["article"] for r in lost})} articles)')
print(f'Naf in LegalRuleML: {len(naf)}; rendered as 除非: {sum("除非" in r["text"] for r in naf)}')
print('example c145-pure:', next(r['text'] for r in rules if r['id'] == 'c145-pure'))
