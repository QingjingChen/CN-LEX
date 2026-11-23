#!/usr/bin/env python3
"""Modification timeline of the Criminal Law (Python standard library only).

Reconstructs every version of the Criminal Law from the 1997 text by applying the thirteen amending acts in order,
checks each reconstructed version word by word against the published consolidated text of that step, and writes
data/statutes/criminal_timeline.json: for every modification its amending act, type, destination (eId), the words
changed (old/new) and the dates of adoption and entry into force. Clauses that are not parsed automatically are
listed for manual review.

  python tools/akn_timeline.py            # writes data/statutes/criminal_timeline.json and prints a report

Sources: data/statutes/criminal_versions/*.wiki (Wikisource wikitext, see sources.json), checked against the
official consolidated text data/statutes/criminal_law_2023-12-29.txt.
"""
import difflib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'data' / 'statutes' / 'criminal_versions'
OUT = ROOT / 'data' / 'statutes' / 'criminal_timeline.json'
CN = '零一二三四五六七八九十百千两'

# amending act -> consolidated version published after it (Wikisource page names)
STEPS = [
    ('全国人民代表大会常务委员会关于惩治骗购外汇、逃汇和非法买卖外汇犯罪的决定', '中华人民共和国刑法_1998年'),
    ('中华人民共和国刑法修正案', '中华人民共和国刑法_1999年'),
    ('中华人民共和国刑法修正案（二）', '中华人民共和国刑法_2001年8月'),
    ('中华人民共和国刑法修正案（三）', '中华人民共和国刑法_2001年12月'),
    ('中华人民共和国刑法修正案（四）', '中华人民共和国刑法_2002年'),
    ('中华人民共和国刑法修正案（五）', '中华人民共和国刑法_2005年'),
    ('中华人民共和国刑法修正案（六）', '中华人民共和国刑法_2006年'),
    ('中华人民共和国刑法修正案（七）', '中华人民共和国刑法_2009年2月'),
    ('全国人民代表大会常务委员会关于修改部分法律的决定', '中华人民共和国刑法_2009年8月'),
    ('中华人民共和国刑法修正案（八）', '中华人民共和国刑法_2011年'),
    ('中华人民共和国刑法修正案（九）', '中华人民共和国刑法_2015年'),
    ('中华人民共和国刑法修正案（十）', '中华人民共和国刑法_2017年'),
    ('中华人民共和国刑法修正案（十一）', '中华人民共和国刑法_2020年'),
    ('中华人民共和国刑法修正案（十二）', '中华人民共和国刑法_2023年'),
]
BASE = '中华人民共和国刑法_1997年'


def cn2int(s):
    d = dict(zip('零一二三四五六七八九', range(10)))
    d['两'] = 2
    n, cur = 0, 0
    for ch in s:
        if ch in d:
            cur = d[ch]
        else:
            n += (cur or 1) * {'十': 10, '百': 100, '千': 1000}[ch]
            cur = 0
    return n + cur


def clean(s):
    s = re.sub(r"\{\{gap\}\}|<span[^>]*>|</span>|'''", '', s)
    s = re.sub(r'\[\[(?:[^]|]*\|)?([^]]*)\]\]', r'\1', s)
    s = re.sub(r'<ref[^>]*>.*?</ref>|<ref[^>]*/>|<[^>]+>|\{\{[^}]*\}\}', '', s)
    s = s.replace(',', '，').replace(';', '；').replace(':', '：')
    return s.strip()


ART = re.compile(rf'^第([{CN}]+)条(?:之([{CN}]+))?[\s　]*(.*)$')
ITEM = re.compile(r'^（([一二三四五六七八九十]+)）')
HEADING = re.compile(rf'^(第[{CN}]+(分编|编|章|节)[\s　]|附[\s　]*则$|附件)')


def key_of(n, k=None):
    return f'{n}' + (f'-{k}' if k else '')


def eid_of(key):
    n, _, k = key.partition('-')
    return f'art_{n}' + (f'_{k}' if k else '')


def parse_version(wiki):
    """Consolidated wikitext -> {article key: [paragraph, ...]} (items merged into their paragraph)."""
    arts, cur = {}, None
    for raw in wiki.split('\n'):
        if raw.startswith('=') or raw.startswith('{{header') or raw.startswith('|'):
            cur = None if raw.startswith('=') else cur
            continue
        line = clean(raw)
        if not line:
            continue
        if HEADING.match(line):
            cur = None
            continue
        m = ART.match(line)
        if m and m.group(3):
            k = key_of(cn2int(m.group(1)), cn2int(m.group(2)) if m.group(2) else None)
            cur = arts[k] = [m.group(3)]
        elif cur is not None:
            if ITEM.match(line) and cur:
                cur[-1] += line
            else:
                cur.append(line)
    return arts


