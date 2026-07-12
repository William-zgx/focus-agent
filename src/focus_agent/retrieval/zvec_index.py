from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .index import RetrievalDocument, RetrievalSearchHit


class ZvecRetrievalIndex:
    def __init__(self, *, data_dir: str | Path, dimensions: int):
        try:
            import zvec  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("zvec package is not installed") from exc
        self._zvec = zvec
        self.data_dir = Path(data_dir).expanduser()
        self.dimensions = int(dimensions)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._collections: dict[str, Any] = {}

    def upsert(self, document: RetrievalDocument) -> None:
        if document.vector is None:
            return
        collection = self._collection(document.collection)
        fields = _string_fields(
            {
                **dict(document.fields),
                "source_id": document.source_id,
                "source_type": str(document.fields.get("source_type") or ""),
                "text": document.text,
                "metadata_json": json.dumps(dict(document.fields), ensure_ascii=False),
            }
        )
        status = collection.upsert(
            self._zvec.Doc(
                id=document.doc_id,
                fields=fields,
                vectors={"dense_embedding": [float(value) for value in document.vector]},
            )
        )
        _raise_if_bad_status(status)

    def delete(self, *, collection: str, doc_id: str) -> None:
        status = self._collection(collection).delete(ids=doc_id)
        _raise_if_bad_status(status)

    def search(
        self,
        *,
        collection: str,
        query: str,
        limit: int,
        vector: Sequence[float] | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> list[RetrievalSearchHit]:
        coll = self._collection(collection)
        topk = max(1, int(limit or 1) * 4)
        docs_by_id: dict[str, RetrievalSearchHit] = {}
        query_errors: list[Exception] = []
        if vector is not None:
            try:
                self._merge_docs(
                    docs_by_id,
                    coll.query(
                        queries=self._query(field_name="dense_embedding", vector=vector),
                        topk=topk,
                        include_vector=False,
                        output_fields=["source_id", "text", "metadata_json"],
                    ),
                    filters=filters,
                )
            except Exception as exc:  # noqa: BLE001
                query_errors.append(exc)
        if query.strip():
            try:
                self._merge_docs(
                    docs_by_id,
                    coll.query(
                        queries=self._fts_query(query),
                        topk=topk,
                        include_vector=False,
                        output_fields=["source_id", "text", "metadata_json"],
                    ),
                    filters=filters,
                )
            except Exception as exc:  # noqa: BLE001
                query_errors.append(exc)
        if not docs_by_id and query_errors:
            raise RuntimeError("zvec search failed") from query_errors[0]
        hits = sorted(docs_by_id.values(), key=lambda item: (-item.score, item.doc_id))
        return hits[: max(0, int(limit or 0))]

    def stats(self) -> dict[str, object]:
        stats: dict[str, object] = {"backend": "zvec", "data_dir": str(self.data_dir)}
        for name, collection in self._collections.items():
            raw_stats = getattr(collection, "stats", None)
            stats[name] = str(raw_stats) if raw_stats is not None else "opened"
        return stats

    def _collection(self, name: str):
        existing = self._collections.get(name)
        if existing is not None:
            return existing
        path = self.data_dir / name
        if path.exists():
            collection = self._zvec.open(str(path))
        else:
            zvec = self._zvec
            schema = zvec.CollectionSchema(
                name=name,
                fields=[
                    zvec.FieldSchema("source_id", zvec.DataType.STRING, nullable=True),
                    zvec.FieldSchema("source_type", zvec.DataType.STRING, nullable=True),
                    zvec.FieldSchema(
                        "text",
                        zvec.DataType.STRING,
                        nullable=True,
                        index_param=zvec.FtsIndexParam(
                            tokenizer_name="jieba",
                            filters=["lowercase"],
                        ),
                    ),
                    zvec.FieldSchema("metadata_json", zvec.DataType.STRING, nullable=True),
                ],
                vectors=[
                    zvec.VectorSchema(
                        "dense_embedding",
                        zvec.DataType.VECTOR_FP32,
                        dimension=self.dimensions,
                    )
                ],
            )
            collection = zvec.create_and_open(str(path), schema)
        self._collections[name] = collection
        return collection

    def _merge_docs(
        self,
        docs_by_id: dict[str, RetrievalSearchHit],
        docs: object,
        *,
        filters: Mapping[str, object] | None,
    ) -> None:
        for doc in docs or []:
            doc_id = str(getattr(doc, "id", "") or "")
            fields = _doc_fields(doc)
            metadata = _json_dict(fields.get("metadata_json"))
            if not _matches_filters(metadata, filters):
                continue
            score = float(getattr(doc, "score", 0.0) or 0.0)
            existing = docs_by_id.get(doc_id)
            if existing is None:
                docs_by_id[doc_id] = RetrievalSearchHit(
                    doc_id=doc_id,
                    source_id=str(fields.get("source_id") or metadata.get("source_id") or doc_id),
                    score=score,
                    text=str(fields.get("text") or ""),
                    fields=metadata,
                )
            else:
                docs_by_id[doc_id] = RetrievalSearchHit(
                    doc_id=existing.doc_id,
                    source_id=existing.source_id,
                    score=existing.score + score,
                    text=existing.text,
                    fields=existing.fields,
                )

    def _query(self, *, field_name: str, vector: Sequence[float]):
        query_cls = getattr(self._zvec, "Query", None)
        if query_cls is None:
            from zvec.model.param.query import Query  # type: ignore[import-not-found]

            query_cls = Query

        return query_cls(field_name=field_name, vector=[float(value) for value in vector])

    def _fts_query(self, query: str):
        try:
            from zvec.model.param.query import Fts, Query  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("zvec FTS query API is unavailable") from exc
        return Query(field_name="text", fts=Fts(match_string=query))


def _string_fields(fields: Mapping[str, object]) -> dict[str, str]:
    return {
        str(key): json.dumps(value, ensure_ascii=False)
        if isinstance(value, (dict, list, tuple))
        else str(value)
        for key, value in fields.items()
        if value is not None
    }


def _doc_fields(doc: object) -> dict[str, object]:
    fields = getattr(doc, "fields", None)
    if isinstance(fields, Mapping):
        return dict(fields)
    fields_method = getattr(doc, "fields", None)
    if callable(fields_method):
        value = fields_method()
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _json_dict(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _matches_filters(
    fields: Mapping[str, object],
    filters: Mapping[str, object] | None,
) -> bool:
    for key, expected in dict(filters or {}).items():
        actual = fields.get(key)
        if isinstance(actual, (list, tuple)):
            actual = tuple(str(item) for item in actual)
        if isinstance(expected, (list, tuple)):
            expected = tuple(str(item) for item in expected)
        if actual != expected:
            return False
    return True


def _raise_if_bad_status(status: object) -> None:
    if isinstance(status, list):
        for item in status:
            _raise_if_bad_status(item)
        return
    if isinstance(status, Mapping):
        code = status.get("code")
        if code not in (None, 0):
            raise RuntimeError(str(status))
        return
    ok = getattr(status, "ok", None)
    if callable(ok) and not ok():
        message = getattr(status, "message", lambda: "zvec operation failed")()
        raise RuntimeError(str(message))
