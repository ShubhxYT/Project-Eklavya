from dataclasses import dataclass


@dataclass(frozen=True)
class CourseSection:
    section_id: str
    title: str
    body: str
    pages: tuple[int, ...]
    heading_path: tuple[str, ...]
