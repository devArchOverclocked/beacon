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

        from rapidfuzz import fuzz, process

        choices = [f"{f['name']} {f['path']}" for f in self._files]

        matches = process.extract(
            query,
            choices,
            scorer=fuzz.WRatio,
            limit=limit,
            score_cutoff=35,
        )

        # matches is a list of (matched_string, score, index)
        results = []
        for _matched, _score, idx in matches:
            results.append(self._files[idx])

        return results
