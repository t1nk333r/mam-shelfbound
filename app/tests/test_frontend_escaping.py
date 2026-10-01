"""Search result rows are built with innerHTML, so every MAM-supplied field must
be escaped. Runs app.js under Node with a stub DOM; skipped when Node is absent."""
import json
import pathlib
import shutil
import subprocess

import pytest

APP_JS = pathlib.Path(__file__).resolve().parent.parent / "static" / "app.js"

# A permissive stand-in for the DOM: any property read returns another stub,
# calls return stubs, iteration is empty, and assigned values read back. That is
# enough for app.js to load and for buildResultRow to assign tr.innerHTML.
HARNESS = r"""
const fs = require('fs');
const vm = require('vm');

function stub() {
  const store = {};
  const target = function () {};
  return new Proxy(target, {
    get(_, prop) {
      if (prop in store) return store[prop];
      if (prop === Symbol.iterator) return function* () {};
      if (prop === Symbol.toPrimitive) return () => '';
      if (prop === 'length') return 0;
      if (prop === 'then') return undefined;
      return (store[prop] = stub());
    },
    set(_, prop, value) { store[prop] = value; return true; },
    apply() { return stub(); },
  });
}

const ctx = { document: stub(), window: stub(), console, fetch: () => new Promise(() => {}) };
const [appJs, itemJson] = process.argv.slice(-2);
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(appJs, 'utf8'), ctx);
const item = JSON.parse(itemJson);
process.stdout.write(vm.runInContext('buildResultRow', ctx)(item).innerHTML);
"""

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

PAYLOAD = '<img src=x onerror="alert(1)">'


def render_result_row(item: dict) -> str:
    out = subprocess.run(
        ["node", "-e", HARNESS, str(APP_JS), json.dumps(item)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return out.stdout


def test_result_row_escapes_non_numeric_size():
    html = render_result_row({"id": "1", "title": "Book", "size": PAYLOAD})

    assert "<img" not in html
    assert "&lt;img src=x" in html


def test_result_row_escapes_every_text_field():
    fields = ("title", "author_info", "narrator_info", "format", "size", "added")
    html = render_result_row({"id": "1", "seeders": PAYLOAD, "leechers": 2, **{f: PAYLOAD for f in fields}})

    assert "<img" not in html


def test_result_row_still_formats_numeric_size():
    html = render_result_row({"id": "1", "title": "Book", "size": 1536})

    assert "1.5 KB" in html
