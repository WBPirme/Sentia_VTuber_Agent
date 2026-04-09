import argparse
import json
import os
import sys
from datetime import datetime
from uuid import uuid4

import chromadb
from chromadb.utils import embedding_functions


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "models", "memory_db")
MODEL_PATH = os.path.join(BASE_DIR, "models", "memory_embedding")
COLLECTION_NAME = "sentia_long_term_memory_local_v1"


def build_collection():
    os.makedirs(DB_PATH, exist_ok=True)
    os.environ.setdefault("HF_HOME", os.path.join(DB_PATH, "hf_home"))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    client = chromadb.PersistentClient(path=DB_PATH)
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=MODEL_PATH,
        cache_folder=DB_PATH,
        local_files_only=True,
    )
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )
    return client, collection


def parse_args():
    parser = argparse.ArgumentParser(description="Inspect and edit Sentia memory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("collections", help="Show available memory collections.")

    list_parser = subparsers.add_parser("list", help="List stored memories.")
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument("--contains", default="")

    search_parser = subparsers.add_parser("search", help="Search memories by semantic query.")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=5)

    dump_parser = subparsers.add_parser("dump", help="Dump memories to JSON.")
    dump_parser.add_argument("--output", default=os.path.join(BASE_DIR, "models", "memory_db", "memory_dump.json"))

    restore_parser = subparsers.add_parser("restore", help="Restore memories from JSON.")
    restore_parser.add_argument("--input", required=True)
    restore_parser.add_argument("--replace", action="store_true", help="Replace all existing memories before restore.")

    prune_parser = subparsers.add_parser("prune", help="Delete memories that match a keyword filter.")
    prune_parser.add_argument("--contains", required=True, help="Delete memories whose document contains this text.")
    prune_parser.add_argument("--limit", type=int, default=0, help="Maximum number of matched memories to delete. 0 means no limit.")
    prune_parser.add_argument("--dry-run", action="store_true", help="Preview matches without deleting anything.")

    add_parser = subparsers.add_parser("add", help="Add a memory record.")
    add_parser.add_argument("text")
    add_parser.add_argument("--emotion", default="Neutral")
    add_parser.add_argument("--importance", type=int, default=1)

    update_parser = subparsers.add_parser("update", help="Update a memory record by id.")
    update_parser.add_argument("id")
    update_parser.add_argument("text")
    update_parser.add_argument("--emotion")
    update_parser.add_argument("--importance", type=int)
    update_parser.add_argument("--timestamp")

    delete_parser = subparsers.add_parser("delete", help="Delete memory records by id.")
    delete_parser.add_argument("ids", nargs="+")

    if len(sys.argv) == 1:
        parser.print_help()
        print("\nExamples:")
        print("  .\\.venv\\Scripts\\python.exe .\\tools\\memory_admin.py list --limit 10")
        print("  .\\.venv\\Scripts\\python.exe .\\tools\\memory_admin.py search \"你好\" --limit 5")
        print("  .\\.venv\\Scripts\\python.exe .\\tools\\memory_admin.py dump --output E:\\Sentia\\models\\memory_db\\memory_dump.json")
        print("  .\\.venv\\Scripts\\python.exe .\\tools\\memory_admin.py prune --contains 关机 --dry-run")
        sys.exit(0)

    return parser.parse_args()


def print_memory_row(memory_id, document, metadata):
    timestamp = metadata.get("timestamp", "-") if metadata else "-"
    emotion = metadata.get("emotion", "-") if metadata else "-"
    importance = metadata.get("importance", "-") if metadata else "-"
    print(f"[{memory_id}] {timestamp} | emotion={emotion} | importance={importance}")
    print(document)
    print("-" * 80)


def command_collections(client):
    for collection in client.list_collections():
        model = collection.get_model().configuration_json.get("embedding_function", {})
        model_name = model.get("config", {}).get("model_name", "-")
        print(f"{collection.name} | count={collection.count()} | model={model_name}")


def command_list(collection, limit, contains):
    total = collection.count()
    if total == 0:
        print("No memories stored.")
        return

    data = collection.get(limit=total)
    rows = zip(data.get("ids", []), data.get("documents", []), data.get("metadatas", []))
    filtered = []
    needle = contains.strip().lower()
    for memory_id, document, metadata in rows:
        if needle and needle not in document.lower():
            continue
        filtered.append((memory_id, document, metadata))

    if not filtered:
        print("No memories matched.")
        return

    for memory_id, document, metadata in filtered[-limit:]:
        print_memory_row(memory_id, document, metadata)


