"""Topic overlap over implementation files, never inferred architecture edges."""

from collections import defaultdict
from collections.abc import Mapping, Sequence

from chunkhound.code_mapper.c4.documented import TopicSources
from chunkhound.code_mapper.c4.model import Coverage


def compute_coverage(
    *,
    element_files: Mapping[str, Sequence[str]],
    direct_files: Mapping[str, Sequence[str]],
    topics: Sequence[TopicSources] | None,
) -> dict[str, Coverage]:
    """Inputs include container/system rollups; direct files affect only their owner.

    Aggregate files must be supplied explicitly: these mappings do not encode
    parentage. Empty implementation sets (including documented nodes) have none.
    Topic weight is unique shared files; equal weights sort by topic identifier.
    """
    topic_files: dict[str, set[str]] = defaultdict(set)
    for topic in topics or ():
        topic_files[topic.topic].update(topic.files)
    result = {}
    for element in sorted(set(element_files) | set(direct_files)):
        files = set(element_files.get(element, ())) | set(direct_files.get(element, ()))
        if not files:
            result[element] = Coverage(status="none", topics=[])
        elif topics is None:
            result[element] = Coverage(status="not_computed", topics=[])
        else:
            weights = {
                topic: len(files & cited) for topic, cited in topic_files.items()
            }
            matched = sorted(
                (topic for topic, weight in weights.items() if weight),
                key=lambda topic: (-weights[topic], topic),
            )
            result[element] = Coverage(
                status="covered" if matched else "undescribed", topics=matched
            )
    return result
