#!/usr/bin/env python3
"""Plot the latest directly parsed LRML retrieval results; exclude contaminated QA."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
civil = json.loads((HERE / 'results/civil_rerank_latest_results.json').read_text())
criminal = json.loads((HERE / 'results/criminal_review_retrieval.json').read_text())
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 8, 'axes.spines.top': False,
                     'axes.spines.right': False, 'pdf.fonttype': 42, 'svg.fonttype': 'none'})
fig, axes = plt.subplots(1, 2, figsize=(7, 2.75), sharey=True)
rows = [
 [('BM25', 'B1 BM25'), ('Dense', 'B2 Dense'), ('+hier.', 'B3 AKN-only'),
  ('+elem.', 'B4a AKN+Element'), ('+norms', 'B4 AKN+Element+Norm'), ('Expand', 'B4+ expansion')],
 [('BM25', 'BM25'), ('Dense', 'Dense'), ('Override\nrerank', 'review_override/top20'),
  ('Override\nexpand', 'review_override/expansion'), ('All\nrerank', 'review_all/top20'), ('All\nexpand', 'review_all/expansion')]
]
for ax, data, specs, title in zip(axes, [civil, criminal], rows,
                                ['(a) Civil statutes (176 test queries)', '(b) Criminal statutes (245 test queries)']):
 x = np.arange(len(specs)); width = .36
 for offset, met, label, colour in [(-.5, 'R@10', 'Recall@10', '#a5b5c7'), (.5, 'NDCG@10', 'NDCG@10', '#315c82')]:
  ax.bar(x + offset * width, [data['test'][key][met] for _, key in specs], width,
         label=label, color=colour, edgecolor='white', linewidth=.4)
 ax.set_xticks(x, [label for label, _ in specs], fontsize=7)
 ax.set_title(title, fontsize=9, loc='left')
 ax.set_ylim(0, .9); ax.grid(axis='y', alpha=.2); ax.set_axisbelow(True)
 ax.legend(loc='upper left', fontsize=7, frameon=False, ncol=2)
axes[0].set_ylabel('Score')
fig.tight_layout(pad=1.0)
out=HERE.parent / 'latex/figures/results'
for suffix in ['pdf', 'png', 'svg']:
 fig.savefig(out.with_suffix('.'+suffix), dpi=220 if suffix=='png' else 150, bbox_inches='tight')
print(out)
