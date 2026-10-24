from trust_rag.ingestion.chunker import CHUNK_SIZE, MIN_CHUNK_SIZE, chunk_text


class TestChunker:
    def test_short_text_is_single_chunk(self) -> None:
        chunks = chunk_text("One paragraph.")
        assert len(chunks) == 1
        assert chunks[0].index == 0
        assert chunks[0].content == "One paragraph."

    def test_respects_chunk_size(self) -> None:
        text = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(50))
        chunks = chunk_text(text)
        assert len(chunks) > 1
        assert all(len(c.content) <= CHUNK_SIZE for c in chunks)

    def test_first_chunk_starts_with_first_paragraph(self) -> None:
        text = "\n\n".join(f"para-{i} " + "filler " * 50 for i in range(10))
        chunks = chunk_text(text)
        assert chunks[0].content.startswith("para-0")

    def test_sequential_indices(self) -> None:
        text = "\n\n".join(f"Paragraph {i} " + "word " * 100 for i in range(30))
        chunks = chunk_text(text)
        assert [c.index for c in chunks] == list(range(len(chunks)))

    def test_empty_text(self) -> None:
        assert chunk_text("") == []
        assert chunk_text("   \n\n  ") == []

    def test_invalid_overlap_rejected(self) -> None:
        try:
            chunk_text("hello", chunk_size=100, overlap=100)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    def test_oversized_paragraph_hard_split(self) -> None:
        huge = "word " * 1000  # 5000 chars, single paragraph
        chunks = chunk_text(huge, chunk_size=100, overlap=20)
        assert len(chunks) > 1
        # Hard-split chunks respect the cap; a sub-MIN tail may merge into its
        # predecessor, so the last chunk can exceed by at most MIN + separator.
        assert all(len(c.content) <= 100 + MIN_CHUNK_SIZE + 1 for c in chunks)
