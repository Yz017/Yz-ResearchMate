# 多格式文档入库任务单

> 目标：在现有 PDF 入库能力上，新增对 `.txt` / `.md` / `.docx` / `.html` 的支持。
> 总策略：保留现有分块流水线，仅替换"文档→纯文本+结构"的前置抽取层；把入口从 `parse_pdf_to_chunks` 上提为格式无关的 `parse_document_to_chunks`。
>
> 进度图例：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 已完成 · `[-]` 取消/跳过

> 当前源码状态：多格式入库已经落地。`SUPPORTED_EXTENSIONS` 现为 `.pdf` / `.txt` / `.md` / `.markdown` / `.docx` / `.html` / `.htm`，`pdf_parser.py` 已保留为兼容垫片，API/CLI/scripts 均调用格式无关的 `ingest_document` / `parse_document_to_chunks` 路径。
>
> 当前已知限制：扫描版 PDF 仍需先做 OCR；DOCX 当前解析正文段落和标题，表格不是解析重点；HTML 入库只解析本地文件内容，不递归抓取链接；PDF 尚未设置单文件大小上限。

---

## PR-1：重构（行为不变，只支持 .pdf）

目标：把 `pdf_parser.py` 拆分为可扩展的 `parsers/` 包，且现有测试全部通过。

### 1.1 创建 parsers 包骨架
- [x] 新建目录 `src/researchmate/services/parsers/`
- [x] 新建 `src/researchmate/services/parsers/__init__.py`，导出 `parse_document_to_chunks`、`SUPPORTED_EXTENSIONS`、`UnsupportedFormatError`
- [x] 在 `__init__.py` 中定义 `SUPPORTED_EXTENSIONS`
- [x] 定义 `class UnsupportedFormatError(ValueError)`

### 1.2 抽取共享分块基础模块
- [x] 新建 `src/researchmate/services/parsers/base.py`
- [x] 从 `pdf_parser.py` 迁移到 `base.py`：paragraph、sentence、section 相关正则
- [x] 从 `pdf_parser.py` 迁移到 `base.py`：chunking、paragraph split、long paragraph split、section detection、title inference
- [x] 导出包内复用函数
- [x] 在 `base.py` 中定义通用 `build_chunks_from_pages(pages, *, paper_id, title, ...)` 函数

### 1.3 PDF extractor 拆出
- [x] 新建 `src/researchmate/services/parsers/pdf.py`
- [x] 迁移 `_extract_with_pdfplumber` 和 `_extract_with_pypdf` 进 `pdf.py`
- [x] 在 `pdf.py` 内定义 `extract_pages(path: Path) -> list[ParsedPage]`，承担原 `extract_pdf_pages` 的兜底逻辑
- [x] 保留 `PdfParseError` 类（仍可从 `parsers.pdf` 导出）

### 1.4 dispatch 派发器
- [x] 新建 `src/researchmate/services/parsers/dispatch.py`
- [x] 实现 `parse_document_to_chunks(path, *, paper_id, title, oss_key, user_id, tags, ingested_at, target_tokens=768, max_tokens=1024)`
- [x] 按 `path.suffix.lower()` 选择 extractor；不在 `SUPPORTED_EXTENSIONS` 中时抛 `UnsupportedFormatError`
- [x] 调用 extractor 拿到 `pages`，再调用 `base.build_chunks_from_pages` 产出 chunks

### 1.5 旧入口转薄壳
- [x] 修改 `src/researchmate/services/pdf_parser.py`：仅保留对 `parsers.dispatch.parse_document_to_chunks` 的 re-export 作为 `parse_pdf_to_chunks` 别名
- [x] 保留 `extract_pdf_pages` 和 `PdfParseError` 的导出（向后兼容）
- [x] 在文件顶部加一行注释说明这是兼容垫片

### 1.6 调用点全部切到新入口
- [x] 修改 `src/researchmate/services/__init__.py`：同时导出 `parse_pdf_to_chunks`（兼容）和 `parse_document_to_chunks`（新）
- [x] 修改 `src/researchmate/services/knowledge_base.py`：import 改为 `from researchmate.services.parsers import parse_document_to_chunks`
- [x] 修改 `knowledge_base.py` 的调用为 `parse_document_to_chunks(...)`

### 1.7 测试
- [x] 运行 `pytest tests/unit/test_pdf_parser.py` 验证旧用例通过
- [x] 运行单元测试套件 `pytest tests/unit` 验证无回归
- [x] 跑一次 `python scripts/ingest.py examples/pdfs/rag_basics.pdf` 端到端确认

### 1.8 提交
- [-] commit/PR 手续未在本工作区执行

