#!/bin/sh
# 下载 JUREX-4E LCR 实验所用的数据：
#   - LeCaRDv2 的 1390 候选子集（Qin et al. 2024, GEAR；JUREX-4E 第 8.1 节沿用）
#   - JUREX-4E 专家四要件（155 个罪名）及罪名-法条映射
# 两个来源都是 MIT 许可。数据放在 data/（已 gitignore）。
set -e
cd "$(dirname "$0")"
mkdir -p data/gear data/jurex
G=https://raw.githubusercontent.com/E-qin/GEAR/master/dataset/LeCaRD_version2/LeCaRD_version2_key_src
for f in labels.json pid_charges.json pid_sentences.json pids.json qid_sentences.json \
         test_q_charges.json test_qids.json total_crimes.json; do
  curl -sSfL -o "data/gear/$f" "$G/$f"
done
J=https://raw.githubusercontent.com/THUlawtech/JUREX/main/data
curl -sSfL -o data/jurex/jurex4e.json           "$J/jurex4e.json"
curl -sSfL -o data/jurex/flattened_jurex4e.json "$J/flattened_jurex4e.json"
curl -sSfL -o data/jurex/crime2article.json     "$J/law/crime2article.json"
echo "done: $(ls data/gear data/jurex | wc -l) files"

# CAIL2018 罪名预测（exercise_contest：train 154,592 / valid 17,131 / test 32,508）。
# 来源：Hugging Face china-ai-law-challenge/cail2018（官方镜像）。转成 jsonl 需要 pyarrow：
#   python -c "import pandas as pd,json,sys; [open(f'data/cail2018/exercise_contest_{s}.jsonl','w').writelines(json.dumps({k:(v.tolist() if hasattr(v,'tolist') else v) for k,v in r.items()},ensure_ascii=False)+'\n' for r in pd.read_parquet(f'data/cail2018/exercise_contest_{s}.parquet').to_dict('records')) for s in ['train','valid','test']]"
mkdir -p data/cail2018
H=https://huggingface.co/datasets/china-ai-law-challenge/cail2018/resolve/main/data
for s in train valid test; do
  curl -sSfL -o "data/cail2018/exercise_contest_$s.parquet" "$H/exercise_contest_$s-00000-of-00001.parquet"
done
