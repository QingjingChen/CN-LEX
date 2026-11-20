"""BGE-m3 稠密检索（CLS 池化、L2 归一化、余弦相似度），与 JUREX-4E 第 8.2 节一致。

用法：
  python dense_retrieve.py --field fact -o runs/bge_fact.json
  python dense_retrieve.py --texts q.json c.json -o runs/bge_xxx.json   # 自定义文本（{id: text}）
嵌入会缓存到 cache/emb_<name>.npy，重复运行不重算。
"""
import argparse, json, os, hashlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def load_fact_texts():
    d = os.path.join(HERE, "data/gear")
    qs = json.load(open(f"{d}/qid_sentences.json"))
    cs = json.load(open(f"{d}/pid_sentences.json"))
    qids = json.load(open(f"{d}/test_qids.json"))
    return {q: "".join(qs[q]) for q in qids}, {p: "".join(v) for p, v in cs.items()}


def embed(texts, model, max_len, bs):
    ids = list(texts)
    key = hashlib.md5(json.dumps([texts[i] for i in ids], ensure_ascii=False).encode()).hexdigest()[:12]
    cache = os.path.join(HERE, f"cache/emb_{key}_{max_len}.npy")
    if os.path.exists(cache):
        return ids, np.load(cache)
    model.max_seq_length = max_len
    # 按长度排序再分批，减少 padding
    order = sorted(range(len(ids)), key=lambda i: len(texts[ids[i]]))
    vecs = model.encode([texts[ids[i]] for i in order], batch_size=bs, normalize_embeddings=True,
                        show_progress_bar=True, convert_to_numpy=True)
    out = np.zeros_like(vecs)
    out[order] = vecs
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    np.save(cache, out)
    return ids, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--field", default="fact")
    ap.add_argument("--texts", nargs=2, metavar=("QUERIES", "CANDS"))
    ap.add_argument("--model", default="BAAI/bge-m3")
    ap.add_argument("--max_len", type=int, default=8192)
    ap.add_argument("--bs", type=int, default=4)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    if a.texts:
        q_txt, c_txt = (json.load(open(p)) for p in a.texts)
    else:
        q_txt, c_txt = load_fact_texts()

    import torch
    from sentence_transformers import SentenceTransformer
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer(a.model, device=dev)  # bge-m3 的 ST 配置即 CLS 池化 + normalize
    qids, Q = embed(q_txt, model, a.max_len, a.bs)
    pids, C = embed(c_txt, model, a.max_len, a.bs)
    S = Q @ C.T
    run = {q: {p: float(S[i, j]) for j, p in enumerate(pids)} for i, q in enumerate(qids)}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(run, open(a.out, "w"))
    print("wrote", a.out, len(run), "queries x", len(pids), "cands")


if __name__ == "__main__":
    main()
