"""Malformed documents are client errors; scanner bugs remain server errors."""
import io
import sys
import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from parallax import server


def archive(content=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        if content is not None:
            z.writestr("word/document.xml", content)
    return data.getvalue()


class UploadErrors(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_invalid_documents_and_cleanup(self):
        samples = [("empty.pdf", b""), ("broken.pdf", b"%PDF-1.7\nbroken"),
                   ("empty.docx", b""), ("broken.docx", b"not a zip"),
                   ("missing.docx", archive()), ("xml.docx", archive(b"<broken")),
                   ("wrong.docx", archive(b"<html/>")),
                   ("no-body.docx", archive(b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'))]
        with tempfile.TemporaryDirectory() as folder, patch.object(tempfile, "tempdir", folder):
            for name, content in samples:
                with self.subTest(name=name):
                    response = self.client.post("/scan/file", files={"file": (name, content)})
                    self.assertEqual(response.status_code, 422)
                    self.assertIn("We couldn't read", response.json()["error"])
                    self.assertEqual(list(Path(folder).iterdir()), [])

    def test_unexpected_errors_are_not_invalid_uploads(self):
        pdf = self.client.get("/lab/resume.pdf").content
        for target in ("analyze_pdf", "_report"):
            with patch("parallax.scan." + target, side_effect=RuntimeError("programming bug")):
                with self.assertRaisesRegex(RuntimeError, "programming bug"):
                    self.client.post("/scan/file", files={"file": ("resume.pdf", pdf)})

    def test_unreadable_email_attachment_keeps_report(self):
        email = EmailMessage()
        email.set_content("Please see attached.")
        email.add_attachment(b"broken", maintype="application", subtype="pdf", filename="broken.pdf")
        response = self.client.post("/scan/file", files={"file": ("mail.eml", email.as_bytes())})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["children"][0]["verdict"], "caution")
        self.assertIn("We couldn't read this PDF", response.json()["children"][0]["headline"])


if __name__ == "__main__":
    unittest.main()
