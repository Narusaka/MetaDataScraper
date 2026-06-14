import difflib
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


class CandidateScorer:
    """Build stable, auditable evidence for a metadata candidate."""

    WEIGHTS = {
        "title_similarity": 0.65,
        "token_overlap": 0.20,
        "year": 0.10,
        "media_type": 0.05,
    }

    @staticmethod
    def _normalize(value: str) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).casefold()
        text = re.sub(r"\s*\(\d{4}\)\s*$", "", text)
        return " ".join(text.split())

    @staticmethod
    def _tokens(value: str) -> set:
        return set(re.findall(r"[a-z0-9]+", CandidateScorer._normalize(value)))

    @staticmethod
    def _has_cjk(value: str) -> bool:
        return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value or ""))

    def score(
        self,
        *,
        query: str,
        titles: List[Tuple[str, str]],
        candidate_year: int = 0,
        target_year: Optional[int] = None,
        candidate_type: Optional[str] = None,
        expected_type: Optional[str] = None,
        type_forced: bool = False,
        provider: str = "tmdb",
    ) -> Dict[str, Any]:
        normalized_query = self._normalize(query)
        best = {"score": 0.0, "field": None, "title": None}
        for field, title in titles:
            normalized_title = self._normalize(title)
            score = difflib.SequenceMatcher(None, normalized_query, normalized_title).ratio()
            if score > best["score"]:
                best = {"score": score, "field": field, "title": title}

        query_tokens = self._tokens(normalized_query)
        candidate_tokens = set()
        for _, title in titles:
            candidate_tokens.update(self._tokens(title))
        token_overlap = (
            len(query_tokens & candidate_tokens) / len(query_tokens)
            if query_tokens and candidate_tokens else 0.0
        )

        year_available = bool(target_year)
        if not target_year:
            year_score = None
            year_status = "not_provided"
        elif not candidate_year:
            year_score = 0.5
            year_status = "candidate_unknown"
        elif int(candidate_year) == int(target_year):
            year_score = 1.0
            year_status = "exact"
        else:
            year_score = 0.0
            year_status = "mismatch"

        type_available = bool(type_forced and expected_type)
        if not type_available:
            type_score = None
            type_status = "not_forced"
        elif candidate_type == expected_type:
            type_score = 1.0
            type_status = "exact"
        else:
            type_score = 0.0
            type_status = "mismatch"

        matched_title = str(best.get("title") or "")
        query_has_cjk = self._has_cjk(normalized_query)
        candidate_has_cjk = self._has_cjk(matched_title)
        if not normalized_query or not matched_title:
            script_status = "unknown"
        elif query_has_cjk == candidate_has_cjk:
            script_status = "compatible"
        elif best.get("field") == "alias":
            script_status = "bridged_by_alias"
        else:
            script_status = "localized_or_transliterated"

        dimensions = {
            "title_similarity": {
                "score": round(float(best["score"]), 4),
                "weight": self.WEIGHTS["title_similarity"],
                "status": "alias" if best.get("field") == "alias" else "direct",
                "matched_field": best.get("field"),
                "matched_title": best.get("title"),
            },
            "token_overlap": {
                "score": round(token_overlap, 4),
                "weight": self.WEIGHTS["token_overlap"],
                "status": "available" if query_tokens and candidate_tokens else "unavailable",
            },
            "year": {
                "score": year_score,
                "weight": self.WEIGHTS["year"] if year_available else 0.0,
                "status": year_status,
                "target": target_year,
                "candidate": candidate_year or None,
            },
            "media_type": {
                "score": type_score,
                "weight": self.WEIGHTS["media_type"] if type_available else 0.0,
                "status": type_status,
                "expected": expected_type if type_available else None,
                "candidate": candidate_type,
            },
            "script": {
                "score": None,
                "weight": 0.0,
                "status": script_status,
            },
            "external_evidence": {
                "score": 1.0 if provider != "tmdb" else None,
                "weight": 0.0,
                "status": "corroborated" if provider != "tmdb" else "not_used",
                "provider": provider,
            },
        }

        weighted_total = 0.0
        active_weight = 0.0
        for name in ("title_similarity", "token_overlap", "year", "media_type"):
            dimension = dimensions[name]
            score = dimension["score"]
            weight = dimension["weight"]
            if score is None or weight <= 0:
                continue
            weighted_total += float(score) * float(weight)
            active_weight += float(weight)
        composite_score = weighted_total / active_weight if active_weight else 0.0

        hard_blockers = []
        warnings = []
        if year_status == "mismatch":
            hard_blockers.append("year_mismatch")
        elif year_status == "candidate_unknown":
            warnings.append("candidate_year_unknown")
        if type_status == "mismatch":
            hard_blockers.append("media_type_mismatch")
        if best["score"] < 0.55 and token_overlap < 0.75:
            warnings.append("weak_title_evidence")
        if script_status == "localized_or_transliterated":
            warnings.append("cross_script_title")

        return {
            "schema_version": 1,
            "composite_score": round(composite_score, 4),
            "title_similarity": round(float(best["score"]), 4),
            "token_overlap": round(token_overlap, 4),
            "matched_title": best.get("title"),
            "matched_field": best.get("field"),
            "dimensions": dimensions,
            "hard_blockers": hard_blockers,
            "warnings": warnings,
        }
