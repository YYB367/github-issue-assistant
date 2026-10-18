"""Markdown maps preserve original commands/fences; exact embedding tokens are checked."""
import hashlib
import json

from markdown_it import MarkdownIt

from app.config import EMBEDDING_TOKEN_LIMIT
from app.errors import AppError
from knowledge.models import Chunk, SourceDocument

CHUNKER_VERSION = "markdown-heading-paragraph-v2-target192"


def split_markdown(source: SourceDocument, tokenizer, limit: int = EMBEDDING_TOKEN_LIMIT) -> list[Chunk]:
    lines = source.text.splitlines(keepends=True)
    target_tokens = min(limit, 192)
    tokens = MarkdownIt("commonmark").enable("table").parse(source.text)
    headings = []
    for i, token in enumerate(tokens):
        if token.type == "heading_open" and token.level == 0 and token.map:
            headings.append((token.map[0], token.map[1], int(token.tag[1:]), tokens[i + 1].content))
    # Leaf blocks avoid splitting list items through their fenced configuration examples.
    blocks = []
    for token in tokens:
        if token.type in ("paragraph_open", "fence", "code_block", "table_open", "html_block") and token.map:
            start, end = token.map
            if not any(a <= start and end <= b for a, b, _ in blocks):
                blocks.append((start, end, token.type))
    blocks.sort()
    stack, chunks, current, current_heading, current_title = [], [], None, "", source.title or source.file_path
    heading_index = 0

    def count(text):
        return len(tokenizer.encode(text).ids)

    def emit():
        nonlocal current
        if current is None:
            return
        start, end = current
        body = "".join(lines[start:end]).strip("\n\r")
        text = (current_heading + "\n\n" + body).strip() if current_heading else body
        if not text.strip():
            current = None
            return
        token_count = count(text)
        if token_count > limit:
            raise AppError("chunk_token_limit", "片段超过Embedding token上限，未静默截断。")
        identity = json.dumps([source.repository, source.file_path, source.version,
                               source.content_hash, start, end, text, CHUNKER_VERSION], ensure_ascii=False)
        chunks.append(Chunk(
            chunk_id=hashlib.sha256(identity.encode()).hexdigest(), repository=source.repository,
            file_path=source.file_path, version=source.version, content_hash=source.content_hash,
            source_type=source.source_type, title=current_title, line_start=start + 1, line_end=end,
            chunk_index=len(chunks), text=text, embedding_tokens=token_count,
            updated_at=source.updated_at, issue_number=source.issue_number,
        ))
        current = None

    for start, end, kind in blocks:
        while heading_index < len(headings) and headings[heading_index][0] <= start:
            emit()
            hs, he, depth, title = headings[heading_index]
            stack = [(d, t) for d, t in stack if d < depth] + [(depth, title)]
            current_heading = "\n".join("#" * d + " " + t for d, t in stack)
            current_title = " / ".join(t for _, t in stack)
            heading_index += 1
        block_text = "".join(lines[start:end])
        prefix = current_heading + "\n\n" if current_heading else ""
        if count(prefix + block_text) > limit:
            emit()
            if kind != "paragraph_open":
                raise AppError("oversized_markdown_block", f"完整代码块或表格超过token上限（{source.file_path}:{start + 1}），请人工拆分来源。")
            # Oversized ordinary prose is split at sentence/line boundaries. Single long commands are rejected.
            cursor = start
            while cursor < end:
                boundary = cursor + 1
                if count(prefix + lines[cursor]) > limit:
                    raise AppError("oversized_markdown_line", f"单行超过token上限（{source.file_path}:{cursor + 1}），需要人工拆分。")
                while boundary < end and count(prefix + "".join(lines[cursor:boundary + 1])) <= limit:
                    boundary += 1
                current = (cursor, boundary)
                emit()
                cursor = boundary
            continue
        if current is not None and count(prefix + "".join(lines[current[0]:end])) > target_tokens:
            emit()
        current = (current[0] if current else start, end)
    emit()
    if not chunks:
        raise AppError("empty_document", "来源没有可入库的正文片段。")
    return chunks
