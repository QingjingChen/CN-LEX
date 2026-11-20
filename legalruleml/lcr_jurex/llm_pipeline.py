"""LLM 部分：复现 JUREX-4E 的 BGE+FET(Expert, Mg)，并加入 LegalRuleML 条件。

  python llm_pipeline.py predict                 # 查询罪名预测（论文附录 D / 表 13 的 prompt，Mp）
  python llm_pipeline.py fet --guide expert      # JUREX 原方法：专家四要件引导生成 case-FET
  python llm_pipeline.py fet --guide expert_cond # 同上 + LRML 条件清单（加重情节 / 罪与非罪 / 此罪与彼罪），
                                                 # 并要求输出案件满足的条件编号（用于 S_rule）
  python llm_pipeline.py fet --guide none        # 论文 BGE+FET(Mg)：无外部知识
  python llm_pipeline.py fet ... --limit 20      # 先小规模试跑

罪名来源与 JUREX 代码一致：查询用预测罪名，候选用判决书中的罪名。
所有调用缓存在 llm_cache/<step>/<id>.json，重复运行只补缺。
"""
import argparse, json, os, re, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../.."))
D = os.path.join(HERE, "data")


def load_env():
    env = {}
    for line in open(os.path.join(ROOT, ".env")):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v
    return env


ENV = load_env()


def chat(prompt, model, max_tokens=2048, retries=4):
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": max_tokens}
    if model.startswith("qwen3"):
        body["enable_thinking"] = False
    for k in range(retries):
        try:
            r = requests.post(ENV["LLM_API_URL"], json=body, timeout=300,
                              headers={"Authorization": f"Bearer {ENV['LLM_API_KEY']}"})
            if r.status_code == 400:  # 参数 / 内容审核错误，重试无用
                raise RuntimeError(f"400 {r.text[:300]}")
            r.raise_for_status()
            j = r.json()
            return j["choices"][0]["message"]["content"], j.get("usage", {})
        except Exception as e:  # noqa: BLE001
            if k == retries - 1:
                raise
            time.sleep(2 ** k * 3)


# ---------- 数据 ----------
def cases():
    qs = json.load(open(f"{D}/gear/qid_sentences.json"))
    cs = json.load(open(f"{D}/gear/pid_sentences.json"))
    qids = json.load(open(f"{D}/gear/test_qids.json"))
    pc = json.load(open(f"{D}/gear/pid_charges.json"))
    out = [("q" + q, "".join(qs[q]), None) for q in qids]
    out += [("c" + p, "".join(v), pc[p]) for p, v in cs.items()]
    return out


JUREX = json.load(open(f"{D}/jurex/flattened_jurex4e.json"))
KB = json.load(open(f"{D}/lrml_kb.json")) if os.path.exists(f"{D}/lrml_kb.json") else {}
MAPPED = {"伪造、变造居民身份证罪": "伪造、变造、买卖身份证件罪", "生产、销售、提供假药罪": "生产、销售假药罪"}


# ---------- prompts（逐字取自 JUREX LCR_experiment/LCR_lecard/*.py） ----------
P_PREDICT = ("你是一个刑法领域的律师。请根据罪名列表，对于以下案情事实，请判断它包含了罪名列表中的哪些罪名。"
             "请注意，你只需要输出罪名，不要输出多余的信息，罪名必须在罪名列表中。罪名之间用‘，’隔开。")
P_FET = ("你是一个刑法领域的专家。请对以下案情事实，根据中国刑法知识，按顺序输出："
         "1、犯罪的四要件，包括："
         "犯罪客体（指某种抽象的社会利益的具像化，比如侵犯人身利益的对象是生命权，侵犯财产利益案件的对象是手机、钱包等）、"
         "犯罪客观方面（指犯罪活动的客观事实，包括触发犯罪的关键行为，如偷、抢，和行为所导致的结果，如重伤、死亡、财产损失等）、"
         "犯罪主体（通常为一般主体，但是有特殊主体，比如国家工作人员）、"
         "犯罪主观方面（故意或者过失）"
         "2.罪名：只输出具体的罪名"
         "3.相关法条：只输出法条编号。")
FEWSHOT = """输出格式为json。对于案件中涉及的每个罪名，分别输出为一个字典。参考样例如下：
          {"罪名1":{"犯罪的四要件":{
                "犯罪客体":"人身利益：被害人王某某的生命权、财产利益：车辆",
                "犯罪客观方面":"被告人吴某某酒后驾驶小型轿车与被害人王某某相撞，造成被害人王某某当场死亡及车辆损坏",
                "犯罪主体":"司机被告人吴某某",
                "犯罪主观方面":"过失"},
                "罪名":"交通肇事罪",
                "相关法条":"第133条"},
            "罪名2":{"犯罪的四要件":{
                "犯罪客体":"社会管理秩序...",
                "犯罪客观方面":"...",
                "犯罪主体":"...",
                "犯罪主观方面":"故意"},
                "罪名":"伪造、变造、买卖国家机关公文、证件、印章罪",
                "相关法条":"第280条第1款"}}"""
