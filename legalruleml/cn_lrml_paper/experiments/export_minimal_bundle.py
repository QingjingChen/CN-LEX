#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把民法检索实验需要的最小数据导出到 ../minimal_retrieval/data/（只需运行一次）。

导出内容：
  queries.jsonl     每题 qid、split（dev/test，与论文相同：seed 0，30% 开发）、查询文本、金标条文
  articles.jsonl    《民法典》1,260 条：条号、原文、要件文本（规则层条件 / 例外 / 效果 + 支持该条的前两张 LEGO 卡片）
  emb_queries.npy / emb_articles.npy / emb_elements.npy   BGE-m3 向量（L2 归一化），行顺序与 jsonl 一致
  civil_review.lrml 语义网（CLeXML 民法审核版 LegalRuleML，原样复制）
用法：OPENBLAS_NUM_THREADS=1 HF_HUB_OFFLINE=1 ~/.venvs/lcr_jurex/bin/python export_minimal_bundle.py
"""
import json, os, random, shutil
import numpy as np
from retrieval_lib import embed, HERE
import civil_run as CR
import civil_rerank as RR

OUT = os.path.join(HERE, '../minimal_retrieval/data')


def main():
    os.makedirs(OUT, exist_ok=True)
    ARTS, Q = CR.ARTS, CR.Q
    qs = sorted(Q, key=lambda q: q['qid'])
    dev = set(q['qid'] for q in random.Random(0).sample(qs, round(.3 * len(qs))))
    # 向量：与 civil_semantic.py 完全相同的文本、顺序与截断长度（命中同一缓存）
    _, X = embed({str(q['qid']): q['text'] for q in Q}, max_len=1024, bs=16)
    ids, A = embed({a: ARTS[a]['text'] for a in ARTS}, max_len=1024, bs=16)
    ET = RR.element_texts()
    eids, AE = embed(ET, max_len=1024, bs=16)
    with open(f'{OUT}/queries.jsonl', 'w', encoding='utf-8') as f:
        for q in Q:
            f.write(json.dumps({'qid': q['qid'], 'split': 'dev' if q['qid'] in dev else 'test', 'text': q['text'],
                                'gold': [str(g) for g in q['gold']]}, ensure_ascii=False) + '\n')
    with open(f'{OUT}/articles.jsonl', 'w', encoding='utf-8') as f:
        for a in ids:
            f.write(json.dumps({'id': a, 'text': ARTS[a]['text'], 'element_text': ET.get(a)}, ensure_ascii=False) + '\n')
    E = np.zeros((len(ids), A.shape[1]), dtype=np.float32); has = np.zeros(len(ids), dtype=bool)
    ix = {a: i for i, a in enumerate(eids)}
    for i, a in enumerate(ids):
        if a in ix:
            E[i] = AE[ix[a]]; has[i] = True
    np.save(f'{OUT}/emb_queries.npy', X.astype(np.float32))
    np.save(f'{OUT}/emb_articles.npy', A.astype(np.float32))
    np.save(f'{OUT}/emb_elements.npy', E); np.save(f'{OUT}/has_element.npy', has)
    shutil.copy(os.path.join(HERE, '../lrml/civil_review.lrml'), f'{OUT}/civil_review.lrml')
    print('queries', len(Q), 'dev', len(dev), '| articles', len(ids), '| with element text', int(has.sum()))


if __name__ == '__main__':
    main()
