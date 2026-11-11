import pytest
from vendor.systemram.cli import parse_args, run_cli

def test_cli_parsing_status():
    args = parse_args(["-s"])
    assert args.status is True

def test_cli_parsing_empty_flags():
    args = parse_args(["-Es", "-Ew", "-Em", "-Ec", "-E0"])
    assert args.empty_standby is True
    assert args.empty_working_sets is True
    assert args.empty_modified is True
    assert args.empty_system_cache is True
    assert args.empty_standby0 is True

def test_cli_status_run(capsys):
    args = parse_args(["--status"])
    code = run_cli(args)
    captured = capsys.readouterr()
    assert code == 0
    assert "Memória Física" in captured.out or "Total RAM" in captured.out or "Uso de Memória" in captured.out
