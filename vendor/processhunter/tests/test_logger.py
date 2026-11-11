import logging
from pathlib import Path
import pytest
from vendor.processhunter.core.logger import setup_app_logger, LogEvent, MemoryLogHandler


def test_logger_file_and_memory_emission(tmp_path: Path):
    log_file = tmp_path / "test.log"
    logger, emitter = setup_app_logger(log_file=log_file, logger_name="test_logger")

    received_events: list[LogEvent] = []
    emitter.register_callback(received_events.append)

    logger.info("Teste de mensagem informativa")
    logger.warning("Alerta de aviso")
    logger.error("Erro simulado")

    # Verify file
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Teste de mensagem informativa" in content
    assert "Alerta de aviso" in content
    assert "Erro simulado" in content
    assert " - [INFO] " in content

    # Verify memory listener
    assert len(received_events) == 3
    assert received_events[0].level == "INFO"
    assert received_events[0].message == "Teste de mensagem informativa"
    assert received_events[1].level == "WARNING"
    assert received_events[2].level == "ERROR"


def test_logger_rotation_configured(tmp_path: Path):
    log_file = tmp_path / "rotate.log"
    logger, emitter = setup_app_logger(log_file=log_file, logger_name="rotate_logger")

    has_rotating = any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers)
    assert has_rotating is True
