from __future__ import annotations

import pytest

from app.config import config
from app.ingest import xlsx_reader

PLANILHA = config.dir_planilha / "CORRECAO SIMULADOS 2026.xlsx"

# A planilha real fica fora do repositorio. Onde ela nao existir (CI, outro clone),
# os testes que dependem dela sao pulados em vez de falharem.
requer_planilha = pytest.mark.skipif(
    not PLANILHA.exists(), reason="planilha real ausente (fora do versionamento)"
)


@pytest.fixture(scope="session")
def planilha():
    if not PLANILHA.exists():
        pytest.skip("planilha real ausente")
    return xlsx_reader.ler(PLANILHA)
