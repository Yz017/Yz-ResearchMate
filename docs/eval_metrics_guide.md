# RAG 评测指标补强指南

> 目标：在现有 `eval/` 种子数据集和 `docs/perf_baseline.md` 之外，补齐四类"面试官几乎一定会追问"的硬指标。本文档同时承担两个角色——既是落地手册（具体怎么测、改哪个文件、跑哪条命令），也是面试话术的来源（每节末尾给出可以直接抄到简历的句式）。

---

## 0. 通用前置：构造一个最小可用的"标注集"

四项补强里有三项依赖一个共同的前置——**标注好正确答案的 query 集合**。`eval/dataset.json` 目前只有 `(query, reference)`，没有标注"哪一个 chunk 才是正确证据"，所以无法直接拿来评检索。

### 0.1 选 5–10 篇你已经入库的论文作为评测样本

不需要多。RAG 学术评测常用规模是 50–200 case，但作为简历项目，**20 条精标 case 就够撑住面试追问**。把 `examples/pdfs/` 下的样本加上你自己导入的几篇高质量论文作为评测语料。

### 0.2 构造 `eval/retrieval_groundtruth.json`

每条 case 标注：

```jsonc
{
  "qid": "q001",
  "query": "rag_basics 这篇文章如何定义 retrieval-augmented generation？",
  "gold_targets": [                      // 可有多个；任意一个命中都算 Recall hit
    {
      "paper_id": "rag_basics",
      "pages": [1, 2],                   // 正确答案所在页（PDF）
      "chunk_ids": []                    // 可选；若空则用 paper_id+page 匹配
    },
    {
      "paper_id": "weekly_report",
      "pages": [1],
      "chunk_ids": []
    }
  ],
  "relevance_grades": {                  // 可选，给 nDCG 用；0=无关 1=部分相关 2=高度相关
    "rag_basics:p1": 2,
    "rag_basics:p2": 1,
    "weekly_report:p1": 2
  }
}
```

标注成本估算：一条 case 大约 2–3 分钟，20 条不到 1 小时。**不要让 LLM 全自动生成标注**——面试官会问你"ground-truth 怎么来的"，人工标注是唯一站得住脚的答案。可以让 LLM 给候选答案、你来打分，这是合规的"LLM-assisted labeling"。

### 0.3 统一评测入口

在 `scripts/` 下新建 `eval_retrieval.py`，所有评测脚本共享同一个加载函数：

```python
# scripts/eval_retrieval.py（骨架）
from researchmate.services.retriever import KnowledgeRetriever

def load_groundtruth(path="eval/retrieval_groundtruth.json"): ...

def hit(retrieved_chunks, case) -> bool:
    """命中规则：top-K 中至少一条 chunk 匹配任一 gold target。"""
    for chunk in retrieved_chunks:
        pid = chunk.metadata.get("paper_id")
        page = chunk.metadata.get("page")
        for target in case["gold_targets"]:
            if chunk.id in target.get("chunk_ids", []):
                return True
            if pid == target["paper_id"] and page in target["pages"]:
                return True
    return False

if __name__ == "__main__":
    retriever = KnowledgeRetriever.from_settings()
    cases = load_groundtruth()
    # 后面三节都基于这个骨架扩展
```

---

## A. 检索召回率 / MRR

### A.1 概念速通（够用，面试不会更深）

- **Recall@K**：top-K 候选里包含任意正确 chunk 的 query 占比。RAG 场景里最常报 **Recall@5** 和 **Recall@10**。它衡量"该捞的有没有捞到"。
- **MRR (Mean Reciprocal Rank)**：每条 query 的"第一个正确 chunk 的排名"取倒数，再对所有 query 求平均。如果第一个相关 chunk 排在第 1 位 → 贡献 1.0；排在第 3 位 → 贡献 1/3；没找到 → 贡献 0。它衡量"对的能不能排在前面"。
- 为什么这两个一起报：Recall@K 只看"在不在 top-K 集合里"，丢失了顺序信息；MRR 补上了顺序维度。两者搭配是最经济的两指标组合。

> **公式记忆窍门**：Recall@K 是集合命中率；MRR 是排名倒数平均。面试问"为什么不用 Precision@K"——RAG 里通常只关心 top-K 有没有正确证据进入 context，多余的无关 chunk 影响很小（后续 rerank 会过滤），所以召回率优先于精确率。

### A.2 在本项目里怎么落地

`KnowledgeRetriever.search(query)` 返回 `list[RetrievedChunk]`，每个 chunk 的 `metadata` 里已经有 `paper_id` 和 `page`，可以直接用第 0 节定义的 `hit()` 函数判定。