def command_search(collection, query, limit):
    if collection.count() == 0:
        print("No memories stored.")
        return

    results = collection.query(query_texts=[query], n_results=min(limit, collection.count()))
    ids = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    if not ids:
        print("No memories matched.")
        return

    for memory_id, document, metadata in zip(ids, documents, metadatas):
        print_memory_row(memory_id, document, metadata)


def _get_all_memories(collection):
    total = collection.count()
    if total == 0:
        return []

    data = collection.get(limit=total)
    return list(
        zip(
            data.get("ids", []),
            data.get("documents", []),
            data.get("metadatas", []),
        )
    )


def command_dump(collection, output_path):
    rows = []
    for memory_id, document, metadata in _get_all_memories(collection):
        rows.append(
            {
                "id": memory_id,
                "document": document,
                "metadata": metadata or {},
            }
        )

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)

    print(f"Dumped {len(rows)} memories to {output_path}")


def command_restore(collection, input_path, replace):
    with open(input_path, "r", encoding="utf-8") as file:
        rows = json.load(file)

    if not isinstance(rows, list):
        raise ValueError("Restore file must contain a JSON array.")

    ids = []
    documents = []
    metadatas = []
    for row in rows:
        ids.append(row["id"])
        documents.append(row["document"])
        metadatas.append(row.get("metadata", {}))

    if replace and collection.count():
        existing = collection.get(limit=collection.count())
        existing_ids = existing.get("ids", [])
        if existing_ids:
            collection.delete(ids=existing_ids)

    if ids:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    print(f"Restored {len(ids)} memories from {input_path}")


def command_prune(collection, contains, limit, dry_run):
    needle = contains.strip().lower()
    if not needle:
        print("Keyword is empty, nothing to prune.")
        return

    matches = []
    for memory_id, document, metadata in _get_all_memories(collection):
        if needle in document.lower():
            matches.append((memory_id, document, metadata))

    if limit > 0:
        matches = matches[:limit]

    if not matches:
        print("No memories matched.")
        return

    for memory_id, document, metadata in matches:
        print_memory_row(memory_id, document, metadata)

    if dry_run:
        print(f"Dry run only. Matched {len(matches)} memories.")
        return

    collection.delete(ids=[memory_id for memory_id, _, _ in matches])
    print(f"Deleted {len(matches)} memories.")


def command_add(collection, text, emotion, importance):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    memory_id = f"mem_{uuid4().hex}"
    document = f"[{timestamp}] [情绪:{emotion}] {text}"
    metadata = {"timestamp": timestamp, "emotion": emotion, "importance": importance}
    collection.add(ids=[memory_id], documents=[document], metadatas=[metadata])
    print(f"Added memory: {memory_id}")


def command_update(collection, memory_id, text, emotion, importance, timestamp):
    data = collection.get(ids=[memory_id])
    if not data.get("ids"):
        print(f"Memory not found: {memory_id}")
        return

    existing_metadata = (data.get("metadatas") or [{}])[0] or {}
    final_timestamp = timestamp or existing_metadata.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M")
    final_emotion = emotion or existing_metadata.get("emotion") or "Neutral"
    final_importance = importance if importance is not None else existing_metadata.get("importance", 1)
    document = f"[{final_timestamp}] [情绪:{final_emotion}] {text}"
    metadata = {
        "timestamp": final_timestamp,
        "emotion": final_emotion,
        "importance": final_importance,
    }
    collection.update(ids=[memory_id], documents=[document], metadatas=[metadata])
    print(f"Updated memory: {memory_id}")


def command_delete(collection, ids):
    collection.delete(ids=ids)
    print("Deleted:")
    for memory_id in ids:
        print(memory_id)


def main():
    args = parse_args()
    client, collection = build_collection()

    if args.command == "collections":
        command_collections(client)
    elif args.command == "list":
        command_list(collection, args.limit, args.contains)
    elif args.command == "search":
        command_search(collection, args.query, args.limit)
    elif args.command == "dump":
        command_dump(collection, args.output)
    elif args.command == "restore":
        command_restore(collection, args.input, args.replace)
    elif args.command == "prune":
        command_prune(collection, args.contains, args.limit, args.dry_run)
    elif args.command == "add":
        command_add(collection, args.text, args.emotion, args.importance)
    elif args.command == "update":
        command_update(
            collection,
            args.id,
            args.text,
            args.emotion,
            args.importance,
            args.timestamp,
        )
    elif args.command == "delete":
        command_delete(collection, args.ids)
    else:
        raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
