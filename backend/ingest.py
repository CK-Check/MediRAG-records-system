"""
ingest.py  -  Run ONCE (and again whenever source_documents/ changes).

  source_documents/*.txt --parse--> chunks --embed + noise--> faissindex/
                                  +--> records/<patient_id>.json  (for exact tools)

Run:  python ingest.py
"""
import json
from pathlib import Path
from langchain_core.documents import Document
from src.qdrant_store import QdrantStore

from src.ehr_parser import parse_patient_file
from src.dp_embeddings import DPHuggingFaceEmbeddings

ROOT = Path(__file__).resolve().parent
NOISE_SCALE = 0.02  # 0 = no privacy noise. Raise it and re-test search quality!


def build_index(source_dir, records_dir, index_dir, embeddings):
    source_dir, records_dir, index_dir = map(Path, (source_dir, records_dir, index_dir))
    records_dir.mkdir(exist_ok=True)
    docs = []
    files = sorted(source_dir.glob("*.txt"))
    if not files:
        raise SystemExit(f"No .txt files found in {source_dir}")

    for f in files:
        result = parse_patient_file(f)
        rec = result["record"]
        (records_dir / f"{rec['patient_id']}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        docs += [Document(page_content=c["text"], metadata=c["metadata"]) for c in result["chunks"]]
        print(f"[ok] {f.name}: {len(result['chunks'])} chunks, {len(rec['visits'])} visits")
        for flag in result["flags"]:
            print(f"     WARNING {flag}")

    store = QdrantStore.from_documents(docs, embeddings, str(index_dir))
    store.close()
    print(f"[done] {len(docs)} chunks saved to {index_dir}")


if __name__ == "__main__":
    build_index(ROOT / "source_documents", ROOT / "records", ROOT / "index",
                DPHuggingFaceEmbeddings(noise_scale=NOISE_SCALE))