def norm(s):
    return re.sub(r'[\s　]', '', s)


# ---------------------------------------------------------------- amending acts
def act_meta(wiki):
    head = re.search(r'(?:\by|year|年) *= *(\d+) *\| *(?:m|month|月) *= *(\d+) *\| *(?:d|day|日) *= *(\d+)', wiki)
    adopted = f'{int(head.group(1)):04d}-{int(head.group(2)):02d}-{int(head.group(3)):02d}' if head else None
    notes = clean((re.search(r'\| *notes *= *(.*)', wiki) or [None, ''])[1])
    order = re.search(r'主席令第([' + CN + r']+)号', notes)
    body = '\n'.join(clean(l) for l in wiki.split('\n') if not l.startswith('|') and not l.startswith('{{header'))
    force = re.search(r'自(\d{4})年(\d{1,2})月(\d{1,2})日起施行', notes + body)
    if force:
        in_force = f'{int(force.group(1)):04d}-{int(force.group(2)):02d}-{int(force.group(3)):02d}'
    elif '自公布之日起施行' in notes + body:
        in_force = adopted
    else:
        in_force = None
    return dict(adopted=adopted, in_force=in_force, order=cn2int(order.group(1)) if order else None, notes=notes)


def clauses(wiki, criminal_only=False):
    """Body of an amending act -> list of clause texts (head + quoted new text, line breaks kept)."""
    lines = [clean(l) for l in wiki.split('\n') if not l.startswith('|') and not l.startswith('{{header')]
    lines = [l for l in lines if l]
    out, cur = [], None
    for l in lines:
        starts = re.match(rf'^[{CN}]+、', l) or ('刑法第' in l and not l.startswith('“'))
        if l.startswith('本修正案自') or l.startswith('本决定自'):
            break
        if starts and ('刑法' in l or not criminal_only):
            if cur:
                out.append(cur)
            cur = l
        elif cur is not None and (l.startswith('“') or cur.count('“') > cur.count('”') or not starts):
            cur += '\n' + l
    if cur:
        out.append(cur)
    return out


def decision_clauses(wiki):
    """2009 NPCSC decision: word substitutions announced in a heading and applied to listed Criminal Law articles."""
    out, rule = [], None
    for raw in wiki.split('\n'):
        line = clean(raw.strip('= '))
        h = re.search(r'将下列法律[^“]*中的“([^”]+)”修改为“([^”]+)”', line)
        if raw.startswith('='):
            rule = (h.group(1), h.group(2)) if h else None
            continue
        if rule and '中华人民共和国刑法》' in line and '解释' not in line:
            for art in re.findall(rf'第([{CN}]+)条', line):
                out.append(f'将刑法第{art}条中的“{rule[0]}”修改为“{rule[1]}”')
    return out


def quoted(clause):
    """New text after '：“' up to the last '”' -> list of paragraphs."""
    m = re.search(r'：\s*“', clause)
    if not m:
        return None
    body = clause[m.end(): clause.rfind('”')]
    paras = []
    for l in body.split('\n'):
        l = l.strip().strip('“”').strip()
        if not l:
            continue
        if ITEM.match(l) and paras:
            paras[-1] += l
        else:
            paras.append(l)
    return paras


A = rf'第([{CN}]+)条(?:之([{CN}]+))?'
NUM = rf'[{CN}]+'
_ids = [0]


def para(text):
    """A paragraph with a stable identity, so that it can be followed through later renumbering."""
    _ids[0] += 1
    return {'id': _ids[0], 'text': text}


