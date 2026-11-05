"""People become codes ("Person A") before the model sees anything in a turn and are restored afterwards; names the asker could see (tools are scoped to their
permissions) are shown to them, nobody else's ever is. Text is also scrubbed of emails, phones, @handles and query-string links."""

import re
from typing import Any

from ..redact import scrub


class NameCoder:
    def __init__(self, names: list[str]):
        self.names = sorted({n.strip() for n in names if n and len(n.strip()) >= 2}, key=len, reverse=True)
        self.pattern = re.compile("|".join(re.escape(n) for n in self.names)) if self.names else None
        self.codes: dict[str, str] = {}
        self.back: dict[str, str] = {}

    def _code(self, name: str) -> str:
        if name not in self.codes:
            i = len(self.codes)
            code = f"Person {chr(ord('A') + i) if i < 26 else i + 1}"
            self.codes[name], self.back[code] = code, name
        return self.codes[name]

    def code_text(self, s: str) -> str:
        return scrub(self.pattern.sub(lambda m: self._code(m.group(0)), s) if self.pattern else s)

    def code(self, o: Any) -> Any:
        if isinstance(o, str):
            return self.code_text(o)
        if isinstance(o, list):
            return [self.code(x) for x in o]
        if isinstance(o, dict):
            return {k: self.code(v) for k, v in o.items()}
        return o

    def restore(self, s: str) -> str:
        for code in sorted(self.back, key=len, reverse=True):
            s = s.replace(code, self.back[code])
        return s