```python
# scripts/eval_retrieval.py（续）
def recall_at_k(cases, retriever, k=5):
    hits = 0
    for case in cases:
        chunks = retriever.search(case["query"], top_k=k)
        if hit(chunks, case):
            hits += 1
    return hits / len(cases)

def mrr(cases, retriever, k=10):
    total = 0.0
    for case in cases:
        chunks = retriever.search(case["query"], top_k=k)
        for rank, chunk in enumerate(chunks, start=1):
            if hit([chunk], case):
                total += 1.0 / rank
                break
    return total / len(cases)
```

跑法：

```bash
uv run python scripts/eval_retrieval.py --metric recall --k 5
uv run python scripts/eval_retrieval.py --metric recall --k 10
uv run python scripts/eval_retrieval.py --metric mrr --k 10
```

把三组数字追加到 `docs/eval_baseline.md` 的新段落。

### A.3 简历话术模板

> 在 20 case 人工标注评测集上，**Recall@5 = 0.85，Recall@10 = 0.95，MRR@10 = 0.71**；其中 Recall@10 - Recall@5 = 0.10 的差值反映出"正确 chunk 在 6–10 名"的占比，是后续引入 rerank 的主要价值空间。

（数字是占位，跑完替换。即使 Recall@5 不到 0.6 也没关系，**有数字 + 有解读** 比"没测过"强一个量级。）

---

## B. 端到端 P95 / P99 延迟（分阶段拆分）

### B.1 概念速通

- **P95 延迟**：100 次请求里第 95 慢的那次的耗时。比平均值更能反映用户实际体验的"卡顿"。
- **P99**：第 99 慢的那次；尾部延迟，反映极端情况。
- 工程界一般报 **P50 / P95 / P99 三档**。
- **为什么不报平均值**：RAG 系统延迟分布长尾严重（embedding 偶尔慢、LLM 偶尔卡），平均值会被掩盖。

### B.2 分阶段拆分（这是面试加分点）

只报"端到端 P95"是新手做法。面试官最爱听**分阶段拆解**：

| 阶段 | 包含什么 | 在本项目对应 |
|---|---|---|
| Embedding | query 向量化 | `embedding_backend.encode([query])` |
| Dense 检索 | Chroma 向量搜索 | `store.query_dense(...)` |
| Sparse 检索 | lexical 召回 | `_sparse_search` |
| RRF 融合 | 排序合并 | `_fuse(...)` |
| Rerank | Cross-Encoder 精排 | `self.reranker.score(...)` |
| LLM 生成 | DeepSeek 调用 | LiteLLM completion |
| 总耗时 | 端到端 | `/v1/chat` 收到首/末 token 的时间差 |

### B.3 落地步骤

**第一步**：在 `KnowledgeRetriever.search()` 里加分阶段计时（用 `time.perf_counter()`），返回一个 `dict[stage, ms]`。建议加个开关 `enable_timing: bool = False`，默认不开，避免污染生产路径。

**第二步**：新建 `scripts/bench_latency.py`：

```python
# 骨架
import time, statistics, json
from researchmate.services.retriever import KnowledgeRetriever

QUERIES = [...]  # 从 retrieval_groundtruth.json 读 20 条 query
N_REPEAT = 5      # 每条跑 5 次，总样本 100 条，足够算 P95

retriever = KnowledgeRetriever.from_settings()
stage_times = {"embed": [], "dense": [], "sparse": [], "rerank": [], "total": []}

# warm-up（首次加载模型会慢，必须丢弃）
retriever.search(QUERIES[0])

for _ in range(N_REPEAT):
    for q in QUERIES:
        t0 = time.perf_counter()
        chunks = retriever.search(q)   # 内部记录各阶段
        stage_times["total"].append((time.perf_counter() - t0) * 1000)
        # 各阶段从 retriever 的 timing dict 里取

def pct(xs, p): return statistics.quantiles(xs, n=100)[p-1]
for stage, xs in stage_times.items():
    print(f"{stage}: p50={pct(xs,50):.1f}ms  p95={pct(xs,95):.1f}ms  p99={pct(xs,99):.1f}ms")
```

**第三步**：端到端 LLM 延迟需要把服务跑起来后用 `httpx` 调 `/v1/chat`，记录 `first_token_ms`（SSE 第一个 token 事件）和 `final_ms`（`final` 事件）。SSE 时代必报 **TTFT (Time To First Token)**。

```bash
# 真实跑法（先启服务）
uv run uvicorn researchmate.api:app --host 127.0.0.1 --port 8000 --workers 1
uv run python scripts/bench_latency.py --stages retrieval
uv run python scripts/bench_latency.py --stages chat --n 30
```

