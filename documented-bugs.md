### Bug Report — RESOLVED

**Status:** Resolved

**Bug:** Hardlink creation fails when importing media from the downloads directory into the library.

**Impact:** The import process cannot complete, preventing the media from being added to the library.

**Suggested Fix:** Detect when hardlink creation fails due to cross-filesystem or cross-pool limitations (e.g., different ZFS datasets/pools or other filesystems). Provide a configurable fallback to copying the file instead of failing the operation, or allow users to explicitly choose the preferred fallback behavior.

OR 

**Suggested Fix:** Detect when hardlinking is unsupported (such as across different filesystems or ZFS pools) and present a configurable fallback (e.g., copy instead of hardlink) rather than treating it as an error. This allows users to retain hardlinking where supported while accommodating storage layouts where it is not.

**Resolution:** Audiobook imports are now controlled by the `AUDIOBOOK_IMPORT_MODE` setting
(`app/main.py`), which accepts three values and defaults to `hardlink`:

- `hardlink` — hardlink only; a cross-filesystem attempt still fails, with an explicit
  "different filesystems" error instead of a bare `EXDEV`.
- `auto` — hardlink when possible, transparently copy when the kernel says hardlinking is
  unavailable (`EXDEV`, `EPERM`, `EOPNOTSUPP`, `ENOTSUP`, `ENOSYS`), logging a warning.
- `copy` — always copy, never call `os.link`.

An invalid value is rejected at startup. A preflight check (`hardlink_fs_warning`) also warns
up front when the downloads and library directories sit on different filesystems, so the
mismatch surfaces before an import is attempted rather than partway through one.

Covered by `app/tests/test_import_fallback.py` (10 tests, all passing).
