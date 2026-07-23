# MAM Book Finder

Lightweight web app and API for searching MyAnonamouse, sending downloads to Transmission, and importing completed books into audiobook and ebook libraries.

## Screenshots

| Desktop | Mobile |
| --- | --- |
| ![Desktop screenshot](app/static/screenshots/finder_desktop.png) | ![Mobile screenshot](app/static/screenshots/finder_mobile.png) |

## What It Does

- Search MAM for audiobooks and ebooks
- Add torrents to Transmission with a dedicated label
- Track download history
- Auto-import completed audiobooks into `/library` using hardlinks
- Auto-import completed ebooks into `/ebooks-nosend` (default) or `/ebooks` (when `Send to Kindle` is checked) using copies
- Import ebooks into `/ebooks-nosend` by default; check `Send to Kindle` before adding to import into `/ebooks` instead

## Requirements

- Docker and Docker Compose
- Transmission with RPC enabled
- A valid MAM session cookie
- Mounted host paths for `/data`, one shared audiobook media root, an ebook library, and an ebook no-send library

## Quick Start

1. Set your MAM and Transmission settings in `docker-compose.yml`.
2. Mount your host storage to the in-container paths:
   - `/data` for the SQLite database
   - `/storage` for a shared audiobook media root with `downloads` and `audiobooks` subdirectories
   - `/ebooks` for ebooks
   - `/ebooks-nosend` for ebooks that should not be sent to Kindle
3. Start the app:

   ```bash
   docker compose up -d --build
   ```

4. Open the UI at `http://localhost:8080`.

The app exposes `/downloads` and `/library` as symlinks into `/storage/downloads` and `/storage/audiobooks`. This keeps the app paths stable while allowing audiobook hardlinks to work.

If you use Transmission in Docker, mount the same host media root or downloads subdirectory there so completed paths still resolve under `/downloads`. Downloads and the audiobook library must live on the same filesystem; otherwise audiobook imports fail and the History table shows `Failure` with the hardlink error. Ebook imports continue to copy into `/ebooks` or `/ebooks-nosend`.

## Configuration

Runtime config comes from environment variables in `docker-compose.yml`.

| Variable | Purpose |
| --- | --- |
| `MAM_COOKIE` | MAM session cookie |
| `TRANSMISSION_URL` | Transmission RPC URL |
| `TRANSMISSION_USER` | Transmission RPC username |
| `TRANSMISSION_PASS` | Transmission RPC password |


## Notes

- Search, add, and history are available from the main UI.
- The `Send to Kindle` ebook toggle defaults **off**: new ebook adds are tagged `kindle-nosend` in Transmission and imported into `/ebooks-nosend`. Check `Send to Kindle` before adding to send the ebook to Kindle and import it into `/ebooks` instead.
- Failed imports show `Failure` in history and can be retried with the row's `Retry` button after fixing the underlying path, mount, or permission issue.
- The app has no authentication, so do not expose it directly to the public internet.

## License

MIT