def segments(clause):
    """Clause -> [(instruction, [new paragraphs] or None)]; one instruction per line outside quotations."""
    segs, cur = [], None
    for line in clause.split('\n'):
        line = line.strip()
        if cur is not None and cur[1] is not None and not cur[2]:          # inside an open quotation
            body = line.lstrip('“')
            if '”' in body and not body.endswith('”'):
                cut = body.rfind('”')
                cur[1].append(body[:cut])
                cur[2] = True
                line = body[cut + 1:].strip()
                if not line:
                    continue
            else:
                cur[1].append(body.rstrip('”'))
                cur[2] = line.endswith('”')
                continue
        m = re.search(r'：\s*“', line)
        if not m and line.endswith('：') and re.search(r'修改为|增加|作为', line):
            cur = [line[:-1], [], False]                                     # quotation starts on the next line
            segs.append(cur)
            continue
        if m:
            body = line[m.end():]
            if '”' in body and not body.endswith('”'):                     # quotation closes mid-line
                cut = body.rfind('”')
                segs.append([line[:m.start()], [body[:cut]], True])
                rest = body[cut + 1:].strip()
                cur = [rest, None, True]
                if rest:
                    segs.append(cur)
                continue
            cur = [line[:m.start()], [body.rstrip('”')], body.endswith('”')]
        elif re.search(r'修改为：', line) and '“' not in line.split('修改为：', 1)[1][:1]:
            head, body = line.split('修改为：', 1)                         # 1998 decision: text without quotes
            cur = [head + '修改为', [body], True]
        else:
            cur = [line, None, True]
        segs.append(cur)
    out = []
    for instr, paras, _ in segs:
        if paras is not None:
            paras = [x for t in paras for x in re.split(r'(?<=。)“', t)]          # two paragraphs on one line
            merged = []
            for t in paras:
                if ITEM.match(t) and merged:
                    merged[-1] += t
                elif t:
                    merged.append(t)
            paras = merged
        out.append((re.sub(rf'^[{CN}]+、', '', instr), paras))
    return out


def split_items(text):
    parts = re.split(r'(?=（[一二三四五六七八九十]+）)', text)
    return parts[0], parts[1:]


def renumber(items):
    nums = '一二三四五六七八九十'
    return [f'（{nums[i] if i < 10 else "十" + nums[i - 10]}）' + re.sub(r'^（[^）]*）', '', it) for i, it in enumerate(items)]


MODIFIES = re.compile(r'修改为|增加|删去|作为第')


class Manual(Exception):
    pass


