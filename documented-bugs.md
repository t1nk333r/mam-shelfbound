### Bug Report

**Bug:** Hardlink creation fails when importing media from the downloads directory into the library.

**Impact:** The import process cannot complete, preventing the media from being added to the library.

**Suggested Fix:** Detect when hardlink creation fails due to cross-filesystem or cross-pool limitations (e.g., different ZFS datasets/pools or other filesystems). Provide a configurable fallback to copying the file instead of failing the operation, or allow users to explicitly choose the preferred fallback behavior.

OR 

**Suggested Fix:** Detect when hardlinking is unsupported (such as across different filesystems or ZFS pools) and present a configurable fallback (e.g., copy instead of hardlink) rather than treating it as an error. This allows users to retain hardlinking where supported while accommodating storage layouts where it is not.
