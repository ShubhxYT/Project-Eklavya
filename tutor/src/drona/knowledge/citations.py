import re

from drona.contracts import ContextPack, SourceRef, TutorAnswer

CITATION_RE = re.compile(r"\[(S[1-9][0-9]*)\]")


class CitationError(ValueError):
    pass


def validate_answer(
    answer: TutorAnswer, context: ContextPack
) -> tuple[TutorAnswer, tuple[SourceRef, ...]]:
    if answer.unsupported:
        return answer, ()
    ids = tuple(dict.fromkeys(CITATION_RE.findall(answer.text)))
    if not ids or any(source_id not in context.sources for source_id in ids):
        raise CitationError("answer contained missing or unknown citations")
    normalized = TutorAnswer(answer.text, ids, False)
    return normalized, tuple(context.sources[source_id] for source_id in ids)
