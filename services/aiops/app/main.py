from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.db import init_db
from app.drain.parser import DrainParser
from app.adapters.openrca import OpenRCAAdapter
from app.agent.rag import RAGManager
from app.drain.alerter import KeepAlerter
from app.api import ingest, clusters, anomalies, stats, investigate, benchmark


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = get_settings()
    init_db(settings.SQLITE_PATH)
    app.state.settings = settings
    app.state.drain_parser = DrainParser(config_path="drain3.ini")
    app.state.openrca = OpenRCAAdapter(settings.OPENRCA_DATA_DIR)

    # RAG - connect to ChromaDB, load knowledge
    try:
        app.state.rag = RAGManager(
            chroma_url=settings.CHROMA_URL,
            collection_name=settings.CHROMA_COLLECTION,
            knowledge_dir="knowledge",
            openai_api_key=settings.OPENAI_API_KEY,
        )
        app.state.rag.load_knowledge()
    except Exception:
        app.state.rag = None  # Graceful degradation

    # Keep alerter
    if settings.KEEP_API_KEY:
        app.state.alerter = KeepAlerter(
            keep_api_url=settings.KEEP_API_URL,
            keep_api_key=settings.KEEP_API_KEY,
            db_path=settings.SQLITE_PATH,
        )
    else:
        app.state.alerter = None

    yield
    # Shutdown (cleanup if needed)


app = FastAPI(title="AIOps Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(clusters.router, prefix="/clusters", tags=["clusters"])
app.include_router(anomalies.router, prefix="/anomalies", tags=["anomalies"])
app.include_router(stats.router, prefix="/stats", tags=["stats"])
app.include_router(investigate.router, tags=["investigate"])
app.include_router(benchmark.router, prefix="/benchmark", tags=["benchmark"])
