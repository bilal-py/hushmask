import json

from hushmask.cli import main


def test_mask_then_restore(tmp_path, capsys):
    source = tmp_path / "in.txt"
    source.write_text("Rahul Sharma, card 4111 1111 1111 1111", encoding="utf-8")
    vault = tmp_path / "vault.json"

    assert main(["mask", str(source), "--known", "PERSON=Rahul Sharma", "--vault", str(vault)]) == 0
    masked = capsys.readouterr().out
    assert "Rahul" not in masked and "4111" not in masked
    assert len(json.loads(vault.read_text(encoding="utf-8"))) == 2

    answer = tmp_path / "answer.txt"
    answer.write_text(masked, encoding="utf-8")
    assert main(["restore", str(answer), "--vault", str(vault)]) == 0
    assert capsys.readouterr().out == "Rahul Sharma, card 4111 1111 1111 1111"


def test_detect_lists_entities(tmp_path, capsys):
    source = tmp_path / "in.txt"
    source.write_text("mail x@example.com", encoding="utf-8")
    assert main(["detect", str(source)]) == 0
    assert "EMAIL" in capsys.readouterr().out