---

## PR-2：TXT + Markdown 支持

### 2.1 依赖
- [x] `pyproject.toml` `dependencies` 增加 `"charset-normalizer>=3.3,<4.0"`
- [x] `pyproject.toml` `dependencies` 增加 `"markdown-it-py>=3.0,<4.0"`
- [x] `pyproject.toml` mypy `overrides` 增补 `markdown_it.*`
- [x] 运行 `uv lock` 更新 `uv.lock`
- [x] 依赖同步已在当前环境验证

### 2.2 TXT extractor
- [x] 新建 `src/researchmate/services/parsers/txt.py`
- [x] 实现 `extract_pages(path) -> list[ParsedPage]`：优先常见编码，失败后用 `charset-normalizer`，最终回退 UTF-8（errors=`replace`）
- [x] 整个文件作为一个 `ParsedPage(page_number=1, text=...)` 返回（分段交给共享 chunker）

### 2.3 Markdown extractor
- [x] 新建 `src/researchmate/services/parsers/markdown.py`
- [x] 用 `markdown-it-py` 解析为 token 流
- [x] 遍历 token，遇到 `heading_open` 把后续 `inline` 文本作为 section 标记行（形如 `# Section Title`）注入纯文本流
- [x] 代码块（`fence`/`code_block`）原样保留为段落，不被 heading 正则误识
- [x] 列表项、段落 token 顺序拼接为纯文本
- [x] 返回单页 `ParsedPage`

### 2.4 注册到 dispatch
- [x] 修改 `parsers/__init__.py` 的 `SUPPORTED_EXTENSIONS`：加入 `.txt`、`.md`、`.markdown`
- [x] 修改 `parsers/dispatch.py` 的 extractor 表，注册 txt 与 md

### 2.5 单元测试
- [x] 新建 `tests/unit/test_parsers_txt.py`
- [x] 测：UTF-8 中文文件能正确解析为 chunks
- [x] 测：GBK 文件能解析或回退后不抛异常
- [x] 测：空文件触发明确异常
- [x] 新建 `tests/unit/test_parsers_markdown.py`
- [x] 测：`# H1` / `## H2` 被识别为 section
- [x] 测：fenced code block 内容不被识别为 heading
- [x] 测：列表与段落顺序保持

### 2.6 端到端验证
- [x] 用 `scripts/ingest.py README.md` 入库一份 Markdown 文件
- [x] 检索路径由单元测试和离线脚本验证覆盖

### 2.7 提交
- [-] commit/PR 手续未在本工作区执行

---

## PR-3：DOCX 支持

### 3.1 依赖
- [x] `pyproject.toml` `dependencies` 增加 `"python-docx>=1.1,<2.0"`
- [x] `pyproject.toml` mypy `overrides` 增补 `docx.*`
- [x] `uv lock` 和依赖同步

### 3.2 DOCX extractor
- [x] 新建 `src/researchmate/services/parsers/docx.py`
- [-] 未使用 `python-docx` 运行时解析；当前实现直接读取 DOCX zip 中的 `word/document.xml`
- [x] 遍历 XML 段落：`Heading*` 样式输出为 section 标记，其它作为正文段落
- [-] 当前实现不处理表格
- [x] 返回单页 `ParsedPage`

### 3.3 注册到 dispatch
- [x] `SUPPORTED_EXTENSIONS` 加入 `.docx`
- [x] dispatch 表注册 docx extractor

### 3.4 单元测试
- [x] 新建 `tests/unit/test_parsers_docx.py`
- [-] 测试使用 zip/XML 生成最小 DOCX 样例
- [x] 测：Heading 段落被识别为 section
- [x] 测：普通段落正确切块

### 3.5 端到端验证
- [-] 未新增真实 docx 样例到 `examples/docs/`
- [x] DOCX parser 路径由单元测试覆盖

### 3.6 提交
- [-] commit/PR 手续未在本工作区执行

---

## PR-4：HTML 支持 + 引用 citation 适配

### 4.1 依赖
- [x] `pyproject.toml` `dependencies` 增加 `"beautifulsoup4>=4.12,<5.0"`
- [-] 未显式新增 `"lxml>=5.0,<6.0"`；当前环境由依赖树提供 HTML parser 所需运行时
- [x] `pyproject.toml` mypy `overrides` 增补 `bs4.*`
- [x] `uv lock` 和依赖同步

