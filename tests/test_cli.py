"""cli — 도움말 한 장과 인자 처리. 도구를 돌리지 않는다."""
import re
from pathlib import Path

import pytest

from sure_aibom import NAME, __version__
from sure_aibom.cli import HELP, _groups, build_parser, main

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
    assert e.value.code == 0 and capsys.readouterr().out.strip() == f"{NAME} {__version__}"


@pytest.mark.parametrize("argv, message", [
    (["scan"], "sure-aibom scan: error: the following arguments are required: <target>"),
    (["scan", "x", "--spec", "2.0"], "sure-aibom scan: error: argument --spec: invalid choice: '2.0'"),
    (["scan", "x", "--form", "typed"], "sure-aibom: error: unrecognized arguments: --form typed"),
    (["validate"], "sure-aibom validate: error: the following arguments are required: <bom>"),
])
def test_usage_errors_exit_2_and_name_the_command(argv, message, capsys):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2 and message in capsys.readouterr().err


def test_a_missing_data_path_is_an_error_before_any_tool_runs(tmp_path, monkeypatch, capsys):
    import sure_aibom.cli as cli
    monkeypatch.setattr(cli, "run_syft", lambda *a: pytest.fail("데이터 경로가 틀렸는데 도구를 돌렸다"))
    out = tmp_path / "bom.json"
    assert main(["scan", str(tmp_path), "-o", str(out), "--data", str(tmp_path / "nope"), "--data", str(tmp_path)]) == 2
    assert f"[sure-aibom] error: data path not found: {tmp_path / 'nope'}" in capsys.readouterr().err
    assert not out.exists()


def test_hub_datasets_in_data_are_not_paths_and_a_malformed_one_stops_the_scan(tmp_path, monkeypatch, capsys):
    import sure_aibom.cli as cli
    monkeypatch.setattr(cli, "run_syft", lambda *a: pytest.fail("--data 가 틀렸는데 도구를 돌렸다"))
    out = tmp_path / "bom.json"
    assert main(["scan", str(tmp_path), "-o", str(out), "--data", "hf://datasets/a/b/train.csv"]) == 2
    assert "[sure-aibom] error: --data hf://datasets/a/b/train.csv: not a Hugging Face dataset" in capsys.readouterr().err
    assert main(["scan", str(tmp_path), "-o", str(out), "--data", "hf://datasets/stanfordnlp/imdb", "--data", str(tmp_path / "nope")]) == 2
    assert f"[sure-aibom] error: data path not found: {tmp_path / 'nope'}\n" in capsys.readouterr().err   # 허브 데이터셋은 경로로 보지 않는다
    assert not out.exists()


def test_a_revision_the_hub_says_does_not_exist_stops_the_scan_before_any_tool_runs(tmp_path, monkeypatch, capsys):
    import sure_aibom.cli as cli
    import sure_aibom.dataset as ds
    monkeypatch.setattr(cli, "run_syft", lambda *a: pytest.fail("리비전이 틀렸는데 도구를 돌렸다"))
    monkeypatch.setattr(ds, "hf_reachable", lambda: True)
    monkeypatch.setattr(ds, "fetch_revision_error", lambda hf_id, revision: (404, f"Invalid rev id: {revision}"))
    out = tmp_path / "bom.json"
    assert main(["scan", str(tmp_path), "-o", str(out), "--data", "hf://datasets/stanfordnlp/imdb@nope-branch"]) == 2
    assert ("[sure-aibom] error: --data hf://datasets/stanfordnlp/imdb@nope-branch: revision not found on huggingface.co "
            "(Invalid rev id: nope-branch)") in capsys.readouterr().err
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


@pytest.mark.parametrize("argv, message", [
    (["scan", "./nowhere", "--format", "spdx", "--spec", "1.7"], "--spec 1.7 is not a spdx spec (use 3.0.1 or v0.6)"),
    (["scan", "./nowhere", "--spec", "3.0.1"], "--spec 3.0.1 is not a cyclonedx spec (use 1.7 or v0.6)"),
])
def test_a_spec_of_the_other_format_is_a_usage_error_before_anything_runs(argv, message, capsys):
    """형식과 spec 이 맞지 않으면 대상을 보기도 전에 2 로 끝낸다 (없는 대상을 줘도 그 오류가 아니라 이 오류다)."""
    assert main(argv) == 2
    assert capsys.readouterr().err.strip() == f"[sure-aibom] error: {message}"


def test_validate_refuses_a_spec_of_the_other_format(tmp_path, capsys):
    spdx = tmp_path / "bom.spdx.json"
    spdx.write_text('{"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": []}', encoding="utf-8")
    assert main(["validate", str(spdx), "--spec", "1.7"]) == 2
    assert "--spec 1.7 is not a spdx spec" in capsys.readouterr().err
    neither = tmp_path / "x.json"
    neither.write_text('{"hello": 1}', encoding="utf-8")
    assert main(["validate", str(neither), "--spec", "1.7"]) == 2
    assert "not a CycloneDX or SPDX document" in capsys.readouterr().err
