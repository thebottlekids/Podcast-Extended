"""OPML 2.0 generation for subscription export."""

from typing import Sequence, cast
from xml.etree import ElementTree as ET

OPML_DOCUMENT_TITLE = "Podcast-Extended Subscriptions"


def generate_opml(entries: Sequence[tuple[str, str]]) -> bytes:
    """Build an OPML 2.0 document from (title, xml_url) pairs.

    Uses ElementTree so titles/URLs containing ampersands, quotes, or other
    special characters are escaped correctly.
    """
    root = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(root, "head")
    title_el = ET.SubElement(head, "title")
    title_el.text = OPML_DOCUMENT_TITLE
    body = ET.SubElement(root, "body")
    for title, xml_url in entries:
        ET.SubElement(
            body,
            "outline",
            {
                "text": title,
                "title": title,
                "type": "rss",
                "xmlUrl": xml_url,
            },
        )
    return cast(bytes, ET.tostring(root, encoding="UTF-8", xml_declaration=True))
