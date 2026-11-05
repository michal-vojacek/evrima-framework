"""The reference form: reading the submitted values and checking them.

Plain request parsing, like the rest of the admin: the form is small and
its rules (consent before publishing) read better as code than as WTForms
validators. Errors are catalogue keys per field, shown next to the fields.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import urlsplit

from werkzeug.datastructures import MultiDict

from evrima.admin.forms import parse_id
from evrima.editor import sanitize
from minimal_site.modules.references.models import Reference

MAX_NAME = 200
MAX_URL = 500
MAX_PROOF = 500


@dataclass
class ReferenceForm:
    """Values of the form, as typed (for showing them again) and as parsed."""

    client_name: str = ""
    website_url: str = ""
    description: str = ""
    image_id: int | None = None
    consent_on: date | None = None
    consent_on_text: str = ""
    consent_proof: str = ""
    published: bool = False
    errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_reference(cls, reference: Reference) -> "ReferenceForm":
        """The form filled with a stored reference."""
        return cls(
            client_name=reference.client_name, website_url=reference.website_url,
            description=reference.description, image_id=reference.image_id,
            consent_on=reference.consent_on,
            consent_on_text=reference.consent_on.isoformat() if reference.consent_on else "",
            consent_proof=reference.consent_proof, published=reference.published)

    @classmethod
    def from_request(cls, data: MultiDict) -> "ReferenceForm":
        """Read and check submitted values; problems end up in `errors`."""
        form = cls(
            client_name=data.get("client_name", "").strip(),
            website_url=normalise_url(data.get("website_url", "")),
            description=sanitize(data.get("description", "")),
            consent_on_text=data.get("consent_on", "").strip(),
            consent_proof=data.get("consent_proof", "").strip(),
            published=data.get("published") == "on",
        )
        image = data.get("image", "").strip()
        if image:
            form.image_id = parse_id(image)
            if form.image_id is None:
                form.errors["image"] = "references.error.image"

        if not form.client_name:
            form.errors["client_name"] = "references.error.client_name"
        elif len(form.client_name) > MAX_NAME:
            form.errors["client_name"] = "references.error.too_long"
        if form.website_url and not valid_url(form.website_url):
            form.errors["website_url"] = "references.error.url"
        if len(form.consent_proof) > MAX_PROOF:
            form.errors["consent_proof"] = "references.error.too_long"
        if form.consent_on_text:
            try:
                form.consent_on = date.fromisoformat(form.consent_on_text)
            except ValueError:
                form.errors["consent_on"] = "references.error.consent_date"
            else:
                # A day of slack: the server counts in UTC, Czech midnight comes earlier.
                if form.consent_on > date.today() + timedelta(days=1):
                    form.errors["consent_on"] = "references.error.consent_future"
        if form.published and form.consent_on is None and "consent_on" not in form.errors:
            form.errors["published"] = "references.error.consent_needed"
        return form

    def apply(self, reference: Reference) -> None:
        """Copy the checked values to `reference` (the image is handled by the view)."""
        reference.client_name = self.client_name
        reference.website_url = self.website_url
        reference.description = self.description
        reference.consent_on = self.consent_on
        reference.consent_proof = self.consent_proof
        reference.published = self.published


def normalise_url(value: str) -> str:
    """Trim the address and add https:// when it was typed without a scheme."""
    value = value.strip()
    if value and "://" not in value:
        value = "https://" + value
    return value


def valid_url(value: str) -> bool:
    """A web address with http(s), a host with a dot and no spaces, within the length limit."""
    if len(value) > MAX_URL or any(char.isspace() for char in value):
        return False
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and "." in parts.netloc
