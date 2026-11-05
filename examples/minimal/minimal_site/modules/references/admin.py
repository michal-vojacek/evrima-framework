"""Admin screens of the references: list with ordering, form, deletion.

The form is large (description, image, consent), so it has its own page
(docs/framework.md, "Admin" and docs/modules.md). The image is uploaded in the background by the
upload field; the form brings only its id, and the reference claims it on
save. A replaced or removed image is deleted with its variants.
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from evrima import media
from evrima.admin.forms import parse_ids
from evrima.auth import audit, protect
from evrima.auth.sessions import current_admin
from evrima.db import db
from evrima.i18n import translate as t
from evrima.media.models import MediaFile
from evrima.media.views import describe
from minimal_site.modules.references.forms import ReferenceForm
from minimal_site.modules.references.models import Reference

bp = Blueprint("references_admin", __name__, url_prefix="/admin/references", template_folder="templates")
protect(bp)


@bp.get("/")
def index():
    """All references in their website order."""
    references = db.session.scalars(select(Reference).order_by(Reference.position, Reference.id)).all()
    return render_template("references/admin/list.html", references=references)


@bp.route("/new", methods=["GET", "POST"])
def new():
    """Add a reference; it starts at the top of the list."""
    if request.method == "GET":
        return _render_form(ReferenceForm(), None)
    form = ReferenceForm.from_request(request.form)
    _take_image(form, None)
    if form.errors:
        return _render_form(form, None, status=422)

    lowest = db.session.scalar(select(func.min(Reference.position)))
    reference = Reference(position=(lowest - 1) if lowest is not None else 0)
    db.session.add(reference)
    _save(form, reference)
    audit.record("reference.created", admin=current_admin(), detail=reference.client_name)
    flash(t("references.saved", name=reference.client_name), "success")
    return redirect(url_for("references_admin.index"))


@bp.route("/<int:reference_id>", methods=["GET", "POST"])
def edit(reference_id: int):
    """Edit a reference."""
    reference = _get(reference_id)
    if request.method == "GET":
        return _render_form(ReferenceForm.from_reference(reference), reference)
    form = ReferenceForm.from_request(request.form)
    _take_image(form, reference)
    if form.errors:
        return _render_form(form, reference, status=422)

    _save(form, reference)
    audit.record("reference.edited", admin=current_admin(), detail=reference.client_name)
    flash(t("references.saved", name=reference.client_name), "success")
    return redirect(url_for("references_admin.index"))


@bp.post("/<int:reference_id>/delete")
def delete(reference_id: int):
    """Delete a reference together with its image."""
    reference = _get(reference_id)
    name, image = reference.client_name, reference.image
    db.session.delete(reference)
    db.session.commit()
    if image is not None:
        media.delete(image)
    audit.record("reference.deleted", admin=current_admin(), detail=name)
    flash(t("references.deleted", name=name), "success")
    return redirect(url_for("references_admin.index"))


@bp.post("/order")
def order():
    """Save the order from the list (a comma list of ids, first one first)."""
    ids = parse_ids(request.form.get("order"))
    if ids:
        positions = {reference_id: index for index, reference_id in enumerate(ids)}
        for reference in db.session.scalars(select(Reference).where(Reference.id.in_(ids))):
            reference.position = positions[reference.id]
        db.session.commit()
        audit.record("reference.reordered", admin=current_admin())
        flash(t("references.order_saved"), "success")
    return redirect(url_for("references_admin.index"))


def _get(reference_id: int) -> Reference:
    """The reference with `reference_id`, or a 404 page."""
    reference = db.session.get(Reference, reference_id)
    if reference is None:
        abort(404)
    return reference


def _take_image(form: ReferenceForm, reference: Reference | None) -> None:
    """Claim a newly chosen image; keep the current one; refuse anything else.

    Runs only for an otherwise valid form, so a rejected form claims nothing.
    media.take refuses a file that is used elsewhere or is not an image.
    """
    if form.errors or form.image_id is None:
        return
    if reference is not None and form.image_id == reference.image_id:
        return
    if media.take(form.image_id, kinds=("image",)) is None:
        form.errors["image"] = "references.error.image"
        form.image_id = None


def _save(form: ReferenceForm, reference: Reference) -> None:
    """Store the form with its claimed image, then delete the image it replaced."""
    replaced = reference.image if reference.image_id != form.image_id else None
    form.apply(reference)
    reference.image_id = form.image_id
    db.session.commit()         # the reference and the claim of its image together
    if replaced is not None:
        media.delete(replaced)


def _render_form(form: ReferenceForm, reference: Reference | None, status: int = 200):
    """The form page; after a rejected submit with the typed values and the problems."""
    if form.errors:
        flash(t("references.error.summary"), "danger")
    image = db.session.get(MediaFile, form.image_id) if form.image_id is not None else None
    files = [describe(image)] if image is not None else []
    html = render_template("references/admin/form.html", form=form, reference=reference, files=files)
    return html, status
