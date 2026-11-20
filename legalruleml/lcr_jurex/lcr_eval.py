"""LeCaRDv2（GEAR 1390 候选子集）上的类案检索评测，指标与 JUREX-4E 表 4 一致。

run 文件格式：{qid: {pid: score}}（JSON）。分数越高越相关。
标签：data/gear/labels.json，{qid: [[pid, level], ...]}，level ∈ {2, 3}；未标注视为 0。
  NDCG@k 用分级标签（gain = level）；Recall@k、MRR 把所有已标注候选视为相关。
"""
import json, math, sys, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
KS_NDCG = (10, 20, 30)
KS_R = (1, 5, 10, 20, 30)


def load_labels(split="test"):
    """GEAR 的 test_qids.json 有 92 项，但只有 54 个不同查询（有重复）。默认按 54 个唯一查询评测。"""
    lab = json.load(open(os.path.join(HERE, "data/gear/labels.json")))
    qids = json.load(open(os.path.join(HERE, "data/gear/test_qids.json"))) if split == "test" else list(lab)
    return {q: {p: l for p, l in lab[q]} for q in qids}


def dup_weighted(per):
    """按 test_qids.json 原样（92 项、含重复）加权平均，用于和论文数字对照。"""
    qids = json.load(open(os.path.join(HERE, "data/gear/test_qids.json")))
    keys = list(next(iter(per.values())))
    return {k: sum(per[q][k] for q in qids) / len(qids) for k in keys}


def per_query(ranked, rel):
    out = {}
    for k in KS_NDCG:
        dcg = sum(rel.get(p, 0) / math.log2(i + 2) for i, p in enumerate(ranked[:k]))
        ideal = sorted(rel.values(), reverse=True)[:k]
        idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
        out[f"NDCG@{k}"] = dcg / idcg if idcg else 0.0
    for k in KS_R:
        out[f"R@{k}"] = len(set(ranked[:k]) & set(rel)) / len(rel)
    out["MRR"] = next((1 / (i + 1) for i, p in enumerate(ranked) if p in rel), 0.0)
    # JUREX-4E 表 4 的 “MRR” 实为所有相关文档倒数排名的平均（复现得 0.1916 vs 论文 0.1926）
    pos = {p: i for i, p in enumerate(ranked)}
    out["MRR_paper"] = sum(1 / (pos[p] + 1) for p in rel if p in pos) / len(rel)
    return out


def evaluate(run, labels):
    per = {}
    for q, rel in labels.items():
        scores = run.get(q, {})
        ranked = sorted(scores, key=lambda p: -scores[p])
        per[q] = per_query(ranked, rel)
    keys = list(next(iter(per.values())))
    return {k: sum(v[k] for v in per.values()) / len(per) for k in keys}, per


def paired_randomization(per_a, per_b, metric, n=10000, seed=0):
    """双侧配对随机化检验（Fisher 置换），返回 (均值差 b-a, p)。"""
    qs = sorted(set(per_a) & set(per_b))
    d = [per_b[q][metric] - per_a[q][metric] for q in qs]
    obs = abs(sum(d))
    rng = random.Random(seed)
    hit = sum(abs(sum(x if rng.random() < .5 else -x for x in d)) >= obs - 1e-12 for _ in range(n))
    return sum(d) / len(d), (hit + 1) / (n + 1)


def fuse(runs_weights):
    """线性融合若干 run：sum(w * score)。各 run 先按查询做 min-max 归一化以统一尺度。"""
    out = {}
    for run, w in runs_weights:
        for q, s in run.items():
            lo, hi = min(s.values()), max(s.values())
            span = (hi - lo) or 1.0
            o = out.setdefault(q, {})
            for p, v in s.items():
                o[p] = o.get(p, 0.0) + w * (v - lo) / span
    return out


def fmt(m):
    return "  ".join(f"{k}={v:.4f}" for k, v in m.items())


if __name__ == "__main__":
    labels = load_labels()
    base = None
    for path in sys.argv[1:]:
        m, per = evaluate(json.load(open(path)), labels)
        print(f"{os.path.basename(path):40s} [54 unique] {fmt(m)}")
        print(f"{'':40s} [92 w/ dup] {fmt(dup_weighted(per))}")
        if base is None:
            base = per
        else:
            for met in ("NDCG@10", "MRR"):
                d, p = paired_randomization(base, per, met)
                print(f"{'':40s}   vs first: Δ{met}={d:+.4f}  p={p:.4f}")
