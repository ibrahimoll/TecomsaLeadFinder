"""Licensed directory imports (a 5INDEX / Yelleb / Infobel / Kompass / IFP... export, CSV / XLSX; their sites are never
fetched): the user names the directory, upload -> detected columns + what the import would do
(a dry run: exactly what confirming does) -> confirm -> history, where an import can be removed. Managers / admins."""

from typing import Annotated
from zipfile import BadZipFile

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from xlrd import XLRDError

from app.api.deps import DbSession, ManagerOrAdmin
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.services import contributions

router = APIRouter(prefix="/imports/directory", tags=["imports"])
EXTENSIONS = (".csv", ".xlsx", ".xls")  # .xls: 5INDEX's HTML-table export, or a real Excel 97 file


def _run(db, user, file: UploadFile, directory: str, apply: bool) -> dict:
    name = (file.filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if not name.lower().endswith(EXTENSIONS):
        raise BusinessRuleError("Choose the .xlsx, .xls or .csv file exported from the directory.")
    try:
        return contributions.import_directory(db, file_name=name, raw=file.file.read(), directory=directory,
                                              user_id=user.id, apply=apply)
    except ValueError as exc:  # no directory named / no header row with a company column
        raise BusinessRuleError(f"The file could not be read: {exc}.") from exc
    except (BadZipFile, XLRDError) as exc:  # not really a workbook (or password-protected)
        raise BusinessRuleError("The file could not be read as a workbook: open it in Excel, save it as .xlsx.") from exc


@router.post("/preview")
def preview(file: Annotated[UploadFile, File()], directory: Annotated[str, Form(max_length=60)], user: ManagerOrAdmin,
            db: DbSession) -> dict:
    """What importing the file would do (nothing is written)."""
    return _run(db, user, file, directory, apply=False)


@router.post("", status_code=status.HTTP_201_CREATED)
def apply(file: Annotated[UploadFile, File()], directory: Annotated[str, Form(max_length=60)], user: ManagerOrAdmin,
          db: DbSession, confirm: Annotated[bool, Form()] = False) -> dict:
    """Import the file (after its preview: confirm=true)."""
    if not confirm:
        raise BusinessRuleError("Preview the file first, then confirm the import.")
    return _run(db, user, file, directory, apply=True)


@router.get("")
def history(_: ManagerOrAdmin, db: DbSession) -> list[dict]:
    return contributions.imports(db)


@router.get("/coverage")
def coverage(_: ManagerOrAdmin, db: DbSession) -> list[dict]:
    """Per directory: people, people with a mobile / WhatsApp / e-mail, companies with a number."""
    return contributions.coverage(db)


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(import_id: str, user: ManagerOrAdmin, db: DbSession) -> Response:
    """Remove an import: what only it added goes (contacts, people, the companies it created that nothing else
    describes); what other sources also state stays."""
    try:
        contributions.remove_import(db, import_id, user_id=user.id)
    except LookupError as exc:
        raise NotFoundError("No such import") from exc
    except ValueError as exc:
        raise BusinessRuleError(str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
