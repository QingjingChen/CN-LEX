#!/usr/bin/env python3
"""Build the Akoma Ntoso 3.0 documents of the Civil Code and the Criminal Law (Python standard library only).

  python tools/build_akn.py            # writes resources/akn/civil-code.akn.xml and criminal-law.akn.xml

Input: the official texts in data/statutes/. Structure: book (编) > part (分编) > chapter (章) > section (节) >
article (条) > paragraph (款) > list/point (项). Supplementary provisions (附则) are a book with eId book_suppl.

eIds follow the URIs already used by the LegalRuleML and RDF resources (lrml:LegalSource/@sameAs):
  第N条 -> art_N,  第N条之K -> art_N_K,  M-th paragraph -> art_N__para_M,  items -> ..._list_1__point_J.
A paragraph is a line of the article; lines starting with an item number (（一）) belong to the preceding paragraph,
which is how the existing paragraph URIs were numbered.
"""
import datetime
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AKN = 'http://docs.oasis-open.org/legaldocml/ns/akn/3.0'
CNLEX = 'https://github.com/QingjingChen/CN-LEX/ns'          # extension namespace for the exact words changed
ET.register_namespace('', AKN)
ET.register_namespace('cnlex', CNLEX)
TIMELINE = ROOT / 'data' / 'statutes' / 'criminal_timeline.json'

CN = '零一二三四五六七八九十百千'
ART = re.compile(rf'^第([{CN}]+)条(?:之([{CN}]+))?　(.*)$')
HEAD = re.compile(rf'^\s*第([{CN}]+)(分编|编|章|节)[\s　]+(.+?)\s*$')
SUPPL = re.compile(r'^\s*附[\s　]*则\s*$')
ITEM_SPLIT = re.compile(r'(?<=[：；。])(?=（[一二三四五六七八九十]+）)')
ITEM_NUM = re.compile(r'^（([一二三四五六七八九十]+)）')
LEVEL = {'编': 1, '分编': 2, '章': 3, '节': 4}
TAG = {'编': 'book', '分编': 'part', '章': 'chapter', '节': 'section'}
ABBR = {'book': 'book', 'part': 'part', 'chapter': 'chp', 'section': 'sec'}

LAWS = {
    'civil': dict(
        source='civil_code_2020-05-28.txt', out='civil-code.akn.xml', title='中华人民共和国民法典',
        work='/akn/cn/act/2020-05-28/civil-code', work_date=('2020-05-28', 'adoption'),
        expression='zho@', expression_date=('2020-05-28', 'adoption'), articles=1260,
        publication=dict(date='2020-05-28', name='presidentialOrder', number='45', showAs='中华人民共和国主席令第四十五号'),
        in_force='2021-01-01'),                                   # Art. 1260
    'criminal': dict(
        source='criminal_law_2023-12-29.txt', out='criminal-law.akn.xml', title='中华人民共和国刑法',
        work='/akn/cn/act/1997-03-14/criminal-law', work_date=('1997-03-14', 'revision'),
        expression='zho@2023-12-29', expression_date=('2023-12-29', 'consolidation'), articles=None,
        publication=None,                                         # order number of the 1997 revision not verified
        in_force='1997-10-01'),                                   # Art. 452
}


AMEND = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日(中华人民共和国刑法修正案(?:（([一二三四五六七八九十]+)）)?|《全国人民代表大会常务委员会关于修改部分法律的决定》)')


def act_uri(step):
    """AKN URI assigned by CN-LEX to an amending act (naming convention; the act itself is not yet in AKN)."""
    t = step['act']
    if '修正案' in t:
        m = re.search(r'（([一二三四五六七八九十]+)）', t)
        name = f'criminal-law-amendment-{cn2int(m.group(1)) if m else 1}'
    elif '外汇' in t:
        name = 'decision-foreign-exchange-crimes'
    else:
        name = 'decision-amending-certain-laws'
    return f"/akn/cn/act/{step['adopted']}/{name}/zho@"