def apply_clause(version, clause, act):
    """Apply all instructions of a clause. version: {key: [para dict]}. Returns modification records."""
    recs, key = [], None
    for instr, new in segments(clause):
        if not MODIFIES.search(instr):
            if re.search(rf'{A}', instr) and not instr.startswith('依照'):
                pass
            continue
        m = re.search(rf'(?:刑法)?{A}', instr)
        if m and not instr.startswith('原第'):
            key = key_of(cn2int(m.group(1)), cn2int(m.group(2)) if m.group(2) else None)
        if key is None:
            raise Manual(f'no article in instruction: {instr[:60]}')
        tail = instr[m.end():] if m and not instr.startswith('原第') else instr

        def rec(typ, pid, old, new_, item=None):
            recs.append(dict(act=act, type=typ, article=key, para_id=pid, item=item, old=old, new=new_,
                             instruction=instr[:120]))

        # --- insertion of whole articles
        mm = re.search(rf'后增加({NUM})条，?作为', instr)
        if mm:
            names = re.findall(rf'第[{CN}]+条之({NUM})', instr[mm.end():])
            if not new:
                raise Manual('inserted article without text')
            blocks, cur_name = {}, None
            if len(names) == 1:
                blocks[names[0]] = new
            else:
                for t in new:
                    h = re.match(rf'第[{CN}]+条之({NUM})[\s　]*(.*)', t)
                    if h:
                        cur_name = h.group(1)
                        blocks[cur_name] = [h.group(2)]
                    elif cur_name:
                        blocks[cur_name].append(t)
                if sorted(blocks) != sorted(names):
                    raise Manual(f'inserted articles {names} not found in text')
            base = cn2int(m.group(1))
            for nm in names:
                k = key_of(base, cn2int(nm))
                version[k] = [para(t) for t in blocks[nm]]
                for pp in version[k]:
                    recs.append(dict(act=act, type='insertion', article=k, para_id=pp['id'], item=None, old=None,
                                     new=pp['text'], instruction=instr[:120]))
            continue
        art = version.get(key)
        if art is None:
            raise Manual(f'article {key} not in previous version')
        # --- word substitution: 将…中的“x”修改为“y”
        mm = re.search(r'中的“([^”]+)”修改为“([^”]+)”', instr)
        if mm:
            a, b = mm.groups()
            pm = re.search(rf'第({NUM})款', tail)
            targets = [art[cn2int(pm.group(1)) - 1]] if pm else art
            hit = False
            for pp in targets:
                if a in pp['text']:
                    old = pp['text']
                    pp['text'] = old.replace(a, b)
                    rec('substitution', pp['id'], old, pp['text'])
                    hit = True
            if not hit:
                raise Manual(f'words "{a}" not found in {key}')
            continue
        # --- items
        mm = re.search(rf'增加({NUM})项，?作为第({NUM})项', instr)
        if mm or re.search(rf'第({NUM})项修改为', instr):
            pm = re.search(rf'第({NUM})款', tail)
            cands = [art[cn2int(pm.group(1)) - 1]] if pm else [pp for pp in art if split_items(pp['text'])[1]]
            if len(cands) != 1 or not new:
                raise Manual('item change: cannot locate the list')
            pp = cands[0]
            intro, items = split_items(pp['text'])
            old = pp['text']
            if mm:
                i = cn2int(mm.group(2))
                items[i - 1:i - 1] = new
                items = renumber(items)
                pp['text'] = intro + ''.join(items)
                rec('insertion', pp['id'], None, items[i - 1], item=i)
            else:
                i = cn2int(re.search(rf'第({NUM})项修改为', instr).group(1))
                num = re.match(r'^（[^）]*）', items[i - 1]).group(0)
                before = items[i - 1]
                items[i - 1] = num + re.sub(r'^（[^）]*）', '', new[0])
                pp['text'] = intro + ''.join(items)
                rec('substitution', pp['id'], before, items[i - 1], item=i)
            continue
        if re.search(r'原第.项改为第.项', instr):
            continue
        # --- deletions
        if instr.startswith('删去'):
            pm = re.findall(rf'第({NUM})款', tail)
            if pm:
                for p in sorted((cn2int(x) for x in pm), reverse=True):
                    gone = art.pop(p - 1)
                    rec('repeal', gone['id'], gone['text'], None)
            else:
                for gone in art:
                    rec('repeal', gone['id'], gone['text'], None)
                version[key] = [para('（删去）')]
            continue
        # --- paragraph insertion: 增加一款/二款作为第N款(、第M款)
        mm = re.search(rf'增加({NUM})款，?作为第({NUM})款', instr)
        if mm and not re.search(r'将该条修改为', instr):
            if not new:
                raise Manual('inserted paragraph without text')
            at = cn2int(mm.group(2))
            ps = [para(t) for t in new]
            art[at - 1:at - 1] = ps
            for pp in ps:
                rec('insertion', pp['id'], None, pp['text'])
            continue
        # --- 原第N款作为第M款，修改为
        mm = re.search(rf'原第({NUM})款作为第({NUM})款', instr)
        if mm:
            if '修改为' in instr and new:
                pp = art[cn2int(mm.group(2)) - 1]
                old = pp['text']
                pp['text'] = new[0]
                rec('substitution', pp['id'], old, pp['text'])
            continue
        # --- paragraph substitution: 第N款(、第M款)修改为
        pm = re.findall(rf'第({NUM})款', tail.split('修改为')[0])
        if '修改为' in instr and pm and new and '将该条修改为' not in instr:
            idx = [cn2int(x) for x in pm]
            lo, hi = min(idx), max(idx)
            olds = art[lo - 1:hi]
            if len(new) == len(olds):
                for pp, t in zip(olds, new):
                    old = pp['text']
                    pp['text'] = t
                    rec('substitution', pp['id'], old, t)
            else:
                ps = [para(t) for t in new]
                art[lo - 1:hi] = ps
                for pp in olds:
                    rec('repeal', pp['id'], pp['text'], None)
                for pp in ps:
                    rec('insertion', pp['id'], None, pp['text'])
            continue
        # --- whole article substitution (incl. 增加一款…，将该条修改为)
        if '修改为' in instr and new:
            olds = art
            if len(new) == len(olds):
                for pp, t in zip(olds, new):
                    if norm(pp['text']) != norm(t):
                        old = pp['text']
                        pp['text'] = t
                        rec('substitution', pp['id'], old, t)
            else:
                # align unchanged paragraphs by text, the rest become insertions/repeals
                keep = {norm(pp['text']): pp for pp in olds}
                ps = []
                for t in new:
                    if norm(t) in keep:
                        ps.append(keep.pop(norm(t)))
                    else:
                        ps.append(None)
                rest = [pp for pp in olds if norm(pp['text']) in keep]
                out = []
                for i, (t, pp) in enumerate(zip(new, ps)):
                    if pp is None and rest:
                        pp = rest.pop(0)
                        old = pp['text']
                        pp['text'] = t
                        rec('substitution', pp['id'], old, t)
                    elif pp is None:
                        pp = para(t)
                        rec('insertion', pp['id'], None, t)
                    out.append(pp)
                for pp in rest:
                    rec('repeal', pp['id'], pp['text'], None)
                version[key] = out
            continue
        raise Manual(f'instruction not recognised: {instr[:60]}')
    return recs


