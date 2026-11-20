#!/usr/bin/env python3
"""Validate packaged LRML without private upstream drafts or relation JSON."""
import collections
import json
from pathlib import Path
from lxml import etree as E
from review_lrml_reader import ReviewLRML, L


def main():
    here = Path(__file__).resolve().parent
    schema = E.XMLSchema(E.parse(str(here.parent.parent / 'civil_graph/schema/lrml-compact.xsd')))
    result = []
    for law in ('civil', 'criminal'):
        path = here.parent / 'lrml' / f'{law}_review.lrml'
        tree = E.parse(str(path))
        schema.assertValid(tree)
        keys = [e.get('key') for e in tree.getroot().iter() if e.get('key')]
        assert len(keys) == len(set(keys))
        keyset = set(keys)
        for e in tree.getroot().iter():
            for a in ('keyref', 'over', 'under'):
                if e.get(a, '').startswith('#'):
                    assert e.get(a)[1:] in keyset
        doc = ReviewLRML(path)
        counts = collections.Counter(r['type'] for r in doc.iter_relations(False))
        result.append({'law': law, 'rules': len(doc.rules), 'relations': dict(counts),
                       'xsd_valid': True, 'references_valid': True,
                       'review_status': doc.document['review_status']})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