### 4.2 HTML extractor
- [x] 新建 `src/researchmate/services/parsers/html.py`
- [x] 用 `bs4.BeautifulSoup(content, "lxml")` 解析
- [x] 解析前限制文件大小（>10 MB 抛错）
- [x] 移除 `<script>` `<style>` `<nav>` `<footer>` `<header>` 节点
- [x] 按 DOM 顺序遍历，遇 `h1-h6` 注入 section 标记
- [x] 保留 `<p>` `<li>` 文本顺序
- [x] 编码：先尝试 meta/XML charset，回退 charset-normalizer，再回退 UTF-8

### 4.3 注册到 dispatch
- [x] `SUPPORTED_EXTENSIONS` 加入 `.html`、`.htm`
- [x] dispatch 表注册 html extractor

### 4.4 citation 适配
- [x] 修改 `src/researchmate/services/documents.py` 的 citation 属性
- [x] 规则：`page <= 1 且 section 非空且非 "unknown"` → `[source: {paper_id} · {section}]`，否则保留 `[source: {paper_id}, p.{page}]`
- [x] 更新 `RetrievedChunk.citation` 的回退逻辑，保持与新规则一致
- [x] 注：向量库已写入的旧 chunk 的 metadata.citation 仍按旧格式呈现，不做迁移

### 4.5 paper_id 冲突预检
- [x] 在 `KnowledgeBaseService.ingest_document` 中：调用 parse 前检查是否已有同 `paper_id` 的不同 `source_path`
- [x] 若冲突，抛带提示信息的异常，建议用户传 `--paper-id` 或删除既有文档
- [x] 单测覆盖该路径

### 4.6 服务层方法重命名
- [x] `knowledge_base.py`：`ingest_pdf` → `ingest_document`
- [x] 保留 `ingest_pdf = ingest_document` 作为薄别名
- [x] 修改 `src/researchmate/api/app.py` 调用为 `kb_service.ingest_document`
- [x] 修改 API cache path：按 `Path(key).suffix` 保留原扩展名；若 key 无扩展名则抛 `UnsupportedFormatError`
- [x] 修改 `scripts/ingest.py`：位置参数 `path`；函数 `ingest_pdf_paths` → `ingest_document_paths`；保留旧函数名别名

### 4.7 单元测试
- [x] 新建 `tests/unit/test_parsers_html.py`
- [x] 测：`<script>`/`<style>` 内容被剔除
- [x] 测：`<h1>`~`<h3>` 被识别为 section
- [x] 测：超大文件触发预期错误
- [x] 新建/补充 `tests/unit/test_documents_citation.py`
- [x] 测：`page=1 + section="Methods"` → `[source: xxx · Methods]`
- [x] 测：`page=5 + section="Methods"` → `[source: xxx, p.5]`（PDF 行为不变）

### 4.8 端到端验证
- [-] 未逐一通过 API job handler 上传所有格式
- [x] 各格式解析和 citation 行为由单元测试覆盖
- [x] `scripts/smoke_test.py` 现有路径仍覆盖 PDF 服务入库

### 4.9 CLI 文档
- [x] 修改 `src/researchmate/cli/main.py` 的示例 docstring，补 `.md` 和 `.docx` 用例
- [x] 修改 `scripts/ingest.py` 的 argparse `description` 与 `--help`

### 4.10 提交
- [-] commit/PR 手续未在本工作区执行

---

## 收尾任务（PR-4 合并后）

### 5.1 文档
- [x] 更新 `README.md`：在功能列表里把 PDF-only ingest 改为多格式 document ingest
- [x] 更新 `docs/` 下相关说明
- [x] OpenAPI schema 当前没有 PDF-only 字段描述需要替换

### 5.2 兼容垫片清理（下一个 minor 版本前评估）
- [ ] 评估是否移除 `pdf_parser.py` 兼容垫片
- [ ] 评估是否移除 `ingest_pdf` 服务方法别名
- [ ] 在 CHANGELOG 或 release notes 注明 API 变化

### 5.3 已知限制记录
- [x] 在 `docs/` 中记录：DOCX 表格暂不入库
- [x] 在 `docs/` 中记录：扫描版 PDF 仍需 OCR 才能入库
- [x] 在 `docs/` 中记录：HTML 入库不递归抓取链接

---

## 风险检查清单（每个 PR 合并前过一遍）

- [x] OSS key 没有扩展名时的报错路径已覆盖到 API handler 逻辑
- [x] 同 `paper_id` 不同 `source_path` 不会静默覆盖既有 chunks
- [~] HTML 文件 >10 MB 有边界处理；PDF 大小边界未单独限制
- [x] 编码异常路径有多级回退
- [x] 向量库历史数据（PDF）retrieval 行为通过兼容测试保护
- [~] 本地已通过 lint 和 unit；未在本次文档修正中重新跑完整 CI/e2e