def amendments(preface):
    """Header of the consolidated Criminal Law -> [(date, title, AKN URI of the amending act)]."""
    out = []
    for y, mo, d, title, n in AMEND.findall(' '.join(preface)):
        date = f'{int(y):04d}-{int(mo):02d}-{int(d):02d}'
        if '决定' in title:
            name = 'decision-amending-certain-laws'
        else:
            name = f'criminal-law-amendment-{cn2int(n) if n else 1}'
        out.append((date, title.strip('《》'), f'/akn/cn/act/{date}/{name}/zho@'))
    return out


def cn2int(s):
    d = dict(zip('零一二三四五六七八九', range(10)))
    n, cur = 0, 0
    for ch in s:
        if ch in d:
            cur = d[ch]
        else:
            unit = {'十': 10, '百': 100, '千': 1000}[ch]
            n += (cur or 1) * unit
            cur = 0
    return n + cur


def norm(s):
    return re.sub(r'[\s　]+', '', s)


def parse(text):
    """Text -> (preface lines, tree). Tree nodes: {'kind','num','heading','children'} or {'kind':'article',...}."""
    lines = text.split('\n')
    first = next(i for i, l in enumerate(lines) if ART.match(l))
    start = first
    while start > 0 and (HEAD.match(lines[start - 1]) or not lines[start - 1].strip()):   # headings above Art. 1,
        start -= 1                                                                        # up to the first book;
        h = HEAD.match(lines[start])                                                      # the table of contents
        if h and h.group(2) == '编':                                                      # above it is skipped
            break
    end = next((i for i, l in enumerate(lines) if l.strip() == '附件一'), len(lines))
    preface = [l.strip() for l in lines[:start] if l.strip()]
    toc = preface.index('目　　录') if '目　　录' in preface else len(preface)
    root = {'kind': 'body', 'children': [], 'level': 0}
    stack, art = [root], None
    for l in lines[start:end]:
        if not l.strip():
            continue
        m = ART.match(l)
        h = HEAD.match(l)
        if m:
            key = (cn2int(m.group(1)), cn2int(m.group(2)) if m.group(2) else None)
            art = {'kind': 'article', 'key': key, 'num': f'第{m.group(1)}条' + (f'之{m.group(2)}' if m.group(2) else ''),
                   'lines': [m.group(3).strip()]}
            stack[-1]['children'].append(art)
        elif h:
            lvl = LEVEL[h.group(2)]
            while stack[-1]['level'] >= lvl:
                stack.pop()
            node = {'kind': TAG[h.group(2)], 'n': cn2int(h.group(1)), 'num': f'第{h.group(1)}{h.group(2)}',
                    'heading': norm(h.group(3)), 'children': [], 'level': lvl}
            stack[-1]['children'].append(node)
            stack.append(node)
            art = None
        elif SUPPL.match(l):
            while len(stack) > 1:
                stack.pop()
            node = {'kind': 'book', 'n': 'suppl', 'num': None, 'heading': '附则', 'children': [], 'level': 1}
            root['children'].append(node)
            stack.append(node)
            art = None
        elif art is not None:
            art['lines'].append(l.strip())
        else:
            raise ValueError(f'text outside an article: {l[:40]}')
    return preface[:toc], root


def paragraphs(lines):
    paras = []
    for l in lines:
        if ITEM_NUM.match(l) and paras:
            paras[-1] += l
        else:
            paras.append(l)
    return paras


def sub(parent, tag, text=None, **attrs):
    e = ET.SubElement(parent, f'{{{AKN}}}{tag}', {k.replace('_', ''): v for k, v in attrs.items()})
    if text is not None:
        e.text = text
    return e


def p_block(parent, tag, text):
    sub(sub(parent, tag), 'p', text)


