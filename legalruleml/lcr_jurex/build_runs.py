"""把 llm_cache 中的 case-FET 变成检索 run，并做融合 / 加 S_rule。

  python build_runs.py texts  --guide expert       # 写 cache/texts_<guide>_{q,c}.json（供 dense_retrieve --texts）
  python build_runs.py fuse                         # 生成所有组合的 run，并打印结果表

S(q,c) = 0.7 S_fact + 0.3 S_FET                      （JUREX-4E 第 8.2 节，原始余弦直接加权）
       + λ S_x,  S_x ∈ {S_charge, S_rule}
  S_charge = Jaccard(罪名集合)                          对照：只看罪名是否一致
  S_rule   = Jaccard(罪名 ∪ 满足的 LRML 条件编号)          LegalRuleML：罪名 + 加重情节 / 罪与非罪 / 转化条件
罪名集合：查询用预测罪名，候选用判决罪名（与 JUREX 的 FET 引导一致）。
"""
import json, os, re, sys
import llm_pipeline as L
import lcr_eval as E

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "qwen-plus"


def parse_json(raw):
    s = raw
    if "```" in s:
        s = s.split("```json")[-1] if "```json" in s else s.split("```")[1]
        s = s.split("```")[0]
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        pass
    # 输出被 max_tokens 截断时：逐块回收完整的 {"犯罪的四要件": {...}, "罪名": ..., "满足的条件": [...]}
    out = []
    for m in re.finditer(r'"犯罪的四要件"\s*:\s*(\{[^{}]*\})', raw):
        try:
            f = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        rest = raw[m.end():m.end() + 600]
        rest = rest.split('"犯罪的四要件"')[0]
        name = re.search(r'"罪名"\s*:\s*"([^"]*)"', rest)
        conds = re.search(r'"满足的条件"\s*:\s*\[([^\]]*)\]', rest)
        out.append({"犯罪的四要件": f, "罪名": name.group(1) if name else "",
                    "满足的条件": re.findall(r"t\d+", conds.group(1)) if conds else []})
    return out or None


def items(d):
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    if isinstance(d, dict):
        if "犯罪的四要件" in d:
            return [d]
        return [v for v in d.values() if isinstance(v, dict)]
    return []


def fet_text(d):
    """= JUREX step0/step1 的 load_input(add_crime=True)。"""
    crime, crime2 = "", "\t罪名:"
    for i, it in enumerate(items(d), 1):
        f = it.get("犯罪的四要件", {})
        if isinstance(f, dict):
            crime += f"\t罪名{i}: " + ', '.join(f'{k}: {v}' for k, v in f.items())
        crime2 += f"{it.get('罪名', '')}\t"
    return crime + crime2 if crime else ""


def sat_conds(d, allowed):
    out = set()
    for it in items(d):
        v = it.get("满足的条件", [])
        if isinstance(v, str):
            v = re.findall(r"t\d+", v)
        out |= {x for x in v if isinstance(x, str) and x in allowed}
    return out


def load_outputs(guide):
    p = os.path.join(HERE, f"llm_cache/fet_{guide}_{MODEL}")
    return {f[:-5]: json.load(open(f"{p}/{f}"))["output"] for f in os.listdir(p)}


def cmd_texts(guide):
    outs = load_outputs(guide)
    q, c, bad = {}, {}, 0
    for i, raw in outs.items():
        d = parse_json(raw)
        t = fet_text(d) if d else ""
        bad += not t
        (q if i[0] == "q" else c)[i[1:]] = t or " "
    for name, obj in (("q", q), ("c", c)):
        json.dump(obj, open(os.path.join(HERE, f"cache/texts_{guide}_{name}.json"), "w"), ensure_ascii=False)
    print(f"{guide}: queries={len(q)} cands={len(c)} unparsable={bad}")


def jacc(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def atoms():
    preds = L.load_preds()
    outs = load_outputs("expert_cond")
    ch, cond = {}, {}
    for i, fact, gold in L.cases():
        cs = set(L.charges_of(i, gold, preds))
        allowed = {x["id"] for c in cs if c in L.KB for x in L.KB[c]["conditions"]}
        d = parse_json(outs[i]) if i in outs else None
        ch[i] = {"C:" + c for c in cs}
        cond[i] = {"K:" + x for x in sat_conds(d, allowed)} if d else set()
    return ch, cond


def sym_run(ch, cond, use_cond):
    qids = [i for i in ch if i[0] == "q"]
    pids = [i for i in ch if i[0] == "c"]
    run = {}
    for q in qids:
        aq = ch[q] | (cond[q] if use_cond else set())
        run[q[1:]] = {p[1:]: jacc(aq, ch[p] | (cond[p] if use_cond else set())) for p in pids}
    return run


def lin(*rw):
    out = {}
    for run, w in rw:
        for q, s in run.items():
            o = out.setdefault(q, {})
            for p, v in s.items():
                o[p] = o.get(p, 0.0) + w * v
    return out


def cmd_fuse():
    R = lambda n: json.load(open(os.path.join(HERE, f"runs/{n}.json")))
    labels = E.load_labels()
    fact, fx, fxc = R("bge_fact"), R("bge_fet_expert"), R("bge_fet_expert_cond")
    ch, cond = atoms()
    s_charge, s_rule = sym_run(ch, cond, False), sym_run(ch, cond, True)
    nq = sum(bool(cond[i]) for i in cond if i[0] == "q"); nc = sum(bool(cond[i]) for i in cond if i[0] == "c")
    nqa = sum(1 for i in cond if i[0] == "q")
    print(f"cases with ≥1 satisfied LRML condition: queries {nq}/{nqa}, cands {nc}/1390")
    rows = {
        "BGE(fact)": fact,
        "FET only (Expert)": fx,
        "FET only (Expert+LRML cond)": fxc,
        "BGE+FET(Expert)": lin((fact, .7), (fx, .3)),
        "BGE+FET(Expert+LRML cond)": lin((fact, .7), (fxc, .3)),
    }
    base = rows["BGE+FET(Expert)"]
    for lam in (0.05, 0.1, 0.2):
        rows[f"BGE+FET(Expert) +{lam}·S_charge"] = lin((base, 1), (s_charge, lam))
        rows[f"BGE+FET(Expert) +{lam}·S_rule"] = lin((base, 1), (s_rule, lam))
    res = {}
    hdr = False
    for name, run in rows.items():
        if not hdr:
            print(f"{'method':38s} " + " ".join(f"{k:>9s}" for k in E.evaluate(run, labels)[0]))
            hdr = True
        m, per = E.evaluate(run, labels)
        res[name] = (m, per)
        print(f"{name:38s} " + " ".join(f"{v:9.4f}" for v in m.values()))
    print("\npaired randomization tests (10k):")
    pairs = [("BGE+FET(Expert)", "BGE+FET(Expert+LRML cond)")]
    pairs += [("BGE+FET(Expert)", f"BGE+FET(Expert) +0.1·S_{x}") for x in ("charge", "rule")]
    pairs += [("BGE+FET(Expert) +0.1·S_charge", "BGE+FET(Expert) +0.1·S_rule")]
    for a, b in pairs:
        for met in ("NDCG@10", "R@10", "MRR_paper"):
            d, p = E.paired_randomization(res[a][1], res[b][1], met)
            print(f"  {b:34s} vs {a:30s} Δ{met}={d:+.4f} p={p:.3f}")
    json.dump({k: v[0] for k, v in res.items()}, open(os.path.join(HERE, "runs/summary.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if sys.argv[1] == "texts":
        cmd_texts(sys.argv[sys.argv.index("--guide") + 1])
    else:
        cmd_fuse()
