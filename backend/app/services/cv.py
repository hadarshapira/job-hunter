"""Read the text out of an uploaded CV (PDF, Word .docx or plain text)."""

import io


class CVError(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        import pdfplumber

        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                text = "\n".join((page.extract_text() or "") for page in pdf.pages[:10])
        except Exception as exc:  # pdfplumber raises many types for broken files
            raise CVError("Couldn't read that PDF. Is it a valid, unprotected PDF?") from exc
    elif name.endswith(".docx"):
        import docx

        try:
            doc = docx.Document(io.BytesIO(data))
        except Exception as exc:
            raise CVError("Couldn't read that Word file.") from exc
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        text = "\n".join(parts)
    elif name.endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="replace")
    else:
        raise CVError("Upload your CV as a PDF, Word (.docx) or text file.")
    text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if len(text) < 100:
        raise CVError("Found almost no text in that file. If it's a scanned image, export the CV as a text PDF.")
    return text
