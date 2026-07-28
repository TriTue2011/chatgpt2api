"""Chặn React #310: hook nằm DƯỚI guard `if (isCheckingAuth) return`.

Đã xảy ra thật ở tab Giáo viên: ba `useEffect` bị thêm xuống cuối component,
sau guard auth. Lần render đầu `isCheckingAuth=true` nên hàm thoát ở guard —
ba hook đó không chạy. Auth xong render tiếp thì chúng mới chạy, số hook tăng
giữa hai lần render ⇒ React ném #310 ⇒ TRANG TRẮNG, không phải lỗi nhỏ.

Vì sao phải là test Python: `web/next.config.ts` bật
`typescript.ignoreBuildErrors` và repo KHÔNG có eslint, nên
`react-hooks/rules-of-hooks` — thứ lẽ ra bắt được lỗi này — không hề chạy.
Build vẫn xanh và lỗi chỉ hiện ra trên trình duyệt của người dùng.

Test soát THÔ nhưng ăn đúng hình dạng lỗi: trong thân mỗi component ở mức
thụt lề 2, mọi lệnh gọi hook phải đứng TRƯỚC mọi `return` sớm.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.pure

_WEB = Path(__file__).resolve().parents[1] / "web" / "src"

# `const [a, b] = useState(...)`, `const x = useMemo(...)`, `useEffect(...)`
_HOOK = re.compile(r"^  (?:const\s+.*=\s*)?use[A-Z]\w*\s*[(<]")
# Guard mở khối: `  if (...) {`
_IF_OPEN = re.compile(r"^  if\s*\(.*\)\s*\{\s*$")
# Guard một dòng: `  if (...) return ...;`
_IF_RET = re.compile(r"^  if\s*\(.*\)\s*return\b")
# Bắt đầu một hàm ở mức file — mốc chia component.
_TOP_FN = re.compile(r"^(?:export\s+default\s+)?(?:export\s+)?(?:async\s+)?function\s+(\w+)")


def _tsx_files() -> list[Path]:
    return sorted(p for p in _WEB.rglob("*.tsx") if "node_modules" not in p.parts)


def _components(lines: list[str]) -> list[tuple[str, int, int]]:
    """Chia file thành (tên, dòng bắt đầu, dòng kết thúc) theo hàm mức file."""
    starts = [(m.group(1), i) for i, ln in enumerate(lines)
              if (m := _TOP_FN.match(ln))]
    out = []
    for k, (name, i) in enumerate(starts):
        end = starts[k + 1][1] if k + 1 < len(starts) else len(lines)
        out.append((name, i, end))
    return out


def _early_returns(body: list[str], base: int) -> list[int]:
    """Dòng của các `return` sớm ở mức thụt lề 2 (0-index tuyệt đối).

    `return` cuối hàm (JSX chính) KHÔNG tính — nó luôn là dòng return cuối và
    không có hook nào sau nó.
    """
    hits: list[int] = []
    n = len(body)
    i = 0
    while i < n:
        ln = body[i]
        if _IF_RET.match(ln):
            hits.append(base + i)
            i += 1
            continue
        if _IF_OPEN.match(ln):
            # Quét thân khối tới dấu `  }` đóng ở đúng mức 2.
            j = i + 1
            while j < n and not re.match(r"^  \}", body[j]):
                if re.match(r"^\s+return\b", body[j]):
                    hits.append(base + i)
                    break
                j += 1
            i = j + 1
            continue
        i += 1
    return hits


def _violations(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    bad: list[str] = []
    for name, start, end in _components(lines):
        body = lines[start:end]
        hooks = [start + i for i, ln in enumerate(body) if _HOOK.match(ln)]
        if not hooks:
            continue
        guards = _early_returns(body, start)
        last_hook = max(hooks)
        try:
            shown = str(path.relative_to(_WEB.parent))
        except ValueError:  # file tạm trong test tự kiểm
            shown = path.name
        for g in guards:
            if g < last_hook:
                after = [h + 1 for h in hooks if h > g]
                bad.append(
                    f"{shown}:{g + 1} — guard `return` sớm "
                    f"trong {name}() đứng TRƯỚC hook ở dòng {after}. "
                    f"Chuyển hook lên trên guard."
                )
                break
    return bad


class TestRulesOfHooks:
    def test_khong_co_hook_duoi_guard(self):
        bad: list[str] = []
        for f in _tsx_files():
            bad += _violations(f)
        assert not bad, "Hook nằm dưới guard ⇒ React #310 trang trắng:\n" + "\n".join(bad)

    def test_co_quet_duoc_file(self):
        """Nếu regex hỏng, test trên sẽ xanh giả vì không thấy gì để soát."""
        files = _tsx_files()
        assert len(files) > 10, f"chỉ thấy {len(files)} file .tsx — đường dẫn sai?"
        with_hooks = 0
        for f in files:
            lines = f.read_text(encoding="utf-8").splitlines()
            for _n, s, e in _components(lines):
                if any(_HOOK.match(ln) for ln in lines[s:e]):
                    with_hooks += 1
                    break
        assert with_hooks > 5, f"chỉ nhận ra {with_hooks} component có hook"

    def test_bat_duoc_mau_loi_that(self):
        """Red/green: dựng lại đúng hình dạng đã gây #310 và đòi test bắt được."""
        src = [
            "export default function Page() {",
            "  const { isCheckingAuth } = useAuthGuard();",
            "  const [a, setA] = useState(0);",
            "",
            "  if (isCheckingAuth) {",
            "    return <Spin />;",
            "  }",
            "",
            "  useEffect(() => { setA(1); }, []);",
            "",
            "  return <div />;",
            "}",
        ]
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".tsx", delete=False,
                                        encoding="utf-8") as fh:
            fh.write("\n".join(src))
            tmp = Path(fh.name)
        try:
            v = _violations(tmp)
            assert v, "mẫu lỗi kinh điển mà không bắt được ⇒ test vô dụng"
            assert "9" in v[0], v[0]
        finally:
            tmp.unlink()

    def test_guard_return_cuoi_ham_khong_bao_dong_gia(self):
        """`if (!x) return` NẰM TRONG useEffect/hàm con là hợp lệ — mức thụt lề
        khác, không được tính là guard của component."""
        src = [
            "export default function Page() {",
            "  const [a, setA] = useState(0);",
            "  useEffect(() => {",
            "    if (!a) return;",
            "    setA(2);",
            "  }, [a]);",
            "  const b = useMemo(() => {",
            "    if (!a) return 0;",
            "    return a * 2;",
            "  }, [a]);",
            "  return <div>{b}</div>;",
            "}",
        ]
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".tsx", delete=False,
                                        encoding="utf-8") as fh:
            fh.write("\n".join(src))
            tmp = Path(fh.name)
        try:
            assert _violations(tmp) == []
        finally:
            tmp.unlink()