# LRML 扩展：仅在 expert_cond 中追加
P_COND = ("\n此外，下面给出刑法知识图谱（LegalRuleML）中这些罪名的条件清单，每条有编号。"
          "请逐条判断案情事实是否明确满足该条件，在每个罪名的字典中增加一个字段 \"满足的条件\"，"
          "值为满足的条件编号列表（例如 [\"t7939\", \"t7942\"]）；不满足或案情未提及的不要列入。")


def deal_pred(s):
    # 同 JUREX run 代码，但不按“、”切分（罪名本身含“、”）
    s = s.strip().rstrip("。")
    return [x.strip() + ("" if x.strip().endswith("罪") else "罪") for x in re.split(r"[，\n,（]", s) if x.strip()]


def charges_of(cid, gold, preds):
    raw = gold if gold is not None else preds.get(cid, [])
    return sorted({MAPPED.get(c, c) for c in raw})


def fmt_dict(d):
    return "".join(f"\n- {k}:{v} " for k, v in d.items())


def build_prompt(fact, charges, guide, is_query):
    ref = ""
    known = [c for c in charges if c in JUREX]
    other = [c for c in charges if c not in JUREX]
    if guide in ("expert", "expert_cond") and known:
        ref += ("\n相关罪名和专家四要件（仅为参考的关键词，你需要根据案情具体分析）：" if is_query else
                f"\n相关罪名: {known}. 和专家四要件（仅为参考的关键词，你需要根据案情具体分析）：")
        ref += "".join(f"{c}{fmt_dict(JUREX[c])}\n" for c in known)
    if guide in ("expert", "expert_cond") and other and not is_query:
        ref += f"\n其他参考罪名：{other}"
    tail = "\n你只需要输出json，不要输出多余的信息。"
    if guide == "expert_cond":
        conds = [(c, x) for c in charges if c in KB for x in KB[c]["conditions"]]
        if conds:
            tag = {"aggr": "法定情节", "excl": "罪与非罪", "conv": "此罪与彼罪/转化"}
            ref += P_COND + "".join(f"\n[{x['id']}]（{c}·{tag[x['type']]}）{x['text']}" for c, x in conds)
    return P_FET + FEWSHOT + "\n请根据以下案情事实，输出分析结果。请注意，不要直接回答样例的内容。案情事实：" + fact + ref + tail


# ---------- 运行 ----------
def run_many(jobs, outdir, model, workers, max_tokens=2048):
    os.makedirs(outdir, exist_ok=True)
    todo = [(i, p) for i, p in jobs if not os.path.exists(f"{outdir}/{i}.json")]
    print(f"{len(jobs)} jobs, {len(todo)} to run -> {outdir}", file=sys.stderr)
    lock, done, tok = threading.Lock(), [0], [0, 0]

    def one(job):
        i, p = job
        try:
            out, usage = chat(p, model, max_tokens)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {i}: {str(e)[:120]}", file=sys.stderr)
            if "data_inspection_failed" in str(e):  # 平台内容审核拦截：记为空输出，不再重试
                json.dump({"id": i, "model": model, "output": "", "blocked": True},
                          open(f"{outdir}/{i}.json", "w"), ensure_ascii=False)
            return
        json.dump({"id": i, "model": model, "output": out, "usage": usage},
                  open(f"{outdir}/{i}.json", "w"), ensure_ascii=False)
        with lock:
            done[0] += 1
            tok[0] += usage.get("prompt_tokens", 0); tok[1] += usage.get("completion_tokens", 0)
            if done[0] % 50 == 0 or done[0] == len(todo):
                print(f"  {done[0]}/{len(todo)}  tokens in={tok[0]} out={tok[1]}", file=sys.stderr)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, todo))


def load_preds():
    p = os.path.join(HERE, "llm_cache/predict")
    out = {}
    if os.path.isdir(p):
        for f in os.listdir(p):
            j = json.load(open(f"{p}/{f}"))
            out[j["id"]] = [c for c in deal_pred(j["output"]) if c in JUREX or c in KB]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["predict", "fet"])
    ap.add_argument("--guide", default="expert", choices=["none", "expert", "expert_cond"])
    ap.add_argument("--model", default="qwen2.5-72b-instruct")
    ap.add_argument("--predict_model", default="qwen-plus")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个候选（查询全跑）")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    allc = cases()
    if a.step == "predict":
        plist = P_PREDICT + f"罪名列表：{str(list(JUREX))}\n案情事实："
        jobs = [(i, plist + fact) for i, fact, g in allc if g is None]
        run_many(jobs, os.path.join(HERE, "llm_cache/predict"), a.predict_model, a.workers, 256)
        return
    preds = load_preds()
    qs = [x for x in allc if x[2] is None]
    cs = [x for x in allc if x[2] is not None]
    if a.limit:
        cs = cs[:a.limit]
    jobs = []
    for i, fact, gold in qs + cs:
        ch = charges_of(i, gold, preds)
        jobs.append((i, build_prompt(fact, ch, a.guide, gold is None) if a.guide != "none"
                     else P_FET + FEWSHOT + "\n请根据以下案情事实，输出分析结果。请注意，不要直接回答样例的内容。案情事实："
                     + fact + "\n你只需要输出json，不要输出多余的信息。"))
    run_many(jobs, os.path.join(HERE, f"llm_cache/fet_{a.guide}_{a.model}"), a.model, a.workers)


if __name__ == "__main__":
    main()
