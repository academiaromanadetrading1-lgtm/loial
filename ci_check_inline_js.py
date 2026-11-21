"""Check inline browser JavaScript syntax without starting the web server.

Run: python ci_check_inline_js.py join.html scan.html platform.html
Requires Node.js (available on GitHub-hosted Ubuntu runners).
"""
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys
import tempfile


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.inline = []
        self.collecting = False
        self.module = False
        self.current = []

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        options = dict(attrs)
        js_type = (options.get("type") or "").lower()
        self.collecting = "src" not in options and js_type in ("", "text/javascript", "module")
        self.module = js_type == "module"
        self.current = []

    def handle_data(self, data):
        if self.collecting:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.collecting:
            code = "".join(self.current).strip()
            if code:
                self.inline.append((code, self.module))
            self.collecting = False
            self.current = []


def check(path):
    parser = Scripts()
    parser.feed(Path(path).read_text(encoding="utf-8"))
    for index, (code, module) in enumerate(parser.inline, 1):
        with tempfile.TemporaryDirectory(prefix="loial-js-") as folder:
            js = Path(folder) / ("inline.mjs" if module else "inline.js")
            js.write_text(code, encoding="utf-8")
            result = subprocess.run(["node", "--check", str(js)],
                                    capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"{path}: inline script {index} syntax error:\n{result.stderr}")
    print(f"{path}: {len(parser.inline)} inline script(s) syntax OK")


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        raise SystemExit("Pass one or more HTML paths")
    for item in paths:
        check(item)
