from __future__ import annotations



import hashlib

import shutil

import stat

import zipfile



from pathlib import Path, PurePosixPath





# =========================================================

# STEP 3D-A — STATIC WEB PACKAGE VALIDATION

# =========================================================



STATIC_ENTRY_FILE = "index.html"



STATIC_MAX_FILE_COUNT = 2000



STATIC_MAX_SINGLE_FILE_BYTES = (

    25 * 1024 * 1024

)



STATIC_MAX_EXTRACTED_BYTES = (

    150 * 1024 * 1024

)



STATIC_MAX_COMPRESSION_RATIO = 200



# =========================================================

# STEP 3D-C — STATIC ASSET POLICY

# =========================================================



STATIC_ALLOWED_EXTENSIONS = {

    ".html",

    ".htm",



    ".css",



    ".js",

    ".mjs",



    ".json",



    ".png",

    ".jpg",

    ".jpeg",

    ".gif",

    ".webp",

    ".svg",

    ".ico",



    ".woff",

    ".woff2",

    ".ttf",

    ".otf",



    ".txt",

    ".xml",

    ".map",

}





STATIC_BLOCKED_FILENAMES = {

    ".env",

    ".htaccess",

    ".htpasswd",

}





STATIC_BLOCKED_EXTENSIONS = {

    ".exe",

    ".dll",

    ".com",



    ".bat",

    ".cmd",

    ".ps1",



    ".py",

    ".pyc",



    ".php",

    ".phtml",



    ".sh",

    ".bash",



    ".jar",

    ".war",



    ".msi",



    ".pem",

    ".key",

    ".pfx",

    ".p12",

}





class StaticPackageValidationError(

    ValueError

):

    pass





# =========================================================

# SHA-256

# =========================================================



def calculate_sha256(

    path: Path,

) -> str:



    digest = hashlib.sha256()



    with path.open("rb") as source:



        while True:



            chunk = source.read(

                1024 * 1024

            )



            if not chunk:

                break



            digest.update(

                chunk

            )



    return digest.hexdigest()





# =========================================================

# HTML VALIDATION

# =========================================================



def validate_html_bytes(

    raw: bytes,

) -> None:



    try:



        html = raw.decode(

            "utf-8"

        )



    except UnicodeDecodeError as error:



        raise StaticPackageValidationError(

            "index.html must be UTF-8 encoded."

        ) from error





    sample = html.lower()





    if not (

        "<!doctype" in sample

        or "<html" in sample

        or "<body" in sample

    ):



        raise StaticPackageValidationError(

            "index.html does not appear to be "

            "a valid HTML application entry file."

        )





# =========================================================

# ZIP PATH VALIDATION

# =========================================================



def _validate_archive_path(

    filename: str,

) -> PurePosixPath:



    clean_name = str(

        filename or ""

    ).replace(

        "\\\\",

        "/"

    )





    if not clean_name:



        raise StaticPackageValidationError(

            "ZIP contains an empty file path."

        )





    if "\x00" in clean_name:



        raise StaticPackageValidationError(

            "ZIP contains an invalid file path."

        )





    path = PurePosixPath(

        clean_name

    )





    if path.is_absolute():



        raise StaticPackageValidationError(

            f"Absolute paths are not allowed: "

            f"{clean_name}"

        )





    parts = path.parts





    if ".." in parts:



        raise StaticPackageValidationError(

            f"Path traversal is not allowed: "

            f"{clean_name}"

        )





    if parts and ":" in parts[0]:



        raise StaticPackageValidationError(

            f"Drive-qualified paths are not allowed: "

            f"{clean_name}"

        )





    return path





# =========================================================

# SYMLINK CHECK

# =========================================================



def _is_symlink(

    info: zipfile.ZipInfo,

) -> bool:



    unix_mode = (

        info.external_attr >> 16

    )



    return stat.S_ISLNK(

        unix_mode

    )









# =========================================================

# ZIP STRUCTURE VALIDATION

# =========================================================



def _validate_static_asset_type(

    path: PurePosixPath,

) -> None:



    filename = (

        path.name.lower()

    )





    if filename in STATIC_BLOCKED_FILENAMES:



        raise StaticPackageValidationError(

            "Static application contains "

            "a prohibited file: "

            f"{path.as_posix()}"

        )





    suffix = (

        Path(filename)

        .suffix

        .lower()

    )





    if suffix in STATIC_BLOCKED_EXTENSIONS:



        raise StaticPackageValidationError(

            "Static application contains "

            "a prohibited executable or "

            "server-side file: "

            f"{path.as_posix()}"

        )





    if suffix not in STATIC_ALLOWED_EXTENSIONS:



        raise StaticPackageValidationError(

            "Static application contains "

            "an unsupported file type: "

            f"{path.as_posix()}"

        )





