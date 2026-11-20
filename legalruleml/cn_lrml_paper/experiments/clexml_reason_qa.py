#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验 D：检索 → CLeXML 子图 → 推理 → 作答（民法 LEGO 723 题、刑法法考 883 题）。

流程（所有检索只用 题干 / 案情 + 问题 + 选项，不读解析和金标）：
  1 检索     BGE-m3 取前 5 条法条。
  2 子图     CLeXML 审核版 LegalRuleML（civil_review.lrml / criminal_review.lrml）中以这些法条为来源的规则，
             按法条排名取，最多 10 条；再加入这些规则的 Override 伙伴（标准 lrml:Override，方向 over → under）。
  3 条件核验 LLM 对子图中每个原子条件判断 成立 / 不成立 / 未知，并给出题目原文引用；
             “成立”必须附在题目中逐字出现的引用，否则降为“未知”（程序核验）。
  4 推理     确定性求值（与 LegalRuleML → DDL 翻译一致的可废止语义）：And / Or 三值求值；Naf q 只在 q 成立时阻断；
             规则体成立 → 规则适用；若优先规则适用，则被覆盖规则的结论被击败；Neg 结论记为“并非”。
  5 作答     PFC-v3 思维链，附上推理结果（适用 / 被例外阻断 / 被覆盖 / 缺事实）。
条件：P1 PFC + 法条；P2 P1 + 子图规则文本（不推理）；P3 P2 + 推理结果。
指标：EM、选项 F1、配对符号检验；推理侧：每题规则数、适用 / 阻断 / 覆盖数、“成立”判断中引用核验通过的比例（证明有效性）。
用法：~/.venvs/lcr_jurex/bin/python clexml_reason_qa.py --law civil|criminal [--limit N] [--workers 8]
"""
import argparse, collections, json, os, re
from concurrent.futures import ThreadPoolExecutor
import xml.etree.ElementTree as ET
import numpy as np
from retrieval_lib import embed, HERE
import fakao_crim_qa as Q0
import fakao_pfc_qa as PF

L = '{http://docs.oasis-open.org/legalruleml/ns/v1.0/}'
R = '{http://ruleml.org/spec}'
MAXR, CONDS = 8, ('P1', 'P2', 'P3')
LEGO_ALIGNED = os.path.join(HERE, '../../../pfc_v3_40p5_repro/reference_outputs/pfc_v3_aligned.jsonl')
LEGO_ITEMS = os.path.join(HERE, '../../../output/arvix_audit/public_repo_snapshot/data/items.jsonl')
CIVIL_PFC = """请使用 P/F/C（Provision-Fact-Conclusion）方法解答这道中国民法客观题。

角色：站在中立裁判者/考试阅卷者立场。
要求：
1. 先用一句话明确本题要判断的法律对象和题目问法。
2. P-Provision：只列出【给定法条】{extra}中真正控制本题的裁判规则；不要新增未给出的法条。
3. P 阶段必须说明法条关系：一般规则/特别规则/但书例外/限制条件/救济条款之间谁控制结论。
4. 特别注意区分：合同效力、物权变动、对抗效力、责任承担、损害赔偿、优先权/抗辩权，不能把一种法律后果扩大成另一种。
5. 遇到“不得仅以……认定无效”“不影响……效力”“可以请求赔偿”等表述，应按其限制功能理解，不得反向推出合同无效或权利当然消灭。
6. F-Fact：列出会影响判断的题干事实，不要写终局法律结论。
7. C-Conclusion：先做一次“法条关系校验”，再逐项判断 A/B/C/D 的选项命题是否成立。每个选项最多一句判断。
8. Conclusion 必须根据题目问法输出应选项；如果题干问“错误的是/不正确的是/不合法的是/不能成立的是”，应选择错误项。
9. 不要为了覆盖而多选；只有选项的主体、法律谓词、要件事实和法律后果都完整匹配时才选。
10. 每一段用 1-3 句，重点比较选项，不要长篇复述。
11. 最后一行必须且只能是 [正确答案]字母<eoa>，例如 [正确答案]A<eoa> 或 [正确答案]BD<eoa>。

【给定法条】
{arts}
{materials}
【题目】
{question}

请按以下格式输出：
判断对象:

P-Provision:
法条关系:

F-Fact:


C-Conclusion:
法条关系校验:

[正确答案]...<eoa>"""
CHECK = """下面是从 CLeXML 规则库中检索到的规则（LegalRuleML 形式化，条件用谓词表示）。请只根据题目给出的事实，判断每个编号条件是否成立。

规则：
{rules}

题目：
{question}

对每个编号条件给出判断：成立 / 不成立 / 未知。
- “成立”或“不成立”必须附上题目中逐字出现的一段原文（10–40 字）作为依据；题目没有涉及的写“未知”，引用留空。
- 谓词按其英文含义和规则的中文说明理解；变量（P、X 等）对应题目中的当事人或行为，可在不同选项中有不同取值，只要题目中有任一可对应的事实即可判断。
只输出 JSON，格式：{{"条件编号": {{"v": "成立|不成立|未知", "q": "原文引用"}}, ...}}"""


# ---------------------------------------------------------------- 数据
def load(law):
    if law == 'civil':
        out = []
        for l in open(LEGO_ITEMS, encoding='utf-8'):
            r = json.loads(l)
            opts = dict(re.findall(r'([A-D])\.\s*(.*?)(?=\n[A-D]\.|\Z)', r['options'], re.S))
            out.append({'id': r['id'], 'question': f"{r['case']}\n{r['question']}", 'A': opts.get('A', ''), 'B': opts.get('B', ''),
                        'C': opts.get('C', ''), 'D': opts.get('D', ''), 'answer': r['answer'], 'multi': len(r['answer']) > 1, 'year': 0})
        return out
    return Q0.QA


def corpus(law):
    if law == 'civil':
        import civil_run as CR
        return {a: f"《民法典》{v['text']}" for a, v in CR.ARTS.items()}
    return {a: Q0.art_text(a) for a in Q0.LAW}


# ---------------------------------------------------------------- LegalRuleML 解析
class Rules:
    def __init__(self, path):
        root = ET.parse(path).getroot()
        src = {}
        for e in root.iter(L + 'LegalSource'):
            m = re.search(r'#art_(\d+(?:_\d+)?)(?:__para_\d+)?$', e.get('sameAs', ''))
            if m:
                src[e.get('key')] = m.group(1).replace('_', '-')
        arts = collections.defaultdict(set)
        for e in root.iter(L + 'Association'):
            A = {src[s.get('keyref', '').lstrip('#')] for s in e.findall(L + 'appliesSource') if s.get('keyref', '').lstrip('#') in src}
            for t in e.findall(L + 'toTarget'):
                arts[t.get('keyref').lstrip('#')] |= A
        self.rules, self.by_art = {}, collections.defaultdict(list)
        for tag in ('ConstitutiveStatement', 'PrescriptiveStatement'):
            for st in root.iter(L + tag):
                k = st.get('key'); rule = st.find(R + 'Rule')
                if rule is None or rule.find(R + 'if') is None or not arts.get(k):
                    continue
                c = st.find(L + 'Comment')
                note = (c.text or '').split('CNLR_REVIEW_META:')[0].strip() if c is not None else ''
                self.rules[k] = {'key': k, 'articles': sorted(arts[k]), 'note': note[:160],
                                 'body': next(iter(rule.find(R + 'if'))), 'then': rule.find(R + 'then')}
                for a in arts[k]:
                    self.by_art[a].append(k)
        self.over = collections.defaultdict(set); self.under = collections.defaultdict(set)
        for o in root.iter(L + 'Override'):
            a, b = o.get('over').lstrip('#'), o.get('under').lstrip('#')
            if a in self.rules and b in self.rules:
                self.over[a].add(b); self.under[b].add(a)


def atom_str(a):
    rel = a.find(R + 'Rel'); name = rel.get('iri').split(':', 1)[-1] if rel is not None else '?'
    args = [x.text or '' for x in a if x.tag in (R + 'Var', R + 'Ind')]
    return f"{name}({', '.join(args)})"


def leaves(f, rid, acc):
    if f.tag == R + 'Atom':
        acc.append((f'{rid}#{len(acc) + 1}', atom_str(f), f))
    for c in f:
        if c.tag in (R + 'Atom', R + 'And', R + 'Or', R + 'Naf', R + 'Neg'):
            leaves(c, rid, acc)
    return acc


def render(f, ids):
    if f.tag == R + 'Atom':
        return f'[{ids[id(f)]}] {atom_str(f)}'
    kids = [render(c, ids) for c in f if c.tag in (R + 'Atom', R + 'And', R + 'Or', R + 'Naf', R + 'Neg')]
    if f.tag == R + 'And':
        return ' 且 '.join(kids)
    if f.tag == R + 'Or':
        return '（' + ' 或 '.join(kids) + '）'
    if f.tag == R + 'Naf':
        return '除非 ' + kids[0]
    if f.tag == R + 'Neg':
        return '并非 ' + kids[0]
    return ' '.join(kids)


def head_str(then):
    out = []
    for c in then.iter():
        if c.tag == R + 'Atom':
            neg = any(p.tag == R + 'Neg' for p in then.iter() if c in list(p))
            out.append(('并非 ' if neg else '') + atom_str(c))
    return '；'.join(dict.fromkeys(out)) or '（结论）'


def subgraph(RB, arts, sim=None):
    """候选 = 检索法条上的全部规则；按与题目的相似度取前 MAXR 条（sim 为空时按法条排名），再加 Override 伙伴。"""
    cand = [k for a in arts for k in RB.by_art.get(a, [])]
    cand = list(dict.fromkeys(cand))
    if sim is not None:
        cand.sort(key=lambda k: -sim.get(k, 0))
    picked = cand[:MAXR]
    for k in list(picked):
        for o in sorted(RB.under.get(k, set()) | RB.over.get(k, set())):
            if o not in picked and len(picked) < MAXR + 4:
                picked.append(o)
    rules, ids = [], {}
    for k in picked:
        r = RB.rules[k]; lv = leaves(r['body'], k, [])
        for lid, _, el in lv:
            ids[id(el)] = lid
        rules.append({'key': k, 'articles': r['articles'], 'note': r['note'], 'leaves': [(lid, s) for lid, s, _ in lv],
                      'text': f"规则 {k}（第{'、'.join(r['articles'])}条）：{r['note']}\n  如果 {render(r['body'], ids)}\n  则 {head_str(r['then'])}"})
    return rules, ids


# ---------------------------------------------------------------- 推理
def evaluate_rule(f, val):
    """三值求值：T / F / U。Naf q：q 为 T 时为 F（被例外阻断），否则为 T（未证立即不阻断）。"""
    t = f.tag
    if t == R + 'Atom':
        return val.get(id(f), 'U')
    kids = [evaluate_rule(c, val) for c in f if c.tag in (R + 'Atom', R + 'And', R + 'Or', R + 'Naf', R + 'Neg')]
    if t == R + 'And':
        return 'F' if 'F' in kids else ('U' if 'U' in kids else 'T')
    if t == R + 'Or':
        return 'T' if 'T' in kids else ('U' if 'U' in kids else 'F')
    if t == R + 'Naf':
        return 'F' if kids[0] == 'T' else 'T'
    if t == R + 'Neg':
        return {'T': 'F', 'F': 'T', 'U': 'U'}[kids[0]]
    return kids[0] if kids else 'U'


def naf_blocked(f, val):
    return any(c.tag == R + 'Naf' and evaluate_rule(next(iter(c)), val) == 'T' for c in f.iter())


def norm(s):
    return re.sub(r'[\s，,。.；;：:“”"\'、（）()]', '', s or '')


def reason(RB, rules, ids, checks, qtext):
    elem = {lid: el for r in rules for lid, _, el in leaves(RB.rules[r['key']]['body'], r['key'], [])}
    val, judged, quoted = {}, 0, 0
    qn = norm(qtext)
    for lid, el in elem.items():
        c = checks.get(lid) or {}
        v = {'成立': 'T', '不成立': 'F'}.get(c.get('v'), 'U')
        if v != 'U':
            judged += 1
            if c.get('q') and len(norm(c['q'])) >= 4 and norm(c['q']) in qn:
                quoted += 1
            else:
                v = 'U'                   # 引用不在题目中：降为未知
        val[id(el)] = v
    status = {}
    for r in rules:
        body = RB.rules[r['key']]['body']
        v = evaluate_rule(body, val)
        status[r['key']] = 'blocked' if (v == 'F' and naf_blocked(body, val)) else {'T': 'applies', 'F': 'not_applicable', 'U': 'missing_facts'}[v]
    for r in rules:                      # 优先规则适用 → 被覆盖规则的结论被击败
        if status[r['key']] == 'applies' and any(status.get(o) == 'applies' for o in RB.under.get(r['key'], ())):
            status[r['key']] = 'overridden'
    zh = {'applies': '适用', 'blocked': '不适用（例外条件成立）', 'overridden': '被优先规则覆盖', 'not_applicable': '不适用（条件不满足）',
          'missing_facts': '无法判断（缺少事实）'}
    lines = []
    for r in rules:
        k = r['key']; st = status[k]
        if st not in ('applies', 'blocked', 'overridden'):
            continue
        why = [f"[{lid}] {checks.get(lid, {}).get('v', '未知')}：{checks.get(lid, {}).get('q', '')[:30]}" for lid, _ in r['leaves']
               if val.get(id(elem[lid])) != 'U']
        by = ''
        if st == 'overridden':
            by = '，优先规则：' + '、'.join(o for o in RB.under[k] if status.get(o) == 'applies')
        lines.append(f"- 规则 {k}（第{'、'.join(r['articles'])}条）：{zh[st]}{by}" + (f"；依据 {'；'.join(why[:4])}" if why else ''))
    stats = collections.Counter(status.values())
    return ('\n'.join(lines) or '- 没有规则的全部条件都能在题目中找到依据（无可判定适用的规则）'), dict(stats), judged, quoted


# ---------------------------------------------------------------- 提示与运行
def civil_prompt(q, cond, arts, AT, rules, trace):
    extra = '和【CLeXML 规则】' if cond != 'P1' else ''
    mat = ''
    if cond in ('P2', 'P3') and rules:
        mat += '\n【CLeXML 规则】（审核版规则，可能不完整）\n' + '\n'.join(r['text'] for r in rules) + '\n'
    if cond == 'P3' and trace:
        mat += '\n【CLeXML 推理结果】（规则为待专家审核的草稿；条件由模型逐项核验后由推理机求值。“适用”只表示该规则的条件在题目中都能找到依据，规则本身可能不控制本题，需结合法条关系自行判断；“无法判断”表示题目未给出相应事实）\n' + trace + '\n'
    return CIVIL_PFC.format(extra=extra, arts='\n'.join(f'[{i + 1}] {AT[a]}' for i, a in enumerate(arts)), materials=mat, question=Q0.qtext(q))


def criminal_prompt(q, cond, ctx, rules, trace):
    if cond == 'P1':
        return PF.prompt(q, 'P1', ctx)                       # 与 fakao_pfc_qa 的 P1 完全相同（共用缓存）
    base = PF.prompt(q, 'P1', ctx)
    mat = '\n【CLeXML 规则】（审核版规则，可能不完整）\n' + '\n'.join(r['text'] for r in rules) + '\n' if rules else ''
    if cond == 'P3' and trace:
        mat += '\n【CLeXML 推理结果】（规则为待专家审核的草稿；条件由模型逐项核验后由推理机求值。“适用”只表示该规则的条件在题目中都能找到依据，规则本身可能不控制本题，需结合法条关系自行判断；“无法判断”表示题目未给出相应事实）\n' + trace + '\n'
    return base.replace('\n【题目】', mat + '\n【题目】', 1).replace('只列出【给定法条】中', '只列出【给定法条】和【CLeXML 规则】中', 1)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--law', required=True, choices=('civil', 'criminal'))
    ap.add_argument('--limit', type=int, default=0); ap.add_argument('--offset', type=int, default=0, help='跳过前 N 题（民法前 40 题为开发集）')
    ap.add_argument('--model', default='qwen3.5-35b-a3b')
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    data = load(a.law)[a.offset:]; data = data[:a.limit] if a.limit else data
    AT = corpus(a.law); arts = list(AT)
    if a.law == 'criminal':
        ctxs = PF.contexts()
        top = {q['id']: ctxs[q['id']]['arts'] for q in data}
    else:                                              # 民法：LEGO 系统自身的检索结果（前 8 条，只用题目）
        lego = {}
        for l in open(LEGO_ALIGNED, encoding='utf-8'):
            r = json.loads(l)
            lego[f"item-{int(r['qid']) + 1:04d}"] = [str(x) for x in r['provided_article_nos'] if str(x) in AT]
        top = {q['id']: lego.get(q['id'], []) for q in data}
    RB = Rules(os.path.join(HERE, f'../lrml/{a.law}_review.lrml'))
    rk = list(RB.rules)
    _, RE = embed({k: (RB.rules[k]['note'] or k) for k in rk}, max_len=512, bs=32)
    _, QX = embed({q['id']: Q0.qtext(q) for q in data}, max_len=1024, bs=16)
    S = QX @ RE.T
    sub = {q['id']: subgraph(RB, top[q['id']], dict(zip(rk, map(float, S[i])))) for i, q in enumerate(data)}
    system = PF.SYSTEM if a.law == 'criminal' else '你是严谨的中国民法客观题助手。你必须严格基于题干事实、选项和给定法条推理，不得编造未给出的事实或法条。'

    def check(q):
        rules, _ = sub[q['id']]
        if not rules:
            return q['id'], {}
        raw = Q0.chat(CHECK.format(rules='\n'.join(r['text'] for r in rules), question=Q0.qtext(q)), model=a.model,
                      system='你是严谨的法律事实核验助手，只输出 JSON。', max_tokens=3000, seed=7)
        m = re.search(r'\{.*\}', raw, re.S)
        try:
            return q['id'], json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            return q['id'], {}
    with ThreadPoolExecutor(a.workers) as ex:
        checks = dict(ex.map(check, data))
    traces = {}
    for q in data:
        rules, ids = sub[q['id']]
        traces[q['id']] = reason(RB, rules, ids, checks[q['id']], Q0.qtext(q)) if rules else ('', {}, 0, 0)

    def answer(job):
        q, c = job
        rules, _ = sub[q['id']]
        p = (civil_prompt(q, c, top[q['id']], AT, rules, traces[q['id']][0]) if a.law == 'civil'
             else criminal_prompt(q, c, ctxs[q['id']], rules, traces[q['id']][0]))
        try:
            raw = Q0.chat(p, model=a.model, system=system, max_tokens=3000, seed=7)
        except Exception as e:  # noqa: BLE001
            raw = f'ERROR {e}'
        return q['id'], c, raw
    with ThreadPoolExecutor(a.workers) as ex:
        out = list(ex.map(answer, [(q, c) for q in data for c in CONDS]))
    rows = collections.defaultdict(dict)
    for qid, c, raw in out:
        rows[qid][c] = {'raw': raw, 'pred': PF.parse(raw)}
    tag = f"{a.law}_{a.model}{'_off' + str(a.offset) if a.offset else ''}{'_limit' + str(a.limit) if a.limit else ''}"
    with open(os.path.join(HERE, f'results/clexml_reason_{tag}.jsonl'), 'w', encoding='utf-8') as f:
        for q in data:
            f.write(json.dumps({'id': q['id'], 'gold': q['answer'], 'multi': q['multi'], 'arts': top[q['id']],
                                'rules': [r['key'] for r in sub[q['id']][0]], 'checks': checks[q['id']], 'trace': traces[q['id']][0],
                                'status': traces[q['id']][1], **{c: rows[q['id']][c] for c in CONDS}}, ensure_ascii=False) + '\n')
    st = collections.Counter(); judged = quoted = 0
    for q in data:
        st.update(traces[q['id']][1]); judged += traces[q['id']][2]; quoted += traces[q['id']][3]
    res = {'law': a.law, 'model': a.model, 'n': len(data),
           'reasoning': {'questions_with_rules': sum(1 for q in data if sub[q['id']][0]),
                         'mean_rules': float(np.mean([len(sub[q['id']][0]) for q in data])),
                         'questions_with_applying_rule': sum(1 for q in data if traces[q['id']][1].get('applies')),
                         'rule_status': dict(st), 'judged_conditions': judged, 'quote_verified': quoted,
                         'proof_validity': quoted / judged if judged else None},
           'unparsed': {c: sum(rows[q['id']][c]['pred'] == '' for q in data) for c in CONDS}, 'subsets': {}, 'sign': {}}
    subsets = {'all': data, 'single': [q for q in data if not q['multi']], 'multi': [q for q in data if q['multi']],
               'with applying rule': [q for q in data if traces[q['id']][1].get('applies')]}
    for name, S in subsets.items():
        if not S:
            continue
        res['subsets'][name] = {'n': len(S)}
        em = {}
        for c in CONDS:
            s = [Q0.score(rows[q['id']][c]['pred'], q['answer']) for q in S]
            res['subsets'][name][c] = {'EM': float(np.mean([x[0] for x in s])), 'F1': float(np.mean([x[1] for x in s]))}
            em[c] = [x[0] for x in s]
        res['sign'][name] = {f'{y} vs {x}': Q0.sign_test(em[x], em[y]) for x, y in (('P1', 'P2'), ('P2', 'P3'), ('P1', 'P3'))}
    json.dump(res, open(os.path.join(HERE, f'results/clexml_reason_{tag}_summary.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