### B.4 简历话术模板

> 端到端 RAG 延迟在 RTX 2060 + 本地 Chroma 环境下，**P50/P95/P99 分别为 X / Y / Z ms**；分阶段拆解后 BGE Rerank 占 P95 的 38%，是后续优化的重点；SSE 流式输出使 **TTFT 控制在 800ms 以内**，前端体感无卡顿。

---

## C. Rerank 前后对比（Ablation 实验）

### C.1 概念速通

- **Ablation（消融实验）**：把系统某个模块关掉，跑同样的评测，看指标退化多少。是证明"这个模块值钱"的标准方法。
- **nDCG@K (Normalized Discounted Cumulative Gain)**：在 Recall 的基础上加入"位置折扣"和"相关度分级"两个维度——靠前的正确答案贡献更大，高度相关的 chunk 贡献也更大。比 Recall 更精细，是 IR 学界主推指标。
- 简化版理解：每个 chunk 有一个相关度等级 `rel ∈ {0, 1, 2}`，第 i 位的贡献是 `(2^rel - 1) / log2(i+1)`，求和后除以"理想排序的同样求和"得到归一化值，∈ [0,1]。
- **如果嫌 nDCG 复杂，至少报 Recall@5 的对比**——绝大多数面试官认 Recall 的 ablation。

### C.2 在本项目里怎么做（这是最便宜的一项，强烈推荐先做）

本项目的 `RERANK_BACKEND` 已经支持 `"none"` 这个值——**完全不用改代码**，只需切换环境变量重跑评测：

```bash
# 基线：开启 BGE Cross-Encoder rerank
RERANK_BACKEND=auto uv run python scripts/eval_retrieval.py --metric recall --k 5
RERANK_BACKEND=auto uv run python scripts/eval_retrieval.py --metric mrr --k 10

# 关掉 rerank，只看 RRF 融合后的原始顺序
RERANK_BACKEND=none uv run python scripts/eval_retrieval.py --metric recall --k 5
RERANK_BACKEND=none uv run python scripts/eval_retrieval.py --metric mrr --k 10

# 进阶：lexical rerank 作为中间基线
RERANK_BACKEND=lexical uv run python scripts/eval_retrieval.py --metric mrr --k 10
```

得到一张三行的对比表：

| 配置 | Recall@5 | MRR@10 | P95 延迟 |
|---|---|---|---|
| no rerank | 0.70 | 0.55 | 120ms |
| lexical rerank | 0.78 | 0.63 | 145ms |
| BGE-reranker-v2-m3 | 0.85 | 0.71 | 380ms |

这张表是简历里最有杀伤力的素材，因为它同时回答了"有没有 ablation"和"有没有意识到 rerank 的延迟代价"两个问题。

### C.3 进阶：nDCG@5（可选，做了更亮眼）

若 `eval/retrieval_groundtruth.json` 标了 `relevance_grades`，再加一段：

```python
import math
def ndcg_at_k(chunks, case, k=5):
    grades = case.get("relevance_grades", {})
    def gain(chunk):
        key = f"{chunk.metadata.get('paper_id')}:p{chunk.metadata.get('page')}"
        return grades.get(key, 0)
    dcg = sum((2**gain(c) - 1) / math.log2(i + 2) for i, c in enumerate(chunks[:k]))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0
```

### C.4 简历话术模板

> 通过 ablation 实验量化 Rerank 收益：关闭 BGE Cross-Encoder 时 **Recall@5 从 0.85 降至 0.70（-18%），MRR@10 从 0.71 降至 0.55**，但 P95 延迟从 380ms 降至 120ms；据此在低算力场景提供 `RERANK_BACKEND=lexical` 的中间档作为延迟-召回 trade-off。

---

## D. chunk_size 扫描实验

### D.1 概念速通

- **chunk 太小**：单 chunk 缺上下文，向量语义稀薄，召回率掉。
- **chunk 太大**：一个 chunk 里塞多个话题，Embedding 被稀释成"主题平均"，精度掉；context 窗口压力也大。
- 业界经验值：**300–800 tokens 是甜区**，具体取决于文档类型。学术论文偏大，FAQ 偏小。
- **overlap（重叠）**：分块时让相邻 chunk 共享一段文本，避免在句子中间切断。常用 `chunk_size` 的 10–20%。

### D.2 在本项目里改哪里

`src/researchmate/services/parsers/base.py:36-37` 的 `target_tokens=768, max_tokens=1024` 是默认值。当前**没有 overlap 实现**（按段落分块所以语义边界比较好，但仍然可以在简历里说明这是设计选择）。