def inspect_static_zip(

    zip_path: Path,

) -> dict:



    if not zipfile.is_zipfile(

        zip_path

    ):



        raise StaticPackageValidationError(

            "Uploaded file is not a valid ZIP archive."

        )





    file_count = 0



    total_uncompressed = 0



    entry_found = False



    normalized_names: set[str] = set()





    try:



        with zipfile.ZipFile(

            zip_path,

            "r",

        ) as archive:



            infos = archive.infolist()





            if not infos:



                raise StaticPackageValidationError(

                    "Static application ZIP is empty."

                )





            for info in infos:



                path = (

                    _validate_archive_path(

                        info.filename

                    )

                )





                normalized = (

                    path.as_posix()

                )





                if normalized in normalized_names:



                    raise StaticPackageValidationError(

                        "ZIP contains duplicate path: "

                        f"{normalized}"

                    )





                normalized_names.add(

                    normalized

                )





                # -----------------------------------------

                # Symlinks are prohibited.

                # -----------------------------------------



                if _is_symlink(

                    info

                ):



                    raise StaticPackageValidationError(

                        "Symbolic links are not allowed "

                        "inside static application packages: "

                        f"{normalized}"

                    )





                if info.is_dir():

                    continue



                _validate_static_asset_type(

                    path

                )    



                # -----------------------------------------

                # Encrypted ZIP entries are prohibited.

                # -----------------------------------------



                if (

                    info.flag_bits

                    & 0x1

                ):



                    raise StaticPackageValidationError(

                        "Encrypted ZIP entries are not "

                        "supported: "

                        f"{normalized}"

                    )





                file_count += 1





                if (

                    file_count

                    > STATIC_MAX_FILE_COUNT

                ):



                    raise StaticPackageValidationError(

                        "Static application contains too "

                        "many files. Maximum allowed is "

                        f"{STATIC_MAX_FILE_COUNT}."

                    )





                if (

                    info.file_size

                    > STATIC_MAX_SINGLE_FILE_BYTES

                ):



                    raise StaticPackageValidationError(

                        "Static application file is too "

                        "large: "

                        f"{normalized}"

                    )





                total_uncompressed += (

                    info.file_size

                )





                if (

                    total_uncompressed

                    > STATIC_MAX_EXTRACTED_BYTES

                ):



                    raise StaticPackageValidationError(

                        "Extracted static application is "

                        "too large. Maximum extracted size "

                        "is "

                        f"{STATIC_MAX_EXTRACTED_BYTES} bytes."

                    )





                # -----------------------------------------

                # Basic ZIP-bomb protection.

                # -----------------------------------------



                if (

                    info.file_size > 0

                    and info.compress_size == 0

                ):



                    raise StaticPackageValidationError(

                        "Suspicious ZIP entry detected: "

                        f"{normalized}"

                    )





                if (

                    info.compress_size > 0

                    and info.file_size > 0

                ):



                    compression_ratio = (

                        info.file_size

                        / info.compress_size

                    )





                    if (

                        compression_ratio

                        > STATIC_MAX_COMPRESSION_RATIO

                    ):



                        raise StaticPackageValidationError(

                            "Suspicious compression ratio "

                            "detected for: "

                            f"{normalized}"

                        )





                # -----------------------------------------

                # Required entry point.

                #

                # Deliberately root-only for Step 3D-A.

                # -----------------------------------------



                if (

                    normalized

                    == STATIC_ENTRY_FILE

                ):



                    entry_found = True





            if file_count == 0:



                raise StaticPackageValidationError(

                    "Static application ZIP contains "

                    "no files."

                )





            if not entry_found:



                raise StaticPackageValidationError(

                    "Static application ZIP must contain "

                    "index.html at the ZIP root."

                )





            # ---------------------------------------------

            # Validate index.html BEFORE extraction.

            # ---------------------------------------------



            try:



                entry_bytes = archive.read(

                    STATIC_ENTRY_FILE

                )



            except KeyError as error:



                raise StaticPackageValidationError(

                    "Unable to read index.html "

                    "from the ZIP package."

                ) from error





            validate_html_bytes(

                entry_bytes

            )





    except zipfile.BadZipFile as error:



        raise StaticPackageValidationError(

            "Uploaded file is not a valid ZIP archive."

        ) from error





    return {

        "entryFile":

            STATIC_ENTRY_FILE,



        "fileCount":

            file_count,



        "extractedSizeBytes":

            total_uncompressed,

    }





