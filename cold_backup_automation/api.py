from typing import Any, Callable, Dict, Optional

from .api_models import (
    BatchPayload,
    EventPayload,
    MappingPayload,
    ObjectPayload,
    PayloadValidationError,
    SourcePayload,
    TargetPayload,
    VideoPayload,
)
from .db import connect_from_env
from .repository import SucaiMetaRepository


def create_app(repository: Optional[SucaiMetaRepository] = None, connection_factory: Optional[Callable[[], Any]] = None):
    try:
        from fastapi import Body, Depends, FastAPI, HTTPException, Query
    except ModuleNotFoundError as exc:
        raise RuntimeError("FastAPI is required. Install requirements-cold-backup.txt before starting the API.") from exc

    app = FastAPI(title="sucai cold backup metadata API", version="0.1.0")

    def repo_dependency():
        if repository is not None:
            yield repository
            return

        factory = connection_factory or connect_from_env
        connection = factory()
        try:
            yield SucaiMetaRepository(connection)
        finally:
            close = getattr(connection, "close", None)
            if close:
                close()

    def parse_payload(factory, payload: Dict[str, Any]):
        try:
            return factory(payload)
        except PayloadValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "database": "sucai_meta"}

    @app.post("/api/v1/sources")
    def upsert_source(payload: Dict[str, Any] = Body(...), repo: SucaiMetaRepository = Depends(repo_dependency)):
        return repo.upsert_source(parse_payload(SourcePayload.from_api, payload))

    @app.post("/api/v1/targets")
    def upsert_target(payload: Dict[str, Any] = Body(...), repo: SucaiMetaRepository = Depends(repo_dependency)):
        return repo.upsert_target(parse_payload(TargetPayload.from_api, payload))

    @app.post("/api/v1/batches")
    def upsert_batch(payload: Dict[str, Any] = Body(...), repo: SucaiMetaRepository = Depends(repo_dependency)):
        return repo.upsert_batch(parse_payload(BatchPayload.from_api, payload))

    @app.post("/api/v1/batches/{batchId}/videos")
    def upsert_batch_video(batchId: str, payload: Dict[str, Any] = Body(...), repo: SucaiMetaRepository = Depends(repo_dependency)):
        return repo.upsert_batch_video(batchId, parse_payload(VideoPayload.from_api, payload))

    @app.post("/api/v1/objects/upsert")
    def upsert_object(payload: Dict[str, Any] = Body(...), repo: SucaiMetaRepository = Depends(repo_dependency)):
        return repo.upsert_object(parse_payload(ObjectPayload.from_api, payload))

    @app.post("/api/v1/mappings/upsert")
    def upsert_mapping(payload: Dict[str, Any] = Body(...), repo: SucaiMetaRepository = Depends(repo_dependency)):
        return repo.upsert_mapping(parse_payload(MappingPayload.from_api, payload))

    @app.post("/api/v1/events")
    def insert_event(payload: Dict[str, Any] = Body(...), repo: SucaiMetaRepository = Depends(repo_dependency)):
        return repo.insert_event(parse_payload(EventPayload.from_api, payload))

    @app.get("/api/v1/videos/{companyId}/{stationId}/{videoId}")
    def get_video(
        companyId: int,
        stationId: int,
        videoId: int,
        sourceId: Optional[str] = Query(default=None),
        repo: SucaiMetaRepository = Depends(repo_dependency),
    ):
        return {"items": repo.list_videos(companyId, stationId, videoId, sourceId)}

    @app.get("/api/v1/mappings/lookup")
    def lookup_mapping(
        sourceId: str,
        bucket: str,
        key: str,
        versionId: str = Query(default=""),
        repo: SucaiMetaRepository = Depends(repo_dependency),
    ):
        return {"item": repo.lookup_mapping(sourceId, bucket, key, versionId)}

    @app.get("/api/v1/batches/{batchId}/summary")
    def batch_summary(batchId: str, repo: SucaiMetaRepository = Depends(repo_dependency)):
        return {"item": repo.batch_summary(batchId)}

    return app


app = create_app()