def emit_article(parent, a):
    n, k = a['key']
    aid = f'art_{n}' + (f'_{k}' if k else '')
    art = sub(parent, 'article', eId=aid)
    sub(art, 'num', a['num'])
    for i, para in enumerate(paragraphs(a['lines']), 1):
        pid = f'{aid}__para_{i}'
        pe = sub(art, 'paragraph', eId=pid)
        parts = [x for x in ITEM_SPLIT.split(para) if x]
        items = [x for x in parts if ITEM_NUM.match(x)]
        if not items:
            p_block(pe, 'content', para)
            continue
        lst = sub(pe, 'list', eId=f'{pid}__list_1')
        if not ITEM_NUM.match(parts[0]):
            p_block(lst, 'intro', parts[0])
        for j, it in enumerate(items, 1):
            m = ITEM_NUM.match(it)
            pt = sub(lst, 'point', eId=f'{pid}__list_1__point_{j}')
            sub(pt, 'num', m.group(0))
            p_block(pt, 'content', it[m.end():])


def emit_container(parent, node, prefix=''):
    eid = (f'{prefix}__' if prefix else '') + f'{ABBR[node["kind"]]}_{node["n"]}'
    c = sub(parent, node['kind'], eId=eid)
    if node['num']:
        sub(c, 'num', node['num'])
    sub(c, 'heading', node['heading'])
    for ch in node['children']:
        if ch['kind'] == 'article':
            emit_article(c, ch)
        else:
            emit_container(c, ch, eid)


