"""Claim verification: the trust layer.

After an answer is generated, each factual claim in it is checked for
entailment against the retrieved chunks. Verdicts drive the confidence score,
per-claim flags in the response, and abstention when evidence is too weak.

Confidence = 0.6 * verified_fraction + 0.4 * retrieval_strength, where
retrieval_strength normalizes the top chunk's RRF score against the theoretical
maximum (rank 1 in both legs = 2/(k+1)).
"""

import json
from dataclasses import dataclass

from trust_rag.generation.llm import acomplete_json
from trust_rag.retrieval.hybrid import RRF_K, RetrievedChunk

VERIFIED, UNSUPPORTED, CONTRADICTED = "verified", "unsupported", "contradicted"

CONFIDENCE_WEIGHT_VERIFIED = 0.6
CONFIDENCE_WEIGHT_RETRIEVAL = 0.4
ABSTAIN_THRESHOLD = 0.5

MAX_RRF_SCORE = 2.0 / (RRF_K + 1)

_EXTRACT_SYSTEM = (
    "You extract atomic factual claims from text. Respond ONLY with a JSON "
    'object: {"claims": ["...", "..."]}. Split compound statements into '
    "separate claims. Skip citations markers like [1] and non-factual text."
)

_VERIFY_SYSTEM = (
    "You are a strict fact-checker. For each claim, decide whether the numbered "
    "passages support it. Respond ONLY with a JSON object: "
    '{"verdicts": [{"claim": "...", "verdict": "verified|unsupported|contradicted", '
    '"passages": [1]}]}. Use "verified" only if a passage clearly entails the '
    'claim; "contradicted" if a passage states the opposite; otherwise '
    '"unsupported". List the passage numbers that justify the verdict.'
)


@dataclass(frozen=True)
class ClaimVerdict:
    text: str
    verdict: str
    supporting_chunk_ids: list[str]


@dataclass(frozen=True)
class VerificationResult:
    claims: list[ClaimVerdict]
    confidence: float
    abstain: bool
    reason: str | None

    @property
    def verified_fraction(self) -> float:
        if not self.claims:
            return 0.0
        return sum(1 for c in self.claims if c.verdict == VERIFIED) / len(self.claims)


def _retrieval_strength(chunks: list[RetrievedChunk]) -> float:
    if not chunks:
        return 0.0
    return min(chunks[0].rrf_score / MAX_RRF_SCORE, 1.0)


async def verify_answer(
    answer: str, chunks: list[RetrievedChunk]
) -> VerificationResult:
    """Extract claims from `answer` and verify each against `chunks`."""
    if not chunks:
        return VerificationResult([], 0.0, True, "No relevant context was found.")

    extracted = await acomplete_json(_EXTRACT_SYSTEM, answer)
    claims: list[str] = extracted.get("claims", []) if isinstance(extracted, dict) else []
    claims = [c.strip() for c in claims if isinstance(c, str) and c.strip()]
    if not claims:
        # Unparseable extraction or non-factual answer (e.g. an abstention
        # template) — nothing to verify, keep retrieval-only confidence.
        conf = CONFIDENCE_WEIGHT_RETRIEVAL * _retrieval_strength(chunks)
        return VerificationResult(
            [], conf, conf < ABSTAIN_THRESHOLD, "Claims could not be extracted."
        )

    passages = "\n\n".join(f"[{i + 1}] {c.content}" for i, c in enumerate(chunks))
    verified = await acomplete_json(
        _VERIFY_SYSTEM, f"Passages:\n\n{passages}\n\nClaims:\n{json.dumps(claims)}"
    )
    if not isinstance(verified, dict) or not verified.get("verdicts"):
        # Verifier unavailable → treat every claim as unverifiable.
        verdicts = [ClaimVerdict(c, UNSUPPORTED, []) for c in claims]
    else:
        by_claim = {
            v.get("claim"): v
            for v in verified["verdicts"]
            if isinstance(v, dict) and v.get("claim")
        }
        verdicts = []
        for claim in claims:
            v = by_claim.get(claim, {})
            verdict = v.get("verdict", UNSUPPORTED)
            if verdict not in (VERIFIED, UNSUPPORTED, CONTRADICTED):
                verdict = UNSUPPORTED
            numbers = v.get("passages", [])
            supporting = [
                str(chunks[n - 1].id) for n in numbers if isinstance(n, int) and 1 <= n <= len(chunks)
            ]
            verdicts.append(ClaimVerdict(claim, verdict, supporting))

    confidence = round(
        CONFIDENCE_WEIGHT_VERIFIED * (
            sum(1 for v in verdicts if v.verdict == VERIFIED) / len(verdicts)
        )
        + CONFIDENCE_WEIGHT_RETRIEVAL * _retrieval_strength(chunks),
        4,
    )

    abstain = confidence < ABSTAIN_THRESHOLD
    reason = None
    if abstain:
        unsupported = sum(1 for v in verdicts if v.verdict != VERIFIED)
        reason = (
            f"{unsupported} of {len(verdicts)} claims are not supported by the "
            "retrieved documents."
        )
    return VerificationResult(verdicts, confidence, abstain, reason)
