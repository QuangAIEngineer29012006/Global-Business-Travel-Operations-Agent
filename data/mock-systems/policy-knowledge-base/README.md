# Kho tri thức chính sách giả lập

Tài liệu trong thư mục này là nội dung huấn luyện hư cấu, không phải chính sách doanh nghiệp, tư vấn pháp lý, thị thực hay bảo hiểm có thẩm quyền. Mỗi file Markdown là một nguồn tài liệu và chứa các chunks có metadata trong YAML front matter. Metadata retrieval được lập chỉ mục ở `chunk_metadata.csv`.

## Hybrid policy search

The mock runtime parses these Markdown chunks and builds an in-memory SQLite FTS5
keyword index plus normalized semantic embeddings. `search_travel_policy` filters
both result lists by category and combines their ranks with reciprocal rank fusion.
Workflow evidence validation and citations remain unchanged.

Preprocessing builds the same indexes in `data/processed/travel_agent.sqlite`:
`policy_chunks_fts` for keyword search and `policy_embeddings` for vectors and
model identity. It reads the Markdown and CSV fixtures without changing them.

Hybrid mode uses the local multilingual model
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Install
`requirements.txt`; the model is downloaded and cached on first hybrid use, so
initial setup requires network access. Set `POLICY_EMBEDDING_MODEL` to use another
compatible local Sentence Transformers model. For explicitly offline keyword-only
use, set `POLICY_SEMANTIC_MODE=keyword`; hybrid is the default.