# =========================================================

# SECURE EXTRACTION

# =========================================================



def extract_static_zip(

    zip_path: Path,

    destination: Path,

) -> dict:



    inspection = (

        inspect_static_zip(

            zip_path

        )

    )





    if destination.exists():



        raise StaticPackageValidationError(

            "Static package destination "

            "already exists."

        )





    destination.mkdir(

        parents=True,

        exist_ok=False,

    )





    destination_root = (

        destination.resolve()

    )





    try:



        with zipfile.ZipFile(

            zip_path,

            "r",

        ) as archive:



            for info in archive.infolist():



                archive_path = (

                    _validate_archive_path(

                        info.filename

                    )

                )





                target = (

                    destination

                    / Path(

                        *archive_path.parts

                    )

                )





                resolved_target = (

                    target.resolve()

                )





                try:



                    resolved_target.relative_to(

                        destination_root

                    )



                except ValueError as error:



                    raise StaticPackageValidationError(

                        "ZIP entry escapes the "

                        "static application directory: "

                        f"{info.filename}"

                    ) from error





                if info.is_dir():



                    target.mkdir(

                        parents=True,

                        exist_ok=True,

                    )



                    continue





                target.parent.mkdir(

                    parents=True,

                    exist_ok=True,

                )





                written = 0





                with archive.open(

                    info,

                    "r",

                ) as source:



                    with target.open(

                        "xb",

                    ) as output:



                        while True:



                            chunk = source.read(

                                1024 * 1024

                            )





                            if not chunk:

                                break





                            written += len(

                                chunk

                            )





                            # Re-check while extracting.

                            # Never trust ZIP metadata alone.



                            if (

                                written

                                > STATIC_MAX_SINGLE_FILE_BYTES

                            ):



                                raise StaticPackageValidationError(

                                    "Extracted file exceeded "

                                    "the allowed size: "

                                    f"{info.filename}"

                                )





                            output.write(

                                chunk

                            )





                if (

                    written

                    != info.file_size

                ):



                    raise StaticPackageValidationError(

                        "Extracted file size does not "

                        "match ZIP metadata: "

                        f"{info.filename}"

                    )





        entry_path = (

            destination

            / STATIC_ENTRY_FILE

        )





        if not entry_path.is_file():



            raise StaticPackageValidationError(

                "Extracted package does not "

                "contain index.html."

            )





        validate_html_bytes(

            entry_path.read_bytes()

        )





    except Exception:



        shutil.rmtree(

            destination,

            ignore_errors=True,

        )



        raise





    # STEP 3D-D:
    # Validation is complete. Seal extracted package files before
    # the package becomes available to the runtime.
    seal_static_package(
        destination
    )

    return inspection





# =========================================================
# STEP 3D-D — IMMUTABLE STATIC PACKAGE STORAGE
# =========================================================

def _make_static_file_read_only(
    path: Path,
) -> None:
    """
    Defense-in-depth.

    Static application JavaScript runs in the browser and has no
    server-side filesystem API. After package validation we also
    remove normal write bits from extracted package files.

    Windows permission semantics are more limited than POSIX, so
    the primary boundary remains that runtime routes expose no
    filesystem write operation and never execute package content.
    """

    try:
        path.chmod(
            stat.S_IRUSR
            | stat.S_IRGRP
            | stat.S_IROTH
        )
    except OSError:
        pass


def seal_static_package(
    destination: Path,
) -> None:
    """
    Re-check the extracted boundary and mark regular files
    read-only before the package is made runtime-available.
    """

    root = destination.resolve()

    if not root.is_dir():
        raise StaticPackageValidationError(
            "Static package destination is not a directory."
        )

    for candidate in root.rglob("*"):
        resolved = candidate.resolve()

        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise StaticPackageValidationError(
                "Static package contains a path outside "
                "its immutable package directory."
            ) from error

        if candidate.is_symlink():
            raise StaticPackageValidationError(
                "Symbolic links are not allowed inside "
                "static application packages."
            )

        if candidate.is_file():
            _make_static_file_read_only(
                candidate
            )


# =========================================================

# SINGLE HTML PACKAGE

# =========================================================



def validate_single_static_html(

    html_path: Path,

) -> dict:



    raw = html_path.read_bytes()



    validate_html_bytes(

        raw

    )



    return {

        "sha256":

            calculate_sha256(

                html_path

            ),



        "entryFile":

            "index.html",



        "fileCount":

            1,



        "extractedSizeBytes":

            len(raw),

    }