"""从刑法 LegalRuleML 图谱（crim_graph）为每个罪名导出两类知识：

1. lrml_fet：四要件（犯罪客体 / 客观方面 / 犯罪主体 / 主观方面），取自罪名节点下的“构成要件”子树。
   与 JUREX-4E 的 Expert-FET 一一对应，用于“LRML 引导的 case-FET 生成”。
2. conditions：可判定的条件清单，每条带图谱节点编号（= crim_graph.lrml 中的 Statement key）：
   - aggr：法条所列加重 / 情节（相关法条下的枚举项）
   - excl：罪与非罪（出罪、不以本罪论处的情形）
   - conv：此罪与彼罪 / 转化（依他罪论处、择一重罪等）
   用于 S_rule：LLM 判断案件满足哪些条件，再比较 query 与 candidate 的条件向量。

输出：data/lrml_kb.json  {罪名: {"node": id, "fet": {...}, "conditions": [{"id","type","text"}]}}
"""
import json, os, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
CRIM = os.path.join(HERE, "../crim_graph")
N = {n["id"]: n for n in json.load(open(os.path.join(CRIM, "crim_nodes.json")))}

FET_KEYS = {"犯罪客体": "犯罪客体", "客体": "犯罪客体", "客观方面": "客观方面",
            "犯罪主体": "犯罪主体", "主体": "犯罪主体", "主观方面": "主观方面"}
# JUREX-4E / GEAR 罪名名称 → 图谱中的写法
ALIASES = {"强制猥亵、侮辱罪": ["强制猥亵、侮辱妇女罪", "强制猥亵罪"],
           "伪造、变造、买卖身份证件罪": ["伪造、变造居民身份证罪"],
           "生产、销售假药罪": ["生产、销售、提供假药罪"]}


def clean(t):
    return re.sub(r"[TF]{1,2}\d{2}[/，,]?\d*[；;]?|\d{2}/\d+[；;]?", "", t).strip()


def text_of(i, depth=2):
    """节点文本 + 子节点文本（限深度），用于条件描述。"""
    n = N[i]
    parts = [clean(n["clean"])]
    if depth:
        parts += [text_of(c, depth - 1) for c in n["children"]]
    return "".join(p for p in parts if p)[:300]


def child_by_title(i, *titles):
    for c in N[i]["children"]:
        if any(clean(N[c]["clean"]).startswith(t) for t in titles):
            return c
    return None


def head_name(t):
    """'诈骗罪T14/17；TF15/19' → '诈骗罪'；'生产、销售有毒、有害食品罪（20新增）21/45；' → '生产、销售有毒、有害食品罪'"""
    m = re.match(r"^(.*?罪)(?=[\dTF（(★]|$)", t.strip())
    return m.group(1) if m else None


# 罪名节点 = 有“相关法条 / 概念 / 构成要件”子节点、且标题能规范成“…罪”的节点
HEADS = {}
for _n in N.values():
    if any(re.match(r"(相关法条|构成要件|概念)", N[k]["clean"]) for k in _n["children"]):
        h = head_name(_n["clean"])
        if h:
            HEADS.setdefault(h, []).append(_n["id"])


def find_charge_node(name):
    for x in [name] + ALIASES.get(name, []):
        if x in HEADS:
            return max(HEADS[x], key=lambda i: len(N[i]["children"]))
    return None


def extract(name):
    i = find_charge_node(name)
    if not i:
        return None
    fet, conds = {}, []
    ce = child_by_title(i, "构成要件")
    if ce:
        for c in N[ce]["children"]:
            k = FET_KEYS.get(clean(N[c]["clean"]).rstrip("：:"))
            if k:
                fet[k] = "；".join(text_of(g, 1) for g in N[c]["children"]) or clean(N[c]["clean"])
    law = child_by_title(i, "相关法条")
    if law:
        for art in N[law]["children"]:
            for item in N[art]["children"]:
                if re.match(r"[（(][一二三四五六七八九十]+[)）]", N[item]["clean"]):
                    conds.append({"id": item, "type": "aggr", "text": clean(N[item]["clean"])})
    for title, typ in (("罪与非罪", "excl"), ("此罪与彼罪", "conv")):
        sec = child_by_title(i, title)
        if sec:
            for c in N[sec]["children"]:
                conds.append({"id": c, "type": typ, "text": text_of(c, 1)})
    concept = child_by_title(i, "概念")
    return {"node": i, "concept": text_of(concept, 1) if concept else "",
            "fet": fet, "conditions": conds}


def main():
    crimes = json.load(open(os.path.join(HERE, "data/gear/total_crimes.json")))
    pc = json.load(open(os.path.join(HERE, "data/gear/pid_charges.json")))
    freq = collections.Counter(c for v in pc.values() for c in v)
    kb, stat = {}, collections.Counter()
    for c in crimes:
        r = extract(c)
        if r:
            kb[c] = r
        stat["node"] += bool(r)
        stat["fet4"] += bool(r and len(r["fet"]) == 4)
        stat["has_cond"] += bool(r and r["conditions"])
    json.dump(kb, open(os.path.join(HERE, "data/lrml_kb.json"), "w"), ensure_ascii=False, indent=1)
    cov = sum(freq[c] for c in kb) / sum(freq.values())
    print(f"charges: {len(crimes)}  found={stat['node']}  full-4-elements={stat['fet4']}  with-conditions={stat['has_cond']}")
    print(f"candidate charge-mentions covered: {cov:.1%}")
    print("missing:", [c for c in crimes if c not in kb])
    print("no 4 elements:", [c for c in kb if len(kb[c]["fet"]) < 4])


if __name__ == "__main__":
    main()
