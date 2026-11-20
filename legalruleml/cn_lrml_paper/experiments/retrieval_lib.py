# -*- coding: utf-8 -*-
"""检索实验公用部分：字符二元组 BM25、BGE-m3 嵌入（带缓存）、指标、配对随机化检验。"""
import collections, hashlib, json, math, os, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')


# ---------------------------------------------------------------- BM25（中文按字符二元组切分）
def bigrams(t):
    t = ''.join(ch for ch in t if not ch.isspace())
    return [t[i:i + 2] for i in range(len(t) - 1)]


class BM25:
    def __init__(self, docs, k1=1.2, b=0.75):
        self.ids = list(docs)
        self.tf = [collections.Counter(bigrams(docs[i])) for i in self.ids]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / len(self.len)
        df = collections.Counter(t for c in self.tf for t in c)
        N = len(self.ids)
        self.idf = {t: math.log(1 + (N - n + .5) / (n + .5)) for t, n in df.items()}
        self.k1, self.b = k1, b

    def score(self, q):
        qt = collections.Counter(bigrams(q))
        out = {}
        for i, (c, L) in enumerate(zip(self.tf, self.len)):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * L / self.avg)
            for t, qf in qt.items():
                f = c.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            out[self.ids[i]] = s
        return out


# ---------------------------------------------------------------- BGE-m3
_model = None


def embed(texts, max_len=8192, bs=4, model='BAAI/bge-m3'):
    """texts: {id: text} → (ids, L2 归一化矩阵)。按内容哈希缓存。"""
    global _model
    ids = list(texts)
    key = hashlib.md5(json.dumps([texts[i] for i in ids], ensure_ascii=False).encode()).hexdigest()[:12]
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f'emb_{key}_{max_len}.npy')
    if os.path.exists(path):
        return ids, np.load(path)
    if _model is None:
        import torch
        from sentence_transformers import SentenceTransformer
        dev = 'mps' if torch.backends.mps.is_available() else 'cpu'
        _model = SentenceTransformer(model, device=dev)
    _model.max_seq_length = max_len
    order = sorted(range(len(ids)), key=lambda i: len(texts[ids[i]]))
    vecs = _model.encode([texts[ids[i]] for i in order], batch_size=bs, normalize_embeddings=True,
                         show_progress_bar=True, convert_to_numpy=True)
    out = np.zeros_like(vecs)
    out[order] = vecs
    np.save(path, out)
    return ids, out


def minmax(s):
    lo, hi = min(s.values()), max(s.values())
    span = (hi - lo) or 1.0
    return {k: (v - lo) / span for k, v in s.items()}


# ---------------------------------------------------------------- 指标
def metrics(scores, rel, ks_r=(5, 10, 30), ks_n=(10, 30)):
    """rel: {id: gain}。Recall 把 gain>0 视为相关；NDCG 用分级 gain。MRR = 首个相关结果的倒数排名。"""
    ranked = sorted(scores, key=lambda p: -scores[p])
    out = {}
    for k in ks_n:
        dcg = sum(rel.get(p, 0) / math.log2(i + 2) for i, p in enumerate(ranked[:k]))
        ideal = sorted(rel.values(), reverse=True)[:k]
        idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
        out[f'NDCG@{k}'] = dcg / idcg if idcg else 0.0
    for k in ks_r:
        out[f'R@{k}'] = len(set(ranked[:k]) & set(rel)) / len(rel)
    out['MRR'] = next((1 / (i + 1) for i, p in enumerate(ranked) if p in rel), 0.0)
    return out


def mean(per, keys=None):
    keys = keys or list(next(iter(per.values())))
    return {k: sum(v[k] for v in per.values()) / len(per) for k in keys}


def randomization(per_a, per_b, metric, n=10000, seed=0):
    """双侧配对随机化检验，返回 (均值差 b-a, p)。"""
    qs = sorted(set(per_a) & set(per_b))
    d = [per_b[q][metric] - per_a[q][metric] for q in qs]
    obs = abs(sum(d))
    rng = random.Random(seed)
    hit = sum(abs(sum(x if rng.random() < .5 else -x for x in d)) >= obs - 1e-12 for _ in range(n))
    return sum(d) / len(d), (hit + 1) / (n + 1)
