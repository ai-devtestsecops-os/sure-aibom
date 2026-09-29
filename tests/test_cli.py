"""cli — 도움말 한 장과 인자 처리. 도구를 돌리지 않는다."""
import re
from pathlib import Path

import pytest

from aibom_cli import __version__
from aibom_cli.cli import HELP, _groups, build_parser, main

README = Path(__file__).parents[1] / "README.md"


@pytest.mark.parametrize("argv", [["--help"], ["-h"], ["scan", "--help"], ["validate", "-h"], []])
def test_every_help_entry_prints_the_same_page(argv, capsys):
    if argv:
        with pytest.raises(SystemExit) as e:
            main(argv)
        assert e.value.code == 0
    else:
        assert main(argv) == 0                                     # 명령 없이 실행하면 도움말
    assert capsys.readouterr().out == HELP


def test_readme_usage_block_is_the_help_page():
    """README 의 사용 절은 --help 와 글자까지 같다. 한쪽만 고치면 여기서 걸린다."""
    block = re.search(r"## 사용\n\n```\n(.*?)```\n", README.read_text(encoding="utf-8"), re.S)
    assert block and block.group(1) == HELP


def test_help_mentions_every_option_the_parser_accepts():
    parser = build_parser()
    commands = next(a for a in parser._actions if a.dest == "command").choices
    for sub in [parser, *commands.values()]:
        for action in sub._actions:
            for flag in action.option_strings:
                assert flag in HELP, f"{sub.prog} 의 {flag} 가 도움말에 없다"
            if action.metavar and action.metavar != "<command>":
                assert action.metavar in HELP, f"{sub.prog} 의 {action.metavar} 가 도움말에 없다"
    for name in commands:
        assert f"  {name} <" in HELP


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.strip() == f"aibom-cli {__version__}"


@pytest.mark.parametrize("argv, message", [
    (["scan"], "aibom-cli scan: error: the following arguments are required: <target>"),
    (["scan", "x", "--spec", "2.0"], "aibom-cli scan: error: argument --spec: invalid choice: '2.0'"),
    (["scan", "x", "--form", "typed"], "aibom-cli: error: unrecognized arguments: --form typed"),
    (["validate", "bom.json"], "aibom-cli validate: error: the following arguments are required: --spec"),
])
def test_usage_errors_exit_2_and_name_the_command(argv, message, capsys):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2 and message in capsys.readouterr().err


def test_a_missing_data_path_is_an_error_before_any_tool_runs(tmp_path, monkeypatch, capsys):
    import aibom_cli.cli as cli
    monkeypatch.setattr(cli, "run_syft", lambda *a: pytest.fail("데이터 경로가 틀렸는데 도구를 돌렸다"))
    out = tmp_path / "bom.json"
    assert main(["scan", str(tmp_path), "-o", str(out), "--data", str(tmp_path / "nope"), "--data", str(tmp_path)]) == 2
    assert f"[aibom-cli] error: data path not found: {tmp_path / 'nope'}" in capsys.readouterr().err
    assert not out.exists()


def test_data_can_be_given_more_than_once():
    args = build_parser().parse_args(["scan", "x", "--data", "a", "--data", "b"])
    assert args.data == ["a", "b"] and build_parser().parse_args(["scan", "x"]).data == []


def test_groups_count_only_real_datasets_as_datasets():
    """type=data 라도 data[] 에 dataset 항목이 없으면(cdxgen 의 apt 저장소 설정) 데이터셋으로 세지 않는다."""
    comps = [
        {"type": "library", "name": "numpy"}, {"type": "operating-system", "name": "debian"},
        {"type": "machine-learning-model", "name": "bert"},
        {"type": "data", "name": "imdb", "data": [{"type": "dataset", "name": "stanfordnlp/imdb"}]},
        {"type": "data", "name": "deb.debian.org/debian", "data": []},
        {"type": "file", "name": "/usr/bin/apt"},
    ]
    assert _groups(comps) == "2 packages, 1 model, 1 dataset, 1 file, 1 other"
    assert _groups(comps, skip=("datasets",)) == "2 packages, 1 model, 1 file, 1 other"
    assert _groups([]) == "nothing found"