def diff_versions(a, b):
    """Article keys whose paragraphs differ between two versions."""
    keys = sorted(set(a) | set(b), key=lambda k: tuple(int(x) for x in k.split('-')))
    return [k for k in keys if [norm(x) for x in a.get(k, [])] != [norm(x) for x in b.get(k, [])]]


def word_diff(old, new):
    """Minimal changed spans between two strings."""
    if old is None or new is None:
        return []
    sm = difflib.SequenceMatcher(None, norm(old), norm(new), autojunk=False)
    return [dict(op=op, old=norm(old)[i1:i2], new=norm(new)[j1:j2])
            for op, i1, i2, j1, j2 in sm.get_opcodes() if op != 'equal']


def joined(v, k):
    return norm(''.join(pp['text'] if isinstance(pp, dict) else pp for pp in v.get(k, [])))


def order(keys):
    return sorted(keys, key=lambda k: tuple(int(x) for x in k.split('-')))


def main():
    read = lambda name: (SRC / f'{name}.wiki').read_text(encoding='utf-8')
    version = {k: [para(t) for t in v] for k, v in parse_version(read(BASE)).items()}
    report, manual, timeline = [], [], []
    for act, published in STEPS:
        wiki = read(act)
        meta = act_meta(wiki)
        before = {k: joined(version, k) for k in version}
        recs = []
        cls = decision_clauses(wiki) if act.startswith('全国人民代表大会常务委员会关于修改') else clauses(wiki)
        for c in cls:
            snapshot = {k: [dict(pp) for pp in v] for k, v in version.items()}
            try:
                recs += apply_clause(version, c, act)
            except (Manual, KeyError, IndexError) as e:
                version.clear()
                version.update(snapshot)
                manual.append(dict(act=act, reason=str(e), clause=c[:400]))
        changed = [k for k in order(set(before) | set(version)) if before.get(k, '') != joined(version, k)]
        wiki_v = parse_version(read(published)) if (SRC / f'{published}.wiki').exists() else {}
        soft = [k for k in order(set(version) | set(wiki_v)) if wiki_v and joined(version, k) != joined(wiki_v, k)]
        timeline.append(dict(act=act, **meta, modifications=recs, articles_changed=[eid_of(k) for k in changed],
                             differs_from_wikisource_version=[eid_of(k) for k in soft]))
        report.append((act, meta['adopted'], meta['in_force'], len(recs), len(changed), len(soft)))
    # current (2023) position of every paragraph identity
    where = {pp['id']: (k, i) for k, ps in version.items() for i, pp in enumerate(ps)}
    for step in timeline:
        for r in step['modifications']:
            pos = where.get(r['para_id'])
            if pos is None:
                r['destination'] = None
                r['note'] = 'paragraph no longer in force (removed by a later act)'
            else:
                k, i = pos
                r['destination'] = f'{eid_of(k)}__para_{i + 1}' + (f'__list_1__point_{r["item"]}' if r['item'] else '')
            r['words'] = word_diff(r['old'], r['new'])
    official = parse_version((ROOT / 'data' / 'statutes' / 'criminal_law_2023-12-29.txt').read_text(encoding='utf-8'))
    touched = {r['article'] for st in timeline for r in st['modifications']}
    content, base_typos = [], []
    for k in order(set(version) | set(official)):
        if joined(version, k) != joined(official, k):
            d = dict(article=eid_of(k), words=word_diff(''.join(pp['text'] for pp in version.get(k, [])),
                                                         ''.join(official.get(k, []))))
            (content if k in touched or k not in version else base_typos).append(d)
    split = [eid_of(k) for k in order(set(version) & set(official))
             if joined(version, k) == joined(official, k) and len(version[k]) != len(official[k])]
    OUT.write_text(json.dumps(dict(base=BASE, steps=timeline, manual_review=manual,
                                   final_content_differences=content,
                                   never_amended_articles_differing_from_official=base_typos,
                                   final_paragraph_split_differences=split),
                              ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{"act":16s} adopted     in force   mods articles vs-wikisource')
    for act, ad, inf, n, ch, soft in report:
        print(f'{act[-8:]:16s} {ad} {inf} {n:4d} {ch:8d} {soft:6d}')
    print(f'manual review: {len(manual)} | final vs official 2023: amended articles differing {len(content)}, '
          f'never-amended articles differing {len(base_typos)}, paragraph split differing {len(split)}')


if __name__ == '__main__':
    main()