def build(law, today):
    cfg = LAWS[law]
    preface, tree = parse((ROOT / 'data' / 'statutes' / cfg['source']).read_text(encoding='utf-8'))
    doc = ET.Element(f'{{{AKN}}}akomaNtoso')
    act = sub(doc, 'act', name=cfg['work'].rsplit('/', 1)[-1])
    meta = sub(act, 'meta')
    ident = sub(meta, 'identification', source='#cnlex')
    work, expr = cfg['work'], f"{cfg['work']}/{cfg['expression']}"
    w = sub(ident, 'FRBRWork')
    sub(w, 'FRBRthis', value=f'{work}/!main')
    sub(w, 'FRBRuri', value=work)
    sub(w, 'FRBRdate', date=cfg['work_date'][0], name=cfg['work_date'][1])
    sub(w, 'FRBRauthor', href='#npc')
    sub(w, 'FRBRcountry', value='cn')
    sub(w, 'FRBRname', value=cfg['title'])
    e = sub(ident, 'FRBRExpression')
    sub(e, 'FRBRthis', value=f'{expr}/!main')
    sub(e, 'FRBRuri', value=expr)
    sub(e, 'FRBRdate', date=cfg['expression_date'][0], name=cfg['expression_date'][1])
    sub(e, 'FRBRauthor', href='#npc')
    sub(e, 'FRBRlanguage', language='zho')
    m = sub(ident, 'FRBRManifestation')
    sub(m, 'FRBRthis', value=f'{expr}/!main.xml')
    sub(m, 'FRBRuri', value=f'{expr}.akn')
    sub(m, 'FRBRdate', date=today, name='generation')
    sub(m, 'FRBRauthor', href='#cnlex')
    if cfg['publication']:
        sub(meta, 'publication', **cfg['publication'])
    steps = json.loads(TIMELINE.read_text(encoding='utf-8'))['steps'] if law == 'criminal' and TIMELINE.exists() else []
    life = sub(meta, 'lifecycle', source='#cnlex')
    sub(life, 'eventRef', eId='evt_1', date=cfg['work_date'][0], source='#original', type='generation')
    sub(life, 'eventRef', eId='evt_2', date=cfg['in_force'], source='#original', type='generation')
    groups = [('tg_1', 'evt_2')]
    n_evt = 2
    for i, st in enumerate(steps, 1):
        n_evt += 1
        sub(life, 'eventRef', eId=f'evt_{n_evt}', date=st['adopted'], source=f'#amd_{i}', type='amendment')
        if st['in_force'] and st['in_force'] != st['adopted']:
            n_evt += 1
            sub(life, 'eventRef', eId=f'evt_{n_evt}', date=st['in_force'], source=f'#amd_{i}', type='amendment')
        groups.append((f'tg_{i + 1}', f'evt_{n_evt}'))
    if steps:
        analysis = sub(meta, 'analysis', source='#cnlex')
        pmods = sub(analysis, 'passiveModifications')
        k = 0
        for i, st in enumerate(steps, 1):
            for r in st['modifications']:
                k += 1
                dest = r['destination'] or ('art_' + r['article'].replace('-', '_'))
                tm = sub(pmods, 'textualMod', eId=f'pmod_{k}', type=r['type'])
                sub(tm, 'source', href=f'#amd_{i}')
                sub(tm, 'destination', href=f'#{dest}')
                sub(tm, 'force', period=f'#tg_{i + 1}')
                if r['type'] == 'substitution' and len(r['words']) <= 3:
                    # short changes: the exact words, paired old/new by @n
                    pairs = [(str(n), w['old'], w['new']) for n, w in enumerate(r['words'], 1)]
                else:
                    # insertions, repeals and extensive rewrites: the whole paragraph (or article) text
                    pairs = [('1', r['old'] if r['type'] != 'insertion' else '',
                              r['new'] if r['type'] != 'repeal' else '')]
                for tag, pos in (('old', 1), ('new', 2)):
                    if any(pr[pos] for pr in pairs):
                        holder = sub(tm, tag)
                        for pr in pairs:
                            if pr[pos]:
                                w = ET.SubElement(holder, f'{{{CNLEX}}}words', n=pr[0])
                                w.text = pr[pos]
    temp = sub(meta, 'temporalData', source='#cnlex')
    for gid, evt in groups:
        sub(sub(temp, 'temporalGroup', eId=gid), 'timeInterval', start=f'#{evt}', refersTo='#inForce')
    refs = sub(meta, 'references', source='#cnlex')
    sub(refs, 'original', eId='original', href=work + '/' + ('zho@' if law == 'civil' else f"zho@{cfg['work_date'][0]}"),
        showAs=cfg['title'])
    for i, st in enumerate(steps, 1):
        sub(refs, 'passiveRef', eId=f'amd_{i}', href=act_uri(st), showAs=st['act'])
    sub(refs, 'TLCOrganization', eId='npc', href='/ontology/organization/cn/npc', showAs="National People's Congress")
    if steps:
        sub(refs, 'TLCOrganization', eId='npcsc', href='/ontology/organization/cn/npcsc',
            showAs="Standing Committee of the National People's Congress")
    sub(refs, 'TLCOrganization', eId='cnlex', href='/ontology/organization/cnlex', showAs='CN-LEX')
    sub(refs, 'TLCConcept', eId='inForce', href='/ontology/concept/inForce', showAs='in force')
    pre = sub(act, 'preface')
    t = sub(pre, 'p', **{'class': 'title'})
    sub(t, 'docTitle', cfg['title'])
    for line in preface[1:]:
        sub(pre, 'p', line)
    body = sub(act, 'body')
    for node in tree['children']:
        if node['kind'] == 'article':
            emit_article(body, node)
        else:
            emit_container(body, node)
    if steps:
        by_eid = {e.get('eId'): e for e in doc.iter() if e.get('eId')}
        latest = {}
        for i, st in enumerate(steps, 1):
            for r in st['modifications']:
                if r['destination'] and r['type'] != 'repeal':
                    latest[r['destination']] = i
                    if r['type'] == 'insertion' and r['destination'].endswith('__para_1'):
                        latest.setdefault('art_' + r['article'].replace('-', '_'), i)
        for eid, i in latest.items():
            if eid in by_eid:
                by_eid[eid].set('period', f'#tg_{i + 1}')
    n_art = len(list(doc.iter(f'{{{AKN}}}article')))
    if cfg['articles'] is not None and n_art != cfg['articles']:
        raise ValueError(f'{law}: {n_art} articles, expected {cfg["articles"]}')
    ET.indent(doc, space=' ')
    out = ROOT / 'resources' / 'akn' / cfg['out']
    out.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(doc).write(out, encoding='UTF-8', xml_declaration=True)
    return out, n_art


def main():
    today = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().isoformat()
    for law in LAWS:
        out, n = build(law, today)
        print(f'{out.relative_to(ROOT)}: {n} articles')


if __name__ == '__main__':
    main()
