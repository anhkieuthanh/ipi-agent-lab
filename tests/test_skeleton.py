"""Khung dự án (STT-13): layout, docker-compose và dependency nền phải khớp hợp đồng.

Không cần Docker — chỉ đọc file. Lỗi ở đây nghĩa là khung bị trôi khỏi
`Y_TUONG_DU_AN.md` mục 13 (cây thư mục, service docker-compose).
"""

import importlib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]


@pytest.mark.parametrize(
    "rel",
    [
        "config/defenses.yaml",
        "config/models.yaml",
        "config/rag.yaml",
        "src/agent",
        "src/rag",
        "src/attack/payloads",
        "src/defense",
        "src/eval",
        "src/obs",
        "dashboard/app.py",
        "dashboard/pages",
        "scripts",
    ],
)
def test_layout_co_du_thu_muc(rel):
    assert (ROOT / rel).exists(), f"thiếu {rel}"


@pytest.mark.parametrize("mod", ["agent", "rag", "attack", "defense", "eval", "obs"])
def test_package_nap_duoc(mod):
    importlib.import_module(mod)


@pytest.mark.parametrize("mod", ["fastapi", "sqlmodel", "uvicorn", "streamlit", "qdrant_client"])
def test_dependency_nen_da_cai(mod):
    importlib.import_module(mod)


def test_compose_du_service():
    # Canary listener (STT-34) thêm vào đây khi hiện thực xong.
    assert set(SERVICES) == {"qdrant", "mailhog", "app", "dashboard"}


def test_compose_image_ben_thu_ba_da_pin():
    for name, svc in SERVICES.items():
        image = svc.get("image")
        if image is None:
            continue  # build tại chỗ
        assert ":" in image and not image.endswith(":latest"), f"{name} chưa pin: {image}"


def test_service_ha_tang_deu_co_healthcheck():
    # `app` là dev container đứng chờ, không phục vụ request nên không cần healthcheck.
    for name in ("qdrant", "mailhog", "dashboard"):
        assert "healthcheck" in SERVICES[name], f"{name} thiếu healthcheck"


def test_app_cho_ha_tang_healthy():
    deps = SERVICES["app"]["depends_on"]
    for name in ("qdrant", "mailhog"):
        assert deps[name]["condition"] == "service_healthy"
