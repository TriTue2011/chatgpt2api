"""Gemini Web phải lấy model từ registry do tài khoản thực tế khám phá."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


class _Client:
    def __init__(self, models):
        self.models = models

    def list_models(self):
        return self.models

    def resolve_model(self, name: str):
        target = name.lower()
        for model in self.models:
            aliases = {str(x).lower() for x in getattr(model, "aliases", [])}
            if target in {
                str(model.model_name).lower(),
                str(model.model_id).lower(),
                *aliases,
            }:
                return model
        raise ValueError(name)


def _model(name: str, model_id: str, *, available: bool = True, aliases=()):
    return SimpleNamespace(
        model_name=name,
        model_id=model_id,
        is_available=available,
        aliases=list(aliases),
    )


def test_catalog_dong_gop_nhieu_tai_khoan_va_bo_model_guest_khong_dung_duoc(
    monkeypatch,
) -> None:
    from api import gemini_web as gma

    flash = _model("gemini-flash", "a1")
    pro = _model("gemini-pro", "b2")
    unavailable = _model("gemini-ultra", "c3", available=False)
    monkeypatch.setattr(gma, "_clients", {
        "one": _Client([flash, unavailable]),
        "two": _Client([flash, pro]),
    })

    assert gma.available_model_ids() == ["gma/gemini-flash", "gma/gemini-pro"]


def test_resolve_model_dung_registry_dong_thay_vi_enum_cung(monkeypatch) -> None:
    from api import gemini_web as gma

    dynamic = _model(
        "gemini-3.6-flash",
        "hex-new",
        aliases=("3.6-flash",),
    )
    monkeypatch.setattr(gma, "_clients", {"one": _Client([dynamic])})
    assert gma._resolve_model("gma/3.6-flash") == "gemini-3.6-flash"


def test_guest_warm_khong_chan_model_cua_account_con_lanh(monkeypatch) -> None:
    from api import gemini_web as gma

    guest_pro = _model("gemini-3-pro", "b2", available=False, aliases=("pro",))
    monkeypatch.setattr(gma, "_clients", {"guest": _Client([guest_pro])})

    # Registry guest biết model này nhưng không được dùng; account đăng nhập
    # còn lạnh phải có cơ hội init và resolve nó ở vòng retry phía sau.
    assert gma._resolve_model("gma/pro") == "gemini-3-pro"


def test_account_guest_khong_duoc_dung_model_bi_danh_dau_unavailable() -> None:
    from api import gemini_web as gma

    guest = _Client([_model("gemini-pro", "b2", available=False)])
    with pytest.raises(gma._ModelUnavailable):
        gma._model_for_client(guest, "gemini-pro")


def test_model_dong_duoc_noi_vao_catalog_openai(monkeypatch) -> None:
    from api import gemini_web as gma
    from services.protocol import openai_v1_models as catalog

    monkeypatch.setattr(
        gma,
        "available_model_ids",
        lambda: ["gma/gemini-flash", "gma/gemini-pro"],
    )
    assert catalog._fetch_gemini_web_api_models() == {
        "gma/gemini-flash",
        "gma/gemini-pro",
    }


def test_cache_tinh_van_duoc_ghep_registry_dang_song(monkeypatch) -> None:
    from services.protocol import openai_v1_models as catalog

    monkeypatch.setattr(
        catalog,
        "_fetch_gemini_web_api_models",
        lambda: {
            "gma/gemini-model-vua-xuat-hien",
            "gma/gemini-image-moi",
        },
    )
    rows = catalog._merge_runtime_gma_models([
        {"id": "gma/auto", "object": "model", "owned_by": "gemini_web_api"},
    ])
    assert {row["id"] for row in rows} == {
        "gma/auto",
        "gma/gemini-model-vua-xuat-hien",
        "gma/gemini-model-vua-xuat-hien:text",
        "gma/gemini-image-moi",
    }


def test_dependency_gemini_api_ghim_commit_co_registry_dong() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    revision = "b38110e82fe0e41bbf53a03646ef87ddc88a996a"
    assert f'rev = "{revision}"' in pyproject
    assert f"#{revision}" in lock


def test_registry_warm_khong_ket_luan_som_ten_sai_cua_account_con_lanh(
    monkeypatch,
) -> None:
    from api import gemini_web as gma

    monkeypatch.setattr(gma, "_clients", {
        "one": _Client([_model("gemini-flash", "a1")]),
    })
    assert gma._resolve_model("gma/khong-ton-tai") == "khong-ton-tai"