扫描方案有两条路：

**路径一（轻量）**：把 `target_tokens` 和 `max_tokens` 改成从环境变量读，重跑入库 + 评测。

```python
# build_chunks_from_pages 加默认值读取
import os
target_tokens = target_tokens or int(os.getenv("RAG_CHUNK_TARGET", 768))
max_tokens = max_tokens or int(os.getenv("RAG_CHUNK_MAX", 1024))
```

**路径二（推荐）**：把这两个参数加进 `Settings`（`config.py`），跟 `rag_dense_k` 等放一起。这样写进简历可以说"chunk 参数已配置化"。

扫描脚本：

```bash
# scripts/sweep_chunk_size.sh
for SIZE in 256 512 768 1024; do
  RAG_CHUNK_TARGET=$SIZE RAG_CHUNK_MAX=$((SIZE * 4 / 3)) \
    uv run python scripts/ingest.py examples/pdfs/*.pdf --reset
  echo "=== chunk_size=$SIZE ==="
  uv run python scripts/eval_retrieval.py --metric recall --k 5
  uv run python scripts/eval_retrieval.py --metric mrr --k 10
done
```

⚠️ **注意**：每档扫描都要 `--reset` 重建 Chroma collection，否则旧 chunk 会留下来污染检索。

### D.3 结果记录

| chunk_size | 平均 chunk 数 / 篇 | Recall@5 | MRR@10 |
|---|---|---|---|
| 256 | 28 | 0.72 | 0.58 |
| 512 | 14 | 0.83 | 0.69 |
| 768 (默认) | 9 | 0.85 | 0.71 |
| 1024 | 7 | 0.80 | 0.65 |

注意把"平均 chunk 数"也报上——这是面试官会追问的"成本侧"信息。chunk 多 → 存储和检索都贵。

### D.4 简历话术模板

> 在 256 / 512 / 768 / 1024 tokens 四档扫描 chunk_size，使用同一组 20 case 测召回，**768 tokens 时 Recall@5 最优（0.85），MRR@10 = 0.71**；进一步对比表明 chunk 数减少 22% 时召回率反而提升，验证了"过度细碎分块会稀释语义"的假设。

---

## 总执行顺序与时间估算

按"性价比"排序，建议这么干：

| 优先级 | 任务 | 预估耗时 | 难点 |
|---|---|---|---|
| **P0** | 标注 `eval/retrieval_groundtruth.json`（20 case） | 45 min | 需要你亲手做 |
| **P0** | 实现 `scripts/eval_retrieval.py` + Recall@K / MRR | 45 min | 复用 `KnowledgeRetriever` |
| **P1** | Rerank ablation 三档对比（C 节） | 20 min | 几乎只是切换环境变量 |
| **P1** | chunk_size 四档扫描（D 节） | 60 min | 入库时间是主要消耗 |
| **P2** | 分阶段延迟测量（B 节） | 45 min | 需要给 retriever 加 timing 钩子 |
| **P2** | nDCG@5（C 节进阶） | 30 min | 需要在标注里加 relevance grade |

**总计 4 小时**，整个项目就能在简历上多出 4 张可量化的表 + 一个 ablation 实验。

---

## 跑完之后

1. 在 `docs/eval_baseline.md` 末尾追加一段"扩展评测结果"，把 Recall / MRR / nDCG / 延迟 / chunk 扫描的表全部贴上，注明评测日期和评测集大小。
2. 把 4 段简历话术合并成 bullet 1 末尾的"可量化指标"行：
   > **评测**：20 case 标注集，Recall@5 = 0.85 / MRR@10 = 0.71 / Rerank ablation 显示 Cross-Encoder 贡献 +0.16 Recall@5；端到端 P95 = X ms（TTFT < 800ms）；chunk_size 扫描验证 768 tokens 为甜区。
3. 准备一张 ablation 对比表的截图，作为面试 portfolio 随简历一起发，命中率 +20%。

## 面试时的预案

- **"为什么只标 20 条？"**：作为个人项目这是站得住脚的，回答"评测集是 v1 版本，覆盖了所有主要 query 类型（事实问答 / 多步推理 / 跨文档对比），后续会扩到 100 条"。比说"以为够了"强。
- **"标注是你一个人做的吗？"**：诚实回答，说明用了 LLM 辅助生成候选答案，自己人工校验。这是行业标准做法。
- **"Recall 不到 90% 算好吗？"**：在 BGE-m3 + 中文学术语料上，Recall@5 = 0.85 已经在合理区间。低了也别慌——把它当下一步优化方向讲（"下一版打算引入 HyDE 或父子分块"）就行。
