from erbuild.cli import main


def test_ar(capsys):
    assert main(["ar", "Blood Uchigatana", "--str", "12", "--dex", "40", "--arc", "50"]) == 0
    out = capsys.readouterr().out
    assert "Physical       445" in out
    assert "Bleed          110" in out


def test_optimize_frontier(capsys):
    args = ["optimize", "Blood Uchigatana", "--class", "samurai", "--level", "150", "--vig", "60"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Highest AR:" in out
    assert "Pareto-optimal builds" in out
    assert "VIG 60" in out


def test_optimize_min_buildup(capsys):
    args = ["optimize", "Blood Uchigatana", "--class", "samurai", "-l", "150", "--vig", "60",
            "--min-buildup", "110", "--min", "mnd=20"]
    assert main(args) == 0
    assert "Highest AR with Bleed >= 110" in capsys.readouterr().out


def test_optimize_errors(capsys):
    assert main(["optimize", "Uchigatana", "--class", "samurai", "-l", "5"]) == 1
    assert "too low" in capsys.readouterr().err
    assert main(["optimize", "Uchigatana", "--class", "samurai", "-l", "50", "--min", "foo"]) == 1
    assert "STAT=N" in capsys.readouterr().err
    assert main(["optimize", "Uchigatan", "--class", "samurai", "-l", "50"]) == 1
    assert "Did you mean" in capsys.readouterr().err
    assert main(["optimize", "Heavy Claymore", "--class", "hero", "-l", "50", "--min-buildup", "5"]) == 1
    assert "no status buildup" in capsys.readouterr().err


def test_enemies_commands(capsys, enemy_cache):
    base = ["--enemy-data", str(enemy_cache), "enemies"]
    assert main([*base, "search", "knight", "--cycle", "ng+1"]) == 0
    assert "10,000 HP" in capsys.readouterr().out
    assert main([*base, "show", "Soldier", "--location", "field"]) == 0
    out = capsys.readouterr().out
    assert "HP 800" in out and "Negation %" in out and "immune" in out
    assert main([*base, "show", "Soldier"]) == 1
    assert "different stats" in capsys.readouterr().err


def test_ar_and_optimize_vs_enemy(capsys, enemy_cache):
    enemy = ["--enemy", "Knight [Boss]", "--attack-type", "slash", "--mv", "120"]
    ar = ["ar", "Blood Uchigatana", "--str", "12", "--dex", "40", "--arc", "50", *enemy]
    assert main(["--enemy-data", str(enemy_cache), *ar]) == 0
    out = capsys.readouterr().out
    assert "vs Knight [Boss] (Castle, NG) | MV 120, slash attack" in out
    assert "Per hit" in out and "per proc" in out

    opt = ["optimize", "Blood Uchigatana", "--class", "samurai", "-l", "120", "--vig", "40", *enemy]
    assert main(["--enemy-data", str(enemy_cache), *opt]) == 0
    out = capsys.readouterr().out
    assert "Most damage per hit:" in out
    assert "--min-buildup" not in out

    assert main(["--enemy-data", str(enemy_cache), *opt, "--min-buildup", "50"]) == 1
    assert "can't be combined" in capsys.readouterr().err


def test_missing_enemy_data(capsys, tmp_path):
    missing = str(tmp_path / "none.json")
    assert main(["--enemy-data", missing, "enemies", "search", "x"]) == 1
    assert "erbuild enemies update" in capsys.readouterr().err


def test_user_errors_never_print_tracebacks(capsys, tmp_path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not json")
    for argv, message in [
        (["ar", "Uchigatana", "--str", "0"], "between 1 and 99"),
        (["ar", "Uchigatana", "--upgrade", "30"], "upgrade level must be 0..25"),
        (["--data", str(tmp_path / "missing.json"), "ar", "Uchigatana"], "Can't read weapon data"),
        (["--data", str(bad_json), "ar", "Uchigatana"], "isn't erbuild weapon data"),
    ]:
        assert main(argv) == 1
        err = capsys.readouterr().err
        assert message in err and "Traceback" not in err


def test_numeric_options_are_validated(capsys):
    import pytest

    for argv, message in [
        (["ar", "Uchigatana", "--upgrade", "-1"], "must be at least 0"),
        (["optimize", "Uchigatana", "--class", "samurai", "-l", "50", "--mv", "0"], "greater than 0"),
        (["optimize", "Uchigatana", "--class", "samurai", "-l", "50", "--mv", "-50"], "greater than 0"),
        (["optimize", "Uchigatana", "--class", "samurai", "-l", "50", "--bleed-flat", "-5"], "at least 0"),
        (["optimize", "Uchigatana", "--class", "samurai", "-l", "50", "--min-buildup", "nan"], "finite"),
        (["search", "uchi", "--limit", "0"], "at least 1"),
    ]:
        with pytest.raises(SystemExit) as exit_info:
            main(argv)
        assert exit_info.value.code == 2
        assert message in capsys.readouterr().err


def test_enemy_variant_option(capsys, enemy_cache):
    base = ["--enemy-data", str(enemy_cache)]
    assert main([*base, "enemies", "show", "Mage", "--location", "tower"]) == 1
    assert "variant number" in capsys.readouterr().err
    assert main([*base, "enemies", "show", "Mage", "--location", "tower", "--variant", "2"]) == 0
    assert "120" in capsys.readouterr().out
