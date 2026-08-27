"""Document loading via LangChain community loaders."""

from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document

from app.logging_config import get_logger

logger = get_logger(__name__)

# Map file extension -> LangChain loader class.
_LOADERS = {
    ".pdf": PyPDFLoader,
    ".txt": TextLoader,
    ".md": TextLoader,
}


def load_document(path: str | Path) -> list[Document]:
    """Load a single file into a list of LangChain Documents."""
    path = Path(path)
    loader_cls = _LOADERS.get(path.suffix.lower())
    if loader_cls is None:
        raise ValueError(
            f"Unsupported file type '{path.suffix}'. Supported: {sorted(_LOADERS)}"
        )

    logger.debug("Loading %s with %s", path, loader_cls.__name__)
    docs = loader_cls(str(path)).load()
    logger.deep_debug("Loaded %d document(s) from %s", len(docs), path)  # type: ignore[attr-defined]
    return docs
