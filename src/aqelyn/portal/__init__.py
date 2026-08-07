"""The authenticated customer portal (ECR-0118).

Register / log in / consent / upload / read, all gated by a session and scoped to the session's
tenant. This is the customer write boundary; the operator surface stays read-only and loopback.
"""

from aqelyn.portal.app import PortalApplication
from aqelyn.portal.ingest import UploadRefused, ingest_posture_document
from aqelyn.portal.server import PortalServer

__all__ = [
    "PortalApplication",
    "PortalServer",
    "UploadRefused",
    "ingest_posture_document",
]
