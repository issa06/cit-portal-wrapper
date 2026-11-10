from cit_campus_mcp.documents.client import DocumentsClient


def test_documents_host_guard():
    client = DocumentsClient()
    assert client._allowed("https://kmsk.is.it-chiba.ac.jp/portal/test.pdf")
    assert not client._allowed("https://example.com/test.pdf")
