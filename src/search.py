from __future__ import annotations

from src.db import Database


class Searcher:
    """In-memory fuzzy searcher over the indexed file list."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._files: list[dict] = []
        self.reload()

    def reload(self) -> None:
        """Load all files from the database into memory."""
        self._files = self._db.get_all_files()

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search for files matching *query*.

        If *query* is empty the first *limit* files are returned in
        alphabetical order (the DB already returns them sorted by name).

        Otherwise rapidfuzz WRatio is used against the combined
        ``"{name} {path}"`` string.  Only results with a score >= 35 are
        returned, sorted by score descending.
        """
        if not query.strip():
            return self._files[:limit]

        from rapidfuzz import fuzz, process, utils

        # Score against name (primary) and full "name + path" (secondary).
        # Taking the max means a strong name match isn't diluted by the path.
        query_proc = utils.default_process(query)
        scored: list[tuple[float, int]] = []
        for i, f in enumerate(self._files):
            name_score = fuzz.WRatio(query_proc, utils.default_process(f["name"]))
            full_score = fuzz.WRatio(
                query_proc, utils.default_process(f"{f['name']} {f['path']}")
            )
            best = max(name_score, full_score)
            if best >= 20:
                scored.append((best, i))

        scored.sort(key=lambda x: -x[0])
        return [self._files[i] for _, i in scored[:limit]]
